#!/usr/bin/env python3
"""Strategy-evolution lab (Cycle 31) — sleeves, ensemble, cost/delay simulator.

RESEARCH / PAPER ONLY. Pure stdlib (the host that runs the daemons has no
numpy). Public 1h candles from data/1h/ (see data_1h.py); no keys, no orders.

Model
-----
* One HOURLY grid (BTC hours, gaps forward-filled). Daily (00:00 UTC) and 4h
  bars are resampled from it, so every timeframe shares one clock.
* A SLEEVE is one strategy family with fixed parameters. It emits a list of
  (hour, weights) changes: `weights` is a tuple over UNIVERSE (long-only, each
  >= 0, sum <= 1). A signal computed on a bar that closes at hour h is emitted
  at h (the first hour that bar's close is known) — never earlier.
* The ENSEMBLE (genome) mixes sleeves: total = gate * voltarget * sum_i w_i *
  sleeve_i, with optional regime switching (separate weight vectors for
  BTC > SMA200 "bull" vs otherwise "side"), and an optional bear gate (the
  repo's dd regime filter, src/regime.py).
* The SIMULATOR fills each change `delay` hours after it is emitted, at that
  hour's open (= prior hour close), paying `cost` per side on traded notional
  (fee 0.05% + slippage). Equity is marked at every 00:00 UTC.
"""
import bisect
import csv
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
import regime  # noqa: E402  (single source of truth for the dd bear filter)

DATA_DIR = os.path.join(ROOT, "data", "1h")
UNIVERSE = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE", "KRW-ADA"]
BTC, ETH = 0, 1
A = len(UNIVERSE)
FEE = 0.0005           # Upbit KRW market, per side
SLIP = 0.0005          # assumed slippage per side (conservative vs TAKER_SLIP_BPS)
COST = FEE + SLIP
H = 3600


