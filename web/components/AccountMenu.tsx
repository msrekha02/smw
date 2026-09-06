"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Button } from "./ui";

/**
 * Who you are signed in as, and the way out.
 *
 * The address is shown rather than an avatar or a first name: the whole point
 * of this control is to make it obvious which of two test users you are
 * currently looking at.
 */
export function AccountMenu() {
  const { status, email, mode, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (status !== "authed") return null;

  const label = email ?? "signed in";
  const initial = (email ?? "?").trim().charAt(0).toUpperCase();

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-2 rounded-full border border-ink-line py-1 pl-1 pr-3 text-xs text-minor transition-colors hover:border-brand/50 hover:text-white"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink-raised text-[11px] font-semibold text-white">
          {initial}
        </span>
        <span className="hidden max-w-[16ch] truncate sm:block">{label}</span>
      </button>

      {open && (
        <div
          role="menu"
          className="animate-in absolute right-0 z-40 mt-2 w-64 rounded-card border border-ink-line bg-ink-soft p-3 shadow-bento"
        >
          <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-faint">
            Signed in as
          </div>
          <div className="mt-1 truncate text-sm text-white" title={label}>
            {label}
          </div>
          <div className="mt-1 text-[11px] text-faint">
            {mode === "supabase"
              ? "Supabase JWT, verified against the project JWKS"
              : "Local dev token, HS256"}
          </div>
          <Button
            className="mt-3 w-full"
            onClick={() => {
              setOpen(false);
              signOut();
            }}
          >
            Sign out
          </Button>
        </div>
      )}
    </div>
  );
}
