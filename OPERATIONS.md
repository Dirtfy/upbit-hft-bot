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
state in `live_engine_risk.json`; log in `logs/live_engine.log`.

## Autonomous-process operating model (owner directive 2026-09-27)

**Principle: every "code" artifact — data collection now, the trading loop next —
runs as its own OS process, independent of any Claude/leader turn. Claude spends
tokens only when the owner commands a turn, and then it only READS those
processes' output/logs/stored data to report and decide. Running the loop itself
must never happen inside a leader turn.** Rationale: a leader turn is a Claude
turn, which costs tokens; the whole point of "implement it in code" is that the
process runs autonomously and cheaply without an LLM in the loop.

**Live today — 4h data accumulation daemon.**
```bash
paper_trading/daemon_4h.sh {start|ensure|status|stop|restart|logs}
```
- Detached with `setsid` (reparents to PID 1), so it survives every turn boundary
  and uses **zero Claude tokens** (verified `ppid=1`). Loops `collect_4h.py` every
  4h, appends closed candles to the committed trail `paper_trading/market_data_4h.csv`.
- Crash-resilient loop; gap-free idempotent backfill fills any downtime on the
  next tick. Log: `logs/collect_4h_daemon.log`, PID: `logs/collect_4h_daemon.pid`.
- **Keep-alive / restart:** no system cron or systemd exists in this env, so a
  host reboot is the only thing that stops it. `daemon_4h.sh ensure` re-launches
  it *only if* not already running (idempotent) — the leader calls this one line
  at the start of a commanded turn (a liveness check, NOT accumulation). Optional
  belt-and-suspenders company cron for reboot-proof restart is in
  `paper_trading/README.md`.
- **Commit split:** the daemon only appends locally; the leader commits/pushes the
  accumulated trail on command (clean git history, no push races).

**Next — move the trading loop to the same model.** `src/live_engine.py` /
`paper_trading/paper_trader.py` will get the identical daemon wrapper
(`setsid` detached loop + `ensure` self-heal + resilient loop + local-write /
leader-commits-on-command). The leader turn will then only run `ensure` + read
the ledger/log to report PnL — it will never drive the trading loop itself. All
existing safety (paper-only default, 1,000,000 KRW cap, kill switch, live gating)
is unchanged; a daemon does not relax any gate.

## Known limitations

- Live maker-entry fill accounting uses the order's reported price/volume as an
  approximation of the executed average; a production build should reconcile
  `open_notional` from `get_order()` partial-fill detail.
- Single market (KRW-BTC), single position at a time by design.
