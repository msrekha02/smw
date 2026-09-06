"use client";

/**
 * Chart 1: the move against the range it was expected to stay inside.
 *
 * The cone is `sigma_idio * sqrt(t)`, which is the same dispersion the scorer
 * divides by, so a line leaving the outer cone is exactly a |z| above 2 and the
 * picture cannot disagree with the number beside it.
 *
 * The path itself is sliced server-side by `signals.window_days`, the function
 * the scorer uses to decide which sessions are in the window. Re-deriving that
 * slice here would put a chart on screen that quietly disagrees with the score.
 */

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { severityColor } from "@/components/ui";
import type { Decomposition, Tier } from "@/lib/types";

/** How many points to sample the cone at. The path itself is never resampled. */
const CONE_SAMPLES = 56;

/**
 * The cone is the range a move was expected to stay inside, so it is drawn
 * neutral. Painting it in the tier colour would make an in-range move look
 * alarming, which is the opposite of what the chart is for: the tier colour
 * appears only where the line actually leaves the outer cone.
 */
const CONE = "#8EA4BD";
const INSIDE = "#E6ECF3";

interface Row {
  t: number;
  band1: [number, number];
  band2: [number, number];
  /** Present only at real observations, so the line is never interpolated. */
  cum?: number;
  /** The same value, present only where it sits outside the outer cone. */
  outside?: number;
  d?: string;
  z?: number;
}

/**
 * Merge the cone grid and the observed path into one series.
 *
 * Recharts needs a single array, so the cone is sampled on its own grid and the
 * observations are inserted at their own `t`. Cone-only rows carry no `cum`,
 * which is what keeps the line from inventing points between sessions.
 */
function buildSeries(d: Decomposition): { rows: Row[]; tMax: number } {
  const sigma = d.sigma_idio;
  const path = d.window_path;
  const tMax = Math.max(path[path.length - 1]?.t ?? 0, d.n_eff, 1e-6);

  const band = (t: number) => sigma * Math.sqrt(Math.max(t, 0));
  const at = new Map<number, { cum: number; d: string }>();
  for (const p of path) at.set(p.t, { cum: p.cum, d: p.d });

  const ts = new Set<number>([0, ...path.map((p) => p.t)]);
  for (let i = 0; i <= CONE_SAMPLES; i++) ts.add((tMax * i) / CONE_SAMPLES);

  const rows: Row[] = [...ts]
    .sort((a, b) => a - b)
    .map((t) => {
      const s1 = band(t);
      const s2 = 2 * s1;
      const hit = at.get(t);
      const row: Row = {
        t,
        band1: [-s1, s1],
        band2: [-s2, s2],
      };
      if (hit) {
        row.cum = hit.cum;
        row.d = hit.d;
        row.z = s1 > 0 ? hit.cum / s1 : 0;
        if (Math.abs(hit.cum) > s2) row.outside = hit.cum;
      }
      return row;
    });

  return { rows, tMax };
}

function describe(d: Decomposition, tier: Tier): string {
  const pct = (x: number) => `${(x * 100).toFixed(2)}%`;
  const z = d.sigma_expected > 0 ? d.excess / d.sigma_expected : 0;
  const where =
    Math.abs(z) > 2
      ? "outside its two-sigma expected range"
      : Math.abs(z) > 1
        ? "inside its two-sigma expected range but beyond one sigma"
        : "inside its normal range";
  // A window of zero closed sessions is a same-session recheck, not "over 0
  // trading sessions".
  const span =
    d.n_days === 0
      ? "so far this session"
      : `over ${d.n_days} trading ${d.n_days === 1 ? "session" : "sessions"}`;
  return (
    `Cumulative move net of sector ${span}: ${pct(d.excess)}, ` +
    `which is ${Math.abs(z).toFixed(1)} sigma and ${where}. ` +
    `Tier ${tier}.`
  );
}

/** Data sufficient to draw anything at all. */
export function hasCone(d: Decomposition | null): d is Decomposition {
  return Boolean(
    d && d.sigma_idio && d.sigma_idio > 0 && d.window_path && d.window_path.length > 0,
  );
}

/* --------------------------------------------------------------------------
 * Compact: the card
 * ----------------------------------------------------------------------- */

/**
 * ~120x40, cone and line only.
 *
 * Deliberately not a `ResponsiveContainer`: this renders once per card in a
 * list, and a fixed box cannot cause a resize-observer cascade. It shrinks
 * rather than overflows because the flex parent owns the remaining width.
 */
