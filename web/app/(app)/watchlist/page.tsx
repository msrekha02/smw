// "use client";

// import Link from "next/link";
// import { useEffect, useMemo, useState } from "react";
// import {
//   addTicker,
//   getQuota,
//   getWatchlist,
//   removeTicker,
//   searchSymbols,
// } from "@/lib/api";
// import {
//   Badge,
//   Button,
//   Card,
//   EmptyState,
//   PageHeader,
//   Skeleton,
//   StatusBadge,
//   Tabs,
//   TextInput,
// } from "@/components/ui";
// import type { SymbolRow, WatchlistItem } from "@/lib/types";

// type Filter = "all" | "active" | "seeding";

// export default function WatchlistPage() {
//   const [items, setItems] = useState<WatchlistItem[] | null>(null);
//   const [q, setQ] = useState("");
//   const [rows, setRows] = useState<SymbolRow[]>([]);
//   const [msg, setMsg] = useState<string | null>(null);
//   const [err, setErr] = useState<string | null>(null);
//   const [credits, setCredits] = useState<number | null>(null);
//   const [filter, setFilter] = useState<Filter>("all");

//   const refresh = async () => {
//     setItems(await getWatchlist());
//     try {
//       setCredits((await getQuota()).your_seed_credits_left);
//     } catch {
//       /* the quota panel is informational */
//     }
//   };

//   useEffect(() => {
//     void refresh();
//   }, []);

//   // Search is a local trigram query, so it stays fast and keeps working during
//   // a provider outage. Debounced only to avoid rendering on every keystroke.
//   useEffect(() => {
//     if (q.trim().length < 1) {
//       setRows([]);
//       return;
//     }
//     const id = window.setTimeout(async () => {
//       try {
//         setRows(await searchSymbols(q.trim()));
//       } catch {
//         setRows([]);
//       }
//     }, 150);
//     return () => window.clearTimeout(id);
//   }, [q]);

//   const list = items ?? [];
//   const watched = useMemo(() => new Set(list.map((i) => i.ticker)), [list]);
//   const counts = useMemo(
//     () => ({
//       all: list.length,
//       active: list.filter((i) => i.status === "active").length,
//       seeding: list.filter((i) => i.status !== "active").length,
//     }),
//     [list],
//   );
//   const shown = useMemo(
//     () =>
//       filter === "all"
//         ? list
//         : list.filter((i) =>
//             filter === "active" ? i.status === "active" : i.status !== "active",
//           ),
//     [list, filter],
//   );

//   return (
//     <div>
//       <PageHeader
//         eyebrow="Watchlist"
//         title="Your watchlist"
//         subtitle={
//           <>
//             US-listed equities and ETFs. Both free data tiers are US-only, so the
//             scope is enforced when you add rather than failing later.
//             {credits != null && ` ${credits} seeding credits left today.`}
//           </>
//         }
//       />

//       <Card className="p-4">
//         <TextInput
//           value={q}
//           onChange={(e) => setQ(e.target.value)}
//           placeholder="Search by ticker or name"
//           aria-label="Search symbols"
//         />
//         {rows.length > 0 && (
//           <ul className="mt-3 divide-y divide-white/5 overflow-hidden rounded-[10px] border border-ink-line">
//             {rows.map((r) => (
//               <li
//                 key={r.ticker}
//                 className="flex items-center gap-3 px-3 py-2 text-sm"
//               >
//                 <span className="w-16 shrink-0 font-semibold text-white">
//                   {r.ticker}
//                 </span>
//                 <span className="min-w-0 flex-1 truncate text-minor">{r.name}</span>
//                 {r.seeded && (
//                   <Badge color="#10B981" wash="rgba(16,185,129,0.12)">
//                     ready
//                   </Badge>
//                 )}
//                 <Button
//                   variant={watched.has(r.ticker) ? "quiet" : "primary"}
//                   disabled={watched.has(r.ticker)}
//                   onClick={async () => {
//                     setErr(null);
//                     try {
//                       const res = await addTicker(r.ticker);
//                       setMsg(res.message);
//                       setQ("");
//                       await refresh();
//                     } catch (e) {
//                       setErr(e instanceof Error ? e.message : "could not add");
//                     }
//                   }}
//                 >
//                   {watched.has(r.ticker) ? "Added" : "Add"}
//                 </Button>
//               </li>
//             ))}
//           </ul>
//         )}
//         {msg && <p className="mt-3 text-xs text-up">{msg}</p>}
//         {err && <p className="mt-3 text-xs text-critical">{err}</p>}
//       </Card>

