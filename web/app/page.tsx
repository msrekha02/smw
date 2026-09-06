// import type { Metadata } from "next";
// import Link from "next/link";
// import { LandingNav } from "@/components/landing/LandingNav";

// /**
//  * The public page.
//  *
//  * A server component with no data fetching, because everything it claims is
//  * either a property of the design or a number already measured and written
//  * down. Nothing here reads from the API: a marketing page that can be down
//  * because Postgres is down is worse than one that is merely static.
//  *
//  * Every figure traces to README.md or to the calibration artifact behind
//  * /calibration. Nothing is projected, rounded up, or invented.
//  */

// export const metadata: Metadata = {
//   title: "Smart Market Watchlist",
//   description:
//     "A watchlist that gets quieter as it gets smarter. It surfaces what is statistically unusual for a specific stock, since you last looked, net of what its sector did.",
//   openGraph: {
//     title: "Smart Market Watchlist",
//     description:
//       "Ranks moves by surprise, not by size: idiosyncratic displacement measured against a stock's own expected range for a window as long as your absence.",
//   },
// };

// /* Clears the 64px sticky bar with room to breathe. */
// const ANCHOR = "scroll-mt-24";

// export default function LandingPage() {
//   return (
//     <div className="min-h-screen bg-[var(--surface-0)] text-[var(--ink-1)]">
//       <LandingNav />

//       <main>
//         <Hero />
//         <Problem />
//         <HowItWorks />
//         <Features />
//         <HowItReads />
//         <Evidence />
//         <Close />
//       </main>

//       <footer className="border-t border-[var(--line-1)]">
//         <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-4 py-8 text-sm text-[var(--ink-2)] sm:flex-row sm:items-center sm:justify-between sm:px-6">
//           <span>Smart Market Watchlist</span>
//           <span>
//             US-listed equities and ETFs. A prototype running under personal-use
//             provider licences.
//           </span>
//         </div>
//       </footer>
//     </div>
//   );
// }

// /* --------------------------------------------------------------------------
//  * 1. Hero
//  * ----------------------------------------------------------------------- */

// function Hero() {
//   return (
//     <section className="mx-auto w-full max-w-6xl px-4 pb-24 pt-24 sm:px-6 sm:pb-32 sm:pt-32">
//       <div className="max-w-3xl">
//         <h1 className="animate-in text-balance text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-[1.08] tracking-tight text-[var(--ink-1)]">
//           A watchlist that gets quieter as it gets smarter.
//         </h1>

//         <p className="animate-in stagger-1 mt-6 max-w-2xl text-[clamp(1rem,2.2vw,1.25rem)] leading-relaxed text-[var(--ink-2)]">
//           Surfaces what is statistically unusual for a specific stock, since you
//           last looked, net of what its sector did.
//         </p>

//         <div className="animate-in stagger-2 mt-10 flex flex-wrap items-center gap-x-8 gap-y-4">
//           <Link
//             href="/login"
//             className="inline-flex items-center rounded-[10px] bg-[var(--brand)] px-6 py-3 text-base font-semibold text-[var(--surface-0)] transition-colors hover:bg-[var(--brand-strong)] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)]"
//           >
//             Get Started
//           </Link>

//           <Link
//             href="#how"
//             className="inline-flex items-center gap-2 text-base font-medium text-[var(--brand)] transition-colors hover:text-[var(--ink-1)]"
//           >
//             See how it works
//             <span aria-hidden="true" className="translate-y-px">
//               &rarr;
//             </span>
//           </Link>
//         </div>
//       </div>
//     </section>
//   );
// }

// /* --------------------------------------------------------------------------
//  * 2. Problem
//  * ----------------------------------------------------------------------- */

// const PROBLEMS = [
//   {
//     n: "01",
//     title: "A red day is not information.",
//     body: "When the market drops 5%, twenty of your twenty holdings turn red. Nothing on that screen distinguishes a stock that fell with everything else from one that fell for its own reasons.",
//   },
//   {
//     n: "02",
//     title: "“Today” is the wrong window.",
//     body: "Standard watchlists reset at midnight. If you last looked on Friday, a Tuesday percentage answers a question you didn’t ask.",
//   },
//   {
//     n: "03",
//     title: "One percent means different things.",
//     body: "A 1% move in a utility is remarkable. A 1% move in a biotech is Tuesday. A single threshold applied to every holding is either too loud for one and silent for the other.",
//   },
// ];

// function Problem() {
//   return (
//     <section id="problem" className={`${ANCHOR} border-t border-[var(--line-1)]`}>
//       <div className="mx-auto w-full max-w-6xl px-4 py-24 sm:px-6 sm:py-28">
//         <h2 className="max-w-3xl text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
//           Every watchlist tells you what moved. None tell you what matters.
//         </h2>

//         <ol className="mt-14 grid gap-x-10 gap-y-12 md:grid-cols-3">
//           {PROBLEMS.map((p) => (
//             <li key={p.n}>
//               <span className="num text-sm text-[var(--brand)]">{p.n}</span>
//               <h3 className="mt-3 text-lg font-semibold leading-snug text-[var(--ink-1)]">
//                 {p.title}
//               </h3>
//               <p className="mt-3 text-base leading-relaxed text-[var(--ink-2)]">
//                 {p.body}
//               </p>
//             </li>
//           ))}
//         </ol>

