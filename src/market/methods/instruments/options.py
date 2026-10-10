"""Option instruments: turn one exposure window into option legs, cash flows and a daily value path.

Every window is simulated with $1 of capital (PLAN §7b, decisions D11–D13):

  csp           sell puts on collateral = strike × shares; at expiry an OTM put expires and the
                next one is sold the next session; an ITM put is assigned and the shares are held
                to the window's end (no more puts).
  covered_call  buy shares, sell calls on all of them; at expiry an OTM call expires and the next
                is sold; an ITM call is called away and the shares are re-bought the next session.
  leap          long calls sized by `sizing` (see _open_leap), the rest in T-bills; rolled at the
                window's value when DTE falls below `roll_below`.
  diagonal      the LEAP above plus a short call on the same share count, re-sold at each expiry
                (an ITM short call is settled at intrinsic, the LEAP is kept).

With method["fallback"] == "stock", a LEAP / diagonal window that finds no qualifying call holds
the stock instead of cash, and swaps it for the call on the first session one qualifies. method["short_prefer"] picks the short leg's expiry nearest that DTE.

Timing: a contract is chosen on the session before it is opened (the data a report sees), then
filled at the opening session's mid(open, close) with the spread haircut — sells at mid × (1 − h),
buys at mid × (1 + h). Expiry settles at the underlying's close. When the window ends every leg
is closed at that session's fill price, the same session the stock version exits. A held contract
with no bar is valued with Black-Scholes at its last observed IV. Cash earns the T-bill rate and
dividends are credited on shares held. A split inside a window closes everything the session
before the ex-date, holds cash over the ex-date, and reopens the next session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from market.methods import option_math as om

SHORT_KINDS = {"csp": "P", "covered_call": "C", "diagonal": "C"}


# ------------------------------------------------------------------ market data access
class OptionData:
    """In-memory option panel plus the underlying's raw prices, dividends and splits."""

    def __init__(self, bars: pd.DataFrame, panel, dividends: pd.DataFrame, rate: float, haircut: dict,
                 liquidity: dict):
        bars = bars.reset_index(drop=True)
        bars["session"] = pd.to_datetime(bars["session"])
        bars["expiry"] = pd.to_datetime(bars["expiry"])
        self.bars = bars
        # Row positions per key, materialized into small frames on first use.
        self._root_session_idx = bars.groupby(["root", "session"], sort=False).indices
        self._contract_idx = bars.groupby(["root", "expiry", "kind", "strike"], sort=False).indices
        self._root_session: dict = {}
        self._contracts: dict = {}
        self.panel = panel
        self.sessions = panel.sessions
        self.rate = rate
        self.haircut = haircut
        self.liquidity = liquidity
        self.raw_open = panel.open * panel.split_factor
        self.raw_vwap = panel.vwap * panel.split_factor
        self.raw_close = panel.raw_close
        self.dividends = {sid: g.set_index("ex_date")["amount"].groupby(level=0).sum()
                          for sid, g in dividends.assign(ex_date=pd.to_datetime(dividends["ex_date"])).groupby("security_id")}
        self.last_session = bars["session"].max() if len(bars) else None
        self._iv_cache: dict = {}

    # -- underlying
    def spot_close(self, sid, s) -> float:
        return float(self.raw_close.at[s, sid])

    def spot_mid(self, sid, s) -> float:
        o, c = self.raw_open.at[s, sid], self.raw_close.at[s, sid]
        return float((o + c) / 2) if pd.notna(o) else float(c)

    def stock_fill(self, sid, s) -> float:
        v = self.raw_vwap.at[s, sid]
        return float(v) if pd.notna(v) and v > 0 else self.spot_mid(sid, s)

    def dividend_on(self, sid, s) -> float:
        d = self.dividends.get(sid)
        return float(d.get(s, 0.0)) if d is not None else 0.0

    # -- options
    def rows_on(self, root, s) -> pd.DataFrame | None:
        key = (root, s)
        if key not in self._root_session:
            idx = self._root_session_idx.get(key)
            self._root_session[key] = None if idx is None else self.bars.iloc[idx]
        return self._root_session[key]

    def contract_bars(self, contract):
        """(sorted sessions, {session: {"open", "close"}}) for one contract, or None."""
        if contract not in self._contracts:
            idx = self._contract_idx.get(contract)
            if idx is None:
                self._contracts[contract] = None
            else:
                rows = self.bars.iloc[idx].sort_values("session")
                sessions = list(rows["session"])
                values = {d: {"open": o, "close": c} for d, o, c in
                          zip(sessions, rows["open"].to_numpy(float), rows["close"].to_numpy(float))}
                self._contracts[contract] = (pd.DatetimeIndex(sessions), values)
        return self._contracts[contract]

    def bar(self, contract, s):
        found = self.contract_bars(contract)
        return None if found is None else found[1].get(s)

    def last_bar_on_or_before(self, contract, s):
        found = self.contract_bars(contract)
        if found is None:
            return None, None
        sessions, values = found
        i = sessions.searchsorted(s, side="right") - 1
        return (sessions[i], values[sessions[i]]) if i >= 0 else (None, None)

    def iv_of(self, contract, premium, sid, s) -> float:
        root, expiry, kind, strike = contract
        t = (expiry - s).days / 365.0
        return float(om.implied_vol(np.array([kind]), np.array([premium]), self.spot_close(sid, s), np.array([strike]),
                                    np.array([t]), self.rate, self.div_yield(sid, s))[0])

    def model_iv(self, contract, sid, s, fallback: float | None) -> float | None:
        """IV from the contract's last bar on/before s (cached), else `fallback`."""
        when, bar = self.last_bar_on_or_before(contract, s)
        if when is None:
            return fallback
        key = (contract, when)
        if key not in self._iv_cache:
            self._iv_cache[key] = self.iv_of(contract, float(bar["close"]), sid, when)
        iv = self._iv_cache[key]
        return iv if np.isfinite(iv) else fallback

    def model(self, contract, sid, s, spot, iv) -> float:
        root, expiry, kind, strike = contract
        t = (expiry - s).days / 365.0
        if iv is None or not np.isfinite(iv):
            return float(max(spot - strike, 0) if kind == "C" else max(strike - spot, 0))
        return float(om.price(kind, spot, strike, t, self.rate, self.div_yield(sid, s), iv))

    def haircut_pct(self, mid: float, dte: int, abs_delta: float, mult: float) -> float:
        h = self.haircut
        pct = max(h["base_pct"], h["min_dollars"] / mid) if mid > 0 else h["base_pct"]
        if dte > h["wide_dte"] or abs_delta < h["wide_abs_delta"]:
            pct *= h["wide_multiplier"]
        return pct * mult

    def chain(self, sid, root, sel: pd.Timestamp) -> pd.DataFrame | None:
        """Every contract traded on `sel` with its IV and delta (cached: shared by all methods)."""
        key = ("chain", root, sel)
        if key not in self._iv_cache:
            rows = self.rows_on(root, sel)
            if rows is not None:
                rows = rows[rows["close"] > 0]
                spot, q = self.spot_close(sid, sel), self.div_yield(sid, sel)
                t = (rows["expiry"] - sel).dt.days.to_numpy() / 365.0
                kinds = rows["kind"].to_numpy()
                strikes = rows["strike"].to_numpy(float)
                iv = om.implied_vol(kinds, rows["close"].to_numpy(float), spot, strikes, t, self.rate, q)
                d = om.delta(kinds, spot, strikes, t, self.rate, q, np.nan_to_num(iv, nan=0.3))
                rows = rows.assign(iv=iv, delta=d).dropna(subset=["iv"])
            self._iv_cache[key] = rows
        return self._iv_cache[key]

    def select(self, sid, root, sel: pd.Timestamp, open_day: pd.Timestamp, kind: str, target: float,
               dte_lo: int, dte_hi: int, prefer_dte: int | None = None, relaxed: bool = False,
               tolerance: float | None = None):
        """A liquid contract traded on `sel` near `target` delta, or None.

        Without `tolerance`: the delta closest to target (in the expiry nearest `prefer_dte`, if given).
        With `tolerance`: only strikes within ±tolerance of target qualify; the expiry nearest
        `prefer_dte` that has one wins, and within it the most-traded qualifying strike."""
        key = ("pick", root, sel, open_day, kind, target, dte_lo, dte_hi, prefer_dte, relaxed, tolerance)
        if key in self._iv_cache:
            return self._iv_cache[key]
        pick = None
        rows = self.chain(sid, root, sel)
        if rows is not None and len(rows):
            dte = (rows["expiry"] - open_day).dt.days
            liq = self.liquidity["leap" if relaxed else "short"]
            cand = rows[(rows["kind"] == kind) & dte.between(dte_lo, dte_hi)
                        & (rows["volume"] >= liq["min_volume"]) & (rows["transactions"] >= liq["min_transactions"])]
            if tolerance is not None:
                cand = cand[(cand["delta"] - target).abs() <= tolerance]
            if len(cand):
                if prefer_dte is not None:
                    gap = ((cand["expiry"] - open_day).dt.days - prefer_dte).abs()
                    cand = cand[cand["expiry"] == cand.loc[gap.idxmin(), "expiry"]]
                if tolerance is not None:
                    row = cand.loc[cand["volume"].idxmax()]
                else:
                    row = cand.iloc[(cand["delta"] - target).abs().argsort().iloc[0]]
                pick = {"contract": (root, row["expiry"], kind, float(row["strike"])), "iv": float(row["iv"]),
                        "delta": float(row["delta"])}
        self._iv_cache[key] = pick
        return pick

    def div_yield(self, sid, s) -> float:
        key = ("q", sid, s)
        if key not in self._iv_cache:
            d = self.dividends.get(sid)
            spot = self.raw_close.at[s, sid]
            trailing = d.loc[s - pd.Timedelta(days=365): s].sum() if d is not None else 0.0
            self._iv_cache[key] = float(trailing / spot) if trailing and pd.notna(spot) and spot > 0 else 0.0
        return self._iv_cache[key]


