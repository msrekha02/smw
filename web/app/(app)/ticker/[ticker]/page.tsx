"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { getTicker } from "@/lib/api";
import { Panel } from "@/components/States";
import { Badge, Card, PageHeader, SectionHeading, Skeleton } from "@/components/ui";
import { compact, money, pct, sectorLabel } from "@/lib/format";
import type { TickerDetail } from "@/lib/types";

export default function TickerPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = use(params);
  const [d, setD] = useState<TickerDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getTicker(ticker)
      .then(setD)
      .catch((e) => setErr(e instanceof Error ? e.message : "not found"));
  }, [ticker]);

  if (err) return <Panel title={ticker.toUpperCase()} tone="warn" body={err} />;
  if (!d)
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-28 w-full" />
      </div>
    );

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/digest"
          className="text-xs text-faint transition-colors hover:text-white"
        >
          &larr; Digest
        </Link>
        <div className="mt-2">
          <PageHeader
            eyebrow={sectorLabel(d.instrument_class, d.sector)}
            title={d.ticker}
            subtitle={
              <>
                {d.name} &middot; benchmarked to{" "}
                {d.benchmark_ticker ?? "nothing (broad ETF, beta pinned to 0)"}{" "}
                &middot; {d.sample_days} sessions of history
              </>
            }
          />
        </div>
      </div>

      {d.frozen_reason && (
        <Panel title="Scores paused" tone="danger" body={d.frozen_reason} />
      )}

      <Card className="p-5">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-xs sm:grid-cols-4">
          <Stat k="Beta (used)" v={d.beta_used?.toFixed(2) ?? "--"} />
          <Stat k="Beta (raw)" v={d.beta_raw?.toFixed(2) ?? "--"} />
          <Stat k="R-squared" v={d.r2?.toFixed(2) ?? "--"} />
          <Stat k="Daily sigma" v={pct(d.sigma_idio, 2)} />
          <Stat k="52-week high" v={money(d.wk52_high)} />
          <Stat k="52-week low" v={money(d.wk52_low)} />
          <Stat k="Avg volume (20d)" v={compact(d.adv20)} />
          <Stat k="Last bar" v={d.last_bar_date ?? "--"} />
        </dl>
      </Card>

      {d.beta_used != null && d.beta_raw != null && d.beta_used !== d.beta_raw && (
        <p className="max-w-3xl text-xs leading-relaxed text-faint">
          The raw regression slope is {d.beta_raw.toFixed(2)}; scoring uses{" "}
          {d.beta_used.toFixed(2)}, shrunk toward 1.0 in proportion to how much of
          this stock&apos;s variance the sector actually explains. A confident beta
          from a poorly-explained regression is the likeliest source of a false
          critical.
        </p>
      )}

      <Residuals d={d} />
      <Earnings dates={d.earnings} />
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-faint">{k}</dt>
      <dd className="num mt-1 text-sm text-white">{v}</dd>
    </div>
  );
}

/**
 * The empirical distribution of standardised residuals.
 *
 * Collected during the seed pass at the cost of one array append inside a loop
 * that already runs. Shown for honesty about how non-normal this ticker really
 * is; deliberately NOT used for scoring.
 */
function Residuals({ d }: { d: TickerDetail }) {
  const h = d.residual_hist;
  if (!h || !h.n) return null;
  const max = Math.max(...h.counts, 1);
  const width = (h.hi - h.lo) / h.bins;

  // A normal curve at the same scale, so the reader can see the gap.
  const normal = h.counts.map((_, i) => {
    const x = h.lo + width * (i + 0.5);
    return (Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI)) * width * h.n;
  });
  const normalMax = Math.max(...normal, 1);

  return (
    <section>
      <SectionHeading title="Residual distribution" aside={`${h.n} sessions`} />
      <p className="mb-3 max-w-3xl text-xs leading-relaxed text-faint">
        {h.n} standardised daily residuals. If returns were normal the bars would
        follow the outline. They do not: {(h.tail_3s * 100).toFixed(2)}% of days
        exceed 3 sigma against 0.27% under a normal, and kurtosis is{" "}
        {h.kurtosis.toFixed(1)} against 3.
      </p>

      <Card className="p-4">
        <div className="flex h-32 items-end gap-[2px] rounded-[10px] bg-ink-inset p-3">
          {h.counts.map((c, i) => (
            <div key={i} className="relative flex-1">
              <div
                className="w-full rounded-sm bg-brand/70"
                style={{ height: `${(c / max) * 100}px` }}
                title={`${(h.lo + width * i).toFixed(1)}σ to ${(
                  h.lo +
                  width * (i + 1)
                ).toFixed(1)}σ: ${c}`}
              />
              <div
                className="absolute bottom-0 left-0 w-full border-t border-notable/60"
                style={{ height: `${(normal[i] / normalMax) * 100}px` }}
              />
            </div>
          ))}
        </div>
        <div className="mt-1.5 flex justify-between text-[10px] text-faint">
          <span>{h.lo}σ</span>
          <span>0</span>
          <span>+{h.hi}σ</span>
        </div>
      </Card>
      <p className="mt-2.5 text-xs text-faint">{d.scoring_note}</p>
    </section>
  );
}

function Earnings({ dates }: { dates: string[] }) {
  if (!dates.length) return null;
  return (
    <section>
      <SectionHeading title="Earnings" />
      <p className="mb-3 max-w-3xl text-xs leading-relaxed text-faint">
        Earnings widens the expected range on those days; it never adds score. A
        large move on a scheduled catalyst is less surprising than the same move
        on a random Tuesday.
      </p>
      <div className="flex flex-wrap gap-1.5">
        {dates.slice(0, 16).map((d) => (
          <Badge key={d} className="num" color="var(--ink-2)">
            {d}
          </Badge>
        ))}
      </div>
    </section>
  );
}
