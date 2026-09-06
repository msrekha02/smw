"use client";

import { useEffect, useState } from "react";
import { Button, Card, TextInput } from "@/components/ui";
import { ApiError, OfflineError, getAuthMode, setToken, announceAuthChange } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AuthMode } from "@/lib/types";

/**
 * Sign-in.
 *
 * No password, because there is nothing to protect yet and pretending otherwise
 * would be theatre. What this screen exists to prove is that two email
 * addresses are two users: separate watchlists, separate checkpoints, separate
 * read receipts. A Supabase deployment replaces it with a real identity
 * provider and the paste box below is how you get in meanwhile.
 */
export default function LoginPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [mode, setMode] = useState<AuthMode | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [paste, setPaste] = useState("");

  useEffect(() => {
    getAuthMode()
      .then(setMode)
      .catch(() =>
        setMode({ mode: "dev", local_login: false, notice: null }),
      );
  }, []);

  const local = mode?.local_login ?? true;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await signIn(email.trim());
    } catch (e) {
      if (e instanceof OfflineError) setErr("The API is unreachable from this browser.");
      else if (e instanceof ApiError) setErr(e.message);
      else setErr("Sign-in failed.");
      setBusy(false);
    }
  };

  // return (
  //   <div className="mx-auto max-w-md py-10">
  //     <div className="animate-in">
  //       <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-brand">
  //         Smart Market Watchlist
  //       </div>
  //       <h1 className="text-2xl font-semibold tracking-tight text-white">Sign in</h1>
  //       <p className="mt-1.5 text-sm leading-relaxed text-minor">
  //         Your watchlist, your checkpoints and your read receipts are stored
  //         against this address and nobody else&apos;s.
  //       </p>
  //     </div>

  //     <Card className="animate-in mt-6 p-6">
  //       <form onSubmit={submit}>
  //         <label
  //           htmlFor="email"
  //           className="block text-[11px] font-semibold uppercase tracking-[0.1em] text-faint"
  //         >
  //           Email
  //         </label>
  //         <TextInput
  //           id="email"
  //           type="email"
  //           autoComplete="email"
  //           autoFocus
  //           required
  //           disabled={!local}
  //           placeholder="you@example.com"
  //           value={email}
  //           onChange={(e) => setEmail(e.target.value)}
  //           className="mt-1.5"
  //         />
  //         <Button
  //           type="submit"
  //           variant="primary"
  //           disabled={busy || !local || !email.trim()}
  //           className="mt-3 w-full py-2.5 text-sm"
  //         >
  //           {busy ? "Signing in..." : "Continue"}
  //         </Button>
  //       </form>

  //       {err && <p className="mt-3 text-xs text-critical">{err}</p>}

  //       {local ? (
  //         <p className="mt-5 rounded-[10px] border border-notable/30 bg-notable/[0.07] px-3 py-2.5 text-[11px] leading-relaxed text-notable">
  //           Dev auth — any email signs in. Set{" "}
  //           <code className="font-mono">SUPABASE_JWKS_URL</code> to enable real
  //           JWT verification.
  //         </p>
  //       ) : (
  //         <p className="mt-5 rounded-[10px] border border-ink-line bg-ink-inset px-3 py-2.5 text-[11px] leading-relaxed text-minor">
  //           Local sign-in is off because a Supabase project is configured. Tokens
  //           come from Supabase Auth and are verified against its JWKS.
  //         </p>
  //       )}
  //     </Card>

  //     <details className="mt-4 text-xs text-faint">
  //       <summary className="cursor-pointer hover:text-minor">
  //         Paste a Supabase token instead
  //       </summary>
  //       <textarea
  //         value={paste}
  //         onChange={(e) => setPaste(e.target.value)}
  //         rows={3}
  //         placeholder="eyJhbGciOi..."
  //         className="mt-2 w-full rounded-[10px] border border-ink-line bg-ink-inset p-2.5 font-mono text-[11px] text-white outline-none focus:border-brand/60"
  //       />
  //       <Button
  //         className="mt-2"
  //         onClick={() => {
  //           if (!paste.trim()) return;
  //           setToken(paste.trim());
  //           // The provider re-checks the token against `/api/auth/me` and
  //           // redirects, so a token that does not verify never gets in.
  //           announceAuthChange();
  //         }}
  //       >
  //         Use this token
  //       </Button>
  //     </details>

  //     <p className="mt-8 text-[11px] leading-relaxed text-faint">
  //       No API keys are required. The stack boots on recorded fixtures, so the
  //       whole product works at any hour.
  //     </p>
  //   </div>
  // );
  return (
    <div className="mx-auto max-w-md py-10">
      <div className="animate-in">
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-brand">
          Smart Market Watchlist
        </div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Sign in</h1>
        <p className="mt-1.5 text-sm leading-relaxed text-minor">
          Your watchlist, your checkpoints and your read receipts are stored
          against this address and nobody else&apos;s.
        </p>
      </div>

      <Card className="animate-in mt-6 p-6">
        <form onSubmit={submit}>
          <label
            htmlFor="email"
            className="block text-[11px] font-semibold uppercase tracking-[0.1em] text-faint"
          >
            Email
          </label>
          <TextInput
            id="email"
            type="email"
            autoComplete="email"
            autoFocus
            required
            disabled={!local}
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1.5"
          />
          <Button
            type="submit"
            variant="primary"
            disabled={busy || !local || !email.trim()}
            className="mt-3 w-full py-2.5 text-sm"
          >
            {busy ? "Signing in..." : "Continue"}
          </Button>
        </form>

        {err && <p className="mt-3 text-xs text-critical">{err}</p>}
      </Card>
    </div>
  );
}