# ------------------------------------------------------------------ book keeping
@dataclass
class Leg:
    contract: tuple | None          # (root, expiry, kind, strike); None for shares
    qty: float                      # shares-equivalent, + long / − short
    open_date: pd.Timestamp
    open_price: float
    delta: float | None = None
    iv: float | None = None
    close_date: pd.Timestamp | None = None
    close_price: float | None = None
    close_reason: str | None = None

    @property
    def kind(self) -> str:
        return "S" if self.contract is None else self.contract[2]


@dataclass
class WindowResult:
    marks: pd.Series                 # session → value at the close (capital = 1 at entry)
    exit_value: float | None         # value after exit fills (None while open)
    legs: list[Leg] = field(default_factory=list)
    events: dict = field(default_factory=dict)


class Book:
    def __init__(self, data: OptionData, sid: str, root: str, method: dict, mult: float):
        self.d, self.sid, self.root, self.m, self.mult = data, sid, root, method, mult
        self.cash = 0.0
        self.shares = 0.0
        self.legs: list[Leg] = []         # open option legs
        self.closed: list[Leg] = []
        self.share_leg: Leg | None = None
        self.value_before_open = 0.0
        self.on_fallback = False          # holding the stock until a qualifying call appears
        self.events = {"option_opens": 0, "no_contract": 0, "assigned": 0, "called_away": 0,
                       "model_fills": 0, "premium": 0.0, "rolls": 0, "stock_fallback": 0}

    # -- prices
    def option_mid(self, leg: Leg, s) -> float:
        bar = self.d.bar(leg.contract, s)
        if bar is not None and pd.notna(bar["close"]):
            o, c = bar["open"], bar["close"]
            return float((o + c) / 2) if pd.notna(o) else float(c)
        self.events["model_fills"] += 1
        iv = self.d.model_iv(leg.contract, self.sid, s, leg.iv)
        return self.d.model(leg.contract, self.sid, s, self.d.spot_mid(self.sid, s), iv)

    def option_mark(self, leg: Leg, s) -> float:
        bar = self.d.bar(leg.contract, s)
        if bar is not None and pd.notna(bar["close"]):
            return float(bar["close"])
        iv = self.d.model_iv(leg.contract, self.sid, s, leg.iv)
        return self.d.model(leg.contract, self.sid, s, self.d.spot_close(self.sid, s), iv)

    def value(self, s) -> float:
        v = self.cash + self.shares * self.d.spot_close(self.sid, s)
        return v + sum(leg.qty * self.option_mark(leg, s) for leg in self.legs)

    # -- trades
    def fill(self, leg: Leg, s, buying: bool) -> float:
        mid = self.option_mid(leg, s)
        dte = (leg.contract[1] - s).days
        h = self.d.haircut_pct(mid, dte, abs(leg.delta or 0.5), self.mult)
        return max(mid * (1 + h), 0.0) if buying else max(mid * (1 - h), 0.0)

    def open_option(self, pick: dict, qty: float, s) -> Leg:
        leg = Leg(pick["contract"], qty, s, 0.0, pick["delta"], pick["iv"])
        price = self.fill(leg, s, buying=qty > 0)
        leg.open_price = price
        self.cash -= qty * price
        if qty < 0:
            self.events["premium"] += -qty * price
        self.legs.append(leg)
        self.events["option_opens"] += 1
        return leg

    def close_option(self, leg: Leg, s, reason: str, price: float | None = None) -> None:
        if price is None:
            price = self.fill(leg, s, buying=leg.qty < 0)
        self.cash += leg.qty * price
        leg.close_date, leg.close_price, leg.close_reason = s, price, reason
        self.legs.remove(leg)
        self.closed.append(leg)

    def buy_shares(self, amount: float, s) -> None:
        px = self.d.stock_fill(self.sid, s)
        n = amount / px
        self.shares += n
        self.cash -= n * px
        self.share_leg = Leg(None, n, s, px)

    def share_change(self, n: float, price: float, s, reason: str) -> None:
        """Shares in (+n, e.g. assignment) or out (−n, e.g. called away) at `price`."""
        self.shares += n
        self.cash -= n * price
        if n > 0:
            self.share_leg = Leg(None, n, s, price)
        elif self.share_leg is not None:
            self.share_leg.close_date, self.share_leg.close_price, self.share_leg.close_reason = s, price, reason
            self.closed.append(self.share_leg)
            self.share_leg = None

    def sell_all_shares(self, s, reason: str) -> None:
        if self.shares:
            self.share_change(-self.shares, self.d.stock_fill(self.sid, s), s, reason)


