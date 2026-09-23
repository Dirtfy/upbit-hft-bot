"""Risk manager — the safety envelope around the strategy.

Enforces, independently of the strategy logic:
  * Exposure cap: total open notional never exceeds MAX_EXPOSURE_KRW (mission
    hard limit of 1,000,000 KRW), regardless of account balance.
  * Per-trade sizing: each entry uses at most PER_TRADE_KRW.
  * Daily loss kill switch: if realized loss for the day exceeds
    DAILY_LOSS_LIMIT_KRW, trading halts and a flag file is written; the bot
    will not re-enter until the flag is manually cleared.
  * Minimum order size (Upbit rejects < 5,000 KRW).

State (realized PnL, day, halted flag) is persisted to disk so a restart does
not reset the kill switch within the same day.
"""
import json
import os
import time
from datetime import datetime, timezone

import config


class RiskHalt(Exception):
    """Raised when a hard risk limit forbids opening a position."""


class RiskManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.halt_flag = state_path + ".HALT"
        self.s = {
            "day": self._today(),
            "realized_pnl_today": 0.0,
            "open_notional": 0.0,
            "trades_today": 0,
        }
        self._load()

    def _today(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path) as f:
                    self.s.update(json.load(f))
            except Exception:
                pass
        self._rollover()

    def _save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.s, f)
        os.replace(tmp, self.state_path)

    def _rollover(self):
        today = self._today()
        if self.s.get("day") != today:
            self.s["day"] = today
            self.s["realized_pnl_today"] = 0.0
            self.s["trades_today"] = 0
            self._save()

    # ---- kill switch -------------------------------------------------------
    def is_halted(self):
        return os.path.exists(self.halt_flag)

    def trip_halt(self, reason):
        with open(self.halt_flag, "w") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {reason}\n")

    def clear_halt(self):
        if os.path.exists(self.halt_flag):
            os.remove(self.halt_flag)

    # ---- tradable-capital cap (Cycle 15) -----------------------------------
    def tradable_capital(self, free_balance=None):
        """The fixed trading budget sizing may draw from. Profit above the base is
        locked and never re-risked:
            tradable = min(BASE_TRADABLE_CAPITAL_KRW, free_balance)
        If free_balance is None the account balance is not being tracked here (the
        paper runner enforces the cap in its own book), so return the full base.
        Drawdown: if free_balance < base, tradable = free_balance — we never deploy
        more than the base, nor money we don't have."""
        base = config.BASE_TRADABLE_CAPITAL_KRW
        if free_balance is None:
            return base
        return max(0.0, min(base, free_balance))

    def protected_profit(self, free_balance):
        """Balance set aside above the base (never re-risked). 0 while at/below base."""
        return max(0.0, free_balance - config.BASE_TRADABLE_CAPITAL_KRW)

    # ---- sizing / checks ---------------------------------------------------
    def can_open(self, free_balance=None):
        """Return the KRW notional allowed for a new entry, or raise RiskHalt.
        Sizing draws from the capped tradable capital, NOT the raw balance."""
        self._rollover()
        if self.is_halted():
            raise RiskHalt("kill switch active (HALT flag present)")
        if self.s["realized_pnl_today"] <= -config.DAILY_LOSS_LIMIT_KRW:
            self.trip_halt(
                f"daily loss limit hit: {self.s['realized_pnl_today']:.0f} KRW")
            raise RiskHalt("daily loss limit reached")
        budget = min(config.MAX_EXPOSURE_KRW, self.tradable_capital(free_balance))
        headroom = budget - self.s["open_notional"]
        size = min(config.PER_TRADE_KRW, headroom)
        if size < config.MIN_ORDER_KRW:
            raise RiskHalt(
                f"no tradable headroom (budget={budget:.0f}, "
                f"open={self.s['open_notional']:.0f})")
        return size

    def gap_capped_notional(self, stop_distance_frac=None, free_balance=None):
        """Cycle-13 execution-gap sizing. During a <=MAX_BLIND_HOURS outage the
        bot cannot act, so bound the worst-case blind loss to DAILY_LOSS_LIMIT.

        If a RESTING protective stop is in the market, the worst-case loss is the
        stop distance (plus gap-through), so cap on `stop_distance_frac`.
        Otherwise fall back to the conservative BLIND_WORST_MOVE. Returns the
        gap-safe notional (<= can_open()), also capped to tradable capital."""
        base = self.can_open(free_balance)
        move = stop_distance_frac if stop_distance_frac else config.BLIND_WORST_MOVE
        move = max(move, 1e-6)
        gap_safe = config.DAILY_LOSS_LIMIT_KRW / move
        return min(base, gap_safe)

    def record_open(self, notional):
        self.s["open_notional"] += notional
        # never let accounting drift above the cap
        self.s["open_notional"] = min(self.s["open_notional"],
                                      config.MAX_EXPOSURE_KRW)
        self._save()

    def record_close(self, notional, realized_pnl):
        self.s["open_notional"] = max(0.0, self.s["open_notional"] - notional)
        self.s["realized_pnl_today"] += realized_pnl
        self.s["trades_today"] += 1
        self._save()
        if self.s["realized_pnl_today"] <= -config.DAILY_LOSS_LIMIT_KRW:
            self.trip_halt(
                f"daily loss limit hit: {self.s['realized_pnl_today']:.0f} KRW")

    def snapshot(self):
        return dict(self.s, halted=self.is_halted())