export function ExpectedRangeConeCompact({
  decomposition: d,
  tier,
  width = 120,
  height = 40,
}: {
  decomposition: Decomposition;
  tier: Tier;
  width?: number;
  height?: number;
}) {
  const { rows, tMax } = buildSeries(d);
  const colour = severityColor(tier);
  const single = d.window_path.length === 1;

  return (
    <div
      style={{ width, height }}
      className="shrink-0"
      role="img"
      aria-label={describe(d, tier)}
    >
      <ComposedChart
        width={width}
        height={height}
        data={rows}
        margin={{ top: 3, right: 2, bottom: 3, left: 2 }}
      >
        <XAxis dataKey="t" type="number" domain={[0, tMax]} hide />
        <YAxis type="number" domain={["dataMin", "dataMax"]} hide />
        <Area
          dataKey="band2"
          stroke={CONE}
          strokeOpacity={0.28}
          strokeWidth={0.75}
          fill={CONE}
          fillOpacity={0.1}
          isAnimationActive={false}
        />
        <Area
          dataKey="band1"
          stroke="none"
          fill={CONE}
          fillOpacity={0.16}
          isAnimationActive={false}
        />
        <ReferenceLine y={0} stroke="rgba(255,255,255,0.22)" strokeWidth={1} />
        <Line
          dataKey="cum"
          type="monotone"
          stroke={INSIDE}
          strokeWidth={1.4}
          dot={single ? { r: 2.5, fill: colour, stroke: "none" } : false}
          connectNulls
          isAnimationActive={false}
        />
        <Line
          dataKey="outside"
          type="monotone"
          stroke={colour}
          strokeWidth={1.8}
          dot={single ? { r: 2.5, fill: colour, stroke: "none" } : false}
          connectNulls={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Expanded: the maths panel
 * ----------------------------------------------------------------------- */

export function ExpectedRangeCone({
  decomposition: d,
  tier,
}: {
  decomposition: Decomposition;
  tier: Tier;
}) {
  const { rows, tMax } = buildSeries(d);
  const colour = severityColor(tier);
  const single = d.window_path.length === 1;

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-xs font-semibold text-white">Against its normal range</h4>
        <span className="text-[10px] text-faint">
          shaded bands are 1 and 2 sigma
        </span>
      </div>

      <div
        className="h-52 w-full"
        role="img"
        aria-label={describe(d, tier)}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 10, bottom: 20, left: 4 }}
          >
            <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={[0, tMax]}
              tick={{ fill: "#5C738A", fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
              tickFormatter={(v: number) =>
                Number.isInteger(v) ? String(v) : v.toFixed(1)
              }
              label={{
                value: "trading days in the window",
                position: "insideBottom",
                offset: -12,
                fill: "#5C738A",
                fontSize: 10,
              }}
            />
            <YAxis
              type="number"
              domain={["dataMin", "dataMax"]}
              tick={{ fill: "#5C738A", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={52}
              tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`}
              label={{
                value: "Move net of sector",
                angle: -90,
                position: "insideLeft",
                fill: "#5C738A",
                fontSize: 10,
                style: { textAnchor: "middle" },
              }}
            />
            <Tooltip content={<ConeTooltip />} cursor={false} />
            <Area
              dataKey="band2"
              stroke={CONE}
              strokeOpacity={0.35}
              strokeWidth={1}
              fill={CONE}
              fillOpacity={0.1}
              isAnimationActive={false}
            />
            <Area
              dataKey="band1"
              stroke="none"
              fill={CONE}
              fillOpacity={0.16}
              isAnimationActive={false}
            />
            <ReferenceLine y={0} stroke="rgba(255,255,255,0.3)" strokeWidth={1} />
            <Line
              dataKey="cum"
              type="monotone"
              stroke={INSIDE}
              strokeWidth={1.6}
              dot={single ? { r: 3.5, fill: colour, stroke: "none" } : false}
              activeDot={{ r: 3, fill: colour, stroke: "none" }}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              dataKey="outside"
              type="monotone"
              stroke={colour}
              strokeWidth={2.2}
              dot={single ? { r: 3.5, fill: colour, stroke: "none" } : false}
              activeDot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function ConeTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: Row }>;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row || row.cum == null) return null;
  return (
    <div className="rounded-[8px] border border-ink-line bg-ink-soft px-2.5 py-1.5 text-[11px] shadow-bento">
      <div className="text-white">{row.d || "now"}</div>
      <div className="num mt-0.5 text-minor">
        {(row.cum * 100).toFixed(2)}% net of sector
      </div>
      <div className="num text-faint">
        {row.z == null ? "--" : `${row.z.toFixed(1)} sigma at day ${row.t.toFixed(1)}`}
      </div>
    </div>
  );
}
