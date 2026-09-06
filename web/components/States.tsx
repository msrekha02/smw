"use client";

/** Every state the digest can be in, written out rather than left to a spinner. */

import { Button, Card, EmptyState, Skeleton } from "./ui";

export function Panel({
  title,
  body,
  tone = "info",
  action,
}: {
  title: string;
  body: string;
  tone?: "info" | "warn" | "danger";
  action?: React.ReactNode;
}) {
  const skin =
    tone === "danger"
      ? "border-critical/40 bg-critical/[0.07]"
      : tone === "warn"
        ? "border-notable/40 bg-notable/[0.07]"
        : "border-ink-line bg-ink-soft";
  return (
    <div className={`rounded-card border p-5 ${skin}`}>
      <h2 className="text-sm font-semibold text-white">{title}</h2>
      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-minor">{body}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function LoadingDigest() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading your digest">
      <Skeleton className="h-9 w-56" />
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-24 w-full" />
      ))}
    </div>
  );
}

export function EmptyWatchlist() {
  return (
    <Card>
      <EmptyState
        title="Nothing on your watchlist yet"
        hint="Add a few tickers and the next visit is measured from this moment. The first view of a new ticker is a checkpoint, not a finding."
        action={
          <a href="/watchlist">
            <Button variant="primary">Add tickers</Button>
          </a>
        }
      />
    </Card>
  );
}

export function OfflinePanel({ onRetry }: { onRetry: () => void }) {
  return (
    <Panel
      title="You are offline"
      tone="warn"
      body="Showing the last digest this device received. Nothing has been acknowledged, so nothing will be lost."
      action={<Button onClick={onRetry}>Try again</Button>}
    />
  );
}

export function NetworkErrorPanel({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <Panel
      title="The digest could not be loaded"
      tone="danger"
      body={message}
      action={<Button onClick={onRetry}>Retry</Button>}
    />
  );
}

export function BootstrapPanel({ message }: { message: string }) {
  return (
    <div className="mb-4">
      <Panel title="Benchmarks are still seeding" tone="warn" body={message} />
    </div>
  );
}

export function MarketBanner({
  banner,
  returnPct,
  z,
}: {
  banner: string;
  returnPct: number;
  z: number;
}) {
  return (
    <div className="mb-4 rounded-card border border-notable/40 bg-notable/[0.08] px-4 py-3">
      <p className="text-sm text-white/90">{banner}</p>
      <p className="num mt-1 text-xs text-notable">
        SPY {(returnPct * 100).toFixed(2)}% &middot; {Math.abs(z).toFixed(1)}σ
      </p>
    </div>
  );
}