//         <p className="mt-14 text-base text-[var(--ink-2)]">
//           This project is an answer to all three.
//         </p>
//       </div>
//     </section>
//   );
// }

// /* --------------------------------------------------------------------------
//  * 3. How it works
//  * ----------------------------------------------------------------------- */

// const STEPS = [
//   {
//     n: "1",
//     title: "Learn what’s normal",
//     body: "Five years of daily bars per ticker. Nightly, the system estimates how volatile that stock usually is and how much of it is explained by its sector.",
//   },
//   {
//     n: "2",
//     title: "Remember exactly where you left off",
//     body: "Each holding checkpoints the price you actually saw, not the price at midnight. Your window is your absence, whatever length it was.",
//   },
//   {
//     n: "3",
//     title: "Subtract what the sector did",
//     body: "A stock down 6% on a day its sector fell 4% has moved 2% for its own reasons. That remainder is what gets scored.",
//   },
//   {
//     n: "4",
//     title: "Rank by surprise, not by size",
//     body: "The remainder is measured against that stock’s own expected range for a window that long. Most days, nothing crosses. That’s the point.",
//   },
// ];

// function HowItWorks() {
//   return (
//     <section id="how" className={`${ANCHOR} border-t border-[var(--line-1)]`}>
//       <div className="mx-auto w-full max-w-6xl px-4 py-24 sm:px-6 sm:py-28">
//         <h2 className="text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
//           Four steps, run per stock
//         </h2>

//         <ol className="mt-14 grid gap-x-8 gap-y-12 md:grid-cols-4">
//           {STEPS.map((s) => (
//             <li key={s.n} className="border-t border-[var(--line-1)] pt-5">
//               <span className="num inline-flex h-7 w-7 items-center justify-center rounded-full border border-[var(--line-1)] bg-[var(--surface-1)] text-xs text-[var(--brand)]">
//                 {s.n}
//               </span>
//               <h3 className="mt-4 text-base font-semibold leading-snug text-[var(--ink-1)]">
//                 {s.title}
//               </h3>
//               <p className="mt-2.5 text-sm leading-relaxed text-[var(--ink-2)]">
//                 {s.body}
//               </p>
//             </li>
//           ))}
//         </ol>
//       </div>
//     </section>
//   );
// }

// /* --------------------------------------------------------------------------
//  * 4. Features
//  * ----------------------------------------------------------------------- */

// const FEATURES = [
//   {
//     title: "It separates the market from the stock",
//     body: "Each move is measured net of what its sector did, so a market-wide selloff surfaces one line about the market instead of twenty about nothing.",
//   },
//   {
//     title: "The window is whatever your absence was",
//     body: "Ninety seconds or nine months. The expected range scales as σ · √t, so a four-day gap and a four-week gap are judged against different bars, not the same threshold.",
//   },
//   {
//     title: "Live data can never corrupt the model",
//     body: "Baselines are computed only from settled end-of-day bars. Intraday prices are displayed but never written to a statistic, so a bad tick can move a card and never move what “normal” means.",
//   },
// ];

// function Features() {
//   return (
//     <section id="features" className={`${ANCHOR} border-t border-[var(--line-1)]`}>
//       <div className="mx-auto w-full max-w-6xl px-4 py-24 sm:px-6 sm:py-28">
//         <h2 className="text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
//           What that buys you
//         </h2>

//         <div className="mt-14 grid gap-6 md:grid-cols-3">
//           {FEATURES.map((f) => (
//             <div key={f.title} className="glass-panel rounded-[var(--radius)] p-6">
//               <h3 className="text-base font-semibold leading-snug text-[var(--ink-1)]">
//                 {f.title}
//               </h3>
//               <p className="mt-3 text-sm leading-relaxed text-[var(--ink-2)]">
//                 {f.body}
//               </p>
//             </div>
//           ))}
//         </div>
//       </div>
//     </section>
//   );
// }

// /* --------------------------------------------------------------------------
//  * 5. How it reads
//  * ----------------------------------------------------------------------- */

// /**
//  * One digest card, exactly as the app renders it.
//  *
//  * Static markup carrying the values from the `single_name` scenario, which is
//  * asserted end to end in `tests/test_scenarios.py`. The cone is inline SVG
//  * rather than the charting component, so this page needs no client bundle and
//  * no request: the geometry is the same sigma-root-t the scorer divides by,
//  * drawn once instead of computed per card.
//  */
// function HowItReads() {
//   return (
//     <section className="border-t border-[var(--line-1)]">
//       <div className="mx-auto w-full max-w-6xl px-4 py-24 sm:px-6 sm:py-28">
//         <h2 className="text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
//           How it reads
//         </h2>

