# Operations Note — upbit-hft-bot

How the bot is risk-limited, and how to start/stop it. Keep this short and
operational; the strategy rationale is in `research/STRATEGY_AND_BACKTEST.md`.

## TL;DR safety posture

- **Paper mode is the default.** Real orders happen only with `--live` *and* a
  typed confirmation.
- **Hard exposure cap: 1,000,000 KRW** total open notional, enforced by the
  risk manager independently of the strategy — it cannot be exceeded even if the
  account holds more, and even if the strategy tries.
- **Per-trade size: 200,000 KRW** (5 slots max within the cap).
- **Kill switch:** if realized loss in a UTC day exceeds **50,000 KRW**, trading
  halts and a `state.json.HALT` flag is written. The bot will not re-enter until
  you delete that file.

All limits live in one place: `src/config.py`.

## Secrets (never committed, never logged)

1. `cp secrets.env.example secrets.env`
2. Put the Upbit keys in `secrets.env`. It is gitignored.
3. The bot loads keys from the environment (or `secrets.env`); `config.redact()`
   scrubs key-shaped strings from any log line. Keys are never printed.

## Start / stop

```bash
# Paper trading (no keys needed, uses the live public price feed):
./run.sh                 # loops forever
./run.sh --once          # single iteration (good for cron/testing)

# Live trading (REAL money; asks you to type "TRADE LIVE"):
./run.sh --live

# Stop: Ctrl-C. State (open position accounting, daily PnL) persists in
# state.json, so a restart resumes safely within the same day.
```

### Emergency stop / kill switch

- **Halt entries immediately:** create the flag file —
  `touch state.json.HALT`. The bot stops opening new positions on its next loop.
- **Resume:** delete it — `rm state.json.HALT`.
- The kill switch also trips automatically on the daily loss limit.
- Note: the halt flag blocks *new entries*; an open position is still managed to
  its stop/take-profit/timeout so it is not left unmanaged. To flatten
  everything instantly, stop the bot and sell manually in the Upbit app.

## Monitoring

- Human-readable log: `logs/bot.log` (also echoed to stdout).
- Risk/PnL state: `state.json` (`realized_pnl_today`, `open_notional`,
  `trades_today`, `day`).

## Before going live (do not skip)

The backtest shows the strategy is only marginally break-even after fees. Per
`research/STRATEGY_AND_BACKTEST.md` §7:
1. Run **paper mode for 3–4 weeks / ≥100 trades**; confirm net-positive PnL.
2. Switch entries to **limit (maker) orders** (the client supports it) to avoid
   paying the spread — this is the difference between losing and winning.
3. Only then a **minimal live test** (e.g. 50k–100k KRW/trade), kill switch
   armed, before any scaling.

The provided account currently holds **0 KRW** — it must be funded before live
trading is even possible. We recommend not funding it for live use until the bar
above is met.

## Execution model (maker entries — updated 2026-09-10)

Entries are **limit (maker) orders** at the best bid, polled for fill and
cancelled after `ENTRY_TTL_CANDLES` (3) candles if unfilled. Take-profit rests
as a maker limit sell; stop-loss / mean-revert / timeout exit at market (taker).
Knobs live in `src/config.py` (`ENTRY_TTL_CANDLES`, `TAKER_SLIP_BPS`). Paper
mode simulates the identical fill logic against the live feed, so paper results
match `backtest/backtest_maker.py`.

## Verdict from paper trading (READ BEFORE RUNNING LIVE)

Large-sample paper trading (83 days / ~200 trades) and an 864-config walk-
forward showed this strategy **loses money after fees** (≈ −4%, ≈ −19%/yr
naive-annualized; 0/864 configs profitable). **Do not run this strategy live.**
The bot and risk harness are sound and reusable; the *strategy* lacks a net
edge. See `research/STRATEGY_AND_BACKTEST.md` §10.

## Bear-market strategy engine (added 2026-09-23)

A separate, defensive **regime-filter** strategy (be long BTC only in confirmed
up-regimes; hold KRW cash through downtrends) with its own runnable backtest and
its own live/dry-run engine. Design + evidence + citations:
`research/BEAR_MARKET_STRATEGY.md`.

```bash
# Backtest (9y daily KRW-BTC): metrics, trade log, ASCII chart, bear-window table
python3 backtest/bear_backtest.py                 # all variants
python3 backtest/bear_backtest.py --mode breakout_regime --capital 1000000

# Live/DRY-RUN engine — DRY-RUN BY DEFAULT (no keys, no orders, logs intended order)
python3 src/live_engine.py                        # dry-run, mode=long_flat
python3 src/live_engine.py --mode breakout_regime # dry-run, bear-defended breakout
python3 src/live_engine.py --live                 # attempts live (see gating below)
```

