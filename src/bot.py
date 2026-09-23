#!/usr/bin/env python3
"""Upbit KRW-BTC scalping bot — paper and live, with MAKER (limit) entries.

  * PAPER (default): uses the live Upbit *public* price feed but simulates
    fills and PnL locally. No API keys required, no real orders. This is how
    you forward-test the strategy before risking capital.
  * LIVE: places real orders via the authenticated API. Requires keys and the
    explicit --live flag AND typing the confirmation phrase.

Execution model (mirrors backtest/backtest_maker.py so paper == backtest):
  ENTRY  — resting LIMIT buy at the best bid (maker; joins the book instead of
           crossing the spread). Filled only if price trades down to it;
           cancelled if unfilled after config.ENTRY_TTL_CANDLES candles.
  EXIT   — take-profit is a maker LIMIT sell; stop-loss / mean-revert / timeout
           are taker MARKET sells (you must get out).

Every entry passes the RiskManager (exposure cap, per-trade size, daily-loss
kill switch); the strategy can never bypass those limits.

Run:
    python3 bot.py            # paper mode
    python3 bot.py --live     # live mode (asks for confirmation)
    python3 bot.py --once     # single iteration (for testing/cron)
"""
import argparse
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from risk import RiskManager, RiskHalt  # noqa: E402
from upbit_client import UpbitClient, UpbitError  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(HERE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {config.redact(str(msg))}"
    print(line, flush=True)
    with open(os.path.join(LOG_DIR, "bot.log"), "a") as f:
        f.write(line + "\n")


class Bot:
    def __init__(self, live=False):
        self.live = live
        self.market = config.MARKET
        self.p = dict(config.STRAT)              # strategy params
        self.win = self.p["window"]
        self.closes = deque(maxlen=self.win)     # rolling window of closes
        self.risk = RiskManager(os.path.join(HERE, "state.json"))
        self.client = UpbitClient(*config.load_keys()) if live else UpbitClient("", "")
        self._last_candle_ts = None
        self._candle_i = 0                        # closed-candle counter
        self.pending = None   # resting entry: {limit, placed_i, notional, uuid?}
        self.pos = None       # open position: {qty, entry, notional, tp, sl,
                              #                  entered_i, exit_uuid?}

    # ---- price feed --------------------------------------------------------
    def _warm_up(self):
        candles = list(reversed(self.client.candles_1m(self.market, self.win + 5)))
        for c in candles[:-1]:
            self.closes.append(float(c["trade_price"]))
        self._last_candle_ts = candles[-1]["candle_date_time_utc"]
        log(f"warmed up with {len(self.closes)} closes; "
            f"last candle {self._last_candle_ts}")

    def _new_closed_candle(self):
        candles = self.client.candles_1m(self.market, count=2)
        closed = candles[1]  # [0] is the forming minute, [1] is the closed one
        if closed["candle_date_time_utc"] == self._last_candle_ts:
            return None
        self._last_candle_ts = closed["candle_date_time_utc"]
        self._candle_i += 1
        return closed

    def _zscore(self, price):
        if len(self.closes) < self.win:
            return None, 0.0
        n = len(self.closes)
        mean = sum(self.closes) / n
        var = sum((c - mean) ** 2 for c in self.closes) / n
        std = var ** 0.5
        if std <= 0:
            return None, 0.0
        return (price - mean) / std, std

    def _price(self):
        return float(self.client.ticker(self.market)["trade_price"])

    def _best_bid(self):
        ob = self.client.orderbook(self.market)
        return float(ob["orderbook_units"][0]["bid_price"])

    # ---- entries -----------------------------------------------------------
    def _place_maker_buy(self, notional):
        limit = self._best_bid() if self.live else self._price()
        qty = notional / limit
        uuid_ = None
        if self.live:
            resp = self.client.buy_limit(self.market, int(limit), qty)
            uuid_ = resp.get("uuid")
            log(f"LIVE maker BUY limit @ {limit:,.0f} vol={qty:.8f} uuid={uuid_}")
        else:
            log(f"PAPER maker BUY limit @ {limit:,.0f} ({notional:,.0f} KRW)")
        self.pending = {"limit": limit, "placed_i": self._candle_i,
                        "notional": notional, "qty": qty, "uuid": uuid_}

    def _poll_entry(self, price):
        pe = self.pending
        filled = False
        if self.live:
            o = self.client.get_order(pe["uuid"])
            if o.get("state") == "done":
                ev = float(o.get("executed_volume", pe["qty"]) or pe["qty"])
                paid = float(o.get("price", pe["limit"])) * ev  # approx notional
                self._open_position(pe["limit"], ev, paid or pe["notional"])
                filled = True
        else:
            if price <= pe["limit"]:
                self._open_position(pe["limit"], pe["qty"], pe["notional"])
                filled = True
        if filled:
            self.pending = None
        elif self._candle_i - pe["placed_i"] >= config.ENTRY_TTL_CANDLES:
            if self.live and pe["uuid"]:
                try:
                    self.client.cancel(pe["uuid"])
                except UpbitError as e:
                    log(f"cancel failed (may have filled): {e}")
            log("maker BUY unfilled within TTL -> cancelled")
            self.pending = None

    def _open_position(self, entry, qty, notional):
        self.pos = {
            "qty": qty, "entry": entry, "notional": notional,
            "entered_i": self._candle_i,
            "tp": entry * (1 + self.p["take_profit_pct"]),
            "sl": entry * (1 - self.p["stop_loss_pct"]),
            "exit_uuid": None,
        }
        self.risk.record_open(notional)
        log(f"ENTER {qty:.8f} BTC @ {entry:,.0f}  tp={self.pos['tp']:,.0f} "
            f"sl={self.pos['sl']:,.0f}")
        if self.live:  # rest a maker take-profit immediately
            try:
                r = self.client.sell_limit(self.market, int(self.pos["tp"]), qty)
                self.pos["exit_uuid"] = r.get("uuid")
            except UpbitError as e:
                log(f"could not place maker TP: {e}")

    # ---- exits -------------------------------------------------------------
    def _close_position(self, price, reason, maker):
        pos = self.pos
        entry_fee = pos["notional"] * config.UPBIT_FEE
        proceeds = pos["qty"] * price
        exit_fee = proceeds * config.UPBIT_FEE
        pnl = (proceeds - exit_fee) - (pos["notional"] + entry_fee)
        if self.live:
            if pos.get("exit_uuid") and not maker:
                try:
                    self.client.cancel(pos["exit_uuid"])  # cancel resting TP
                except UpbitError:
                    pass
            if not maker:  # taker exit: market sell what we hold
                self.client.sell_market(self.market, pos["qty"])
            log(f"LIVE EXIT reason={reason} ~{price:,.0f}")
        else:
            log(f"PAPER EXIT {pos['qty']:.8f} BTC @ {price:,.0f} reason={reason} "
                f"pnl={pnl:+,.0f} KRW")
        self.risk.record_close(pos["notional"], pnl)
        self.pos = None

    def _manage_position(self, price, new_candle, close):
        pos = self.pos
        # intrabar, checked every poll: stop first (worst case), then TP
        if price <= pos["sl"]:
            self._close_position(pos["sl"] * (1 - config.TAKER_SLIP_BPS / 1e4),
                                 "stop_loss", maker=False)
            return
        if price >= pos["tp"]:
            self._close_position(pos["tp"], "take_profit", maker=True)
            return
        if new_candle:  # mean-revert / timeout only evaluated on a closed candle
            z, _ = self._zscore(close)
            if z is not None and z >= self.p["exit_z"]:
                self._close_position(close * (1 - config.TAKER_SLIP_BPS / 1e4),
                                     "mean_revert", maker=False)
            elif self._candle_i - pos["entered_i"] >= self.p["max_hold"]:
                self._close_position(close * (1 - config.TAKER_SLIP_BPS / 1e4),
                                     "timeout", maker=False)

    # ---- main step ---------------------------------------------------------
    def step(self):
        candle = self._new_closed_candle()
        new_candle = candle is not None
        close = float(candle["trade_price"]) if new_candle else None
        price = self._price()

        if self.pending is not None:
            self._poll_entry(price)
        elif self.pos is not None:
            self._manage_position(price, new_candle, close)
        elif new_candle:  # flat: look for an entry on the freshly closed candle
            z, std = self._zscore(close)
            if z is not None and z <= -self.p["entry_z"]:
                std_bps = (std / close) * 1e4
                if std_bps >= self.p["min_std_bps"]:
                    try:
                        notional = self.risk.can_open()
                    except RiskHalt as e:
                        log(f"entry blocked by risk: {e}")
                    else:
                        self._place_maker_buy(notional)

        if new_candle:
            self.closes.append(close)

    def run(self, once=False):
        mode = "LIVE" if self.live else "PAPER"
        log(f"=== bot start mode={mode} market={self.market} params={self.p} ===")
        log(f"risk: cap={config.MAX_EXPOSURE_KRW:,.0f} "
            f"per_trade={config.PER_TRADE_KRW:,.0f} "
            f"daily_loss_limit={config.DAILY_LOSS_LIMIT_KRW:,.0f}")
        if self.risk.is_halted():
            log("!! HALT flag present -> not trading. Clear state.json.HALT to resume.")
        self._warm_up()
        while True:
            try:
                self.step()
            except (UpbitError, RiskHalt) as e:
                log(f"error: {e}")
            except Exception as e:  # never die silently in a trading loop
                log(f"UNEXPECTED: {type(e).__name__}: {config.redact(str(e))}")
            if once:
                break
            time.sleep(config.POLL_SECONDS)


def confirm_live():
    phrase = "TRADE LIVE"
    log("LIVE MODE requested. This places REAL orders with REAL money.")
    log(f"Exposure is hard-capped at {config.MAX_EXPOSURE_KRW:,.0f} KRW.")
    try:
        got = input(f'Type "{phrase}" to proceed: ').strip()
    except EOFError:
        got = ""
    return got == phrase


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="place REAL orders")
    ap.add_argument("--once", action="store_true", help="single iteration")
    ap.add_argument("--yes", action="store_true",
                    help="skip live confirmation prompt (use with care)")
    args = ap.parse_args()
    if args.live and not config.LIVE_TRADING_ENABLED:
        log("live requested but config.LIVE_TRADING_ENABLED is False "
            "(master switch, off by default) -> aborting. This is the go-live gate.")
        sys.exit(1)
    if args.live and not args.yes and not confirm_live():
        log("live confirmation not given; aborting.")
        sys.exit(1)
    Bot(live=args.live).run(once=args.once)


if __name__ == "__main__":
    main()