def _ts(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- data
class Market:
    """Hourly grid for UNIVERSE + resampled daily/4h BTC bars."""

    def __init__(self, data_dir=DATA_DIR, end=None):
        btc = self._read(os.path.join(data_dir, "KRW-BTC.csv"), full=True, end=end)
        self.t0 = _ts(btc[0][0])
        last = _ts(btc[-1][0])
        self.n = int((last - self.t0).total_seconds() // H) + 1
        n = self.n
        self.o, self.h, self.l, self.c = ([None] * n for _ in range(4))
        for r in btc:
            i = self._idx(r[0])
            self.o[i], self.h[i], self.l[i], self.c[i] = r[1], r[2], r[3], r[4]
        self._ffill_ohlc()
        # close per asset (None before listing), forward-filled after listing
        self.close = [self.c]
        for m in UNIVERSE[1:]:
            p = os.path.join(data_dir, f"{m}.csv")
            arr = [None] * n
            if os.path.exists(p):
                for r in self._read(p, full=False, end=end):
                    i = self._idx(r[0])
                    if 0 <= i < n:
                        arr[i] = r[1]
                last_v = None
                for i in range(n):
                    if arr[i] is None:
                        arr[i] = last_v
                    else:
                        last_v = arr[i]
            self.close.append(arr)
        self.d = self._resample(24)
        self.h4 = self._resample(4)
        self.h1 = {"start": list(range(n)), "end": [i + 1 for i in range(n)],
                   "o": self.o, "h": self.h, "l": self.l, "c": self.c}
        self.day_marks = [b for b in self.d["start"]] + [self.d["end"][-1]]

    @staticmethod
    def _read(path, full, end=None):
        out = []
        with open(path) as f:
            for r in csv.DictReader(f):
                if end and r["time_utc"] >= end:
                    break
                if full:
                    out.append((r["time_utc"], float(r["open"]), float(r["high"]),
                                float(r["low"]), float(r["close"])))
                else:
                    out.append((r["time_utc"], float(r["close"])))
        return out

    def _idx(self, s):
        return int((_ts(s) - self.t0).total_seconds() // H)

    def _ffill_ohlc(self):
        for i in range(self.n):
            if self.c[i] is None:
                p = self.c[i - 1]
                self.o[i] = self.h[i] = self.l[i] = self.c[i] = p

    def _resample(self, step):
        # align to UTC multiples of `step` hours
        first = 0
        while (self.t0 + timedelta(hours=first)).hour % step:
            first += 1
        bars = {"start": [], "end": [], "o": [], "h": [], "l": [], "c": []}
        i = first
        while i + step <= self.n:
            bars["start"].append(i)
            bars["end"].append(i + step)
            bars["o"].append(self.o[i])
            bars["h"].append(max(self.h[i:i + step]))
            bars["l"].append(min(self.l[i:i + step]))
            bars["c"].append(self.c[i + step - 1])
            i += step
        return bars

    def hour_of(self, iso):
        return max(0, min(self.n, self._idx(iso)))

    def time_of(self, h):
        return self.t0 + timedelta(hours=h)

    def bars(self, tf):
        return {"1d": self.d, "4h": self.h4, "1h": self.h1}[tf]

    def daily_close_series(self, asset):
        arr = self.close[asset]
        return [arr[e - 1] for e in self.d["end"]]


BARS_PER_DAY = {"1d": 1, "4h": 6, "1h": 24}


# ------------------------------------------------------------------- indicators
def _sma_series(x, n):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _rsi_series(c, n):
    """Wilder RSI."""
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0)
        l += max(-d, 0)
    g /= n
    l /= n
    out[n] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def _atr_series(h, l, c, n):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
                          for i in range(1, len(c))]
    out = [None] * len(c)
    if len(c) < n:
        return out
    a = sum(tr[:n]) / n
    out[n - 1] = a
    for i in range(n, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def _w(asset_weights):
    w = [0.0] * A
    for a, v in asset_weights.items():
        w[a] = v
    return tuple(w)


ZERO = tuple([0.0] * A)
LONG_BTC = _w({BTC: 1.0})


def _binary_events(bars, states, w_on=LONG_BTC):
    """states[k] in {0,1} decided at close of bar k -> events at bars.end[k]."""
    ev, prev = [], None
    for k, s in enumerate(states):
        if s != prev:
            ev.append((bars["end"][k], w_on if s else ZERO))
            prev = s
    return ev


# ---------------------------------------------------------------------- sleeves
# Each returns a list of (hour, weights) changes, no lookahead. Param grids live
# in SLEEVE_SPACE; the GA only ever samples from these grids.

def s_tsmom(mk, tf, days):
    """Time-series momentum (Moskowitz/Ooi/Pedersen 2012): long iff the
    lookback return is positive."""
    b = mk.bars(tf)
    c = b["c"]
    L = days * BARS_PER_DAY[tf]
    st = [1 if k >= L and c[k] > c[k - L] else 0 for k in range(len(c))]
    return _binary_events(b, st)


def s_donchian(mk, tf, n_in, n_out, atr_k):
    """Donchian channel breakout (Turtle style) with optional ATR(14) trail —
    the repo's Cycle 3-6 family. n_in/n_out in DAYS, scaled to bars."""
    b = mk.bars(tf)
    h, l, c = b["h"], b["l"], b["c"]
    bpd = BARS_PER_DAY[tf]
    ni, no = n_in * bpd, n_out * bpd
    atr = _atr_series(h, l, c, 14 * bpd) if atr_k else None
    st, s, peak = [], 0, 0.0
    hh = _rolling_max(h, ni)
    ll = _rolling_min(l, no)
    for k in range(len(c)):
        if k < max(ni, no) + 1:
            st.append(0)
            continue
        if s == 0:
            if c[k] > hh[k - 1]:
                s, peak = 1, c[k]
        else:
            peak = max(peak, c[k])
            stop = atr_k and atr[k] is not None and c[k] < peak - atr_k * atr[k]
            if c[k] < ll[k - 1] or stop:
                s = 0
        st.append(s)
    return _binary_events(b, st)


def _rolling_max(x, n):
    from collections import deque
    out, dq = [None] * len(x), deque()
    for i, v in enumerate(x):
        while dq and x[dq[-1]] <= v:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - n:
            dq.popleft()
        out[i] = x[dq[0]]
    return out


def _rolling_min(x, n):
    return [-v for v in _rolling_max([-v for v in x], n)]


def s_volbreak(mk, k, ma_days):
    """Larry Williams volatility breakout on DAILY ranges, triggered INTRADAY
    from 1h bars: buy once the hour's high crosses open_d + k*(H-L)_{d-1}
    (signal known at that hour's close), exit at the next 00:00 UTC open.
    Optional filter (popular Korean variant): prior close > SMA(ma_days)."""
    d = mk.d
    sma = _sma_series(d["c"], ma_days) if ma_days else None
    ev = []
    for j in range(1, len(d["c"])):
        if sma is not None and (sma[j - 1] is None or d["c"][j - 1] <= sma[j - 1]):
            continue
        trig = d["o"][j] + k * (d["h"][j - 1] - d["l"][j - 1])
        s, e = d["start"][j], d["end"][j]
        for i in range(s, e - 1):          # entering on the last hour is pointless
            if mk.h[i] >= trig:
                ev.append((i + 1, LONG_BTC))
                ev.append((e, ZERO))
                break
    return ev


def s_meanrev(mk, tf, rsi_n, lo, hi, trend):
    """RSI mean reversion (Connors RSI(2) style): buy when RSI < lo, exit when
    RSI > hi. trend=1 only buys while close > its 200-day SMA."""
    b = mk.bars(tf)
    c = b["c"]
    r = _rsi_series(c, rsi_n)
    sma = _sma_series(c, 200 * BARS_PER_DAY[tf]) if trend else None
    st, s = [], 0
    for k in range(len(c)):
        if r[k] is None:
            st.append(0)
            continue
        if s == 0:
            if r[k] < lo and (sma is None or (sma[k] is not None and c[k] > sma[k])):
                s = 1
        elif r[k] > hi:
            s = 0
        st.append(s)
    return _binary_events(b, st)


def s_rotation(mk, days, top_k, every):
    """Cross-sectional momentum rotation over UNIVERSE (daily): every `every`
    days hold the top_k coins by `days`-day return, equal weight, only those
    with positive momentum (absolute filter, 'dual momentum')."""
    d = mk.d
    closes = [mk.daily_close_series(a) for a in range(A)]
    ev, prev = [], None
    for j in range(days, len(d["c"]), every):
        moms = []
        for a in range(A):
            c0, c1 = closes[a][j - days], closes[a][j]
            if c0 and c1:
                moms.append((c1 / c0 - 1, a))
        moms.sort(reverse=True)
        pick = [a for m, a in moms[:top_k] if m > 0]
        w = _w({a: 1.0 / top_k for a in pick})
        if w != prev:
            ev.append((d["end"][j], w))
            prev = w
    return ev


def s_pairs(mk, n, z0):
    """ETH/BTC relative value (long-only switch, Gatev et al. 2006 idea): when
    log(ETH/BTC) is z0 std below its n-day mean hold ETH (cheap leg) until z>0;
    when z0 above, hold BTC until z<0; else flat."""
    d = mk.d
    be, ee = mk.daily_close_series(BTC), mk.daily_close_series(ETH)
    ev, s, prev = [], 0, None
    lr = [math.log(e / b) if e and b else None for e, b in zip(ee, be)]
    for j in range(n, len(lr)):
        win = lr[j - n + 1:j + 1]
        if any(v is None for v in win):
            continue
        m = sum(win) / n
        sd = math.sqrt(sum((v - m) ** 2 for v in win) / n) or 1e-12
        z = (lr[j] - m) / sd
        if s == 0:
            s = 1 if z < -z0 else (-1 if z > z0 else 0)
        elif s == 1 and z > 0:
            s = 0
        elif s == -1 and z < 0:
            s = 0
        w = _w({ETH: 1.0}) if s == 1 else (LONG_BTC if s == -1 else ZERO)
        if w != prev:
            ev.append((d["end"][j], w))
            prev = w
    return ev


def s_hold(mk):
    """Always long BTC (buy-and-hold). With a bear gate this IS the official
    long_flat book, so the GA can rediscover/beat the current strategy."""
    return [(0, LONG_BTC)]


SLEEVES = {
    "hold": (s_hold, {}),
    "tsmom": (s_tsmom, {"tf": ["1d", "4h", "1h"], "days": [10, 20, 40, 60, 90, 120, 180]}),
    "donchian": (s_donchian, {"tf": ["1d", "4h"], "n_in": [10, 20, 30, 55],
                              "n_out": [5, 10, 20], "atr_k": [0, 2, 3, 4]}),
    "volbreak": (s_volbreak, {"k": [0.3, 0.4, 0.5, 0.6, 0.7], "ma_days": [0, 3, 5, 10, 20]}),
    "meanrev": (s_meanrev, {"tf": ["1d", "4h", "1h"], "rsi_n": [2, 3, 5, 14],
                            "lo": [10, 20, 30], "hi": [50, 60, 70], "trend": [0, 1]}),
    "rotation": (s_rotation, {"days": [7, 14, 30, 60, 90], "top_k": [1, 2, 3],
                              "every": [1, 7]}),
    "pairs": (s_pairs, {"n": [20, 60, 120], "z0": [1.0, 1.5, 2.0]}),
}
SLEEVE_NAMES = list(SLEEVES)
WEIGHT_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]
META_SPACE = {
    "gate": ["none", "dd20_10", "dd12.5_5"],
    "vt": [0, 0.4, 0.6, 0.8],            # annualised vol target on BTC (0 = off)
    "band": [0.0, 0.05, 0.1, 0.2],       # rebalance band in weight units
    "regime_switch": [0, 1],
}


class Lab:
    """Caches sleeve outputs and daily overlays for one Market."""

    def __init__(self, mk):
        self.mk = mk
        self.cache = {}
        self.evals = 0
        dbars = [{"close": c} for c in mk.d["c"]]
        self.gates = {"none": [1] * len(dbars)}
        for name, (de, dx) in {"dd20_10": (0.20, 0.10), "dd12.5_5": (0.125, 0.05)}.items():
            p = dict(sma_long=200, band=0.0, dd_window=365, dd_enter=de, dd_exit=dx)
            self.gates[name] = [1 if r == "bull" else 0 for r in regime.compute_regimes(dbars, p)]
        c = mk.d["c"]
        sma200 = _sma_series(c, 200)
        self.bull = [1 if s is not None and c[k] > s else 0 for k, s in enumerate(sma200)]
        rets = [0.0] + [math.log(c[k] / c[k - 1]) for k in range(1, len(c))]
        self.rv = [None] * len(c)
        for k in range(20, len(c)):
            w = rets[k - 19:k + 1]
            m = sum(w) / 20
            self.rv[k] = math.sqrt(sum((x - m) ** 2 for x in w) / 19 * 365)

    def sleeve(self, name, params):
        key = (name, tuple(sorted(params.items())))
        if key not in self.cache:
            if len(self.cache) > 400:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = SLEEVES[name][0](self.mk, **params)
        return self.cache[key]

    # ---- genome -> combined event list
    def events(self, g):
        mk = self.mk
        streams = []
        for i, name in enumerate(SLEEVE_NAMES):
            wb, ws = g["w_bull"][i], g["w_side"][i] if g["regime_switch"] else g["w_bull"][i]
            if wb == 0 and ws == 0:
                continue
            streams.append((i, self.sleeve(name, g["p"][name])))
        times = set()
        for _, ev in streams:
            times.update(t for t, _ in ev)
        gate = self.gates[g["gate"]]
        times.update(mk.d["end"])               # daily overlays can change at each close
        times = sorted(t for t in times if t <= mk.n)
        sb = sum(g["w_bull"])
        ss = sum(g["w_side"]) if g["regime_switch"] else sb
        norm_b, norm_s = max(1.0, sb), max(1.0, ss)
        ptr = [0] * len(streams)
        cur = [ZERO] * len(streams)
        dk = -1
        ends = mk.d["end"]
        out, prev = [], None
        for t in times:
            for si, (_, ev) in enumerate(streams):
                p = ptr[si]
                while p < len(ev) and ev[p][0] <= t:
                    cur[si] = ev[p][1]
                    p += 1
                ptr[si] = p
            while dk + 1 < len(ends) and ends[dk + 1] <= t:
                dk += 1
            if dk < 0:
                tot = ZERO
            else:
                bull = (not g["regime_switch"]) or self.bull[dk]
                wv, nm = (g["w_bull"], norm_b) if bull else (g["w_side"], norm_s)
                scale = gate[dk]
                if g["vt"] and self.rv[dk]:
                    scale *= min(1.0, g["vt"] / self.rv[dk])
                if scale == 0:
                    tot = ZERO
                else:
                    acc = [0.0] * A
                    for si, (i, _) in enumerate(streams):
                        wi = wv[i]
                        if wi:
                            for a, x in enumerate(cur[si]):
                                if x:
                                    acc[a] += wi * x
                    tot = tuple(round(scale * v / nm, 4) for v in acc)
            if tot != prev:
                out.append((t, tot))
                prev = tot
        return out

    def evaluate(self, g, start, end, delay=0, cost=COST):
        self.evals += 1
        return simulate(self.mk, self.events(g), start, end, delay, cost, g.get("band", 0.0))


# -------------------------------------------------------------------- simulator
def simulate(mk, events, start, end, delay=0, cost=COST, band=0.0, capital=1.0,
             cap=None, record=False):
    """A change emitted at hour t (signal bar closed at t) is filled at the OPEN
    of hour t+delay: delay=0 is the classic 'next-bar open' fill, delay=5 is the
    repo's 5h blind-window assumption (config.MAX_BLIND_HOURS). Fills pay `cost`
    per side. Marks equity at every 00:00 UTC in [start, end]. Returns a
    metrics dict (+ trade log if record)."""
    closes = mk.close
    # marks: every 00:00 UTC inside the window, plus the window edges (so a
    # forward book launched mid-day is marked at launch and at the last hour)
    marks = sorted(set([start, end] + [m for m in mk.day_marks if start < m < end]))
    ev = [(t + delay, w) for t, w in events]
    # state at `start`: the last target emitted before start becomes the initial
    # target, filled at start (so a window starts 'in position' like a live run)
    k = bisect.bisect_right([t for t, _ in ev], start) - 1
    queue = ([(start, ev[k][1])] if k >= 0 else []) + [e for e in ev[k + 1:] if e[0] < end]
    units = [0.0] * A
    cash = capital
    curw = [0.0] * A
    eq_marks, trades, turnover, fees = [], 0, 0.0, 0.0
    log = []
    qi = 0
    exposure_sum = 0.0

    def px(a, hr):
        return closes[a][hr - 1] if hr >= 1 else closes[a][0]

    def equity(hr):
        return cash + sum(units[a] * px(a, hr) for a in range(A) if units[a])

    for m in marks + [None]:
        # a mark at hour m is the equity BEFORE fills at m: those fills belong
        # to the next day (same bucketing as the trade log), so a day's mark
        # never changes once hour m has been seen (append-only forward books)
        while qi < len(queue) and (m is None or queue[qi][0] < m):
            t, w = queue[qi]
            qi += 1
            if t >= end:
                break
            eq = equity(t)
            book = eq if cap is None else min(eq, cap)
            for a in range(A):
                p = px(a, t)
                tw = w[a] if p else 0.0
                cw = units[a] * p / eq if (p and eq > 0) else 0.0
                if abs(tw - cw) < 1e-9:
                    continue
                if band and tw > 0 and cw > 0 and abs(tw - cw) < band:
                    continue
                dv = tw * book - units[a] * p
                c = abs(dv) * cost
                units[a] += dv / p
                cash -= dv + c
                fees += c
                trades += 1
                turnover += abs(dv) / eq
                if record:
                    log.append({"hour": t, "asset": UNIVERSE[a], "side": "BUY" if dv > 0 else "SELL",
                                "price": p, "notional": abs(dv), "cost": c})
            curw = w
        if m is not None:
            e = equity(m)
            eq_marks.append((m, e))
            exposure_sum += sum(curw)
    out = metrics(eq_marks, trades, turnover, fees, exposure_sum, log if record else None)
    eq_end = equity(end)
    out["final_equity"] = eq_end
    out["final_w"] = [round(units[a] * px(a, end) / eq_end, 4) if (eq_end > 0 and units[a]) else 0.0
                      for a in range(A)]
    return out


def metrics(eq_marks, trades, turnover, fees, exposure_sum, log=None):
    eq = [e for _, e in eq_marks]
    out = {"days": len(eq), "trades": trades}
    if len(eq) < 3:
        out.update(cagr=0, mdd=0, sharpe=0, total=0, turnover=0, exposure=0, rets=[])
        return out
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    yrs = (len(eq) - 1) / 365.0
    total = eq[-1] / eq[0] - 1
    peak, mdd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = max(mdd, 1 - e / peak)
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / max(1, len(rets) - 1))
    out.update(
        total=total, cagr=(eq[-1] / eq[0]) ** (1 / yrs) - 1 if eq[-1] > 0 else -1,
        mdd=mdd, sharpe=(m / sd * math.sqrt(365)) if sd > 0 else 0.0,
        turnover=turnover / yrs, exposure=exposure_sum / len(eq), rets=rets,
        fees=fees, eq=eq_marks)
    if log is not None:
        out["log"] = log
    return out


