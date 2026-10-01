#!/usr/bin/env python3
"""Bear-strategy trading engine — DRY-RUN by default, live behind a hard gate.

One idempotent decision per invocation (daily cadence, cron-friendly). It:
  1. pulls closed daily KRW-BTC candles from the LIVE Upbit public API,
  2. derives the target position (long / flat) from EXACTLY the backtested logic
     (src/bear_strategy.targets — the regime filter is the single source of
     truth), and
  3. reconciles target vs current position into at most one order (BUY / SELL /
     HOLD), sized and vetoed by the shared RiskManager (1,000,000 KRW cap,
     per-trade size, daily-loss kill switch).

SAFETY — live order placement is OFF by default and gated behind ALL of:
    (a) config.LIVE_TRADING_ENABLED is True   (master config switch, default False)
    (b) the --live CLI flag
    (c) a typed confirmation phrase (unless --yes)
    (d) API keys present in the environment / secrets.env
If any is missing the engine runs DRY-RUN: it computes and LOGS the exact order
it *would* place, touches no keys, and calls no private endpoint. Flipping to
live is a config change (flag + keys) — not a code change.

Usage:
    python3 src/live_engine.py                      # DRY-RUN (default, safe)
    python3 src/live_engine.py --mode long_flat     # regime long/flat (default)
    python3 src/live_engine.py --mode breakout_regime
    python3 src/live_engine.py --live               # attempt live (needs all gates)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import bear_strategy as bs  # noqa: E402
from regime import compute_regimes  # noqa: E402
from risk import RiskManager, RiskHalt  # noqa: E402
from upbit_client import UpbitClient, UpbitError  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(HERE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
STATE_PATH = os.path.join(LOG_DIR, "live_engine_state.json")   # dry-run position memory
CONFIRM_PHRASE = "TRADE LIVE"


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} [live_engine] {config.redact(str(msg))}"
    print(line, flush=True)
    with open(os.path.join(LOG_DIR, "live_engine.log"), "a") as f:
        f.write(line + "\n")


def fetch_closed_daily(client, count=600):
    # paginated public history: SMA200 + 365-bar drawdown breaker need >365 bars
    # of warmup, more than the 200-row single-call cap.
    raw = client.candles_history(config.MARKET, kind="days", count=count)
    bars = [{"t": c["candle_date_time_utc"], "open": float(c["opening_price"]),
             "high": float(c["high_price"]), "low": float(c["low_price"]),
             "close": float(c["trade_price"])} for c in raw]     # oldest->newest
    return bars[:-1]                                   # drop the forming candle


DAILY_CANDLE_HOURS = 24            # engine decides off CLOSED daily candles


def candle_age_hours(candle_open_iso, now=None):
    """Hours since the given DAILY candle closed. Upbit stamps a candle by its
    OPEN time; a daily candle opened at T closes at T+24h. Returns age of that
    close vs `now` (UTC). Used to detect a stale/lagging data feed."""
    now = now or datetime.now(timezone.utc)
    open_dt = datetime.fromisoformat(candle_open_iso)
    if open_dt.tzinfo is None:
        open_dt = open_dt.replace(tzinfo=timezone.utc)
    close_dt = open_dt + timedelta(hours=DAILY_CANDLE_HOURS)
    return (now - close_dt).total_seconds() / 3600.0


RISK_PATH_LIVE = os.path.join(HERE, "live_engine_risk.json")
# Dry-run keeps its own risk book so simulated fills exercise the cap / kill
# switch exactly like live, without ever touching the live risk state.
RISK_PATH_DRY = os.path.join(LOG_DIR, "live_engine_risk.dryrun.json")
EMPTY_STATE = {"position": 0, "entry": None, "qty": 0.0, "notional": 0.0}


def _load_state(path=STATE_PATH):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return dict(EMPTY_STATE, **json.load(f))
        except Exception:
            pass
    return dict(EMPTY_STATE)


def _save_state(s, path=STATE_PATH):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, path)


def live_gates_ok(args):
    """Return (ok, reasons) — every gate that must pass before a real order."""
    reasons = []
    if not args.live:
        reasons.append("--live flag not set")
    if not config.LIVE_TRADING_ENABLED:
        reasons.append("config.LIVE_TRADING_ENABLED is False (master switch)")
    try:
        config.load_keys()
    except RuntimeError:
        reasons.append("API keys not present")
    return (not reasons), reasons


def current_live_position(client):
    """(position, qty) from the real account: long if BTC holding is tradable."""
    qty, _ = client.balance("BTC")
    px = float(client.ticker(config.MARKET)["trade_price"])
    return (1 if qty * px >= config.MIN_ORDER_KRW else 0), qty


def round_trip_pnl(notional, qty, exit_px, fee=config.UPBIT_FEE):
    """Realized KRW PnL of selling `qty` at `exit_px` that cost `notional` KRW to
    buy. The buy fee is already inside notional (qty = notional*(1-fee)/px); the
    sell fee comes off the proceeds."""
    return qty * exit_px * (1 - fee) - notional


def execute(target, last, *, risk, state_path, live=False, client=None,
            free_krw=None, now=None, slip_bps=config.TAKER_SLIP_BPS, log=log):
    """Reconcile `target` (0/1) against the current position for the latest
    CLOSED candle `last` and place at most one order. Shared by the engine and
    the shadow replay, so the replay exercises this exact code. Returns an event
    dict (action, fill, fees, pnl, which risk path fired).

    Dry-run fills at the candle close moved `slip_bps` against us (market order).
    Live orders go to the exchange; fills are estimated the same way for the
    risk book and reconciled by the account."""
    tag = "LIVE" if live else "DRY-RUN"
    ev = {"action": "HOLD", "risk_path": None}

    # ---- data-freshness guard ----
    # Never open fresh risk on stale market data (feed outage / exchange lag /
    # engine idle for days). Protective exits stay allowed — reducing risk is
    # always safe even if the last candle is old.
    age_h = candle_age_hours(last["t"], now)
    stale = age_h > config.MAX_CANDLE_STALENESS_HOURS
    if stale:
        log(f"[{tag}] WARNING: data feed looks stale "
            f"— latest closed candle is {age_h:.1f}h old "
            f"(> {config.MAX_CANDLE_STALENESS_HOURS:.0f}h). New entries blocked; "
            f"protective exits still allowed.")

    st = _load_state(state_path)
    if live:
        pos, qty = current_live_position(client)
        free_krw, _ = client.balance("KRW")
    else:
        pos, qty = st["position"], st["qty"]
        if free_krw is None:
            free_krw = config.BASE_TRADABLE_CAPITAL_KRW   # assume the base in dry-run
    halted = risk.is_halted()

    if target == 1 and pos == 0:
        # HALT and stale data block NEW risk only.
        if halted:
            log(f"[{tag}] want BUY but risk HALT flag present -> no entry. Clear "
                f"{risk.halt_flag} to resume.")
            ev["risk_path"] = "halt_blocked_entry"
            return ev
        if stale:
            log(f"[{tag}] want BUY but data is stale: latest closed candle is "
                f"{age_h:.1f}h old (> {config.MAX_CANDLE_STALENESS_HOURS:.0f}h "
                f"limit) -> refusing new entry, HOLD until the feed is fresh.")
            ev["risk_path"] = "stale_blocked_entry"
            return ev
        try:
            notional = risk.can_open(free_balance=free_krw)   # respects cap+per-trade
        except RiskHalt as e:
            log(f"[{tag}] want BUY but risk vetoes: {e}")
            ev["risk_path"] = f"veto: {e}"
            return ev
        px = last["close"] * (1 + slip_bps / 1e4)
        filled_qty = notional * (1 - config.UPBIT_FEE) / px
        if live:
            resp = client.buy_market(config.MARKET, int(notional))
            log(f"[LIVE] BUY market ~{notional:,.0f} KRW resp_uuid={resp.get('uuid')}")
        else:
            log(f"[DRY-RUN] would BUY ~{notional:,.0f} KRW (~{filled_qty:.8f} BTC "
                f"@ ~{px:,.0f}); no order placed, no keys used")
        risk.record_open(notional)
        _save_state({"position": 1, "entry": px, "qty": filled_qty,
                     "notional": notional}, state_path)
        ev.update(action="BUY", fill=px, qty=filled_qty, notional=notional,
                  fee=notional * config.UPBIT_FEE,
                  slippage=filled_qty * (px - last["close"]))

    elif target == 0 and pos == 1:
        # Exits are always allowed (even under HALT / stale data): they reduce risk.
        if halted:
            ev["risk_path"] = "exit_allowed_under_halt"
        elif stale:
            ev["risk_path"] = "exit_allowed_on_stale_data"
        px = last["close"] * (1 - slip_bps / 1e4)
        # notional falls back to entry*qty for state files written before Cycle 27
        notional = st["notional"] or (st["entry"] or px) * qty
        pnl = round_trip_pnl(notional, qty, px)
        if live:
            resp = client.sell_market(config.MARKET, qty)
            log(f"[LIVE] SELL market {qty:.8f} BTC resp_uuid={resp.get('uuid')} "
                f"(est. pnl ~{pnl:+,.0f} KRW; account reconciles)")
        else:
            log(f"[DRY-RUN] would SELL {qty:.8f} BTC @ ~{px:,.0f} "
                f"(paper pnl ~{pnl:+,.0f} KRW after fees); no order placed, "
                f"no keys used")
        risk.record_close(notional, pnl)
        _save_state(dict(EMPTY_STATE), state_path)
        ev.update(action="SELL", fill=px, qty=qty, notional=notional, pnl=pnl,
                  fee=qty * px * config.UPBIT_FEE,
                  slippage=qty * (last["close"] - px))
        if risk.is_halted() and not halted:
            ev["risk_path"] = "kill_switch_tripped"
            log(f"[{tag}] daily loss limit hit -> HALT flag written "
                f"({risk.halt_flag}); no new entries until it is cleared.")

    else:
        log(f"[{tag}] HOLD — position already {'LONG' if pos else 'FLAT'}, "
            f"target {'LONG' if target else 'FLAT'}; no order")
    return ev


def decide_and_execute(args, live):
    p = dict(config.BEAR)
    # keys only touched in genuine live mode; public client otherwise
    client = UpbitClient(*config.load_keys()) if live else UpbitClient("", "")
    risk = RiskManager(RISK_PATH_LIVE if live else RISK_PATH_DRY)

    bars = fetch_closed_daily(client)
    regimes = compute_regimes(bars, p)
    target = bs.targets(bars, p, args.mode)[-1]        # desired 0/1 for now
    last = bars[-1]
    log(f"mode={args.mode} last_closed={last['t']} close={last['close']:,.0f} "
        f"regime={regimes[-1]} -> target={'LONG' if target else 'FLAT'}")
    execute(target, last, risk=risk, state_path=STATE_PATH, live=live,
            client=client)


def confirm_live():
    print(f"\n*** LIVE MODE: this will place REAL orders on Upbit "
          f"(cap {config.MAX_EXPOSURE_KRW:,.0f} KRW). ***")
    try:
        return input(f'Type "{CONFIRM_PHRASE}" to proceed: ').strip() == CONFIRM_PHRASE
    except EOFError:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=list(bs.MODES), default="long_flat",
                    help="strategy target: long_flat (default) / breakout / "
                         "breakout_regime")
    ap.add_argument("--live", action="store_true",
                    help="attempt LIVE trading (also needs config + keys + confirm)")
    ap.add_argument("--yes", action="store_true", help="skip the live confirm prompt")
    args = ap.parse_args()

    ok, reasons = live_gates_ok(args)
    live = False
    if args.live:
        if not ok:
            log("LIVE requested but gates NOT satisfied -> staying DRY-RUN. "
                "Missing: " + "; ".join(reasons))
        elif not args.yes and not confirm_live():
            log("live confirmation not given -> staying DRY-RUN.")
        else:
            live = True
            log("ALL LIVE GATES PASSED — trading LIVE.")
    else:
        log("DRY-RUN (default). No --live flag; no orders, no keys.")

    try:
        decide_and_execute(args, live)
    except UpbitError as e:
        log(f"upbit error: {e}")
    except Exception as e:  # never crash silently
        log(f"UNEXPECTED {type(e).__name__}: {config.redact(str(e))}")


if __name__ == "__main__":
    main()