# ------------------------------------------------------------------ methods
def _short_pick(book: Book, sel, s):
    m, kind = book.m, SHORT_KINDS[book.m["instrument"]]
    target = m["short_delta"] if m["instrument"] == "diagonal" else m["delta"]
    lo, hi = m["short_dte"]
    return book.d.select(book.sid, book.root, sel, s, kind, target, lo, hi, prefer_dte=m.get("short_prefer"))


def _leap_pick(book: Book, sel, s):
    ld = book.m["leap_dte"]
    return book.d.select(book.sid, book.root, sel, s, "C", book.m["delta"], ld["min"], ld["max"],
                         prefer_dte=ld["prefer"], relaxed=True, tolerance=book.m.get("delta_tol"))


def _open_short(book: Book, sel, s) -> bool:
    """Sell the method's short leg at session s; False when no contract qualifies."""
    pick = _short_pick(book, sel, s)
    if pick is None:
        book.events["no_contract"] += 1
        return False
    inst = book.m["instrument"]
    if inst == "csp":
        qty = -book.value_before_open / pick["contract"][3]
    elif inst == "covered_call":
        qty = -book.shares
    else:                                     # diagonal: same share count as the long call
        qty = -sum(leg.qty for leg in book.legs if leg.qty > 0)
    if qty == 0:
        return False
    book.open_option(pick, qty, s)
    return True


