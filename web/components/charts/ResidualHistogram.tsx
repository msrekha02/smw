"use client";

/**
 * Chart 3: the distribution behind the fat-tails table.
 *
 * The table above it asserts that the tails are heavier than a normal; this is
 * that assertion drawn, with the normal scaled to the same area so the two are
 * directly comparable rather than merely adjacent. The shaded |u| > 3 regions
 * are the alerts the table's last row is about.
 */

import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  ReferenceArea,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import type { ResidualHistogram as Hist } from "@/lib/types";

const TAIL = 3;

const normalPdf = (x: number) => Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);

export function ResidualHistogram({
  hist,
  observedTail3,
  normalTail3,
}: {
  hist: Hist;
  observedTail3: number;
  normalTail3: number;
}) {
  const width = (hist.hi - hist.lo) / hist.bins;

  // The normal is scaled to the same total area, so its height is comparable to
  // the bars rather than merely the same shape.
  const rows = hist.counts.map((count, i) => {
    const mid = hist.lo + width * (i + 0.5);
    return {
      mid,
      // An empty bin is a gap, not a zero-height bar: a log axis has no zero,
      // and drawing one there would claim an observation nobody made.
      count: count > 0 ? count : null,
      normal: normalPdf(mid) * width * hist.n,
    };
  });

  // A log count axis, because the tails ARE the finding and on a linear axis
  // they are invisible: the centre bin holds two thousand observations and the
  // 4-sigma bins hold ten, so both the observed bar and the normal curve read
  // as zero height and the chart appears to disprove its own caption. On a log
  // axis the gap between the bars and the curve out in the tails is the thing
  // you actually see.
  const pct = (x: number) => `${(x * 100).toFixed(2)}%`;
  const label =
    `Distribution of ${hist.n.toLocaleString()} standardised daily residuals ` +
    `against a standard normal scaled to the same area. ` +
    `${pct(observedTail3)} of observations fall beyond three sigma, where a ` +
    `normal distribution predicts ${pct(normalTail3)}.`;

  return (
    <div>
      <div className="h-56 w-full" role="img" aria-label={label}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 8, bottom: 18, left: 4 }}
          >
            <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />

            {/* Drawn first so the bars and the curve sit on top of the shading. */}
            <ReferenceArea
              x1={hist.lo}
              x2={-TAIL}
              fill="#EF4444"
              fillOpacity={0.13}
              stroke="none"
            />
            <ReferenceArea
              x1={TAIL}
              x2={hist.hi}
              fill="#EF4444"
              fillOpacity={0.13}
              stroke="none"
            />

            <XAxis
              dataKey="mid"
              type="number"
              domain={[hist.lo, hist.hi]}
              ticks={[-8, -6, -4, -3, 0, 3, 4, 6, 8]}
              tick={{ fill: "#5C738A", fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
              tickFormatter={(v: number) => `${v}`}
              label={{
                value: "standardised residual (sigma)",
                position: "insideBottom",
                offset: -10,
                fill: "#5C738A",
                fontSize: 10,
              }}
            />
            <YAxis
              scale="log"
              domain={[0.8, "dataMax"]}
              allowDataOverflow
              ticks={[1, 10, 100, 1000]}
              tick={{ fill: "#5C738A", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={44}
              tickFormatter={(v: number) =>
                v >= 1000 ? `${v / 1000}k` : String(v)
              }
              label={{
                value: "days (log)",
                angle: -90,
                position: "insideLeft",
                fill: "#5C738A",
                fontSize: 10,
                style: { textAnchor: "middle" },
              }}
            />

            <Bar
              dataKey="count"
              fill="#4F8FE8"
              fillOpacity={0.75}
              isAnimationActive={false}
            />
            <Area
              dataKey="normal"
              type="monotone"
              stroke="#F59E0B"
              strokeWidth={1.6}
              fill="none"
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-minor">
        <span className="text-critical">{pct(observedTail3)}</span> of
        observations sit in the shaded regions beyond three sigma; a normal
        distribution predicts{" "}
        <span className="text-notable">{pct(normalTail3)}</span>.
      </p>
    </div>
  );
}