//       {items === null ? (
//         <div className="mt-5 space-y-2">
//           {[0, 1, 2].map((i) => (
//             <Skeleton key={i} className="h-11 w-full" />
//           ))}
//         </div>
//       ) : list.length === 0 ? (
//         <Card className="mt-5">
//           <EmptyState
//             title="Nothing here yet"
//             hint="Add a ticker above. The first view is a checkpoint, not a finding: the next visit is measured from the moment you add it."
//           />
//         </Card>
//       ) : (
//         <>
//           <div className="mb-3 mt-6">
//             <Tabs
//               active={filter}
//               onChange={setFilter}
//               tabs={[
//                 { id: "all", label: "All", count: counts.all },
//                 { id: "active", label: "Scoreable", count: counts.active },
//                 { id: "seeding", label: "Seeding", count: counts.seeding },
//               ]}
//             />
//           </div>

//           <Card>
//             <ul className="divide-y divide-white/5">
//               {shown.map((i) => (
//                 <li
//                   key={i.ticker}
//                   className="flex items-center gap-3 px-4 py-2.5 text-sm"
//                 >
//                   <Link
//                     href={`/ticker/${i.ticker}`}
//                     className="w-16 shrink-0 font-semibold text-white hover:text-brand"
//                   >
//                     {i.ticker}
//                   </Link>
//                   <span className="min-w-0 flex-1 truncate text-minor">
//                     {i.name}
//                   </span>
//                   <span className="hidden w-40 shrink-0 truncate text-xs text-faint sm:block">
//                     {i.sector ?? i.instrument_class.replace("_", " ")}
//                   </span>
//                   <span className="num hidden w-14 shrink-0 text-xs text-faint md:block">
//                     {i.benchmark_ticker ?? "none"}
//                   </span>
//                   <StatusBadge status={i.status} />
//                   <Button
//                     className="hover:border-critical/60 hover:text-critical"
//                     onClick={async () => {
//                       await removeTicker(i.ticker);
//                       await refresh();
//                     }}
//                   >
//                     Remove
//                   </Button>
//                 </li>
//               ))}
//               {shown.length === 0 && (
//                 <li className="px-4 py-8 text-center text-sm text-faint">
//                   No tickers in this state.
//                 </li>
//               )}
//             </ul>
//           </Card>
//         </>
//       )}
//     </div>
//   );
// }

"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { addTicker, getQuota, getWatchlist, removeTicker, searchSymbols } from "@/lib/api";
import { Badge, Button, EmptyState, PageHeader, Skeleton, StatusBadge, Tabs, TextInput } from "@/components/ui";
import { displayName, sectorLabel } from "@/lib/format";
import type { SymbolRow, WatchlistItem } from "@/lib/types";

