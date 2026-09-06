"use client";

import type {
  AuthMode,
  Calibration,
  Digest,
  Me,
  SymbolRow,
  TickerDetail,
  TokenResponse,
  WatchlistItem,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const TOKEN_KEY = "smw.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(t: string) {
  window.localStorage.setItem(TOKEN_KEY, t);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

/** Broadcast so the header, the route guard and other tabs all follow. */
export const AUTH_EVENT = "smw:auth";

export function announceAuthChange() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_EVENT));
  }
}

/**
 * The expiry claim, read without verifying the signature.
 *
 * Only ever used to skip a request that is certainly going to 401. The server
 * is the authority on whether a token is good; this is politeness, not a check.
 */
export function tokenClaims(): { sub?: string; email?: string; exp?: number } | null {
  const t = getToken();
  if (!t) return null;
  try {
    const [, payload] = t.split(".");
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export function tokenLooksLive(): boolean {
  const claims = tokenClaims();
  if (!claims) return false;
  return typeof claims.exp !== "number" || claims.exp * 1000 > Date.now();
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export class OfflineError extends Error {}

async function request<T>(
  path: string,
  init: RequestInit = {},
  raw = false,
): Promise<T> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers || {}),
      },
    });
  } catch {
    // A dead network is a different state from a server that said no, and the
    // UI shows them differently.
    throw new OfflineError("network unreachable");
  }
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* keep the status text */
    }
    // A 401 means the token this device holds is no longer identity. Drop it
    // here rather than in every caller, so one expired token cannot leave the
    // app half signed-in.
    if (res.status === 401) {
      clearToken();
      announceAuthChange();
    }
    throw new ApiError(res.status, detail);
  }
  if (raw) return res as unknown as T;
  return (await res.json()) as T;
}

/**
 * Which sign-in path is live. Unauthenticated: the screen has to know before
 * it has a token to show anyone.
 */
export async function getAuthMode(): Promise<AuthMode> {
  const r = await fetch(`${API_BASE}/api/auth/mode`);
  if (!r.ok) throw new ApiError(r.status, "could not read the auth mode");
  return (await r.json()) as AuthMode;
}

/** Sign in. Local dev issues its own token; a Supabase deployment supplies one. */
export async function signIn(email: string): Promise<TokenResponse> {
  let r: Response;
  try {
    r = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
  } catch {
    throw new OfflineError("network unreachable");
  }
  if (!r.ok) {
    let detail = "sign-in was refused";
    try {
      const body = await r.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "that does not look like an email address";
    } catch {
      /* keep the default */
    }
    throw new ApiError(r.status, detail);
  }
  const body = (await r.json()) as TokenResponse;
  setToken(body.access_token);
  announceAuthChange();
  return body;
}

/** Who the server says the held token is. The only real check of a token. */
export const getMe = () => request<Me>("/api/auth/me");

export function signOut() {
  clearToken();
  announceAuthChange();
}

export async function health(): Promise<Record<string, unknown>> {
  const r = await fetch(`${API_BASE}/healthz`);
  return r.json();
}

/**
 * The digest, with ETag revalidation.
 *
 * A 304 means nothing changed, so the caller keeps the digest it already has --
 * including the token it holds, so any pending acks stay valid.
 */
export async function fetchDigest(
  etag: string | null,
  asIfLastSeen?: string | null,
): Promise<{ digest: Digest | null; etag: string | null; notModified: boolean }> {
  const token = getToken();
  const qs = new URLSearchParams();
  if (asIfLastSeen) qs.set("as_if_last_seen", asIfLastSeen);
  const url = `${API_BASE}/api/digest${qs.toString() ? `?${qs}` : ""}`;

  let res: Response;
  try {
    res = await fetch(url, {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(etag ? { "If-None-Match": etag } : {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new OfflineError("network unreachable");
  }

  if (res.status === 304) {
    return { digest: null, etag, notModified: true };
  }
  if (!res.ok) {
    if (res.status === 401) {
      clearToken();
      announceAuthChange();
    }
    throw new ApiError(res.status, res.statusText);
  }
  return {
    digest: (await res.json()) as Digest,
    etag: res.headers.get("ETag"),
    notModified: false,
  };
}

export interface AckResult {
  results: Record<string, "applied" | "superseded" | "not_found">;
}

export async function ack(token: string, tickers?: string[]): Promise<AckResult> {
  return request<AckResult>("/api/ack", {
    method: "POST",
    body: JSON.stringify({ token, tickers }),
  });
}

/**
 * Read receipts, flushed on the way out.
 *
 * `keepalive` rather than `sendBeacon`: a beacon cannot set an Authorization
 * header, so that path could not authenticate at all.
 */
export function ackKeepalive(token: string, tickers: string[]) {
  const auth = getToken();
  if (!auth || tickers.length === 0) return;
  fetch(`${API_BASE}/api/ack`, {
    method: "POST",
    keepalive: true,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth}` },
    body: JSON.stringify({ token, tickers }),
  }).catch(() => {
    // If a tab dies before the flush lands, receipts are lost and the cards
    // reappear. Showing something twice is an annoyance; hiding a critical the
    // user never read is the failure that loses trust permanently.
  });
}

export interface FeedbackEvent {
  ticker: string;
  tier: string;
  attention: number;
  shown_at?: string;
  clicked_through?: boolean;
  dismissed_fast?: boolean;
  thumb?: number | null;
}

export async function sendFeedback(events: FeedbackEvent[]) {
  if (!events.length) return;
  return request("/api/feedback", {
    method: "POST",
    body: JSON.stringify({ events }),
  });
}

export const getWatchlist = () => request<WatchlistItem[]>("/api/watchlist");

export const searchSymbols = (q: string) =>
  request<SymbolRow[]>(`/api/search?q=${encodeURIComponent(q)}`);

export const addTicker = (ticker: string) =>
  request<{ ticker: string; status: string; message: string; seed_credits_left: number }>(
    "/api/watchlist",
    { method: "POST", body: JSON.stringify({ ticker }) },
  );

export const removeTicker = (ticker: string) =>
  request<void>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });

export const getTicker = (ticker: string) =>
  request<TickerDetail>(`/api/tickers/${encodeURIComponent(ticker)}`);

export const getCalibration = () => request<Calibration>("/api/calibration");

export const getQuota = () =>
  request<{
    partitions: Record<string, { limit: number; spent: number; remaining: number }>;
    your_seed_credits_left: number;
    note: string;
  }>("/api/quota");
