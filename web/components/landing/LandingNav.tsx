"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

const SECTIONS = [
  { id: "problem", label: "Problem" },
  { id: "how", label: "How it works" },
  { id: "features", label: "Features" },
  { id: "evidence", label: "Evidence" },
];

const NAV_H = 72;

export function LandingNav() {
  const { status } = useAuth();
  const [active, setActive] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  const signedIn = status === "authed";

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const targets = SECTIONS.map((s) => document.getElementById(s.id)).filter(
      (el): el is HTMLElement => el !== null,
    );
    if (!targets.length) return;

    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: `-${NAV_H + 8}px 0px -55% 0px`, threshold: 0 },
    );
    targets.forEach((t) => io.observe(t));
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    let lastScrollY = window.scrollY;

    const handleScroll = () => {
      const currentScrollY = window.scrollY;
      
      if (currentScrollY > 40 && currentScrollY > lastScrollY) {
        setScrolled(true);
      } else if (currentScrollY < lastScrollY || currentScrollY <= 40) {
        setScrolled(false);
      }
      
      lastScrollY = currentScrollY;
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header className="fixed top-0 left-0 right-0 z-50 w-full pt-5 px-4 sm:px-8 transition-all duration-500">
      <div
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={`mx-auto max-w-6xl rounded-2xl transition-all duration-500 ${
          scrolled && !isHovered
            ? "bg-black/30 backdrop-blur-md border border-white/5 shadow-none"
            : "bg-[var(--surface-0)]/40 backdrop-blur-xl border border-white/10 shadow-[0_8px_32px_0_rgba(0,0,0,0.36),0_0_20px_0_var(--brand-glow)]"
        }`}
      >
        <div className="flex h-16 w-full items-center justify-between px-6 sm:px-8">
          {/* Brand Logo & Name */}
          <Link
            href="/"
            className="flex items-center gap-3 group shrink-0"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--brand)]/20 border border-[var(--brand)]/40 text-[var(--brand)] group-hover:scale-105 group-hover:border-[var(--brand)] group-hover:shadow-[0_0_15px_var(--brand-glow)] transition-all duration-300">
              <span className="text-base font-bold tracking-wider">S</span>
            </div>
            <span className="text-base font-semibold tracking-tight text-white/90 group-hover:text-white transition-colors">
              Smart Market Watchlist
            </span>
          </Link>

          {/* Navigation Links Pill */}
          <nav
            aria-label="Sections"
            className="hidden items-center gap-1.5 md:flex bg-white/[0.03] p-1.5 rounded-full border border-white/10 backdrop-blur-md"
          >
            {SECTIONS.map((s) => {
              const isActive = active === s.id;
              return (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  aria-current={isActive ? "location" : undefined}
                  className={`rounded-full px-5 py-1.5 text-sm font-medium transition-all duration-200 ${
                    isActive
                      ? "bg-white/10 text-white border border-white/15 shadow-sm"
                      : "text-white/60 hover:text-white hover:bg-white/5"
                  }`}
                >
                  {s.label}
                </a>
              );
            })}
          </nav>

          {/* Action Button */}
          <div className="shrink-0">
            <Link
              href={signedIn ? "/digest" : "/login"}
              className="relative inline-flex items-center justify-center rounded-full bg-[var(--brand)]/20 border border-[var(--brand)]/50 px-6 py-2 text-sm font-semibold text-white backdrop-blur-sm transition-all duration-300 hover:bg-[var(--brand)] hover:shadow-[0_0_25px_var(--brand-glow)] hover:scale-105"
            >
              {signedIn ? "Open app" : "Sign In"}
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}