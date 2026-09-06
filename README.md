# Smart Market Watchlist

A watchlist that gets **quieter** as it gets smarter. It surfaces what is
statistically unusual **for that specific stock**, **since you last looked**,
**net of what its sector did**, and says why in one line.

```bash
docker compose up
```

Open <http://localhost:3000>, enter any email, press **Continue**. No API keys.
No waiting for market hours.

---

## What it looks like

<img width="1917" height="891" alt="Screenshot 2026-09-06 220133" src="https://github.com/user-attachments/assets/2ef13c80-3561-4237-a190-42be451e3ab6" />

*The digest. Every card carries the move, the range that was expected of it, and
one sentence assembled from the same numbers that produced the ranking.*

<img width="1916" height="905" alt="Screenshot 2026-09-06 220150" src="https://github.com/user-attachments/assets/7f24d928-a633-424a-8820-8b40b479a84b" />

*Show the maths. The raw move, how much of it the sector explains, the remainder
that belongs to the stock, and the range that was expected over a window this
long. Nothing here is a black box.*

<img width="1917" height="911" alt="Screenshot 2026-09-06 220257" src="https://github.com/user-attachments/assets/c88b9eb0-2096-4414-b38b-059371a1d840" />

*Calibration. Twelve months replayed through the same scoring function the app
calls. The model predicted 1.62 criticals per week and measured 6.27; the gap is
fat tails, reported rather than corrected for.*

---

## Contents

