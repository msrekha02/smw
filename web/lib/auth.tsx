"use client";

/**
 * Session state for the whole app.
 *
 * A token in `localStorage` is a claim, not a session, so the provider asks the
 * server who it belongs to before letting anything render. That one round trip
 * is what makes an expired or foreign token fail on boot rather than on
 * whichever page happens to need data first.
 *
 * Sign-out clears the token and the read receipts together: receipts are keyed
 * to a digest issued for one user, and carrying them across a sign-in would ack
 * one person's cards against another's checkpoints.
 */

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  AUTH_EVENT,
  getMe,
  signIn as apiSignIn,
  signOut as apiSignOut,
  tokenLooksLive,
} from "./api";
import { useReceipts } from "./receipts";

export type AuthStatus = "loading" | "authed" | "anon";

interface AuthValue {
  status: AuthStatus;
  email: string | null;
  userId: string | null;
  /** "dev" for the local HS256 issuer, "supabase" once JWKS is configured. */
  mode: string | null;
  signIn: (email: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue>({
  status: "loading",
  email: null,
  userId: null,
  mode: null,
  signIn: async () => undefined,
  signOut: () => undefined,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [email, setEmail] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [mode, setMode] = useState<string | null>(null);
  const resetReceipts = useReceipts((s) => s.reset);

  const anon = useCallback(() => {
    setStatus("anon");
    setEmail(null);
    setUserId(null);
    setMode(null);
  }, []);

  const refresh = useCallback(async () => {
    // An expired token is knowable without a round trip, so skip the request
    // that is certain to 401.
    if (!tokenLooksLive()) {
      anon();
      return;
    }
    try {
      const me = await getMe();
      setEmail(me.email);
      setUserId(me.user_id);
      setMode(me.mode);
      setStatus("authed");
    } catch {
      // Includes the offline case. Treating an unreachable API as signed out is
      // the safe direction: the alternative shows a shell that cannot load.
      anon();
    }
  }, [anon]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Sign-in and sign-out in one tab, and a 401 anywhere in the app, both land
  // here. `storage` covers the same user in a second tab.
  useEffect(() => {
    const onChange = () => void refresh();
    window.addEventListener(AUTH_EVENT, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(AUTH_EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  }, [refresh]);

  const signIn = useCallback(
    async (address: string) => {
      resetReceipts();
      const body = await apiSignIn(address);
      setEmail(body.email);
      setUserId(body.user_id);
      setStatus("authed");
      router.replace("/digest");
    },
    [resetReceipts, router],
  );

  const signOut = useCallback(() => {
    resetReceipts();
    apiSignOut();
    anon();
    router.replace("/login");
  }, [anon, resetReceipts, router]);

  const value = useMemo(
    () => ({ status, email, userId, mode, signIn, signOut }),
    [status, email, userId, mode, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