//         <div className="glass-panel mt-12 rounded-[var(--radius)] p-3 sm:p-6">
//           <div
//             className="overflow-hidden rounded-[var(--radius-sm)] bg-[var(--surface-1)]"
//             style={{ borderLeft: "2px solid var(--critical)" }}
//           >
//             <article className="p-4">
//               <div className="flex flex-wrap items-start justify-between gap-3">
//                 <div className="flex min-w-0 items-baseline gap-2">
//                   <span
//                     className="mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full"
//                     style={{
//                       background: "var(--critical)",
//                       boxShadow: "0 0 8px var(--critical)",
//                     }}
//                   />
//                   <span className="text-base font-semibold tracking-tight text-[var(--ink-1)]">
//                     NVDA
//                   </span>
//                   <span className="truncate text-xs text-[var(--ink-2)]">
//                     NVIDIA Corporation
//                   </span>
//                 </div>

//                 <div className="flex items-center gap-4">
//                   <div className="text-right">
//                     <div className="num text-base text-[var(--ink-1)]">164.83</div>
//                     <div className="num text-xs" style={{ color: "var(--critical)" }}>
//                       -6.30%
//                     </div>
//                   </div>
//                   <ConeSparkline />
//                 </div>
//               </div>

//               <p className="mt-2.5 text-sm leading-relaxed text-[var(--ink-1)]">
//                 Down 6.3% since Friday&rsquo;s close while tech was flat &mdash; 3.4
//                 sigma weaker than its sector explains, on 3.9x normal volume.
//               </p>

//               <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-[var(--ink-2)]">
//                 <span className="inline-flex items-center gap-1.5">
//                   <span
//                     className="inline-block h-2 w-2 rounded-full"
//                     style={{ background: "var(--good)" }}
//                   />
//                   <span>live</span>
//                 </span>
//                 <span>since Friday 4:00pm</span>
//                 <span className="rounded-[6px] border border-[var(--line-1)] px-2 py-0.5">
//                   Show the maths
//                 </span>
//               </div>
//             </article>
//           </div>

//           <p className="mt-5 text-sm text-[var(--ink-2)]">
//             Every card shows the move, what was expected of it, and why it crossed.
//           </p>
//         </div>
//       </div>
//     </section>
//   );
// }

// /**
//  * The move against the range it was expected to stay inside.
//  *
//  * The bands are 1 and 2 sigma widening as the square root of elapsed trading
//  * days, so the point where the line leaves the outer band is exactly where |z|
//  * passes 2, and the picture cannot disagree with the number beside it.
//  *
//  * The viewBox does the scaling rather than a fixed width, so on a phone the
//  * cone narrows instead of pushing the price off the edge of the card.
//  */
// function ConeSparkline() {
//   const band2 =
//     "2.0,17.3 10.0,13.8 18.0,12.4 26.0,11.3 34.0,10.3 42.0,9.5 50.0,8.8 58.0,8.1 66.0,7.4 74.0,6.8 82.0,6.3 90.0,5.7 98.0,5.2 106.0,4.7 114.0,4.3 122.0,3.8 130.0,3.4 130.0,31.2 122.0,30.8 114.0,30.3 106.0,29.9 98.0,29.4 90.0,28.9 82.0,28.3 74.0,27.8 66.0,27.2 58.0,26.5 50.0,25.8 42.0,25.1 34.0,24.3 26.0,23.3 18.0,22.2 10.0,20.8";
//   const band1 =
//     "2.0,17.3 10.0,15.6 18.0,14.8 26.0,14.3 34.0,13.8 42.0,13.4 50.0,13.0 58.0,12.7 66.0,12.4 74.0,12.1 82.0,11.8 90.0,11.5 98.0,11.3 106.0,11.0 114.0,10.8 122.0,10.5 130.0,10.3 130.0,24.3 122.0,24.0 114.0,23.8 106.0,23.6 98.0,23.3 90.0,23.1 82.0,22.8 74.0,22.5 66.0,22.2 58.0,21.9 50.0,21.6 42.0,21.2 34.0,20.8 26.0,20.3 18.0,19.8 10.0,19.0";

//   return (
//     <svg
//       viewBox="0 0 132 44"
//       className="h-11 w-[104px] shrink-0 sm:w-[132px]"
//       role="img"
//       aria-label="Cumulative move net of sector over one trading session: -6.30 percent, which is 3.4 sigma and outside its two-sigma expected range. Tier critical."
//     >
//       <polygon
//         points={band2}
//         fill="#8EA4BD"
//         fillOpacity="0.1"
//         stroke="#8EA4BD"
//         strokeOpacity="0.28"
//         strokeWidth="0.75"
//       />
//       <polygon points={band1} fill="#8EA4BD" fillOpacity="0.16" />
//       <line
//         x1="2"
//         y1="17.3"
//         x2="130"
//         y2="17.3"
//         stroke="rgba(255,255,255,0.22)"
//         strokeWidth="1"
//       />
//       <path
//         d="M2.0,17.3 L130.0,41.0"
//         fill="none"
//         stroke="#E6ECF3"
//         strokeWidth="1.4"
//       />
//       <path
//         d="M46.3,25.5 L130.0,41.0"
//         fill="none"
//         stroke="var(--critical)"
//         strokeWidth="1.8"
//       />
//       <circle cx="130" cy="41" r="2.5" fill="var(--critical)" />
//     </svg>
//   );
// }

