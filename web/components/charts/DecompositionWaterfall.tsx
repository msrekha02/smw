"use client";

/**
 * Chart 2: where the raw move went.
 *
 * Raw move, minus the part the sector explains, leaves the idiosyncratic
 * remainder. Only the remainder is scored, so it carries the weight, and the
 * normal range for the window is drawn as a band through its row: the overshoot
 * past the band is the finding, visible without reading a number.
 */

import {
  Bar,
  Cell,
  LabelList,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  BarChart,
  XAxis,
  YAxis,
} from "recharts";
import { severityColor } from "@/components/ui";
import type { Decomposition, Tier } from "@/lib/types";

const RAW = "Raw move";
const SECTOR = "Sector explained";
const IDIO = "Idiosyncratic";
/** The band row is named with its own width: it draws no bar to label. */
const rangeLabel = (band: number) => `Normal range +/-${(band * 100).toFixed(1)}%`;

export function DecompositionWaterfall({
  decomposition: d,
  tier,
}: {
  decomposition: Decomposition;
  tier: Tier;
}) {
  const colour = severityColor(tier);
  const sectorPart = d.beta_used * d.bench_return;
  const band = d.sigma_expected;

  const RANGE = rangeLabel(band);
  const pct = (x: number) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;

  // The label is precomputed per row rather than formatted in the chart, so a
  // row that carries no bar can still carry its own text.
  const rows = [
    { name: RAW, value: d.cum_return, kind: "raw" as const, label: pct(d.cum_return) },
    { name: SECTOR, value: sectorPart, kind: "sector" as const, label: pct(sectorPart) },
    { name: IDIO, value: d.excess, kind: "idio" as const, label: pct(d.excess) },
    // Draws no bar: its row is where the band is drawn, and it carries its
    // width in the row label rather than in a value tag.
    { name: RANGE, value: 0, kind: "band" as const, label: "" },
  ];

  // The domain has to hold both the bars and the band, or an overshoot would be
  // clipped at exactly the moment it matters.
  const reach = Math.max(
    Math.abs(d.cum_return),
    Math.abs(sectorPart),
    Math.abs(d.excess),
    band,
    1e-4,
  );
  const limit = reach * 1.25;

  const label =
    `Raw move ${pct(d.cum_return)}. Sector explains ${pct(sectorPart)}. ` +
    `Idiosyncratic remainder ${pct(d.excess)}, against a normal range of ` +
    `plus or minus ${(band * 100).toFixed(1)}% for this window.`;

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-xs font-semibold text-white">How the move splits</h4>
        <span className="num text-[10px] text-faint">
          normal range +/-{(band * 100).toFixed(1)}%
        </span>
      </div>

      <div className="h-[132px] w-full" role="img" aria-label={label}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 4, right: 46, bottom: 2, left: 4 }}
            barCategoryGap="22%"
          >
            <XAxis type="number" domain={[-limit, limit]} hide />
            <YAxis
              type="category"
              dataKey="name"
              width={132}
              tick={{ fill: "#8EA4BD", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
            />

            {/* Drawn before the bars so it sits behind the remainder. */}
            <ReferenceArea
              x1={-band}
              x2={band}
              y1={IDIO}
              y2={RANGE}
              fill="#8EA4BD"
              fillOpacity={0.16}
              stroke="rgba(255,255,255,0.18)"
              strokeDasharray="3 3"
            />
            <ReferenceLine x={0} stroke="rgba(255,255,255,0.3)" />

            <Bar dataKey="value" isAnimationActive={false} radius={2}>
              {rows.map((r) => (
                <Cell
                  key={r.name}
                  fill={r.kind === "idio" ? colour : "#8EA4BD"}
                  fillOpacity={
                    r.kind === "idio" ? 1 : r.kind === "band" ? 0 : 0.45
                  }
                />
              ))}
              <LabelList
                dataKey="label"
                position="right"
                style={{ fontSize: 10 }}
                fill="#A3B8CC"
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
