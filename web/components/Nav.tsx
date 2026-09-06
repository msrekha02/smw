"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AccountMenu } from "./AccountMenu";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/digest", label: "Digest" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/calibration", label: "Calibration" },
];

export function Nav() {
  const pathname = usePathname();
  const { status } = useAuth();
  const signedIn = status === "authed";

  return (
    <header className="sticky top-0 z-30 border-b border-ink-line bg-ink/85 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-5 px-5 py-3">
        <Link
          href={signedIn ? "/digest" : "/login"}
          className="shrink-0 text-sm font-semibold tracking-tight text-white"
        >
          Smart Market Watchlist
        </Link>

        {/* The nav is not offered to someone who cannot follow it. */}
        {signedIn && (
          <nav className="flex min-w-0 items-center gap-1 overflow-x-auto text-sm">
            {LINKS.map((l) => {
              const on =
                pathname === l.href || pathname.startsWith(`${l.href}/`);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={on ? "page" : undefined}
                  className={`rounded-[9px] px-2.5 py-1 transition-colors ${
                    on
                      ? "bg-ink-raised text-white"
                      : "text-minor hover:text-white"
                  }`}
                >
                  {l.label}
                </Link>
              );
            })}
          </nav>
        )}

        <div className="ml-auto shrink-0">
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