// /* --------------------------------------------------------------------------
//  * 6. Evidence
//  * ----------------------------------------------------------------------- */

// const FIGURES = [
//   {
//     stat: "20 → 1",
//     label: "Twenty stocks down over 2%, one card surfaced",
//     note: "In the market_crash scenario every one of the twenty rows falls more than 2%, and the digest shows a single card: the index itself, which had a 5.9 sigma day as an instrument in its own right.",
//   },
//   {
//     stat: "16.7",
//     label: "Kurtosis, against 3.0 under a normal",
//     note: "Real returns are fat-tailed, so |z| exceeds 3 on 1.64% of checks against a predicted 0.27%. That is 6.1x the normal tail rate, reported rather than corrected for.",
//   },
//   {
//     stat: "5 years",
//     label: "Of daily bars, per ticker",
//     note: "Split-adjusted history behind every baseline, recomputed nightly from settled bars and never written to by an intraday price.",
//   },
// ];

// function Evidence() {
//   return (
//     <section id="evidence" className={`${ANCHOR} border-t border-[var(--line-1)]`}>
//       <div className="mx-auto w-full max-w-6xl px-4 py-24 sm:px-6 sm:py-28">
//         <h2 className="max-w-3xl text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
//           The thresholds were measured, not assumed
//         </h2>

//         <p className="mt-6 max-w-3xl text-base leading-relaxed text-[var(--ink-2)]">
//           Most tools that claim to filter noise never check whether they did. This
//           one replays a year of market history through the same scoring code the
//           app runs, and reports what it found &mdash; including where the model was
//           wrong.
//         </p>

//         <dl className="mt-14 grid gap-6 md:grid-cols-3">
//           {FIGURES.map((f) => (
//             <div
//               key={f.stat}
//               className="rounded-[var(--radius)] border border-[var(--line-1)] bg-[var(--surface-1)] p-6"
//             >
//               <dt className="num text-[clamp(2rem,4.5vw,2.75rem)] font-medium leading-none text-[var(--ink-1)]">
//                 {f.stat}
//               </dt>
//               <dd className="mt-4 text-sm font-medium text-[var(--ink-1)]">
//                 {f.label}
//               </dd>
//               <dd className="mt-2 text-sm leading-relaxed text-[var(--ink-2)]">
//                 {f.note}
//               </dd>
//             </div>
//           ))}
//         </dl>

//         <div className="mt-10 flex flex-wrap items-center gap-x-8 gap-y-3">
//           <p className="text-sm text-[var(--ink-2)]">
//             Measured from the running system, not projected.
//           </p>
//           <Link
//             href="/calibration"
//             className="inline-flex items-center gap-2 text-sm font-medium text-[var(--brand)] transition-colors hover:text-[var(--ink-1)]"
//           >
//             Read the full calibration data
//             <span aria-hidden="true" className="translate-y-px">
//               &rarr;
//             </span>
//           </Link>
//         </div>
//       </div>
//     </section>
//   );
// }

// /* --------------------------------------------------------------------------
//  * 7. Close
//  * ----------------------------------------------------------------------- */

// function Close() {
//   return (
//     <section className="border-t border-[var(--line-1)]">
//       <div className="mx-auto w-full max-w-6xl px-4 py-24 sm:px-6 sm:py-32">
//         <h2 className="max-w-2xl text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
//           Most days it will have nothing to say.
//         </h2>
//         <p className="mt-5 max-w-2xl text-base leading-relaxed text-[var(--ink-2)]">
//           Twenty tickers and a checkpoint a few sessions back are seeded on first
//           sign-in, so there is a real diff on screen immediately.
//         </p>
//         <Link
//           href="/login"
//           className="mt-10 inline-flex items-center rounded-[10px] bg-[var(--brand)] px-6 py-3 text-base font-semibold text-[var(--surface-0)] transition-colors hover:bg-[var(--brand-strong)] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand)]"
//         >
//           Get Started
//         </Link>
//       </div>
//     </section>
//   );
// }

import type { Metadata } from "next";
import Link from "next/link";
import { LandingNav } from "@/components/landing/LandingNav";

/**
 * The public page.
 *
 * A server component with no data fetching, because everything it claims is
 * either a property of the design or a number already measured and written
 * down. Nothing here reads from the API: a marketing page that can be down
 * because Postgres is down is worse than one that is merely static.
 *
 * Every figure traces to README.md or to the calibration artifact behind
 * /calibration. Nothing is projected, rounded up, or invented.
 */

export const metadata: Metadata = {
  title: "Smart Market Watchlist",
  description:
    "A watchlist that gets quieter as it gets smarter. It surfaces what is statistically unusual for a specific stock, since you last looked, net of what its sector did.",
  openGraph: {
    title: "Smart Market Watchlist",
    description:
      "Ranks moves by surprise, not by size: idiosyncratic displacement measured against a stock's own expected range for a window as long as your absence.",
  },
};

