"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Decomposition } from "./Decomposition";
import {
  ExpectedRangeConeCompact,
  hasCone,
} from "./charts/ExpectedRangeCone";
import { Badge, Button, Card, LiveDot, SeverityDot } from "./ui";
import { DWELL_MS, VISIBLE_RATIO, useReceipts } from "@/lib/receipts";
import {
  STATE_COPY,
  dirClass,
  money,
  pct,
  tierAccent,
  tierWash,
} from "@/lib/format";
import type { DigestCard as CardData } from "@/lib/types";

export function DigestCardView({ card }: { card: CardData }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const shownAt = useRef<number>(Date.now());
  const armed = useReceipts((s) => s.armed);
  const markRead = useReceipts((s) => s.markRead);
  const dismiss = useReceipts((s) => s.dismiss);
  const thumb = useReceipts((s) => s.thumb);
  const clickThrough = useReceipts((s) => s.clickThrough);
  const [dismissed, setDismissed] = useState(false);
  const [voted, setVoted] = useState<number | null>(null);

  // 2 continuous seconds at >=50% visibility, and only once the user has
  // actually done something. Arming on load would ack a short list before the
  // reader had oriented.
  useEffect(() => {
    if (!armed || card.state !== "ok" || card.tier === "critical") return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;

    let timer: number | undefined;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && entry.intersectionRatio >= VISIBLE_RATIO) {
          timer = window.setTimeout(
            () => markRead(card.ticker, card.tier),
            DWELL_MS,
          );
        } else if (timer) {
          window.clearTimeout(timer);
          timer = undefined;
        }
      },
      { threshold: [VISIBLE_RATIO] },
    );
    io.observe(el);
    return () => {
      if (timer) window.clearTimeout(timer);
      io.disconnect();
    };
  }, [armed, card.state, card.ticker, card.tier, markRead]);

  if (dismissed) return null;

  const isCritical = card.tier === "critical";
  const stateCopy = card.state !== "ok" ? STATE_COPY[card.state] : null;

  return (
    <Card
      ref={ref}
      interactive
      accent={tierAccent(card.tier)}
      data-ticker={card.ticker}
      className={`card-enter ${tierWash(card.tier)}`}
    >
      <article className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="mt-1.5">
              <SeverityDot severity={card.tier} />
            </span>
            <Link
              href={`/ticker/${card.ticker}`}
              onClick={() => clickThrough(card.ticker, card.tier, card.attention)}
              className="text-base font-semibold tracking-tight text-white transition-colors hover:text-brand"
            >
              {card.ticker}
            </Link>
            <span className="truncate text-xs text-faint">{card.name}</span>
            {stateCopy && <StatePill copy={stateCopy} />}
            {card.confidence === "reduced" && (
              <ConfidenceChip reasons={card.confidence_reasons} />
            )}
          </div>

          <div className="flex items-center gap-4">
            {card.price != null && (
              <div className="text-right">
                <div className="num text-base text-white">{money(card.price)}</div>
                <div className={`num text-xs ${dirClass(card.change_pct)}`}>
                  {pct(card.change_pct)}
                </div>
              </div>
            )}
            {/* The move against the range it was expected to stay inside.
                A ticker with no baseline gets no chart rather than an empty
                frame that implies a measurement nobody made. */}
            {hasCone(card.decomposition) && (
              <ExpectedRangeConeCompact
                decomposition={card.decomposition}
                tier={card.tier}
              />
            )}
          </div>
        </div>

        <p className="mt-2.5 text-sm leading-relaxed text-white/85">
          {card.reason}
        </p>

        {card.action && (
          <div className="mt-3 rounded-[10px] border border-critical/40 bg-critical/[0.07] p-3 text-xs">
            <p className="text-white/85">{card.action.message}</p>
            <p className="mt-1 text-minor">{card.action.cta}</p>
          </div>
        )}

        {card.extended_hours && (
          <p className="mt-2 text-xs text-faint">{card.extended_hours.label}</p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-faint">
          {card.freshness && <Freshness f={card.freshness} />}
          {card.since_label && <span>since {card.since_label}</span>}
          {card.decomposition && (
            <Button onClick={() => setOpen((v) => !v)} aria-expanded={open}>
              {open ? "Hide the maths" : "Show the maths"}
            </Button>
          )}

          {isCritical && card.state === "ok" && (
            <div className="ml-auto flex items-center gap-2">
              <span className="text-faint">Useful?</span>
              <Button
                className={voted === 1 ? "border-brand/60 text-white" : ""}
                onClick={() => {
                  setVoted(1);
                  thumb(card.ticker, card.tier, card.attention, 1);
                }}
              >
                Yes
              </Button>
              <Button
                className={voted === -1 ? "border-brand/60 text-white" : ""}
                onClick={() => {
                  setVoted(-1);
                  thumb(card.ticker, card.tier, card.attention, -1);
                }}
              >
                No
              </Button>
              {/* Critical cards never auto-ack. Clearing one is an explicit act. */}
              <Button
                onClick={() => {
                  const fast = Date.now() - shownAt.current < 3000;
                  dismiss(card.ticker, card.tier, card.attention, fast);
                  setDismissed(true);
                }}
              >
                Mark read
              </Button>
            </div>
          )}
        </div>

        {open && card.decomposition && (
          <Decomposition
            d={card.decomposition}
            attention={card.attention}
            tier={card.tier}
          />
        )}
      </article>
    </Card>
  );
}

function StatePill({ copy }: { copy: { label: string; tone: string } }) {
  const [color, wash] =
    copy.tone === "danger"
      ? ["#EF4444", "rgba(239,68,68,0.12)"]
      : copy.tone === "warn"
        ? ["#F59E0B", "rgba(245,158,11,0.12)"]
        : ["#8EA4BD", "rgba(255,255,255,0.05)"];
  return (
    <Badge color={color} wash={wash}>
      {copy.label}
    </Badge>
  );
}

function ConfidenceChip({ reasons }: { reasons: string[] }) {
  return (
    <Badge
      color="#F59E0B"
      wash="rgba(245,158,11,0.12)"
      title={reasons.join("; ")}
      className="cursor-help"
    >
      Reduced confidence
    </Badge>
  );
}

function Freshness({
  f,
}: {
  f: { source: string; label: string; stale: boolean };
}) {
  const live = f.label === "live" && !f.stale;
  const color = f.stale ? "var(--warn)" : live ? "var(--good)" : "var(--ink-3)";
  return (
    <span className="inline-flex items-center gap-1.5">
      <LiveDot color={color} ping={live} />
      <span>{f.stale ? `stale (${f.label})` : f.label}</span>
    </span>
  );
}
