"use client";

/**
 * Read receipts.
 *
 * A card marks read after 2 continuous seconds at >=50% visibility -- but the
 * observer does not arm until the first user interaction. Arming on load routes
 * around "never ack on page load" through the viewport path: on a short list
 * where everything fits on screen, the whole digest would ack while the user is
 * still orienting.
 *
 * Critical cards NEVER auto-ack. They require an explicit dismissal, because
 * that is where a wrongly-cleared diff costs the most trust.
 *
 * Receipts batch for 5 seconds and flush on `visibilitychange -> hidden` and
 * `pagehide` with `fetch(..., {keepalive: true})`. If a tab dies before the
 * flush, receipts are lost and the cards reappear. That is the correct
 * direction to fail.
 */

import { create } from "zustand";
import { ack, ackKeepalive, sendFeedback, type FeedbackEvent } from "./api";

export const DWELL_MS = 2000;
export const VISIBLE_RATIO = 0.5;
export const FLUSH_MS = 5000;

interface ReceiptState {
  armed: boolean;
  token: string | null;
  pending: Set<string>;
  acked: Set<string>;
  feedback: FeedbackEvent[];
  lastResults: Record<string, string>;

  arm: () => void;
  setToken: (t: string | null) => void;
  markRead: (ticker: string, tier: string) => void;
  dismiss: (ticker: string, tier: string, attention: number, fast: boolean) => void;
  thumb: (ticker: string, tier: string, attention: number, value: number) => void;
  clickThrough: (ticker: string, tier: string, attention: number) => void;
  impression: (events: FeedbackEvent[]) => void;
  flush: (keepalive?: boolean) => Promise<void>;
  reset: () => void;
}

export const useReceipts = create<ReceiptState>((set, get) => ({
  armed: false,
  token: null,
  pending: new Set(),
  acked: new Set(),
  feedback: [],
  lastResults: {},

  arm: () => {
    if (!get().armed) set({ armed: true });
  },

  setToken: (t) => set({ token: t }),

  markRead: (ticker, tier) => {
    // The rule that makes the mechanic trustworthy, enforced in the store
    // rather than in each caller.
    if (tier === "critical") return;
    const { pending, acked } = get();
    if (acked.has(ticker) || pending.has(ticker)) return;
    const next = new Set(pending);
    next.add(ticker);
    set({ pending: next });
  },

  dismiss: (ticker, tier, attention, fast) => {
    const next = new Set(get().pending);
    next.add(ticker);
    set({
      pending: next,
      feedback: [
        ...get().feedback,
        { ticker, tier, attention, dismissed_fast: fast },
      ],
    });
  },

  thumb: (ticker, tier, attention, value) =>
    set({ feedback: [...get().feedback, { ticker, tier, attention, thumb: value }] }),

  clickThrough: (ticker, tier, attention) =>
    set({
      feedback: [...get().feedback, { ticker, tier, attention, clicked_through: true }],
    }),

  impression: (events) => set({ feedback: [...get().feedback, ...events] }),

  flush: async (keepalive = false) => {
    const { token, pending, feedback, acked } = get();
    const tickers = [...pending];

    if (feedback.length) {
      set({ feedback: [] });
      if (!keepalive) await sendFeedback(feedback).catch(() => undefined);
    }
    if (!token || tickers.length === 0) return;

    if (keepalive) {
      ackKeepalive(token, tickers);
      const merged = new Set(acked);
      tickers.forEach((t) => merged.add(t));
      set({ pending: new Set(), acked: merged });
      return;
    }

    try {
      const res = await ack(token, tickers);
      const merged = new Set(acked);
      // Only clear what the server actually applied or already had. A
      // `not_found` stays pending so a transient race does not silently drop
      // the receipt.
      Object.entries(res.results).forEach(([t, outcome]) => {
        if (outcome === "applied" || outcome === "superseded") merged.add(t);
      });
      const stillPending = new Set(
        tickers.filter((t) => res.results[t] === "not_found"),
      );
      set({ pending: stillPending, acked: merged, lastResults: res.results });
    } catch {
      // Keep them pending; the next flush retries.
    }
  },

  reset: () =>
    set({ pending: new Set(), acked: new Set(), feedback: [], lastResults: {} }),
}));

/** Arm on the first real interaction, then never again. */
export function installArmListeners() {
  if (typeof window === "undefined") return () => undefined;
  const arm = () => useReceipts.getState().arm();
  const opts = { passive: true, once: true } as AddEventListenerOptions;
  window.addEventListener("scroll", arm, opts);
  window.addEventListener("pointerdown", arm, opts);
  window.addEventListener("keydown", arm, opts);
  window.addEventListener("wheel", arm, opts);
  window.addEventListener("touchstart", arm, opts);
  return () => {
    window.removeEventListener("scroll", arm);
    window.removeEventListener("pointerdown", arm);
    window.removeEventListener("keydown", arm);
    window.removeEventListener("wheel", arm);
    window.removeEventListener("touchstart", arm);
  };
}

export function installFlushListeners() {
  if (typeof window === "undefined") return () => undefined;
  const onHide = () => {
    if (document.visibilityState === "hidden") {
      void useReceipts.getState().flush(true);
    }
  };
  const onPageHide = () => void useReceipts.getState().flush(true);
  document.addEventListener("visibilitychange", onHide);
  window.addEventListener("pagehide", onPageHide);
  const timer = window.setInterval(() => {
    void useReceipts.getState().flush(false);
  }, FLUSH_MS);
  return () => {
    document.removeEventListener("visibilitychange", onHide);
    window.removeEventListener("pagehide", onPageHide);
    window.clearInterval(timer);
  };
}
