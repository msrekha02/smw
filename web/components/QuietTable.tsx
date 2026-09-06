"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { dirClass, money, pct } from "@/lib/format";
import type { DigestCard } from "@/lib/types";

const ROW_H = 34;
const OVERSCAN = 6;

/**
 * The collapsed tail of the list.
 *
 * Minor and quiet rows are the majority on any ordinary day and none of them
 * deserve a card. Virtualised because a 100-ticker watchlist should not render
 * 100 rows to show eight.
 */
export function QuietTable({
  cards,
  summary,
}: {
  cards: DigestCard[];
  summary: string | null;
}) {
  const [open, setOpen] = useState(false);
  const scroller = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const viewportH = Math.min(cards.length * ROW_H, 340);

  const { start, end, padTop } = useMemo(() => {
    const s = Math.max(Math.floor(scrollTop / ROW_H) - OVERSCAN, 0);
    const e = Math.min(
      Math.ceil((scrollTop + viewportH) / ROW_H) + OVERSCAN,
      cards.length,
    );
    return { start: s, end: e, padTop: s * ROW_H };
  }, [scrollTop, viewportH, cards.length]);

  if (!cards.length) return null;

  return (
    <section className="mt-6">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between rounded-card border border-ink-line bg-ink-soft px-4 py-2.5 text-left text-sm transition-colors hover:border-brand/50"
      >
        <span className="text-white/85">
          {cards.length} {cards.length === 1 ? "name" : "names"} inside their normal
          range
        </span>
        <span className="text-xs text-faint">{open ? "Hide" : "Show"}</span>
      </button>

      {summary && !open && (
        <p className="mt-2 px-1 text-xs text-faint">{summary}</p>
      )}

      {open && (
        <div
          ref={scroller}
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
          style={{ maxHeight: 340 }}
          className="mt-2 overflow-y-auto rounded-card border border-ink-line bg-ink-soft"
        >
          <div style={{ height: cards.length * ROW_H, position: "relative" }}>
            <div style={{ transform: `translateY(${padTop}px)` }}>
              {cards.slice(start, end).map((c) => (
                <div
                  key={c.ticker}
                  style={{ height: ROW_H }}
                  className="flex items-center gap-3 border-b border-white/5 px-3 text-xs last:border-0"
                >
                  <Link
                    href={`/ticker/${c.ticker}`}
                    className="w-16 shrink-0 font-semibold text-white transition-colors hover:text-brand"
                  >
                    {c.ticker}
                  </Link>
                  <span className="num w-20 shrink-0 text-right text-white/80">
                    {money(c.price)}
                  </span>
                  <span
                    className={`num w-20 shrink-0 text-right ${dirClass(c.change_pct)}`}
                  >
                    {pct(c.change_pct)}
                  </span>
                  <span className="num w-16 shrink-0 text-right text-faint">
                    {c.decomposition ? `${c.decomposition.z_move.toFixed(1)}σ` : "--"}
                  </span>
                  <span className="truncate text-minor">{c.reason}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
