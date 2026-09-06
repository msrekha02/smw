"use client";

import type { Decomposition as D, Tier } from "@/lib/types";
import { pct, sigma } from "@/lib/format";
import { DecompositionWaterfall } from "./charts/DecompositionWaterfall";
import { ExpectedRangeCone, hasCone } from "./charts/ExpectedRangeCone";

const BAR_COLORS: Record<string, string> = {
  move: "bg-brand",
  path: "bg-[#8B5CF6]",
  volume: "bg-[#2DD4BF]",
  breach: "bg-notable",
};

const BAR_LABEL: Record<string, string> = {
  move: "Displacement",
  path: "Path",
  volume: "Volume",
  breach: "52-week breach",
};

/**
 * The panel that shows its work.
 *
 * Every number here was used in the score, so the arithmetic on screen is the
 * arithmetic that produced the ranking. The contributions sum to the attention
 * score exactly.
 */
export function Decomposition({
  d,
  attention,
  tier,
}: {
  d: D;
  attention: number;
  tier: Tier;
}) {
  const entries = Object.entries(d.contributions) as Array<[string, number]>;
  const max = Math.max(...entries.map(([, v]) => v), 0.001);

  return (
    <div className="mt-3 space-y-4 rounded-[12px] border border-ink-line bg-ink-inset p-4 text-xs">
      {hasCone(d) && (
        <section>
          <ExpectedRangeCone decomposition={d} tier={tier} />
        </section>
      )}

      {/* The chart supplements the table below rather than replacing it: the
          table is the arithmetic, the chart is what it means. */}
      <section>
        <DecompositionWaterfall decomposition={d} tier={tier} />
      </section>

      <section>
        <h4 className="mb-2 font-medium text-white/80">How the move was split</h4>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
          <Row k="Price move" v={pct(d.cum_return)} />
          <Row
            k={`${d.bench_ticker ?? "Benchmark"} move`}
            v={d.beta_used === 0 ? "not applied" : pct(d.bench_return)}
          />
          <Row
            k="Beta used"
            v={
              d.beta_used === 0
                ? "0 (pinned)"
                : `${d.beta_used.toFixed(2)}${
                    d.beta_raw != null ? ` (raw ${d.beta_raw.toFixed(2)})` : ""
                  }`
            }
          />
          <Row k="Idiosyncratic" v={pct(d.excess)} strong />
          <Row k="Daily sigma" v={pct(d.sigma_idio)} />
          <Row k="R-squared" v={d.r2 == null ? "--" : d.r2.toFixed(2)} />
        </dl>
        <p className="mt-2 leading-relaxed text-minor">
          {d.beta_used === 0
            ? "Benchmarked against nothing, so the whole move is its own."
            : `Idiosyncratic = price move minus beta times the ${
                d.bench_ticker ?? "benchmark"
              } move.`}
        </p>
      </section>

      <section>
        <h4 className="mb-2 font-medium text-white/80">Expected range</h4>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
          <Row k="Sessions in window" v={d.n_eff.toFixed(2)} />
          <Row k="Expected sigma" v={pct(d.sigma_expected)} />
          <Row k="z (displacement)" v={sigma(d.z_move)} strong />
          <Row k="z (largest day)" v={sigma(d.z_path)} />
          <Row
            k="Peak volume"
            v={`${d.vol_ratio.toFixed(1)}x normal`}
          />
          <Row
            k="52-week"
            v={
              d.breach_direction
                ? `new ${d.breach_direction}`
                : "inside its range"
            }
          />
        </dl>
        {d.earnings_note && (
          <p className="mt-2 rounded border border-notable/30 bg-notable/[0.06] p-2 leading-relaxed text-notable">
            {d.earnings_note}
          </p>
        )}
      </section>

      <section>
        <h4 className="mb-2 font-medium text-white/80">
          Attention {attention.toFixed(2)}
        </h4>
        <div className="space-y-1.5">
          {entries.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <span className="w-28 shrink-0 text-minor">{BAR_LABEL[k] ?? k}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-sm bg-white/5">
                <div
                  className={`h-full rounded-sm ${BAR_COLORS[k] ?? "bg-white/40"}`}
                  style={{ width: `${(v / max) * 100}%` }}
                />
              </div>
              <span className="num w-10 shrink-0 text-right text-minor">
                {v.toFixed(2)}
              </span>
              <span className="num w-12 shrink-0 text-right text-white/30">
                x{d.weights[k]?.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-minor">
          Built from absolute magnitudes, with direction carried separately, so a
          crash cannot sort below a small gain.
        </p>
      </section>
    </div>
  );
}

function Row({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-white/5 py-1">
      <dt className="text-minor">{k}</dt>
      <dd className={`num ${strong ? "text-white" : "text-white/70"}`}>{v}</dd>
    </div>
  );
}
