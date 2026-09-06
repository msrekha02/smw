"use client";

/**
 * The shared kit. Every surface in the app is built from these, so a spacing or
 * colour decision is made once here rather than re-argued per page.
 *
 * The document-library pieces from the source design system (document-type
 * badges, document reference links) are deliberately absent: this app has no
 * documents, and a component with nothing to name is worse than no component.
 */

import { Component } from "react";

/* --------------------------------------------------------------------------
 * Containment
 * ----------------------------------------------------------------------- */

/**
 * Catches render errors in whatever subtree it wraps, so one broken page cannot
 * blank the whole app. React has no hook equivalent: an error boundary must be
 * a class with `getDerivedStateFromError`.
 */
export class ErrorBoundary extends Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("ErrorBoundary caught a render error:", error, info?.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="animate-in flex flex-col items-center justify-center px-6 py-20 text-center">
          <div className="mb-3 h-2.5 w-2.5 rounded-full bg-critical shadow-[0_0_16px_#EF4444]" />
          <div className="text-lg font-semibold text-white">This page hit an error</div>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-minor">
            Nothing was acknowledged, so nothing has been lost. The other pages
            are unaffected.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 rounded-[10px] border border-brand/60 bg-ink-raised px-5 py-2 text-sm font-semibold text-white transition-shadow hover:shadow-glow"
          >
            Reload page
          </button>
          <pre className="mt-6 max-w-lg overflow-auto rounded-[8px] bg-ink-inset p-3 text-left font-mono text-[11px] text-faint">
            {String(this.state.error?.message || this.state.error)}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}

/* --------------------------------------------------------------------------
 * Surfaces
 * ----------------------------------------------------------------------- */

/**
 * The bento card. The hover lift and edge glow are opt-out (`interactive`),
 * because a card that is only a container should not behave like a target.
 */
export function Card({
  children,
  className = "",
  interactive = false,
  accent,
  ref,
  ...rest
}: {
  children: React.ReactNode;
  className?: string;
  interactive?: boolean;
  /** A left rule in a tier colour, for cards that carry a severity. */
  accent?: string;
  /** Forwarded so callers can observe the card, e.g. for read receipts. */
  ref?: React.Ref<HTMLDivElement>;
} & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      ref={ref}
      className={`group relative overflow-hidden rounded-card border border-ink-line bg-ink-soft ${
        interactive
          ? "transition-all duration-500 hover:-translate-y-0.5 hover:border-brand/60 hover:shadow-bento"
          : ""
      } ${className}`}
      style={accent ? { borderLeft: `2px solid ${accent}` } : undefined}
      {...rest}
    >
      {interactive && (
        <>
          <div className="pointer-events-none absolute left-0 top-0 h-px w-full bg-gradient-to-r from-transparent via-brand to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
          <div className="pointer-events-none absolute -left-20 -top-20 h-48 w-48 rounded-full bg-brand opacity-0 blur-[80px] transition-opacity duration-700 group-hover:opacity-[0.12]" />
        </>
      )}
      <div className="relative z-10">{children}</div>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="animate-in mb-7 flex flex-col justify-between gap-4 md:flex-row md:items-end">
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-brand">
            {eyebrow}
          </div>
        )}
        <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
        {subtitle && (
          <div className="mt-1.5 max-w-3xl text-sm leading-relaxed text-minor">
            {subtitle}
          </div>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  );
}

