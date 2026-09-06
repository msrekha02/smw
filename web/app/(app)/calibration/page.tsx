"use client";

import { useEffect, useState } from "react";
import { getCalibration } from "@/lib/api";
import { Panel } from "@/components/States";
import {
  Card,
  Gauge,
  PageHeader,
  SectionHeading,
  Skeleton,
} from "@/components/ui";
import { ResidualHistogram } from "@/components/charts/ResidualHistogram";
import type { Calibration } from "@/lib/types";

/**
 * Predicted against observed.
 *
 * Everything else in this system validates the model against itself. This page
 * is where two numbers do not: the alert rate measured by replaying a year of
 * stored bars through the production scorer, and precision@critical, the
 * fraction of criticals a human agreed with.
 */
export default function CalibrationPage() {
  const [c, setC] = useState<Calibration | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getCalibration()
      .then(setC)
      .catch((e) => setErr(e instanceof Error ? e.message : "unavailable"));
  }, []);

  if (err) return <Panel title="No calibration run yet" tone="warn" body={err} />;
  if (!c)
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );

  const p = c.precision_at_critical;

  return (
    <div className="space-y-9">
      <PageHeader
        eyebrow="Validation"
        title="Calibration"
        subtitle={
          <>
            {c.checks.toLocaleString()} checks: {c.universe} tickers replayed over{" "}
            {c.sessions} sessions through the production scorer, not a model of
            it. Rates are per {c.watchlist_size}-ticker watchlist checked once a
            day.
          </>
        }
      />

      <section>
        <SectionHeading title="Alert rate" />
        <Card className="p-4">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[26rem] text-sm">
              <thead>
                <tr className="border-b border-ink-line text-[11px] uppercase tracking-wider text-faint">
                  <th className="py-2 text-left font-medium">Tier</th>
                  <th className="py-2 text-right font-medium">
                    Predicted (normal null)
                  </th>
                  <th className="py-2 text-right font-medium">Observed</th>
                  <th className="py-2 text-right font-medium">Ratio</th>
                </tr>
              </thead>
              <tbody>
                <RateRow
                  label="Critical per week"
                  a={c.predicted.critical_per_week}
                  b={c.observed.critical_per_week}
                />
                <RateRow
                  label="Notable per day"
                  a={c.predicted.notable_per_day}
                  b={c.observed.notable_per_day}
                />
              </tbody>
            </table>
          </div>
        </Card>
        <p className="mt-2.5 max-w-3xl text-xs leading-relaxed text-faint">
          {c.notes[0]}
        </p>
      </section>

      <FatTails residual={c.residual_summary} />

      {/* An artifact generated before the histogram existed simply has no
          chart, rather than an empty frame. */}
      {c.residual_histogram && (
        <section>
          <SectionHeading title="Where the extra alerts come from" />
          <p className="mb-3 max-w-3xl text-sm leading-relaxed text-minor">
            Each bar is a day&apos;s move divided by what was normal for that
            stock at the time. The curve is what a normal distribution predicts.
          </p>
          <Card className="p-4">
            <ResidualHistogram
              hist={c.residual_histogram}
              observedTail3={c.residual_summary.tail_3s}
              normalTail3={c.residual_summary.normal_tail_3s}
            />
          </Card>
        </section>
      )}

      <section>
        <SectionHeading title="Attention distribution" />
        <Card className="p-4">
          <Histogram
            edges={c.attention_histogram.edges}
            counts={c.attention_histogram.counts}
            thresholds={c.thresholds}
          />
        </Card>
      </section>

      <section>
        <SectionHeading
          title="Precision at critical"
          aside={`last ${p.window_days} days`}
        />
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-center gap-8 sm:justify-start">
            <Gauge
              value={p.precision == null ? 0 : p.precision * 100}
              tone="var(--good)"
              display={
                p.precision == null ? "--" : `${Math.round(p.precision * 100)}%`
              }
              label="Agreed with"
            />
            <Gauge
              value={p.click_through_rate == null ? 0 : p.click_through_rate * 100}
              display={
                p.click_through_rate == null
                  ? "--"
                  : `${Math.round(p.click_through_rate * 100)}%`
              }
              label="Click-through"
            />
            <Gauge
              value={p.fast_dismiss_rate == null ? 0 : p.fast_dismiss_rate * 100}
              tone="var(--warn)"
              display={
                p.fast_dismiss_rate == null
                  ? "--"
                  : `${Math.round(p.fast_dismiss_rate * 100)}%`
              }
              label="Dismissed fast"
            />
            <div className="flex flex-col items-center gap-1.5">
              <div className="flex h-14 items-center">
                <span className="num text-2xl font-semibold text-white">
                  {p.critical_shown}
                </span>
              </div>
              <span className="text-center text-[10px] uppercase tracking-wider text-faint">
                Criticals shown
              </span>
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <div className="flex h-14 items-center">
                <span className="num text-2xl font-semibold text-white">
                  {p.explicit_judgements}
                </span>
              </div>
              <span className="text-center text-[10px] uppercase tracking-wider text-faint">
                Explicit judgements
              </span>
            </div>
          </div>
        </Card>
        <p className="mt-2.5 max-w-3xl text-xs leading-relaxed text-faint">
          {p.note} This is the only number here that checks whether
          &ldquo;meaningful&rdquo; is meaningful to a person; the rest validate the
          model against itself.
        </p>
      </section>

      <p className="text-xs text-faint">
        Generated {new Date(c.generated_at).toLocaleString()}. Re-run with{" "}
        <code className="rounded bg-white/5 px-1 font-mono">
          python -m scripts.calibrate
        </code>
        .
      </p>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Fat tails
 * ----------------------------------------------------------------------- */

const pctOf = (x: number) => `${(x * 100).toFixed(2)}%`;

interface TailRow {
  key: string;
  label: string;
  observed: number;
  normal: number;
  format: (n: number) => string;
  highlight?: boolean;
  note?: string;
}

/**
 * The comparison, as a comparison.
 *
 * The observed column on its own says nothing; every one of these numbers only
 * means something against its value under a normal distribution, so the ratio
 * is the column that carries the finding and is weighted accordingly. It is
 * computed from the two columns beside it rather than stated, so it cannot
 * drift away from them.
 */
function FatTails({ residual }: { residual: Record<string, number> }) {
  const rows: TailRow[] = [
    {
      key: "sd",
      label: "Residual sd",
      observed: residual.sd,
      // A standardised residual has unit variance and kurtosis 3 by
      // construction, so these two baselines are definitions, not measurements.
      normal: 1,
      format: (n) => n.toFixed(3),
    },
    {
      key: "kurtosis",
      label: "Kurtosis",
      observed: residual.kurtosis,
      normal: 3,
      format: (n) => n.toFixed(1),
    },
    {
      key: "tail2",
      label: "P(|z| > 2)",
      observed: residual.tail_2s,
      normal: residual.normal_tail_2s,
      format: pctOf,
    },
    {
      key: "tail3",
      label: "P(|z| > 3)",
      observed: residual.tail_3s,
      normal: residual.normal_tail_3s,
      format: pctOf,
      highlight: true,
      note: "drives the critical threshold",
    },
  ];

  return (
    <section>
      <SectionHeading title="Why the gap: fat tails" />
      <p className="mb-3 max-w-3xl text-sm leading-relaxed text-minor">
        Real returns produce far more extreme moves than a normal distribution
        predicts, so a Gaussian threshold fires more often than the maths says it
        should. Reported here rather than silently corrected for.
      </p>

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="hidden sm:table-header-group">
              <tr className="text-[11px] uppercase tracking-wider text-faint">
                <th className="px-4 py-2.5 text-left font-medium">Metric</th>
                <th className="px-4 py-2.5 text-right font-medium">Observed</th>
                <th className="px-4 py-2.5 text-right font-medium">
                  Under normal
                </th>
                <th className="px-4 py-2.5 text-right font-medium">Ratio</th>
              </tr>
            </thead>
            <tbody className="block sm:table-row-group">
              {rows.map((r) => (
                <TailRowView key={r.key} row={r} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </section>
  );
}

/**
 * One row, in two shapes.
 *
 * Above 640px it is a table row. Below it the cells become blocks and inline
 * blocks, so the metric takes a line of its own and the three figures sit under
 * it with their labels. One DOM either way, so the numbers cannot disagree.
 */
function TailRowView({ row }: { row: TailRow }) {
  const ratio = row.normal > 0 ? row.observed / row.normal : null;
  const tone =
    ratio == null
      ? "text-faint"
      : ratio >= 3
        ? "text-notable"
        : ratio >= 1.5
          ? "text-brand"
          : "text-minor";

  return (
    <tr
      className={`block border-t border-ink-line sm:table-row ${
        row.highlight ? "bg-brand/[0.07]" : ""
      }`}
    >
      <th
        scope="row"
        className={`block px-4 pb-1 pt-3 text-left align-middle font-medium text-white sm:table-cell sm:py-3 ${
          row.highlight
            ? "border-l-2 border-brand"
            : "border-l-2 border-transparent"
        }`}
      >
        {row.label}
        {row.note && (
          <span className="ml-0 block text-[11px] font-normal text-brand sm:ml-2 sm:inline">
            {row.note}
          </span>
        )}
      </th>

      <td className="inline-block px-4 pb-3 pt-1 align-middle sm:table-cell sm:py-3 sm:text-right">
        <span className="mr-1.5 text-[10px] uppercase tracking-wider text-faint sm:hidden">
          observed
        </span>
        <span className="num text-white">{row.format(row.observed)}</span>
      </td>

      <td className="inline-block pb-3 pl-0 pr-4 pt-1 align-middle sm:table-cell sm:px-4 sm:py-3 sm:text-right">
        <span className="mr-1.5 text-[10px] uppercase tracking-wider text-faint sm:hidden">
          normal
        </span>
        <span className="num text-minor">{row.format(row.normal)}</span>
      </td>

      <td className="inline-block pb-3 pr-4 pt-1 align-middle sm:table-cell sm:px-4 sm:py-3 sm:text-right">
        <span className="mr-1.5 text-[10px] uppercase tracking-wider text-faint sm:hidden">
          ratio
        </span>
        <span className={`num text-base font-semibold ${tone}`}>
          {ratio == null ? "--" : `${ratio.toFixed(1)}x`}
        </span>
      </td>
    </tr>
  );
}

/* --------------------------------------------------------------------------
 * Alert rate and histogram
 * ----------------------------------------------------------------------- */

function RateRow({ label, a, b }: { label: string; a: number; b: number }) {
  const ratio = a > 0 ? b / a : 0;
  return (
    <tr className="border-b border-white/5 last:border-0">
      <td className="py-2.5 text-left text-white/85">{label}</td>
      <td className="num py-2.5 text-right text-minor">{a.toFixed(2)}</td>
      <td className="num py-2.5 text-right text-white">{b.toFixed(2)}</td>
      <td
        className={`num py-2.5 text-right font-semibold ${
          ratio > 1.5 ? "text-notable" : "text-minor"
        }`}
      >
        {ratio ? `${ratio.toFixed(1)}x` : "--"}
      </td>
    </tr>
  );
}

function Histogram({
  edges,
  counts,
  thresholds,
}: {
  edges: number[];
  counts: number[];
  thresholds: Record<string, number>;
}) {
  const max = Math.max(...counts, 1);
  const span = edges[edges.length - 1] - edges[0] || 1;
  const mark = (v: number) => `${((v - edges[0]) / span) * 100}%`;

  return (
    <div>
      <div className="relative flex h-40 items-end gap-[2px] rounded-[10px] bg-ink-inset p-3">
        {counts.map((c, i) => (
          <div
            key={i}
            title={`${edges[i]} to ${edges[i + 1] ?? "+"}: ${c}`}
            className="flex-1 rounded-sm bg-brand/70"
            style={{ height: `${Math.max((c / max) * 100, c > 0 ? 1 : 0)}%` }}
          />
        ))}
        {(["minor", "notable", "critical"] as const).map((t) => (
          <div
            key={t}
            className="pointer-events-none absolute bottom-0 top-0 border-l border-dashed border-white/25"
            style={{ left: mark(thresholds[t]) }}
          >
            <span className="ml-1 text-[10px] text-faint">{t}</span>
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-faint">
        <span>attention 0</span>
        <span>{edges[edges.length - 1]}+</span>
      </div>
    </div>
  );
}
