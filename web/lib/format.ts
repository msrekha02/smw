import type { Tier } from "./types";

export const pct = (x: number | null | undefined, digits = 2) =>
  x == null ? "--" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`;

export const absPct = (x: number | null | undefined, digits = 2) =>
  x == null ? "--" : `${Math.abs(x * 100).toFixed(digits)}%`;

export const money = (x: number | null | undefined) =>
  x == null
    ? "--"
    : x >= 1000
      ? x.toLocaleString(undefined, { maximumFractionDigits: 0 })
      : x.toFixed(2);

export const sigma = (x: number | null | undefined, digits = 2) =>
  x == null ? "--" : `${x.toFixed(digits)}σ`;

export const compact = (x: number | null | undefined) => {
  if (x == null) return "--";
  const units: Array<[number, string]> = [
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [n, s] of units) {
    if (Math.abs(x) >= n) return `${(x / n).toFixed(1)}${s}`;
  }
  return x.toFixed(0);
};

export const TIER_LABEL: Record<Tier, string> = {
  critical: "Critical",
  notable: "Notable",
  minor: "Minor",
  quiet: "Quiet",
};

/** The left rule on a card. A tier you can ignore does not get a colour. */
export const tierAccent = (tier: Tier) =>
  ({
    critical: "#EF4444",
    notable: "#F59E0B",
    minor: "#1B2437",
    quiet: "#1B2437",
  })[tier];

/** A wash only where the tier is worth interrupting for. */
export const tierWash = (tier: Tier) =>
  ({
    critical: "bg-critical/[0.06]",
    notable: "bg-notable/[0.05]",
    minor: "",
    quiet: "",
  })[tier];

export const dirClass = (x: number | null | undefined) =>
  x == null ? "text-minor" : x < 0 ? "text-down" : "text-up";

export const STATE_COPY: Record<
  string,
  { label: string; tone: "info" | "warn" | "danger" }
> = {
  new: { label: "New", tone: "info" },
  seeding: { label: "Seeding", tone: "info" },
  verifying: { label: "Verifying", tone: "warn" },
  no_data: { label: "No data", tone: "warn" },
  halted: { label: "Halted", tone: "warn" },
  unknown: { label: "Unknown symbol", tone: "warn" },
  action_frozen: { label: "Paused", tone: "danger" },
};

/**
 * What the sector column says.
 *
 * `instrument_class` is a storage detail and is never shown: a broad ETF
 * tracks the whole market rather than a sector, and a sector ETF reports the
 * sector it IS, which the seeding layer fills in from the static universe.
 */
export const sectorLabel = (
  instrumentClass: string,
  sector: string | null | undefined,
) => {
  if (instrumentClass === "broad_etf") return "Broad market";
  return sector?.trim() || "Unclassified";
};

/**
 * A row always has something to show in the name column.
 *
 * The seeding layer names every instrument this system picks for itself, so
 * this only catches a symbol whose provider returned no name at all. The
 * ticker is a worse label than a company name and a much better one than an
 * empty cell.
 */
export const displayName = (
  ticker: string,
  name: string | null | undefined,
) => name?.trim() || ticker;