type Filter = "all" | "active" | "seeding";

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[] | null>(null);
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<SymbolRow[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [credits, setCredits] = useState<number | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const refresh = async () => {
    setItems(await getWatchlist());
    try {
      setCredits((await getQuota()).your_seed_credits_left);
    } catch { }
  };

  useEffect(() => { void refresh(); }, []);

  useEffect(() => {
    if (q.trim().length < 1) {
      setRows([]);
      return;
    }
    const id = window.setTimeout(async () => {
      try { setRows(await searchSymbols(q.trim())); } 
      catch { setRows([]); }
    }, 150);
    return () => window.clearTimeout(id);
  }, [q]);

  const list = items ?? [];
  const watched = useMemo(() => new Set(list.map((i) => i.ticker)), [list]);
  const counts = useMemo(
    () => ({
      all: list.length,
      active: list.filter((i) => i.status === "active").length,
      seeding: list.filter((i) => i.status !== "active").length,
    }),
    [list],
  );
  const shown = useMemo(
    () => filter === "all" ? list : list.filter((i) => filter === "active" ? i.status === "active" : i.status !== "active"),
    [list, filter],
  );

  return (
    <div className="animate-in space-y-8">
      <PageHeader
        eyebrow="Watchlist"
        title="Your universe"
        subtitle={
          <>
            Tracking US-listed equities and ETFs. 
            <span className="ml-2 rounded-full bg-brand/10 px-2 py-0.5 text-[11px] font-medium text-brand">
              {credits != null ? `${credits} seeds remaining today` : "Live"}
            </span>
          </>
        }
      />

      {/* Upgraded Search Card */}
      <div className="glass-panel animate-in stagger-1 rounded-xl p-5">
        <TextInput
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search tickers or companies (e.g., AAPL)"
          aria-label="Search symbols"
          className="w-full bg-surface-inset border-line-2 focus:border-brand/50 focus:ring-2 focus:ring-brand-glow transition-all"
        />
        {rows.length > 0 && (
          <ul className="mt-4 divide-y divide-line-1 overflow-hidden rounded-lg border border-line-1 bg-surface-0/50">
            {rows.map((r) => (
              <li key={r.ticker} className="flex items-center gap-4 px-4 py-3 text-sm hover:bg-surface-2/30 transition-colors">
                <span className="w-16 shrink-0 font-semibold text-ink-1 tracking-wide">{r.ticker}</span>
                <span className="min-w-0 flex-1 truncate text-ink-2">
                  {displayName(r.ticker, r.name)}
                </span>
                {r.seeded && (
                  <Badge color="var(--good)" wash="rgba(16,185,129,0.1)">ready</Badge>
                )}
                <Button
                  variant={watched.has(r.ticker) ? "quiet" : "primary"}
                  disabled={watched.has(r.ticker)}
                  className="rounded-full px-4 text-xs font-medium transition-transform active:scale-95"
                  onClick={async () => {
                    setErr(null);
                    try {
                      const res = await addTicker(r.ticker);
                      setMsg(res.message);
                      setQ("");
                      await refresh();
                    } catch (e) {
                      setErr(e instanceof Error ? e.message : "could not add");
                    }
                  }}
                >
                  {watched.has(r.ticker) ? "Added" : "Add to list"}
                </Button>
              </li>
            ))}
          </ul>
        )}
        {msg && <p className="mt-4 text-xs font-medium text-good">{msg}</p>}
        {err && <p className="mt-4 text-xs font-medium text-critical">{err}</p>}
      </div>

      {items === null ? (
        <div className="mt-8 space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-14 w-full rounded-xl opacity-50" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <div className="glass-panel animate-in stagger-2 mt-8 rounded-xl p-8">
          <EmptyState
            title="Your universe is empty"
            hint="Search for a ticker above. We'll establish a baseline the moment you add it."
          />
        </div>
      ) : (
        <div className="animate-in stagger-2">
          <Tabs
            active={filter}
            onChange={setFilter}
            tabs={[
              { id: "all", label: "All Assets", count: counts.all },
              { id: "active", label: "Monitoring", count: counts.active },
              { id: "seeding", label: "Calibrating", count: counts.seeding },
            ]}
          />

          {/* Upgraded Watchlist Table */}
          <div className="glass-panel mt-6 rounded-xl overflow-hidden">
            <ul className="divide-y divide-line-1">
              {shown.map((i) => (
                <li key={i.ticker} className="group flex items-center gap-4 px-5 py-3.5 text-sm hover:bg-surface-2/40 transition-all duration-200">
                  <Link
                    href={`/ticker/${i.ticker}`}
                    className="w-16 shrink-0 font-semibold text-ink-1 hover:text-brand transition-colors"
                  >
                    {i.ticker}
                  </Link>
                  <span className="min-w-0 flex-1 truncate font-medium text-ink-2">
                    {displayName(i.ticker, i.name)}
                  </span>
                  <span className="hidden w-32 shrink-0 truncate text-xs text-ink-3 sm:block">
                    {sectorLabel(i.instrument_class, i.sector)}
                  </span>
                  <StatusBadge status={i.status} />
                  {/* Always present, not hover-only: a control nobody can see
                      is a control nobody knows about, and on a touch screen
                      hover never happens at all. It rises to full strength on
                      row hover and whenever anything in the row takes focus. */}
                  <Button
                    variant="quiet"
                    aria-label={`Remove ${i.ticker} from your watchlist`}
                    className="opacity-60 transition-all group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 hover:border-critical/40 hover:bg-critical/10 hover:text-critical"
                    onClick={async () => {
                      await removeTicker(i.ticker);
                      await refresh();
                    }}
                  >
                    Drop
                  </Button>
                </li>
              ))}
              {shown.length === 0 && (
                <li className="px-5 py-10 text-center text-sm text-ink-3">
                  No assets currently in this phase.
                </li>
              )}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}