- [What it looks like](#what-it-looks-like)
- [The problem](#the-problem)
- [The solution](#the-solution)
- [Quick start](#quick-start)
- [System architecture](#system-architecture)
- [How a digest is produced](#how-a-digest-is-produced)
- [What counts as meaningful](#what-counts-as-meaningful)
- [Is the alert rate any good?](#is-the-alert-rate-any-good)
- [Key design decisions](#key-design-decisions)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Local development](#local-development)
- [Tests](#tests)
- [Failure modes](#failure-modes)
- [Scope and limits](#scope-and-limits)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)

---

## The problem

A conventional watchlist is a table of percentages that resets at midnight. It
fails in four ways, and all four are failures of framing rather than of data.

**A red day is not information.** When the market falls 5%, twenty of twenty
holdings turn red. Nothing on that screen separates a stock that fell with
everything else from one that fell for its own reasons.

**"Today" is the wrong window.** If you last looked on Friday and it is now
Tuesday, a "today" percentage answers a question you did not ask.

**Size is not surprise.** A 3% move in a utility that normally moves 0.5% a day
is an event. A 3% move in a small-cap semiconductor is a Tuesday. Sorting by
percentage change ranks the second above the first.

**A round trip is invisible.** A stock that spiked 12% on Tuesday and gave it all
back by Friday shows a ~0% weekly change. For someone who was away all week, that
is a total miss — and no consumer watchlist catches it.

## The solution

Rank by **surprise**, not by size, over **your** window.

For each ticker the system holds a per-stock baseline — its own idiosyncratic
volatility, its own beta to its own sector — rebuilt nightly from five years of
split-adjusted daily bars. When you open the app it resolves *since you last
looked* into a reference price and a matching dispersion, removes what the sector
did, and scores what is left on four signals. Anything unremarkable collapses into
one line of text.

Then it tells you, in a sentence built from the same numbers that produced the
ranking:

> Down 6.3% since Friday's close while tech was flat — 3.4 sigma weaker than its
> sector explains, on 3.9x normal volume.

> Moved 5.9 sigma on Tuesday and gave it back, ending −0.9% against its sector
> since Friday's close, on 3.8x normal volume.

> The whole market is down 5.0% today (6.1 sigma). Moves below are measured net
> of that.

---

## Quick start

### Requirements

Docker Desktop, or Docker Engine with Compose v2. Nothing else — no API keys, no
Python, no Node.

### Run

```bash
docker compose up
```

First boot takes about a minute: it applies the schema, syncs the symbol catalog,
seeds the twelve benchmarks, seeds twenty demo tickers, and writes a checkpoint a
few sessions back so there is a real diff on screen rather than a page of zeroes.

**On a completely fresh volume the first run may fail.** The API and worker apply
migrations concurrently and can race on `CREATE EXTENSION pg_trgm`, so compose
reports `dependency failed to start`. It is known and harmless — the extension
exists by then, so run it again and it comes up clean:

```bash
docker compose up -d          # run a second time if the first run races
docker compose ps             # api, worker, web, postgres, redis all up
```

| Service | URL |
|---|---|
| Web | <http://localhost:3000> |
| API docs (OpenAPI) | <http://localhost:8000/docs> |
| Health | <http://localhost:8000/healthz> |

`you@example.com` is the address the demo seeder uses, so it arrives with twenty
tickers and history. **Any other address gets a genuinely empty account** — which
is the point of the sign-in screen.

### If you only have five minutes

Boot, sign in as `you@example.com`, and open the top card's **Show the maths**
panel. That single screen is the whole product: the raw move, how much of it the
sector explains, what is left over, and the range that was expected of it.

Then open **`/calibration`**. It reports that the model predicted 1.62 criticals
per week and measured 6.27 — and explains why that gap was reported rather than
tuned away.

### Sign-in

There are two identity paths and exactly one is live at a time.

With no `SUPABASE_JWKS_URL`, a local HS256 issuer signs a token for **any** email.
There is no password, because there is nothing to protect yet and pretending
otherwise would be theatre. What the screen exists to prove is that two addresses
are two users, which is why the login page says so in as many words:

> *Dev auth — any email signs in. Set `SUPABASE_JWKS_URL` to enable real JWT
> verification.*

Set `SUPABASE_JWKS_URL` and the switch flips in one move: tokens are verified
against the project's JWKS, and `POST /api/auth/login` starts returning 404. The
local issuer is not merely unadvertised in that mode — it is gone, so a deployment
cannot be talked into accepting a token it minted for itself. It also refuses to
run under `PROVIDER_MODE=live`, and `/healthz` reports which path is active.

The user id is derived from the email (`uuid5` over `smw-dev:<email>`) rather than
stored, so the same address is the same account across a `docker compose down -v`,
and `scripts/seed_demo.py` and a browser sign-in land on the same row without
coordinating.

**To watch the isolation for yourself:** sign in as `a@test.com`, add a few
tickers, dismiss a critical; sign out; sign in as `b@test.com` and find an empty
watchlist; sign back in as `a@test.com` and find the tickers still there and the
dismissed card still dismissed. That walk is asserted in
`tests/test_auth.py::test_two_users_watchlists_and_snapshots_are_fully_isolated`,
which fails if `user_id` is ever dropped from a WHERE clause.

### The four demo scenarios

Each one is a claim the product makes, so each is also an assertion in
`tests/test_scenarios.py`.

```bash
REPLAY_SCENARIO=market_crash docker compose up   # a market-wide -5% day
REPLAY_SCENARIO=single_name  docker compose up   # NVDA -6.2%, sector flat
REPLAY_SCENARIO=spike_revert docker compose up   # AMD +12% then round-trips
REPLAY_SCENARIO=baseline     docker compose up   # an ordinary session (default)
```

Switching scenarios needs a fresh database, because the baselines are built from
the scenario's bars. Use `export` rather than an inline variable — if the boot
race above makes you re-run `up`, an inline variable does not survive and the
second run silently boots `baseline`:

```bash
docker compose down -v
export REPLAY_SCENARIO=market_crash
docker compose up -d --build
docker compose up -d                                # if the first run races

docker compose exec api printenv REPLAY_SCENARIO    # confirm it took
```

**Two sets of numbers appear below, and they are not interchangeable.** Figures
from `tests/test_scenarios.py` come from a fixed 25-ticker list scored at the
close through the offline harness. The demo seeder loads a different 20-ticker
watchlist and `REPLAY_CLOCK=compressed` moves prices continuously, so what is on
your screen will differ. Where they diverge, both are named.

**`market_crash`** — a market-wide selloff. On the demo watchlist, thirteen of
the twenty holdings are down more than 2%, and a banner reports the market move
with everything below scored net of it:

> The whole market is down 3.9% today (4.8 sigma). Moves below are measured net
> of that.

The criticals that survive are the ones that fell *harder* than the market
explains — not the ones that merely fell. That distinction is the whole point:
a conventional watchlist shows twenty red rows and cannot tell you which is
which. The exact count on screen moves with the compressed clock; the harness,
scoring its own list at the close and counting equities only, reduces the same
day to a single card.

**`spike_revert`** — AMD ends the week down 0.45%, so the endpoint comparison
sees nothing at all (`z_move = −0.17`). It is still the top card, because the
path term contributes **2.65 of its 3.49** attention against the move term's
0.17. This is the case no consumer watchlist catches.

**`single_name`** — NVDA at −6.3% with its sector flat, 3.4σ weaker than the
sector explains, and the clearest critical on the list.

**`baseline`** — an ordinary session with two events injected into a genuine
one-sigma day. Most of the list stays minor or quiet, and the two loudest cards
are the two injected events (META and BA). The bar is deliberately "most of the
list says nothing" rather than "the list is silent": the measured alert rate lives
on `/calibration`, not in a threshold chosen to flatter a demo.

### Time travel

`?as_if_last_seen=<iso8601>` on the digest re-anchors the diff to any past moment,
so you can look at a historical window on demand instead of waiting a week to
accumulate one. The UI exposes it under **View a past window**.

### Live providers

```bash
PROVIDER_MODE=live TWELVEDATA_API_KEY=... FINNHUB_API_KEY=... docker compose up
```

If a key is missing, that half falls back to replay and says so in `/healthz`,
rather than booting a half-dead system.

---

## System architecture

```
                          ┌──────────────────────────┐
                          │  Next.js 15 (App Router) │
                          │  React 19 · Tailwind     │
                          └───────────┬──────────────┘
                                      │ REST + Bearer JWT
                                      │ ETag / 304
                                      │ adaptive poll: 20 s open, 15 min closed
                          ┌───────────▼──────────────┐
                          │  FastAPI (uvicorn)       │
                          │  routers · digest_service│
                          │  scoring/ (pure)         │
                          └──┬──────────────────┬────┘
                             │                  │
                     ┌───────▼──────┐    ┌──────▼──────┐
                     │  PostgreSQL  │    │    Redis    │
                     │  + pg_trgm   │    │ db0 cache   │
                     └───────▲──────┘    │ db1 locks   │
                             │           │ noeviction  │
                          ┌──┴──────────────────┴────┐
                          │  Worker (one process)    │
                          │  NIGHTLY   fetch→compute │
                          │  INTRADAY  WS top-50     │
                          │            + on-demand   │
                          └───────────┬──────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │  twelvedata · finnhub · replay    │
                    └───────────────────────────────────┘
```

Five containers. The API and worker share one image, because they share the whole
`api/` package — config, calendar, clock, quota, scoring.

### Two clocks

"Unusual" is a claim about a distribution, which is a **daily** object: σ and β
move once a night from settled data. "Since you last looked" is a **per-user**
window that can be 90 seconds or 9 months. The bridge between them is
`session_span()`, which measures trading time in units of one full session,
weekends and holidays contributing nothing.

**Nothing intraday ever writes to a statistic.** That one rule means the λ
constants calibrated for daily data are dimensionally correct, and a corrupted
tick cannot poison a baseline shared by everyone watching that ticker.

### Two providers

Finnhub's `/stock/candle` returns 403 on free keys, so history cannot come from
there at all. Twelve Data charges one credit per `/time_series` call regardless of
bar count — five years of split-adjusted bars for the price of one day.

| | Twelve Data | Finnhub |
|---|---|---|
| Role | The slow clock | The fast clock |
| Free tier | 800 credits/day, 8/min | 60 REST/min (metered at 45) |
| Provides | Daily bars, symbol catalog, market state | Quotes, WebSocket (50 symbols), sectors, earnings |

---

## How a digest is produced

```
1.  GET /api/digest  (Bearer JWT, If-None-Match)
        │
2.  refresh what is stale ──▶ cold tier: cache → single-flight → provider
        │                     (benchmarks included: a stale benchmark
        │                      mis-attributes a sector move to the stock)
        │
3.  one SQL join: watchlist × tickers × baseline × latest × snapshot
        │
4.  per ticker:
        resolve_window()   since-you-last-looked → reference price + dispersion
        signals.*          z_move · z_path · vol_score · breach_score
        score()            weighted composite, tier, two gates
        reasons.build()    the sentence, from the same numbers
        │
5.  rank on ABSOLUTE attention · group into loud / minor / quiet
        │
6.  issue an HMAC digest token carrying every observed price and timestamp
        │
7.  ETag over a stabilised body ──▶ 304 when nothing changed
        │
8.  client: 2 s at ≥50% visibility marks read (never a critical)
            batch 5 s, flush on pagehide with keepalive
        │
9.  POST /api/ack ──▶ monotonic per-ticker checkpoint update
```

The read path does no writes and no avoidable provider calls, which is what keeps
p50 in the tens of milliseconds and makes cost **O(list size)** rather than
O(users × tickers).

---

## What counts as meaningful

Four signals over the user's window, all built from **absolute** magnitudes with
direction carried separately. Ranking a signed composite would sort a −5σ crash
below a +0.5σ drift, where it would never be seen.

```
attention = 1.00 · min(|z_move|, 6)      idiosyncratic displacement
          + 0.45 · min(z_path,  6)       largest single day in the window
          + 0.35 · vol_score             log2 of peak volume ratio, clamped
          + 0.40 · breach_score          continuous 52-week breach
```

| Tier | Threshold |
|---|---|
| critical | ≥ 3.00 |
| notable | 1.75 – 3.00 |
| minor | 0.90 – 1.75 |
| quiet | < 0.90 |

Two gates sit beneath the statistics. `MIN_N_EFF` floors the dispersion so a
recheck ten minutes into a session cannot divide by nearly zero. The
**material-move gate** then requires 0.5% of actual movement before anything can
be called critical or notable.

Earnings **widens σ**; it never adds score. The price reaction *is* the surprise
and `z_move` already contains it, and a 3σ move on a scheduled catalyst is *less*
surprising than one on a random Tuesday. Variance is additive across days, so it
belongs in the denominator:

```
expected σ² = σ_idio² · n_ordinary + (σ_idio · 2.0)² · n_earnings
```

---

## Is the alert rate any good?

```bash
python -m scripts.calibrate      # then open /calibration
```

Twelve months of stored bars for a 40-ticker basket, replayed through
`api.scoring.score.score` — **the same function the digest endpoint calls, not a
model of it.** 10,080 checks:

| | Predicted (normal null) | Observed |
|---|---|---|
| Critical per week | 1.62 | 6.27 |
| Notable per day | 3.81 | 2.78 |

"Predicted" holds the volume and breach terms at their observed values, keeps the
same gates and tiering, and replaces only the return distribution with a standard
normal — so the gap isolates **fat tails** rather than the choice of weights. And
the tails are where you would expect:

| | Observed | Under a normal |
|---|---|---|
| Residual sd | 1.065 | 1.000 |
| Kurtosis | 16.65 | 3.00 |
| P(\|z\| > 3) | 1.65% | 0.27% |

Real returns are fat-tailed, so the realised critical rate runs about four times
the Gaussian prediction. That is **reported, not corrected for**. The residual
histograms are also shown per ticker on the detail page; using them to replace
the Gaussian z is designed and deliberately not built.

**precision@critical** sits on the same page: the fraction of critical cards a
human actually agreed with, from `digest_feedback`. It is `null` rather than `1.0`
before anyone has voted, because an unjudged critical is not a correct one. This
is the only number in the system that checks whether "meaningful" is meaningful to
a person; everything else validates the model against itself.

---

## Key design decisions

Full reasoning for each is in [`ARCHITECTURE.md`](ARCHITECTURE.md).

### Quota is partitioned, and the reserve is unreachable

```
Twelve Data, 800 credits/day
  640  RESERVED  nightly baselines
  120  SEEDING   new tickers, 20/user/day
   40  CATALOG   symbol sync and slack
```

Enforcement is structural rather than by convention: `user_budget()` cannot
construct a reserve budget, and `Budget` refuses to be built against `RESERVED`
without a worker-only token. A request path that tries raises `ReserveViolation`,
which is a bug, not a rate limit. Adding an **already-seeded** ticker costs zero
credits, and watchlists concentrate in mega-caps, so most adds are free. When the
seeding partition is exhausted, adds still succeed and the item reads *"scoreable
tomorrow"* — degradation, not rejection.

### Exactly-once on quota

The credit is spent at the HTTP call, outside any transaction, so a ledger alone
prevents reprocessing but not double-spending. The raw response is written to
`provider_response_cache` **before** parsing, and a retry checks the cache and
skips the call. One window remains open: a crash between the call and the write
costs one credit for one ticker on one night. The ledger over-counts there rather
than under-counting, which is the safe direction against a hard external cap, and
`test_a_crash_inside_the_http_call_overcounts_never_undercounts` asserts it rather
than hiding it.

### Corporate actions: detect and freeze

Bars are fetched with `adjust=splits`, so a restatement is detectable exactly. The
system **never auto-rebases**. It freezes the baseline, suppresses alerts, and
renders a card telling the user to remove and re-add. Any automated rebase built
on a heuristic can, in its failure mode, silently suppress the most important
alert the product will ever generate.

### Read receipts

A card marks read after 2 continuous seconds at ≥50% visibility, and the observer
**does not arm until the first user interaction** — arming on load would ack a
short list through the viewport path while the reader was still orienting.
**Critical cards never auto-ack.** Transport is `fetch(..., {keepalive: true})`,
not `sendBeacon`, because a beacon cannot set an `Authorization` header. If a tab
dies before the flush, receipts are lost and the cards reappear: showing something
twice is an annoyance, hiding a critical nobody read is not.

Acks are monotonic per ticker (`WHERE last_seen_at < :at`), so two devices can ack
in any order and an old tab cannot rewind. The response reports per-ticker
outcomes, because a silent zero-row update returning 200 produces a quiet re-ack
loop that looks exactly like broken receipts.

### A missing benchmark sets beta to 0, not 1.0

A silent beta substitution is the likeliest source of a confident false critical:
a β = 2.1 semiconductor name scored at 1.0 during a −3% sector day shows a
fabricated −3% of idiosyncratic weakness. The card reports reduced confidence and
names the reason instead.

### Scoring constants live in code, not in a table

There is no `scoring_config` table. A scoring change is a deploy, is reviewable in
a diff, and is reproducible by `scripts/calibrate.py`.

---

## API reference

All routes are under `/api` and require `Authorization: Bearer <jwt>` unless
noted. Interactive docs at <http://localhost:8000/docs>.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Provider mode, auth mode, Redis, market state, SPY bar count, last nightly run. **Public** |
| `GET` | `/api/auth/mode` | Which sign-in path is live. **Public** |
| `POST` | `/api/auth/login` | Local dev sign-in. 404 once `SUPABASE_JWKS_URL` is set. **Public** |
| `GET` | `/api/auth/me` | Who the bearer token says you are |
| `GET` | `/api/search?q=` | Local trigram symbol search, ranked exact → prefix → similarity → watchers |
| `GET` | `/api/watchlist` | Your list |
| `POST` | `/api/watchlist` | Add a ticker; seeds in the background |
| `DELETE` | `/api/watchlist/{ticker}` | Remove a ticker |
| `GET` | `/api/digest` | The product. Supports `If-None-Match`, `?as_if_last_seen=`, `?refresh=` |
| `POST` | `/api/ack` | Checkpoint the prices carried in a digest token |
| `POST` | `/api/feedback` | Impressions, click-throughs, dismissals, thumbs |
| `GET` | `/api/tickers/{ticker}` | Baseline detail: β, σ, 52-week extremes, residual histogram |
| `GET` | `/api/calibration` | Predicted vs observed + precision@critical. **Public** |
| `GET` | `/api/quota` | Partition status and your remaining seeding credits |
| `POST` | `/api/dev/token` | The pre-UI sign-in, kept for scripts and `curl` |

Response headers on `/api/digest`: `ETag`, `Cache-Control: private, no-cache`,
`X-Next-Poll-After-Ms`.

---

## Configuration

Everything is optional. `docker compose up` with none of it set boots a fully
working product on the replay providers. See [`.env.example`](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://smw:smw@postgres:5432/smw` | The API uses the pooled URL |
| `DATABASE_URL_DIRECT` | same | The **worker** uses this. Supabase's pooler runs pgbouncer in transaction mode, where session-scoped behaviour is unreliable |
| `REDIS_URL` | `redis://redis:6379/0` | Quote cache and ETag bodies |
| `REDIS_LOCK_URL` | `redis://redis:6379/1` | Locks, on an instance configured `noeviction` |
| `SUPABASE_JWKS_URL` | *(unset)* | Unset enables the local dev sign-in; set disables it entirely |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | |
| `DEV_AUTH_SECRET` | `dev-insecure-local-only` | Signs local dev tokens; ignored once JWKS is set |
| `DIGEST_TOKEN_SECRET` | `dev-insecure-local-only` | **Must** come from the environment: one API instance issues a token and another verifies it |
| `TWELVEDATA_API_KEY` | *(unset)* | Omit and history falls back to replay |
| `FINNHUB_API_KEY` | *(unset)* | Omit and quotes fall back to replay |
| `PROVIDER_MODE` | `replay` | `replay` \| `live` |
| `REPLAY_SCENARIO` | `baseline` | `baseline` \| `market_crash` \| `single_name` \| `spike_revert` |
| `REPLAY_CLOCK` | `compressed` | `compressed` \| `passthrough` \| `pinned` |
| `REPLAY_NOW` | *(unset)* | The instant `pinned` freezes at |
| `SEED_DEMO` | `1` | Run the demo seeder on worker boot |
| `DEMO_EMAIL` | `you@example.com` | |
| `DEMO_BACK_SESSIONS` | *(scenario default)* | How many sessions back the demo checkpoint sits |
| `LOG_LEVEL` | `INFO` | |
| `CORS_ORIGINS` | `*` | Comma-separated |

`REPLAY_CLOCK=compressed` maps the real 24-hour wall clock onto the scenario's
trading session, so prices are always moving and the product is demoable at any
hour. `pinned` freezes it at `REPLAY_NOW`, which is what the tests use.

Scoring constants (weights, thresholds, λ, floors, quota partitions) are in
[`api/config.py`](api/config.py) and are deliberately not environment-driven.

---

## Local development

Docker is the supported path. To run the pieces directly:

### Backend

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements-dev.txt

docker compose up -d postgres redis

# .env.local already points at localhost; export it or set the vars yourself
uvicorn api.main:app --reload --port 8000
python -m worker.main                       # in a second shell
```

The schema applies itself on API and worker startup. Both files in `db/` are
idempotent and re-run on every boot.

### Frontend

```bash
cd web
npm install
npm run dev                       # http://localhost:3000
```

`NEXT_PUBLIC_API_BASE` defaults to `http://localhost:8000`.

### Useful scripts

```bash
python -m scripts.seed_demo --email you@example.com --tickers AAPL,MSFT,NVDA
python -m scripts.seed_demo --back-sessions 5      # widen the demo window
python -m scripts.calibrate                        # rewrites fixtures/calibration.json
python -m scripts.record_fixtures                  # regenerate every bar fixture
RUN_NIGHTLY_ON_BOOT=1 python -m worker.main        # force a nightly pass now
SKIP_BOOTSTRAP=1 python -m worker.main             # skip catalog + benchmark seeding
```

---

## Tests

```bash
docker compose up -d postgres redis
python -m pytest              # 106 tests
cd web && npm test            # 9 tests, the read-receipt rules
```

The pure-maths suite runs with nothing else up. Without Postgres the
database-backed cases skip; without Redis the three stampede and cache-repair
cases skip, each naming the reason rather than failing.

To watch the two-user isolation happen against a running stack rather than read an
assertion about it:

```powershell
docker compose up -d --build
powershell -File scripts/acceptance.ps1
```

It resets `a@test.com` and `b@test.com`, seeds A far enough back that a critical
card exists, dismisses it, signs in as B to find an empty account, and signs back
in as A to find the tickers and the dismissal both still there.

Database-backed tests run against a **separate `smw_test` database** created by
`db/init/`, because several of them truncate tables to get a clean slate and would
otherwise delete whatever you were looking at.

Highlights:

- `ewma_step` matches a pandas `ewm` reference, and the prior-mean rule is
  asserted by writing out the wrong recursion and showing it biases variance low
  by exactly λ².
- One −20% day inflates σ by **+42%** with winsorisation and **+871%** without —
  an order of magnitude, which is the point of the clip.
- The nightly job is killed at every step and the resulting provider calls are
  counted. Crashes at (b), (d), (e) and (f) each cost exactly one call per ticker.
- Weekend, holiday and half-day windows; a 02:00 IST ack landing on the right ET
  session; a 90-day absence capping price *and* days together.
- 200 concurrent requests on one expired cache key produce **exactly one** provider
  call, and every caller is served the same price.
- Loading a digest with every card on screen and touching nothing acknowledges
  nothing, and a critical card is never cleared without an explicit dismissal.
- Two users' `watchlist_items` and `watchlist_snapshots` are fully isolated in both
  directions, and one user's ack does not move the other's checkpoints. Configuring
  `SUPABASE_JWKS_URL` takes the local issuer offline in the same test, both ways.
- Every scenario asserted end to end, plus a determinism check.

---

## Failure modes

| Failure | Behaviour | User sees |
|---|---|---|
| Worker crash | Resumes from ledger + response cache, no re-spend | Nothing, unless the baseline is > 2 sessions old |
| Nightly job incomplete | Retries, resumes next night | `reduced` + "baseline last updated Sep 2" |
| Fresh deploy, no SPY bars | Scored digests withheld | All tickers `seeding` |
| WebSocket drops | Reconnect with backoff, fall to on-demand | "live" → "~1 min" |
| Finnhub 429 / down | Token bucket backs off | Freshness label lengthens |
| Twelve Data quota exhausted | Seeding pauses, reserve untouched | New adds `seeding` |
| Cache stampede | Single-flight lock | One provider call |
| Redis down | Read through to Postgres; acks unaffected | Slower only |
| Benchmark stale or missing | β falls back to 0, not 1.0 | `reduced` + reason |
| Implausible tick | Held one cycle, timeout release | `verifying` |
| History restated | Baseline frozen, alerts paused | Action card with instructions |
| Ticker halted / delisted | Status flip | "no recent trades" / "symbol no longer resolves" |
| Ack superseded | Per-ticker result | Nothing; no retry loop |
| Receipts lost to a tab crash | Cards reappear | Item shown again |

---

## Scope and limits

Expensive work is keyed by ticker, cheap work by user:

```
nightly quota  = O(distinct active tickers)        not O(users)
intraday quota = O(distinct tickers being viewed)  not O(users × tickers)
digest read    = O(list size), no writes, 304 when nothing changed
```

Technical ceiling is roughly 600 tickers with maintained baselines and 50 with
real-time pricing — about 1,000–5,000 users by overlap. **The licence ceiling is
lower and binds first:** Finnhub's free tier is personal, non-commercial use, and
Twelve Data's free Basic tier carries similar limits. This is a prototype running
under personal-use licences; a production deployment needs commercial agreements,
and the likely move is consolidating onto Twelve Data, which costs the free
WebSocket and turns the hot tier into polling.

Scope is **US-listed equities and ETFs**, enforced at add time, because both free
tiers are US-only.

### Designed, not built

Each has a worked design and was cut deliberately; the reasoning is in
[`ARCHITECTURE.md` §21](ARCHITECTURE.md#21-designed-not-built).

Notifications of any kind · two-factor regression (SPY *and* sector,
orthogonalised) · ECDF scoring (residuals are collected and displayed, not scored
with) · Vasicek cross-sectional shrinkage · corporate-action auto-rebase (cut on
safety as much as scope) · multiple watchlists · a middle polling tier · worker
lease / leader election · HMAC key rotation · quarterly sector re-checks ·
leveraged-ETF handling · **extended-hours scoring** (the price is displayed,
explicitly unscored: `AH −8.2% · not scored until the open`) · dividend adjustment
· learned signal weights · non-US markets.

### Where this build departs from its specification

Four deviations, each because building it as literally written would have been
wrong. They are enumerated with full reasoning in
[`ARCHITECTURE.md` §20](ARCHITECTURE.md#20-departures-from-the-build-specification):
the material-move gate applies window-wide rather than to the endpoint difference;
the same-session branch measures dispersion by `session_span` rather than session
fraction elapsed; 52-week extremes are carried per row in `recent_daily`; and a
local HS256 dev issuer exists when no Supabase project is configured.

---

## Project layout

```
api/       config · db · models · schemas · auth · cache · clock · calendar_ny
           quota · digest_token · digest_service · main
           scoring/  window · signals · score · reasons          (pure, no I/O)
           routers/  auth_router · watchlist · digest · ack · tickers · calibration

worker/    main (two schedulers, one process) · catalog · earnings
           nightly/   fetch · ledger · compute · corporate_actions
           intraday/  ws · ondemand · benchmarks · sanity
           baseline/  ewma · seed · persist

providers/ base (two Protocols) · twelvedata · finnhub · replay

scripts/   record_fixtures · calibrate · offline · seed_demo · acceptance.ps1

db/        001_schema.sql · 002_etf_names.sql · init/00_test_db.sql

web/       app/ (App Router, route groups) · components/ (+ 3 charts) · lib/ · tests/

fixtures/  bars/ (65 instruments) · scenarios/ (4) · symbols · profiles ·
           earnings · calibration.json

tests/     106 cases across scoring, windows, EWMA, tokens, integrity,
           the nightly recovery contract, the live layer, auth and the API
```

### Regenerating fixtures

```bash
python -m scripts.record_fixtures    # deterministic; a fixed seed
python -m scripts.calibrate          # rewrites fixtures/calibration.json
```

Bars are synthetic rather than recorded, because redistributing Twelve Data or
Finnhub history would breach both free tiers' terms. They are generated through
the same factor structure the scorer assumes it is fitting, with Student-t
innovations so the tails are fat and the calibration page has something honest to
report. Betas are recoverable, which is what makes the beta test meaningful rather
than circular.

---

## Troubleshooting

**First boot fails with `dependency failed to start`.** On a fresh volume the API
and worker apply migrations concurrently and race on `CREATE EXTENSION pg_trgm`;
the API exits with code 3. Run `docker compose up -d` again — the extension exists
by then and it comes up clean.

**`REPLAY_SCENARIO` reverted to `baseline`.** An inline variable
(`REPLAY_SCENARIO=x docker compose up`) does not survive a second `up`, so a
re-run after the race above silently boots the default. Use `export`, and confirm
with `docker compose exec api printenv REPLAY_SCENARIO`.

**Every card says `seeding`.** SPY has fewer than 260 bars, so scored digests are
withheld deliberately — without that gate every window would silently measure as a
single session. Check `spy_bars` in `/healthz` and give the worker's bootstrap a
minute.

**Switching `REPLAY_SCENARIO` changed nothing.** Baselines are built from the
scenario's bars and persist in the volume. Run
`docker compose down -v` first.

**The digest is all zeroes.** A brand-new ticker is checkpointed at the moment you
add it, so it is quiet by construction. Use **View a past window**, or seed a
checkpoint further back:
`python -m scripts.seed_demo --back-sessions 5`.

**`POST /api/auth/login` returns 404.** `SUPABASE_JWKS_URL` is set, so the local
issuer is off by design and tokens must come from Supabase.

**Tests skip.** Database-backed tests need Postgres at
`TEST_DATABASE_URL` (default `postgresql+asyncpg://smw:smw@localhost:5432/smw_test`).
Run `docker compose up -d postgres redis`; the `smw_test` database is created at
cluster init by `db/init/`.

**`/calibration` returns 503.** No calibration artifact yet. Run
`python -m scripts.calibrate`.