export function SectionHeading({
  title,
  aside,
}: {
  title: string;
  aside?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="text-sm font-semibold tracking-tight text-white">{title}</h2>
      {aside && <span className="text-xs text-faint">{aside}</span>}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Labels
 * ----------------------------------------------------------------------- */

export function Badge({
  children,
  color = "var(--ink-2)",
  wash = "rgba(255,255,255,0.05)",
  className = "",
  title,
}: {
  children: React.ReactNode;
  color?: string;
  wash?: string;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${className}`}
      style={{ color, background: wash, borderColor: wash }}
    >
      {children}
    </span>
  );
}

const STATUS_META: Record<
  string,
  { label: string; color: string; wash: string }
> = {
  active: { label: "Active", color: "#10B981", wash: "rgba(16,185,129,0.12)" },
  seeding: { label: "Seeding", color: "#F59E0B", wash: "rgba(245,158,11,0.12)" },
  halted: { label: "Halted", color: "#F97316", wash: "rgba(249,115,22,0.12)" },
  unknown: { label: "Unknown", color: "#8EA4BD", wash: "rgba(255,255,255,0.05)" },
};

export function statusMeta(status: string) {
  return STATUS_META[status] ?? { ...STATUS_META.unknown, label: status };
}

export function StatusBadge({ status }: { status: string }) {
  const m = statusMeta(status);
  return (
    <Badge color={m.color} wash={m.wash}>
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: m.color, boxShadow: `0 0 8px ${m.color}` }}
      />
      {m.label}
    </Badge>
  );
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: "#EF4444",
  notable: "#F59E0B",
  minor: "#8EA4BD",
  quiet: "#5C738A",
};

export function severityColor(severity: string) {
  return SEVERITY_COLOR[severity] ?? SEVERITY_COLOR.quiet;
}

export function SeverityDot({ severity }: { severity: string }) {
  const c = severityColor(severity);
  return (
    <span
      title={severity}
      className="inline-block h-2 w-2 shrink-0 rounded-full"
      style={{
        background: c,
        boxShadow: severity === "critical" ? `0 0 8px ${c}` : undefined,
      }}
    />
  );
}

/** A live signal. Pings only while something is genuinely arriving. */
export function LiveDot({
  color = "var(--good)",
  ping = true,
  title,
}: {
  color?: string;
  ping?: boolean;
  title?: string;
}) {
  return (
    <span className="relative inline-flex h-2 w-2" title={title}>
      {ping && (
        <span
          className="pulse-live absolute inline-flex h-full w-full rounded-full opacity-75"
          style={{ backgroundColor: color }}
        />
      )}
      <span
        className="relative inline-flex h-2 w-2 rounded-full"
        style={{ backgroundColor: color }}
      />
    </span>
  );
}

/* --------------------------------------------------------------------------
 * Quantities
 * ----------------------------------------------------------------------- */

/** A 0-100 bar. The colour is the reading, so it is never decorative. */
export function HealthBar({
  value,
  label,
}: {
  value: number;
  label?: string;
}) {
  const v = Math.max(0, Math.min(100, value));
  const color =
    v >= 75 ? "#10B981" : v >= 55 ? "#F59E0B" : v >= 35 ? "#F97316" : "#EF4444";
  return (
    <div className="flex min-w-[140px] items-center gap-3">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-ink-inset">
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{ width: `${v}%`, background: color }}
        />
      </div>
      <span className="tnum w-10 text-right text-xs font-semibold" style={{ color }}>
        {Math.round(v)}%
      </span>
      {label && <span className="text-[11px] text-faint">{label}</span>}
    </div>
  );
}

/** A ring for a single proportion. Used where a bar would read as a timeline. */
export function Gauge({
  value,
  max = 100,
  label,
  tone = "var(--brand)",
  display,
}: {
  value: number;
  max?: number;
  label?: string;
  tone?: string;
  /** Overrides the centre text when the number is not a percentage. */
  display?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const arc = "M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831";
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative flex h-14 w-14 items-center justify-center">
        <svg className="absolute h-full w-full -rotate-90" viewBox="0 0 36 36">
          <path d={arc} fill="none" stroke="var(--surface-2)" strokeWidth="3" />
          {/* A rounded cap on a zero-length arc draws a dot, which reads as a
              very small value rather than as no value. */}
          {pct > 0 && (
            <path
              d={arc}
              fill="none"
              stroke={tone}
              strokeWidth="3"
              strokeLinecap="round"
              strokeDasharray={`${pct}, 100`}
            />
          )}
        </svg>
        <span className="tnum text-xs font-semibold text-white">
          {display ?? `${Math.round(pct)}%`}
        </span>
      </div>
      {label && (
        <span className="text-center text-[10px] uppercase tracking-wider text-faint">
          {label}
        </span>
      )}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * States
 * ----------------------------------------------------------------------- */

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="animate-in flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon && <div className="mb-4 text-brand opacity-80">{icon}</div>}
      <div className="text-base font-semibold text-white">{title}</div>
      {hint && (
        <p className="mt-2 max-w-md text-sm leading-relaxed text-minor">{hint}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Controls
 * ----------------------------------------------------------------------- */

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: Array<{ id: T; label: string; count?: number }>;
  active: T;
  onChange: (id: T) => void;
}) {
  return (
    <div
      role="tablist"
      className="inline-flex items-center gap-1 rounded-[12px] border border-ink-line bg-ink-inset p-1"
    >
      {tabs.map((t) => {
        const on = t.id === active;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={on}
            type="button"
            onClick={() => onChange(t.id)}
            className={`flex items-center gap-2 rounded-[9px] px-3.5 py-1.5 text-xs font-semibold transition-colors ${
              on
                ? "bg-ink-raised text-white"
                : "text-minor hover:text-white"
            }`}
          >
            {t.label}
            {t.count != null && (
              <span
                className={`tnum rounded-full px-1.5 text-[10px] ${
                  on ? "bg-brand/25 text-white" : "bg-white/5 text-faint"
                }`}
              >
                {t.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** The one button style in the app, in two weights. */
export function Button({
  children,
  variant = "quiet",
  className = "",
  ...rest
}: {
  children: React.ReactNode;
  variant?: "primary" | "quiet";
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-[10px] px-3.5 py-1.5 text-xs font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed";
  const skin =
    variant === "primary"
      ? "bg-brand text-white hover:shadow-glow"
      : "border border-ink-line text-minor hover:border-brand/50 hover:text-white";
  return (
    <button type="button" className={`${base} ${skin} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function TextInput({
  className = "",
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full rounded-[10px] border border-ink-line bg-ink-inset px-3 py-2 text-sm text-white outline-none transition-colors placeholder:text-faint focus:border-brand/60 ${className}`}
      {...rest}
    />
  );
}