/* Clears the 64px sticky bar with room to breathe. */
const ANCHOR = "scroll-mt-24";

export default function LandingPage() {
  return (
    <div className="relative min-h-screen bg-[var(--surface-0)] text-[var(--ink-1)] selection:bg-[var(--brand)] selection:text-white overflow-hidden">
      {/* Premium Ambient Background Glows */}
      <div className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[800px] w-[1200px] -translate-x-1/2 opacity-30 md:opacity-50">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,var(--brand-glow),transparent_60%)]" />
      </div>

      <LandingNav />

      <main className="relative z-10">
        <Hero />
        <Problem />
        <HowItWorks />
        <Features />
        <HowItReads />
        <Evidence />
        <Close />
      </main>

      <footer className="border-t border-[var(--line-1)] bg-[var(--surface-inset)]">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-10 text-sm text-[var(--ink-2)] sm:flex-row sm:items-center sm:justify-between">
          <span className="font-medium text-[var(--ink-1)]">Smart Market Watchlist</span>
          <span className="text-xs sm:text-sm">
            US-listed equities and ETFs. A prototype running under personal-use
            provider licences.
          </span>
        </div>
      </footer>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * 1. Hero
 * ----------------------------------------------------------------------- */

function Hero() {
  return (
    <section className="group relative mx-auto w-full max-w-6xl px-4 pb-20 pt-28 sm:px-6 sm:pb-32 sm:pt-40">
      {/* 
        Hover Glow Effect: 
        Hidden by default (opacity-0). Fades in smoothly to 100% when 
        the user hovers anywhere in the section (group-hover). 
      */}
      <div className="pointer-events-none absolute inset-0 -z-10 flex items-center justify-center opacity-0 transition-opacity duration-1000 group-hover:opacity-100">
        <div className="h-[40rem] w-[50rem] rounded-full bg-[radial-gradient(circle_at_center,rgba(59,130,246,0.15)_0%,transparent_70%)] blur-[60px]" />
      </div>

      <div className="relative z-10 max-w-4xl text-center mx-auto flex flex-col items-center">
        <div className="animate-in mb-6 inline-flex items-center rounded-full border border-[var(--brand)]/30 bg-[var(--brand)]/10 px-4 py-1.5 text-sm font-medium text-[var(--brand)] backdrop-blur-sm transition-colors group-hover:border-[var(--brand)]/50">
          <span className="relative flex h-2 w-2 mr-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--brand)] opacity-75"></span>
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--brand)]"></span>
          </span>
          Redefining the Signal-to-Noise Ratio
        </div>

        <h1 className="animate-in stagger-1 text-balance text-[clamp(2.5rem,6vw,4.5rem)] font-bold leading-[1.05] tracking-tight text-[var(--ink-1)]">
          A watchlist that gets <br className="hidden sm:block" />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-[var(--brand)]">
            quieter as it gets smarter.
          </span>
        </h1>

        <p className="animate-in stagger-2 mt-8 max-w-2xl text-[clamp(1.125rem,2vw,1.25rem)] leading-relaxed text-[var(--ink-2)] transition-colors duration-500 group-hover:text-[var(--ink-1)]">
          Surfaces what is statistically unusual for a specific stock, since you
          last looked, net of what its sector did.
        </p>

        <div className="animate-in stagger-3 mt-10 flex flex-wrap items-center justify-center gap-6">
          <Link
            href="/login"
            className="group/btn relative inline-flex items-center justify-center rounded-full bg-[var(--brand)] px-8 py-3.5 text-base font-semibold text-white shadow-[0_0_24px_var(--brand-glow)] transition-all hover:bg-[var(--brand-strong)] hover:shadow-[0_0_32px_rgba(59,130,246,0.4)] hover:-translate-y-0.5"
          >
            Get Started
            <svg className="ml-2 h-4 w-4 transition-transform group-hover/btn:translate-x-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </Link>

          <Link
            href="#how"
            className="inline-flex items-center gap-2 text-base font-medium text-[var(--ink-2)] transition-colors hover:text-[var(--ink-1)]"
          >
            See how it works
          </Link>
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------------------
 * 2. Problem
 * ----------------------------------------------------------------------- */

const PROBLEMS = [
  {
    n: "01",
    title: "A red day is not information.",
    body: "When the market drops 5%, twenty of your twenty holdings turn red. Nothing on that screen distinguishes a stock that fell with everything else from one that fell for its own reasons.",
  },
  {
    n: "02",
    title: "“Today” is the wrong window.",
    body: "Standard watchlists reset at midnight. If you last looked on Friday, a Tuesday percentage answers a question you didn’t ask.",
  },
  {
    n: "03",
    title: "One percent means different things.",
    body: "A 1% move in a utility is remarkable. A 1% move in a biotech is Tuesday. A single threshold applied to every holding is either too loud for one and silent for the other.",
  },
];

function Problem() {
  return (
    <section id="problem" className={`${ANCHOR} relative py-24 sm:py-32`}>
      <div className="absolute inset-0 bg-gradient-to-b from-[var(--surface-0)] via-[var(--surface-1)] to-[var(--surface-0)] opacity-50 -z-10" />
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
        <h2 className="max-w-3xl text-[clamp(2rem,4vw,3rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
          Every watchlist tells you what moved.<br />
          <span className="text-[var(--ink-3)]">None tell you what matters.</span>
        </h2>

        <div className="mt-16 grid gap-6 md:grid-cols-3">
          {PROBLEMS.map((p) => (
            <div 
              key={p.n} 
              className="glass-panel group relative rounded-[var(--radius)] p-8 transition-all duration-300 hover:-translate-y-1 hover:border-[var(--brand)]/30 hover:shadow-[0_8px_30px_var(--brand-glow)]"
            >
              <div className="absolute top-0 right-8 -translate-y-1/2">
                <span className="num text-4xl font-black text-[var(--surface-2)] group-hover:text-[var(--brand)]/20 transition-colors duration-500">
                  {p.n}
                </span>
              </div>
              <h3 className="mt-4 text-xl font-semibold leading-snug text-[var(--ink-1)]">
                {p.title}
              </h3>
              <p className="mt-4 text-sm leading-relaxed text-[var(--ink-2)]">
                {p.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------------------
 * 3. How it works
 * ----------------------------------------------------------------------- */

const STEPS = [
  {
    n: "1",
    title: "Learn what’s normal",
    body: "Five years of daily bars per ticker. Nightly, the system estimates how volatile that stock usually is and how much of it is explained by its sector.",
  },
  {
    n: "2",
    title: "Remember where you left off",
    body: "Each holding checkpoints the price you actually saw, not the price at midnight. Your window is your absence, whatever length it was.",
  },
  {
    n: "3",
    title: "Subtract what the sector did",
    body: "A stock down 6% on a day its sector fell 4% has moved 2% for its own reasons. That remainder is what gets scored.",
  },
  {
    n: "4",
    title: "Rank by surprise, not size",
    body: "The remainder is measured against that stock’s own expected range for a window that long. Most days, nothing crosses. That’s the point.",
  },
];

function HowItWorks() {
  return (
    <section id="how" className={`${ANCHOR} py-24 sm:py-32`}>
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-16">
          <h2 className="text-[clamp(2rem,4vw,3rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
            Four steps,<br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-[var(--brand)]">run per stock.</span>
          </h2>
          <p className="max-w-sm text-sm text-[var(--ink-2)] pb-2">
            An analytical approach to filtering market noise, executed automatically every session.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s) => (
            <div key={s.n} className="relative pt-6">
              {/* Top border line with glowing dot on hover */}
              <div className="absolute top-0 left-0 w-full h-[1px] bg-[var(--line-1)] group-hover:bg-[var(--brand)]/30 transition-colors" />
              
              <span className="num inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--brand)]/20 bg-[var(--brand)]/10 text-xs font-bold text-[var(--brand)] shadow-[0_0_12px_var(--brand-glow)]">
                {s.n}
              </span>
              <h3 className="mt-6 text-lg font-semibold leading-snug text-[var(--ink-1)]">
                {s.title}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-[var(--ink-2)]">
                {s.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------------------
 * 4. Features
 * ----------------------------------------------------------------------- */

const FEATURES = [
  {
    title: "Separates the market from the stock",
    body: "Each move is measured net of what its sector did, so a market-wide selloff surfaces one line about the market instead of twenty about nothing.",
  },
  {
    title: "The window is your absence",
    body: "Ninety seconds or nine months. The expected range scales as σ · √t, so a four-day gap and a four-week gap are judged against different bars, not the same threshold.",
  },
  {
    title: "Live data never corrupts the model",
    body: "Baselines are computed only from settled end-of-day bars. Intraday prices are displayed but never written to a statistic, so a bad tick can't move what “normal” means.",
  },
];

function Features() {
  return (
    <section id="features" className={`${ANCHOR} py-24 sm:py-32 relative`}>
      <div className="absolute inset-0 bg-[var(--surface-1)]/30 border-y border-[var(--line-1)] -z-10" />
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
        <h2 className="text-center text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)] mb-14">
          What that buys you
        </h2>

        <div className="grid gap-6 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div 
              key={f.title} 
              className="glass-panel group rounded-[var(--radius)] p-8 transition-all hover:bg-[var(--surface-2)]/40 hover:border-[var(--brand)]/20"
            >
              <div className="mb-6 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--surface-2)] border border-[var(--line-1)] text-[var(--brand)] group-hover:scale-110 group-hover:shadow-[0_0_15px_var(--brand-glow)] transition-all">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h3 className="text-lg font-semibold leading-snug text-[var(--ink-1)]">
                {f.title}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-[var(--ink-2)]">
                {f.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------------------
 * 5. How it reads
 * ----------------------------------------------------------------------- */

function HowItReads() {
  return (
    <section className="py-24 sm:py-32 relative">
      {/* Decorative Glow Behind Card */}
      <div className="absolute left-1/2 top-1/2 -z-10 h-64 w-[80%] -translate-x-1/2 -translate-y-1/2 bg-[var(--critical)] opacity-[0.03] blur-[100px]" />
      
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 flex flex-col lg:flex-row lg:items-center gap-12 lg:gap-20">
        <div className="lg:w-1/2">
          <h2 className="text-[clamp(2rem,4vw,3rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
            How it reads
          </h2>
          <p className="mt-6 text-base leading-relaxed text-[var(--ink-2)]">
            Every card shows the move, what was expected of it, and why it crossed. Information is dense but hierarchal, designed to be read in seconds.
          </p>
        </div>

        <div className="lg:w-1/2 w-full">
          <div className="glass-panel relative rounded-[var(--radius)] p-2 sm:p-4 shadow-[0_20px_40px_-15px_rgba(0,0,0,0.5)]">
            {/* The Actual Card Replica */}
            <div
              className="overflow-hidden rounded-[var(--radius-sm)] bg-[var(--surface-0)] border border-[var(--line-1)] transition-transform hover:-translate-y-0.5"
              style={{ borderLeft: "3px solid var(--critical)" }}
            >
              <article className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 items-baseline gap-2.5">
                    <span
                      className="mt-1.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full animate-pulse"
                      style={{
                        background: "var(--critical)",
                        boxShadow: "0 0 12px var(--critical)",
                      }}
                    />
                    <span className="text-lg font-bold tracking-tight text-[var(--ink-1)]">
                      NVDA
                    </span>
                    <span className="truncate text-xs font-medium text-[var(--ink-3)]">
                      NVIDIA Corporation
                    </span>
                  </div>

                  <div className="flex items-center gap-5">
                    <div className="text-right">
                      <div className="num text-lg font-semibold text-[var(--ink-1)]">164.83</div>
                      <div className="num text-xs font-medium" style={{ color: "var(--critical)" }}>
                        -6.30%
                      </div>
                    </div>
                    <ConeSparkline />
                  </div>
                </div>

                <p className="mt-4 text-sm leading-relaxed text-[var(--ink-1)]">
                  Down 6.3% since Friday&rsquo;s close while tech was flat &mdash; <strong className="font-semibold text-white">3.4 sigma weaker</strong> than its sector explains, on 3.9x normal volume.
                </p>

                <div className="mt-5 flex flex-wrap items-center gap-3 text-xs font-medium text-[var(--ink-2)]">
                  <span className="inline-flex items-center gap-1.5 bg-[var(--surface-1)] px-2 py-1 rounded-md border border-[var(--line-1)]">
                    <span
                      className="inline-block h-1.5 w-1.5 rounded-full"
                      style={{ background: "var(--good)", boxShadow: "0 0 8px var(--good)" }}
                    />
                    <span>live</span>
                  </span>
                  <span className="bg-[var(--surface-1)] px-2 py-1 rounded-md border border-[var(--line-1)]">since Friday 4:00pm</span>
                  <span className="ml-auto rounded-md bg-[var(--surface-2)] border border-[var(--line-1)] px-3 py-1 hover:text-white hover:bg-[var(--line-1)] transition-colors cursor-pointer">
                    Show the maths
                  </span>
                </div>
              </article>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ConeSparkline() {
  const band2 =
    "2.0,17.3 10.0,13.8 18.0,12.4 26.0,11.3 34.0,10.3 42.0,9.5 50.0,8.8 58.0,8.1 66.0,7.4 74.0,6.8 82.0,6.3 90.0,5.7 98.0,5.2 106.0,4.7 114.0,4.3 122.0,3.8 130.0,3.4 130.0,31.2 122.0,30.8 114.0,30.3 106.0,29.9 98.0,29.4 90.0,28.9 82.0,28.3 74.0,27.8 66.0,27.2 58.0,26.5 50.0,25.8 42.0,25.1 34.0,24.3 26.0,23.3 18.0,22.2 10.0,20.8";
  const band1 =
    "2.0,17.3 10.0,15.6 18.0,14.8 26.0,14.3 34.0,13.8 42.0,13.4 50.0,13.0 58.0,12.7 66.0,12.4 74.0,12.1 82.0,11.8 90.0,11.5 98.0,11.3 106.0,11.0 114.0,10.8 122.0,10.5 130.0,10.3 130.0,24.3 122.0,24.0 114.0,23.8 106.0,23.6 98.0,23.3 90.0,23.1 82.0,22.8 74.0,22.5 66.0,22.2 58.0,21.9 50.0,21.6 42.0,21.2 34.0,20.8 26.0,20.3 18.0,19.8 10.0,19.0";

  return (
    <svg
      viewBox="0 0 132 44"
      className="h-11 w-[104px] shrink-0 sm:w-[132px]"
      role="img"
      aria-label="Cumulative move net of sector over one trading session: -6.30 percent, which is 3.4 sigma and outside its two-sigma expected range."
    >
      <polygon points={band2} fill="#8EA4BD" fillOpacity="0.08" stroke="#8EA4BD" strokeOpacity="0.25" strokeWidth="1" />
      <polygon points={band1} fill="#8EA4BD" fillOpacity="0.12" />
      <line x1="2" y1="17.3" x2="130" y2="17.3" stroke="rgba(255,255,255,0.15)" strokeWidth="1" strokeDasharray="2 2" />
      <path d="M2.0,17.3 L130.0,41.0" fill="none" stroke="#E6ECF3" strokeWidth="1.5" strokeOpacity="0.8" />
      <path d="M46.3,25.5 L130.0,41.0" fill="none" stroke="var(--critical)" strokeWidth="2" />
      <circle cx="130" cy="41" r="3" fill="var(--surface-0)" stroke="var(--critical)" strokeWidth="2" />
    </svg>
  );
}

/* --------------------------------------------------------------------------
 * 6. Evidence
 * ----------------------------------------------------------------------- */

const FIGURES = [
  {
    stat: "20 → 1",
    label: "Twenty stocks down over 2%, one card surfaced",
    note: "In the market_crash scenario every one of the twenty rows falls more than 2%, and the digest shows a single card: the index itself, which had a 5.9 sigma day.",
  },
  {
    stat: "16.7",
    label: "Kurtosis, against 3.0 under a normal",
    note: "Real returns are fat-tailed, so |z| exceeds 3 on 1.64% of checks against a predicted 0.27%. That is 6.1x the normal tail rate, reported rather than corrected for.",
  },
  {
    stat: "5 Years",
    label: "Of daily bars, per ticker",
    note: "Split-adjusted history behind every baseline, recomputed nightly from settled bars and never written to by an intraday price.",
  },
];

function Evidence() {
  return (
    <section id="evidence" className={`${ANCHOR} py-24 sm:py-32 bg-[var(--surface-1)]/20 border-y border-[var(--line-1)]`}>
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
        <h2 className="max-w-3xl text-[clamp(1.75rem,3.6vw,2.5rem)] font-semibold leading-tight tracking-tight text-[var(--ink-1)]">
          The thresholds were measured,<br /> not assumed.
        </h2>

        <p className="mt-6 max-w-2xl text-base leading-relaxed text-[var(--ink-2)]">
          Most tools that claim to filter noise never check whether they did. This
          one replays a year of market history through the same scoring code the
          app runs, and reports what it found.
        </p>

        <dl className="mt-16 grid gap-6 md:grid-cols-3">
          {FIGURES.map((f) => (
            <div
              key={f.stat}
              className="glass-panel group rounded-[var(--radius)] p-8 hover:bg-[var(--surface-2)]/50 transition-colors"
            >
              <dt className="num text-[clamp(2.5rem,5vw,3.5rem)] font-bold tracking-tight text-transparent bg-clip-text bg-gradient-to-br from-white to-[var(--ink-3)] group-hover:from-[var(--brand)] group-hover:to-blue-300 transition-all duration-300">
                {f.stat}
              </dt>
              <dd className="mt-6 text-base font-semibold text-[var(--ink-1)]">
                {f.label}
              </dd>
              <dd className="mt-3 text-sm leading-relaxed text-[var(--ink-2)]">
                {f.note}
              </dd>
            </div>
          ))}
        </dl>

        <div className="mt-12 flex flex-wrap items-center gap-x-6 gap-y-3 p-4 rounded-xl bg-[var(--surface-2)]/30 border border-[var(--line-1)] inline-flex">
          <p className="text-sm font-medium text-[var(--ink-2)]">
            Measured from the running system, not projected.
          </p>
          <div className="w-px h-4 bg-[var(--line-1)] hidden sm:block"></div>
          <Link
            href="/calibration"
            className="group inline-flex items-center gap-2 text-sm font-semibold text-[var(--brand)] transition-colors hover:text-white"
          >
            Read the calibration data
            <svg className="h-4 w-4 transition-transform group-hover:translate-x-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </Link>
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------------------
 * 7. Close
 * ----------------------------------------------------------------------- */

function Close() {
  return (
    <section className="py-24 sm:py-40 relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom,var(--brand-glow),transparent_50%)] opacity-40 -z-10" />
      <div className="mx-auto w-full max-w-4xl px-4 sm:px-6 text-center">
        <h2 className="text-[clamp(2.5rem,5vw,3.5rem)] font-bold leading-tight tracking-tight text-[var(--ink-1)]">
          Most days it will have <br className="hidden sm:block" />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-[var(--brand)]">nothing to say.</span>
        </h2>
        <p className="mt-6 mx-auto max-w-2xl text-lg leading-relaxed text-[var(--ink-2)]">
          Twenty tickers and a checkpoint a few sessions back are seeded on first
          sign-in, so there is a real diff on screen immediately.
        </p>
        <div className="mt-12">
          <Link
            href="/login"
            className="group relative inline-flex items-center justify-center rounded-full bg-[var(--brand)] px-10 py-4 text-lg font-semibold text-white shadow-[0_0_30px_var(--brand-glow)] transition-all hover:bg-[var(--brand-strong)] hover:shadow-[0_0_40px_rgba(59,130,246,0.5)] hover:-translate-y-1"
          >
            Start your watchlist
            <svg className="ml-2 h-5 w-5 transition-transform group-hover:translate-x-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>
          </Link>
        </div>
      </div>
    </section>
  );
}