**How live/dry-run gating works (off by default).** `src/live_engine.py` places a
real order only when **ALL** of these hold; miss any and it silently stays
dry-run (computing and logging the exact order it *would* place):

1. `config.LIVE_TRADING_ENABLED = True` — master switch, **default False**;
2. the `--live` CLI flag;
3. a typed confirmation phrase `TRADE LIVE` (skip only with `--yes`);
4. API keys present (`secrets.env` / env).

Going live is therefore a **config change (flag + keys), not a code change**. The
same `RiskManager` (1M cap, per-trade size, daily-loss kill switch, HALT flag)
governs the bear engine, so all existing limits apply. The master switch also now
gates the original `bot.py --live`. The account is **unfunded**; do not enable
live without an explicit go-live instruction from the owner.

Runtime state: dry-run position memory in `logs/live_engine_state.json`; risk
state in `live_engine_risk.json` (live) / `logs/live_engine_risk.dryrun.json`
(dry-run; dry-run fills now go through the same RiskManager so the cap and kill
switch behave exactly as live); log in `logs/live_engine.log`. The order path is
`live_engine.execute()`. A HALT flag (or stale data) blocks NEW entries only;
protective exits always go through.

**Counterfactual shadow replay (Cycle 27).** `python3 paper_trading/shadow/shadow_replay.py`
drives `execute()` + `RiskManager` in dry-run over real data with a forced regime,
a synthetic stress walk, and a historical replay. It uses throwaway temp state and
writes only `paper_trading/shadow/` (every record `counterfactual: true`). It never
touches the official paper ledger. It is a one-off research tool, not a daemon.

**Forward SHADOW book — exit speed 12.5% / 5% (owner option B, 2026-10-04).**
`paper_trading/shadow_exit_book/` is a second paper ledger. It runs forward
next to the official one so the final 20/10-vs-12.5/5 choice (around
2026-10-24) rests on real forward data. `shadow_book.py` calls the unchanged
`paper_trader.process()` with all output paths redirected to that directory and
config.BEAR overridden to dd_enter=0.125, dd_exit=0.05, both restored on
exit. Data, fees, fills, sizing and the 1M cap are the same. Every record
carries `book: shadow_exit_12.5_5, official: false`. The first run backfilled
from the official first candle (`backfilled_at_launch: true`).
`compare.py` writes `COMPARE.md`: side-by-side equity, return, position,
divergences, and a check that both books saw identical close prices.
It runs inside the paper daemon's tick, after the official tick, so the host
cron keeps it alive with no extra keep-alive, and a shadow failure cannot
change the official result. `daemon_paper.sh status` prints the comparison
headline. Tests: `tests/test_shadow_exit_book.py`.

## Autonomous-process operating model (owner directive 2026-09-27)

**Principle: every "code" artifact — data collection AND the trading loop — runs
as its own OS process, independent of any Claude/leader turn. Claude spends tokens
only when the owner commands a turn, and then it only READS those processes'
output/logs/stored data to report and decide. Running a loop itself must never
happen inside a leader turn.** Rationale: a leader turn is a Claude turn, which
costs tokens; the whole point of "implement it in code" is that the process runs
autonomously and cheaply without an LLM in the loop.

**Shared machinery — `paper_trading/daemon_lib.sh`.** One reusable library gives
every daemon: detached launch (`setsid`, reparents to PID 1 → survives turns, 0
tokens), a crash-resilient loop, prompt stop via `sleep & wait` traps, and an
idempotent `ensure` self-heal. Each daemon below is just a thin config (its tick
command + its cadence). Adding the next one (e.g. the live engine) is ~30 lines.

**Live daemons (both detached, verified `ppid=1`, zero Claude tokens):**
```bash
paper_trading/daemon_4h.sh    {start|ensure|status|stop|restart|logs}  # 4h data
paper_trading/daemon_paper.sh {start|ensure|status|stop|restart|logs}  # daily paper cycle
```
- **4h collector** — loops `collect_4h.py` every 4h; appends closed candles to the
  committed trail `paper_trading/market_data_4h.csv`. Gap-free idempotent backfill.
  Log `logs/collect_4h_daemon.log`, PID `logs/collect_4h_daemon.pid`.
