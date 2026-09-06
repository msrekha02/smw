"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DigestCardView } from "@/components/Card";
import { QuietTable } from "@/components/QuietTable";
import {
  BootstrapPanel,
  EmptyWatchlist,
  LoadingDigest,
  MarketBanner,
  NetworkErrorPanel,
  OfflinePanel,
  Panel,
} from "@/components/States";
import {
  Button,
  Card,
  LiveDot,
  PageHeader,
  SeverityDot,
  TextInput,
} from "@/components/ui";
import { OfflineError, fetchDigest } from "@/lib/api";
import { useReceipts } from "@/lib/receipts";
import type { Digest } from "@/lib/types";

type Status = "loading" | "ok" | "offline" | "error";

export default function DigestPage() {
  const [digest, setDigest] = useState<Digest | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string>("");
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [asIf, setAsIf] = useState<string | null>(null);

  const etag = useRef<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const setToken = useReceipts((s) => s.setToken);
  const flush = useReceipts((s) => s.flush);
  const resetReceipts = useReceipts((s) => s.reset);
  const impression = useReceipts((s) => s.impression);

  const load = useCallback(async () => {
    try {
      const res = await fetchDigest(etag.current, asIf);
      if (!res.notModified && res.digest) {
        etag.current = res.etag;
        setDigest(res.digest);
        setToken(res.digest.token);
        // One impression per card per digest, so precision@critical has a
        // denominator that means something.
        impression(
          res.digest.cards
            .filter((c) => c.state === "ok")
            .map((c) => ({
              ticker: c.ticker,
              tier: c.tier,
              attention: c.attention,
              shown_at: res.digest!.as_of,
            })),
        );
      }
      setStatus("ok");
      setLastSync(new Date());
      return res.digest?.next_poll_after_ms ?? 20_000;
    } catch (e) {
      if (e instanceof OfflineError) setStatus("offline");
      else {
        setStatus("error");
        setError(e instanceof Error ? e.message : "unknown error");
      }
      return 15_000;
    }
  }, [asIf, impression, setToken]);

  // The server sets the cadence: 20s while the market is open, 15 minutes when
  // it is closed. The client does not guess.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const next = await load();
      if (!alive) return;
      timer.current = window.setTimeout(tick, next);
    };
    void tick();
    return () => {
      alive = false;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [load]);

  useEffect(() => {
    etag.current = null;
    resetReceipts();
  }, [asIf, resetReceipts]);

  const loud = useMemo(
    () => (digest?.cards ?? []).filter((c) => c.state === "ok"),
    [digest],
  );
  const unscored = useMemo(
    () => (digest?.cards ?? []).filter((c) => c.state !== "ok"),
    [digest],
  );

  if (status === "loading" && !digest) return <LoadingDigest />;
  if (status === "offline" && !digest)
    return <OfflinePanel onRetry={() => void load()} />;
  if (status === "error" && !digest)
    return <NetworkErrorPanel message={error} onRetry={() => void load()} />;
  if (!digest) return <LoadingDigest />;

  const total = digest.counts.total ?? 0;
  const open = digest.market.session === "open";

  return (
    <div>
      <PageHeader
        eyebrow="Digest"
        title={digest.since_label}
        subtitle={<TierCounts counts={digest.counts} />}
        actions={
          <>
            <Button
              onClick={() => void flush(false)}
              title="Send pending read receipts now"
            >
              Mark all read
            </Button>
            <Link href="/watchlist">
              <Button>Edit list</Button>
            </Link>
          </>
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-faint">
        <span className="inline-flex items-center gap-2">
          <LiveDot
            color={open ? "var(--good)" : "var(--ink-3)"}
            ping={open && status === "ok"}
          />
          {open ? "Market open" : "Market closed"}
        </span>
        {status === "offline" && <span className="text-notable">offline</span>}
        {lastSync && (
          <span>
            synced {lastSync.toLocaleTimeString([], { timeStyle: "short" })}
          </span>
        )}
        <TimeTravel asIf={asIf} onAsIf={setAsIf} />
      </div>

      {digest.bootstrap && <BootstrapPanel message={digest.bootstrap.message} />}

      {digest.market.elevated && digest.market.banner && (
        <MarketBanner
          banner={digest.market.banner}
          returnPct={digest.market.return_pct}
          z={digest.market.z}
        />
      )}

      {total === 0 && <EmptyWatchlist />}

      {total > 0 && loud.length === 0 && unscored.length === 0 && (
        <Panel
          title="Nothing unusual"
          body={
            digest.quiet_summary ??
            "Every name on your list is inside its normal range."
          }
        />
      )}

      {digest.quiet_summary && loud.length > 0 && (
        <p className="mb-3 text-sm text-minor">{digest.quiet_summary}</p>
      )}

      <div className="space-y-3">
        {loud.map((c) => (
          <DigestCardView key={c.ticker} card={c} />
        ))}
        {unscored.map((c) => (
          <DigestCardView key={c.ticker} card={c} />
        ))}
      </div>

      <QuietTable cards={digest.quiet} summary={digest.quiet_summary} />
    </div>
  );
}

/** The shape of the day in four numbers, coloured by what they cost to ignore. */
function TierCounts({ counts }: { counts: Record<string, number> }) {
  const tiers = [
    { key: "critical", label: "critical" },
    { key: "notable", label: "notable" },
    { key: "minor", label: "minor" },
    { key: "quiet", label: "quiet" },
  ];
  return (
    <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {tiers.map((t) => (
        <span key={t.key} className="inline-flex items-center gap-1.5">
          <SeverityDot severity={t.key} />
          <span className="tnum font-semibold text-white">
            {counts[t.key] ?? 0}
          </span>
          <span className="text-minor">{t.label}</span>
        </span>
      ))}
      {counts.unscored ? (
        <span className="text-faint">{counts.unscored} not scored</span>
      ) : null}
    </span>
  );
}

/**
 * `?as_if_last_seen=` on the digest.
 *
 * Lets you view any historical window on demand rather than waiting a week to
 * accumulate a diff, which is the difference between a demoable product and one
 * you have to take on faith.
 */
function TimeTravel({
  asIf,
  onAsIf,
}: {
  asIf: string | null;
  onAsIf: (v: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");

  return (
    <span className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`underline-offset-2 hover:text-white hover:underline ${
          asIf ? "text-brand" : ""
        }`}
      >
        {asIf ? `Viewing as if last seen ${asIf.slice(0, 16)}` : "View a past window"}
      </button>
      {open && (
        <Card className="absolute left-0 top-6 z-20 w-[19rem] p-3 shadow-bento">
          <TextInput
            type="datetime-local"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <div className="mt-2 flex items-center gap-2">
            <Button
              variant="primary"
              onClick={() => {
                if (!value) return;
                onAsIf(new Date(value).toISOString());
                setOpen(false);
              }}
            >
              Apply
            </Button>
            {asIf && (
              <Button
                onClick={() => {
                  setValue("");
                  onAsIf(null);
                  setOpen(false);
                }}
              >
                Back to live
              </Button>
            )}
          </div>
        </Card>
      )}
    </span>
  );
}