def _open_leap(book: Book, sel, s, capital: float) -> bool:
    """Buy the long call with `capital` of the window's value behind it. Sizing (method["sizing"]):
      notional  calls on capital / spot shares (exposure ≈ delta × stock), the rest in T-bills
      delta     calls on capital / (spot × delta) shares (exposure ≈ the stock), the rest in T-bills
      <float>   that fraction of capital spent on calls (1.0 = all in), the rest in T-bills
    """
    pick = _leap_pick(book, sel, s)
    if pick is None:
        book.events["no_contract"] += 1
        return False
    sizing = book.m.get("sizing", "notional")
    spot = book.d.stock_fill(book.sid, s)
    if sizing == "notional":
        qty = capital / spot
    elif sizing == "delta":
        qty = capital / (spot * pick["delta"])
    else:
        price = book.fill(Leg(pick["contract"], 1.0, s, 0.0, pick["delta"], pick["iv"]), s, buying=True)
        if price <= 0:
            book.events["no_contract"] += 1
            return False
        qty = capital * float(sizing) / price
    book.open_option(pick, qty, s)
    return True


def _start(book: Book, sel, s) -> bool:
    """Open the method's position at s (window entry or after a split / called-away re-buy)."""
    inst = book.m["instrument"]
    book.value_before_open = book.cash + book.shares * book.d.spot_mid(book.sid, s)
    if inst == "csp":
        return _open_short(book, sel, s)
    if inst == "covered_call":
        if book.shares == 0:
            book.buy_shares(book.cash, s)
        return _open_short(book, sel, s)
    if inst in ("leap", "diagonal"):
        ok = _open_leap(book, sel, s, book.cash)
        if ok and inst == "diagonal":
            _open_short(book, sel, s)
        elif not ok and book.m.get("fallback") == "stock":
            if not book.shares:
                book.buy_shares(book.cash, s)         # no qualifying call: hold the stock meanwhile
                book.events["stock_fallback"] += 1
            book.on_fallback = True
            return True
        return ok
    raise ValueError(inst)