- **4h tick extras (Cycle 31, token-free, failures never affect the collector):**
  after `collect_4h.py`, the tick runs `paper_trading/ensemble_books/ensemble_book.py`.
  That script refreshes public 1h candles into `data/1h/` and advances the
  official=false ensemble shadow books, writing `ensemble_books/COMPARE.md` and
  `<book>/SUMMARY.md`. The tick then runs `research/evolution/run_evolution.sh maybe`,
  which starts a detached GA run only when `results/latest.json` is older than 7 days.
  It logs to `logs/evolution.log`, holds a lock at `logs/evolution.lock`, and
  `run_evolution.sh status` reports on it. A due run DEFERS (retried next tick) when MemAvailable < 400 MB or loadavg > nproc, and runs under ionice/nice with a 1 GB address-space cap.
- **Paper trader** — runs `paper_trader.py` once per closed daily candle (00:05 UTC);
  appends one record to `paper_log.jsonl` / `JOURNAL.md` / `market_data_daily.csv`
  and regenerates `SUMMARY.md`. The decision is deterministic strategy code
  (`src/regime.py`+`bear_strategy.py`), not an LLM. Idempotent (only new closed
  candles). Log `logs/paper_daemon.log`, PID `logs/paper_daemon.pid`. Mode override:
  `PAPER_MODE=breakout_regime paper_trading/daemon_paper.sh start`.
- **Keep-alive / restart — the HOST owns the daemons (installed 2026-10-01).**
  A crontab under the host user `ubuntu` runs both `ensure` commands every 10
  minutes:

  ```cron
  */10 * * * * cd /home/ubuntu/Workspace/upbit-hft-bot/leader && paper_trading/daemon_4h.sh ensure >> logs/collect_4h_daemon.log 2>&1
  */10 * * * * cd /home/ubuntu/Workspace/upbit-hft-bot/leader && paper_trading/daemon_paper.sh ensure >> logs/paper_daemon.log 2>&1
  ```

  This is deliberately on the host and not in the container. A daemon started
  inside the `acompany` container reparents to PID 1 *there*, so every container
  restart killed it — which is what the "SIGKILLed together" windows below
  actually were (2026-09-30 ~12–15Z, 2026-10-01 ~08–10Z: container restarts, not
  host reboots). The host loops have `ppid=1` outside the Docker cgroup and
  survive restarts and rebuilds alike.

  **Do not add a second keep-alive, and do not ask the A_Company orchestrator to
  run `ensure`.** The orchestrator lives in the container, so it would die with
  it — the very problem the host cron solves — and a container-side `ensure`
  racing the host's is where cross-namespace duplicates come from. On
  2026-10-03 six loops (three pairs) were found running for this reason; the
  trail survived intact (`dups=0`) but only because every tick is idempotent.

  Verifying it works, rather than assuming: `crontab -l` on the host, and
  `grep CRON /var/log/syslog | grep daemon_` for the firings. `ensure` is safe to
  call from anywhere — including a leader turn inside the container, which now
  correctly reports *"already running (owner=…, heartbeat Ns ago) — nothing to
  do (idempotent)"* and starts nothing.
- **Outage ledger:** the loop stamps `logs/<name>_daemon.heartbeat` every 300s
  while sleeping. If `ensure` finds a dead daemon whose pidfile is still there
  (= killed without a clean stop), it appends the window
  (`last_heartbeat`, `down_at_most`) to `logs/daemon_outages.log` and to the
  daemon log. `status` shows heartbeat age and the recorded outages. Idempotent ticks fill any
  reboot-downtime gap on the next run. The host cron above is the installed
  mechanism; `paper_trading/README.md` describes the same shape.
- **Commit split:** daemons only append locally; the leader commits/pushes the
  accumulated record on command (clean git history, no push races).

**Still leader-driven for now — going LIVE.** `src/live_engine.py` will get the
same daemon wrapper when the owner authorises live trading; until then it stays
off by default and gated (see below). All existing safety (paper-only default,
1,000,000 KRW cap, kill switch, live gating) is unchanged; a daemon relaxes no
gate. Tests: `tests/test_daemons.py` (9/9) exercises the shared lib lifecycle via
a throwaway dummy daemon.

## Known limitations

- Live maker-entry fill accounting uses the order's reported price/volume as an
  approximation of the executed average; a production build should reconcile
  `open_notional` from `get_order()` partial-fill detail.
- Single market (KRW-BTC), single position at a time by design.
