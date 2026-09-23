"""Minimal Upbit REST client — stdlib only.

Auth: Upbit uses a JWT (HS256) in the Authorization header. For endpoints with
query parameters, the JWT payload must include a SHA512 hash of the query
string. We build and sign the JWT by hand (base64url + HMAC-SHA256) so no
third-party packages are required.

Only the endpoints the bot needs are implemented. All private calls are
rate-limit aware via a simple minimum-interval throttle.
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid

API = "https://api.upbit.com"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class UpbitError(Exception):
    pass


class UpbitClient:
    def __init__(self, access_key, secret_key, min_interval=0.12):
        self._access = access_key
        self._secret = secret_key.encode()
        self._min_interval = min_interval
        self._last_call = 0.0

    # ---- low level ---------------------------------------------------------
    def _jwt(self, query_string: str = "") -> str:
        header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = {"access_key": self._access, "nonce": str(uuid.uuid4())}
        if query_string:
            h = hashlib.sha512(query_string.encode()).hexdigest()
            payload["query_hash"] = h
            payload["query_hash_alg"] = "SHA512"
        payload_b64 = _b64url(json.dumps(payload).encode())
        signing_input = f"{header}.{payload_b64}".encode()
        sig = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        return f"{header}.{payload_b64}.{_b64url(sig)}"

    def _throttle(self):
        dt = time.time() - self._last_call
        if dt < self._min_interval:
            time.sleep(self._min_interval - dt)
        self._last_call = time.time()

    def _request(self, method, path, params=None, private=False):
        self._throttle()
        params = params or {}
        query = urllib.parse.urlencode(params) if params else ""
        url = f"{API}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if method == "GET":
            if query:
                url += "?" + query
        else:
            data = json.dumps(params).encode()
            headers["Content-Type"] = "application/json"
        if private:
            headers["Authorization"] = "Bearer " + self._jwt(query)
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise UpbitError(f"HTTP {e.code} {path}: {detail}") from None
        except urllib.error.URLError as e:
            raise UpbitError(f"network error {path}: {e.reason}") from None

    # ---- public ------------------------------------------------------------
    def ticker(self, market):
        return self._request("GET", "/v1/ticker", {"markets": market})[0]

    def orderbook(self, market):
        return self._request("GET", "/v1/orderbook", {"markets": market})[0]

    def candles_1m(self, market, count=200):
        return self._request("GET", "/v1/candles/minutes/1",
                             {"market": market, "count": count})

    def candles_minutes(self, market, unit=240, count=200):
        return self._request("GET", f"/v1/candles/minutes/{unit}",
                             {"market": market, "count": count})

    def candles_days(self, market, count=200):
        return self._request("GET", "/v1/candles/days",
                             {"market": market, "count": count})

    def candles_history(self, market, kind="days", unit=240, count=3000):
        """Paginated public candle history from the live Upbit API (>200 rows).
        Walks back via the `to` cursor, dedups, returns oldest->newest. Public
        read-only; no keys. This is the canonical data-gathering path for both
        research datasets and the forward paper runner."""
        base = "/v1/candles/days" if kind == "days" else \
               f"/v1/candles/minutes/{unit}"
        rows, to = {}, None
        while len(rows) < count:
            params = {"market": market, "count": 200}
            if to:
                params["to"] = to
            page = self._request("GET", base, params)   # throttled in _request
            if not page:
                break
            for c in page:
                rows[c["candle_date_time_utc"]] = c
            new_to = page[-1]["candle_date_time_utc"] + "Z"
            if new_to == to:                              # reached start of history
                break
            to = new_to
        return sorted(rows.values(), key=lambda c: c["candle_date_time_utc"])

    # ---- private -----------------------------------------------------------
    def accounts(self):
        return self._request("GET", "/v1/accounts", private=True)

    def balance(self, currency):
        for a in self.accounts():
            if a["currency"] == currency:
                return float(a["balance"]), float(a.get("avg_buy_price", 0) or 0)
        return 0.0, 0.0

    def order_chance(self, market):
        return self._request("GET", "/v1/orders/chance", {"market": market},
                             private=True)

    def buy_market(self, market, krw_amount):
        """Market buy for a KRW notional (ord_type=price)."""
        return self._request("POST", "/v1/orders", {
            "market": market, "side": "bid",
            "ord_type": "price", "price": str(krw_amount),
        }, private=True)

    def sell_market(self, market, volume):
        """Market sell a coin volume (ord_type=market)."""
        return self._request("POST", "/v1/orders", {
            "market": market, "side": "ask",
            "ord_type": "market", "volume": f"{volume:.8f}",
        }, private=True)

    def buy_limit(self, market, price, volume):
        return self._request("POST", "/v1/orders", {
            "market": market, "side": "bid", "ord_type": "limit",
            "price": str(price), "volume": f"{volume:.8f}",
        }, private=True)

    def sell_limit(self, market, price, volume):
        return self._request("POST", "/v1/orders", {
            "market": market, "side": "ask", "ord_type": "limit",
            "price": str(price), "volume": f"{volume:.8f}",
        }, private=True)

    def get_order(self, uuid_):
        return self._request("GET", "/v1/order", {"uuid": uuid_}, private=True)

    def cancel(self, uuid_):
        return self._request("DELETE", "/v1/order", {"uuid": uuid_},
                             private=True)