def _is_expiry_session(expiry: pd.Timestamp, s, nxt) -> bool:
    return s >= expiry or (nxt is not None and nxt > expiry)


def simulate_window(data: OptionData, sid: str, root: str, entry: pd.Timestamp, exit_: pd.Timestamp | None,
                    method: dict, mult: float = 1.0) -> WindowResult:
    sessions = data.sessions
    i0 = sessions.get_loc(entry)
    i1 = sessions.get_loc(exit_) if exit_ is not None else len(sessions) - 1
    splits = set(data.panel.split_factor[sid].iloc[i0:i1 + 1].diff().fillna(0).ne(0).loc[lambda x: x].index)
    split_days = {sessions[sessions.get_loc(d)] for d in splits}

    book = Book(data, sid, root, method, mult)
    book.cash = 1.0
    inst = method["instrument"]
    marks = {}
    pending = True                    # (re)open the position at this session
    rebuy_shares = False
    exit_value = None
    for i in range(i0, i1 + 1):
        s = sessions[i]
        nxt = sessions[i + 1] if i + 1 < len(sessions) else None
        prev = sessions[i - 1]
        if i > i0:
            book.cash *= 1 + data.rate / 252
            if book.shares:
                book.cash += book.shares * data.dividend_on(sid, s)
        is_exit = exit_ is not None and i == i1
        if is_exit:
            for leg in list(book.legs):
                book.close_option(leg, s, "window end")
            book.sell_all_shares(s, "window end")
            exit_value = book.cash
            marks[s] = book.cash
            break
        if nxt is not None and nxt in split_days:             # close everything before a split
            for leg in list(book.legs):
                book.close_option(leg, s, "split")
            book.sell_all_shares(s, "split")
            pending, rebuy_shares = True, False
            marks[s] = book.value(s)
            continue
        if s in split_days:                                   # hold cash over the ex-date
            marks[s] = book.value(s)
            continue
        if pending:
            pending = not _start(book, prev, s)
        elif book.on_fallback and _leap_pick(book, prev, s) is not None:
            book.sell_all_shares(s, "switch to option")   # a qualifying call appeared: swap the stock for it
            book.on_fallback = False
            _start(book, prev, s)
        elif rebuy_shares:
            book.value_before_open = book.cash
            book.buy_shares(book.cash, s)
            rebuy_shares = False
            if not _open_short(book, prev, s):
                pass                                          # retry the call next session
        elif inst in ("csp", "covered_call", "diagonal") and not any(l.qty < 0 for l in book.legs) \
                and not (inst == "csp" and book.shares) \
                and not (inst == "diagonal" and not any(l.qty > 0 for l in book.legs)):
            book.value_before_open = book.cash + book.shares * data.spot_mid(sid, s)
            _open_short(book, prev, s)                        # re-sell after an expiry (or a miss)
        # LEAP roll: re-establish the long call at the window's current value
        for leg in [l for l in book.legs if l.qty > 0]:
            if (leg.contract[1] - s).days < method["leap_dte"]["roll_below"]:
                book.close_option(leg, s, "roll")
                book.events["rolls"] += 1
                capital = book.cash + sum(l.qty * book.option_mark(l, s) for l in book.legs)
                if not _open_leap(book, prev, s, capital):
                    for other in list(book.legs):             # no replacement: flatten, retry next session
                        book.close_option(other, s, "roll")
                    pending = True
        # expiries settle at the close
        close = data.spot_close(sid, s)
        for leg in [l for l in book.legs if _is_expiry_session(l.contract[1], s, nxt)]:
            _, _, kind, strike = leg.contract
            intrinsic = max(close - strike, 0) if kind == "C" else max(strike - close, 0)
            if inst == "csp" and intrinsic > 0:
                book.close_option(leg, s, "assigned", 0.0)
                book.share_change(-leg.qty, strike, s, "assigned")
                book.events["assigned"] += 1
            elif inst == "covered_call" and intrinsic > 0:
                book.close_option(leg, s, "called away", 0.0)
                book.share_change(-min(book.shares, -leg.qty), strike, s, "called away")
                book.events["called_away"] += 1
                rebuy_shares = True
            else:
                book.close_option(leg, s, "expired" if intrinsic == 0 else "expired ITM", intrinsic)
        marks[s] = book.value(s)
    if book.share_leg is not None:
        book.closed.append(book.share_leg)
    return WindowResult(pd.Series(marks), exit_value, book.closed + book.legs, book.events)