def sub_sharpes(rets, parts=3):
    n = len(rets) // parts
    out = []
    for p in range(parts):
        seg = rets[p * n:(p + 1) * n]
        m = sum(seg) / len(seg)
        sd = math.sqrt(sum((r - m) ** 2 for r in seg) / max(1, len(seg) - 1))
        out.append(m / sd * math.sqrt(365) if sd > 0 else 0.0)
    return out


# ----------------------------------------------------------------- statistics
def deflated_sharpe(sr_ann, rets, n_trials, sr_var_ann):
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio: probability that
    the true SR > the expected MAX SR of n_trials unskilled strategies, adjusted
    for skew/kurtosis and sample length. Inputs annualised; converted to daily."""
    nd = NormalDist()
    T = len(rets)
    if T < 10 or n_trials < 2:
        return float("nan")
    sr = sr_ann / math.sqrt(365)
    v = sr_var_ann / 365
    g = 0.5772156649
    sr0 = math.sqrt(max(v, 1e-12)) * ((1 - g) * nd.inv_cdf(1 - 1 / n_trials)
                                      + g * nd.inv_cdf(1 - 1 / (n_trials * math.e)))
    m = sum(rets) / T
    sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (T - 1))
    skew = sum((r - m) ** 3 for r in rets) / T / sd ** 3
    kurt = sum((r - m) ** 4 for r in rets) / T / sd ** 4
    den = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return nd.cdf((sr - sr0) * math.sqrt(T - 1) / den)


# ---------------------------------------------------------------------- genomes
def random_genome(rng):
    g = {"p": {n: {k: rng.choice(v) for k, v in SLEEVES[n][1].items()} for n in SLEEVE_NAMES}}
    for k, v in META_SPACE.items():
        g[k] = rng.choice(v)
    # sparse weights: each sleeve on with prob 0.4
    g["w_bull"] = [rng.choice(WEIGHT_GRID[1:]) if rng.random() < 0.4 else 0.0 for _ in SLEEVE_NAMES]
    g["w_side"] = [rng.choice(WEIGHT_GRID[1:]) if rng.random() < 0.4 else 0.0 for _ in SLEEVE_NAMES]
    if not any(g["w_bull"]):
        g["w_bull"][rng.randrange(len(SLEEVE_NAMES))] = 1.0
    return g


def mutate(g, rng, pm=0.15):
    g = {"p": {n: dict(v) for n, v in g["p"].items()}, **{k: (list(v) if isinstance(v, list) else v)
                                                           for k, v in g.items() if k != "p"}}
    for n in SLEEVE_NAMES:
        for k, v in SLEEVES[n][1].items():
            if rng.random() < pm:
                g["p"][n][k] = _step(v, g["p"][n][k], rng)
    for k, v in META_SPACE.items():
        if rng.random() < pm:
            g[k] = _step(v, g[k], rng)
    for vec in ("w_bull", "w_side"):
        for i in range(len(SLEEVE_NAMES)):
            if rng.random() < pm:
                g[vec][i] = _step(WEIGHT_GRID, g[vec][i], rng)
    if not any(g["w_bull"]):
        g["w_bull"][rng.randrange(len(SLEEVE_NAMES))] = 0.5
    return g


def _step(grid, cur, rng):
    """Mutate to a neighbouring grid value (local search) or a random one."""
    i = grid.index(cur) if cur in grid else 0
    if rng.random() < 0.7:
        i = max(0, min(len(grid) - 1, i + rng.choice([-1, 1])))
    else:
        i = rng.randrange(len(grid))
    return grid[i]


def crossover(a, b, rng):
    c = {"p": {n: dict((a if rng.random() < 0.5 else b)["p"][n]) for n in SLEEVE_NAMES}}
    for k in META_SPACE:
        c[k] = (a if rng.random() < 0.5 else b)[k]
    for vec in ("w_bull", "w_side"):
        c[vec] = [(a if rng.random() < 0.5 else b)[vec][i] for i in range(len(SLEEVE_NAMES))]
    if not any(c["w_bull"]):
        c["w_bull"] = list(a["w_bull"])
    return c


def key(g):
    """Canonical identity: only parameters of ACTIVE sleeves matter."""
    act = [i for i in range(len(SLEEVE_NAMES))
           if g["w_bull"][i] or (g["regime_switch"] and g["w_side"][i])]
    parts = [f"{k}={g[k]}" for k in META_SPACE]
    parts.append("wb=" + ",".join(str(g["w_bull"][i]) for i in range(len(SLEEVE_NAMES))))
    if g["regime_switch"]:
        parts.append("ws=" + ",".join(str(x) for x in g["w_side"]))
    for i in act:
        n = SLEEVE_NAMES[i]
        parts.append(n + "(" + ",".join(f"{k}={v}" for k, v in sorted(g["p"][n].items())) + ")")
    return "|".join(parts)


def describe(g):
    """Human-readable one-liner of a genome."""
    act = []
    for i, n in enumerate(SLEEVE_NAMES):
        wb = g["w_bull"][i]
        ws = g["w_side"][i] if g["regime_switch"] else None
        if wb or ws:
            pr = ",".join(f"{k}={v}" for k, v in g["p"][n].items())
            w = f"{wb}" if ws is None else f"bull {wb}/side {ws}"
            act.append(f"{n}[{pr}]x{w}")
    meta = f"gate={g['gate']} vt={g['vt']} band={g['band']} switch={g['regime_switch']}"
    return " + ".join(act) + " | " + meta


def fixed_genome(sleeve, params, gate="none", weight=1.0):
    """A single-sleeve genome (used for baselines / hand seeds)."""
    rng = random.Random(0)
    g = random_genome(rng)
    g["p"][sleeve] = dict(params)
    g["w_bull"] = [weight if n == sleeve else 0.0 for n in SLEEVE_NAMES]
    g["w_side"] = list(g["w_bull"])
    g.update(gate=gate, vt=0, band=0.0, regime_switch=0)
    return g
