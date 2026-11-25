"""Learn a carrier's price floor from accepted and declined target prices.

Some carriers now let a shipper name a target price per label. The carrier
checks its spare capacity and either accepts that price or declines, in which
case the contract rate applies. The carrier never says what its lowest price
is, so the savings go to shippers who can work out that floor by lane, day and
package type, label after label.

Same rule as the rest of Sightline: code computes, from outcomes it has seen.
A decline costs the whole discount (the label falls back to contract), so the
learner is a staircase per lane (zone) and weekday: after two accepts in a row
it bids 1% of contract lower; after any decline it steps 2% back up. That
settles just above the floor with a high acceptance rate, and it re-adapts on
its own when capacity changes. A new lane borrows the zone's level until it
has its own history. It never bids at or above the contract price, because a
decline costs nothing extra but an accepted bid above contract would.

``simulate`` compares three strategies on a synthetic carrier whose hidden
floors vary by zone, weekday and weight band: always pay contract, always bid
a fixed 10% below contract, and the learner.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal

CENT = Decimal("0.01")
BANDS = ((1, 2), (3, 5), (6, 10), (11, 20), (21, 150))
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


def band(weight: int) -> str:
    for lo, hi in BANDS:
        if lo <= weight <= hi:
            return f"{lo}-{hi} lb"
    return "150+ lb"


@dataclass(frozen=True)
class Segment:
    service: str
    zone: int
    weekday: str
    band: str

    def parents(self) -> list[tuple]:
        return [(self.service, self.zone, self.weekday, self.band),
                (self.service, self.zone, None, self.band),
                (self.service, self.zone, None, None)]


@dataclass
class Stair:
    level: Decimal          # current bid as a fraction of contract price
    streak: int = 0         # accepts in a row at this level
    n: int = 0


@dataclass
class FloorLearner:
    """Bids as a fraction of each label's contract price, so a lane learns from
    labels of different sizes."""

    opening: Decimal = Decimal("0.90")       # first bid: 10% below contract
    step_down: Decimal = Decimal("0.01")     # after `patience` accepts in a row
    step_up: Decimal = Decimal("0.02")       # after any decline
    patience: int = 2
    warmup: int = 5                          # labels before a lane stops borrowing its zone's level
    stairs: dict[tuple, Stair] = field(default_factory=dict)

    def _keys(self, seg: Segment) -> tuple[tuple, tuple]:
        return (seg.service, seg.zone, seg.weekday), (seg.service, seg.zone)

    def _stair(self, key) -> Stair:
        if key not in self.stairs:
            self.stairs[key] = Stair(self.opening)
        return self.stairs[key]

    def level(self, seg: Segment) -> Decimal:
        lane, zone = self._keys(seg)
        own = self.stairs.get(lane)
        if own is None or own.n < self.warmup:
            return self._stair(zone).level
        return own.level

    def bid(self, seg: Segment, contract_price: Decimal) -> Decimal:
        price = (contract_price * self.level(seg)).quantize(CENT)
        return max(min(price, contract_price - CENT), CENT)   # never at or above contract

    def record(self, seg: Segment, bid: Decimal, contract_price: Decimal, accepted: bool) -> None:
        lane, zone = self._keys(seg)
        for key in (lane, zone):
            st = self._stair(key)
            if key == lane and st.n == 0:
                st.level = self._stair(zone).level   # start where the zone already is
            st.n += 1
            if accepted:
                st.streak += 1
                if st.streak >= self.patience:
                    st.level, st.streak = st.level - self.step_down, 0
            else:
                st.level, st.streak = min(st.level + self.step_up, Decimal("0.99")), 0


# ---------------------------------------------------------------------------
# Simulation on a synthetic carrier
# ---------------------------------------------------------------------------
@dataclass
class Carrier:
    """Hidden floor = contract price x (1 - discount). The discount depends on
    zone and weekday (spare capacity), differs a little by service, and
    wobbles a little label to label. The shipper never sees it."""

    seed: int = 7
    noise: float = 0.01
    _base: dict = field(default_factory=dict)

    def __post_init__(self):
        self.rng = random.Random(self.seed)

    def floor(self, seg: Segment, contract_price: Decimal) -> Decimal:
        key = (seg.service, seg.zone, seg.weekday)
        if key not in self._base:
            spare = {"Mon": 0.03, "Tue": 0.06, "Wed": 0.09, "Thu": 0.07, "Fri": 0.0}[seg.weekday]
            self._base[key] = 0.03 + 0.015 * seg.zone + spare + self.rng.uniform(0, 0.02)
        d = self._base[key] + self.rng.uniform(-self.noise, self.noise)
        return (contract_price * Decimal(str(1 - d))).quantize(CENT)


def simulate(shipments: list[tuple[Segment, Decimal]], labels: int = 3000, seed: int = 7,
             noise: float = 0.01) -> dict:
    """shipments: (segment without weekday, contract price) pairs to sample from."""
    rng = random.Random(seed)
    carrier = Carrier(seed=seed, noise=noise)
    learner = FloorLearner()
    tot = {k: Decimal(0) for k in ("contract", "fixed_10", "learner", "oracle")}
    accepted = {"fixed_10": 0, "learner": 0}
    for _ in range(labels):
        base, contract = rng.choice(shipments)
        seg = Segment(base.service, base.zone, rng.choice(WEEKDAYS), base.band)
        floor = carrier.floor(seg, contract)
        tot["contract"] += contract
        tot["oracle"] += min(floor, contract)
        fixed = (contract * Decimal("0.90")).quantize(CENT)
        ok = fixed >= floor
        accepted["fixed_10"] += ok
        tot["fixed_10"] += fixed if ok else contract
        bid = learner.bid(seg, contract)
        assert bid < contract
        ok = bid >= floor
        accepted["learner"] += ok
        tot["learner"] += bid if ok else contract
        learner.record(seg, bid, contract, ok)
    rows = []
    for name, label in (("contract", "Always pay contract"), ("fixed_10", "Fixed bid 10% below contract"),
                        ("learner", "Floor learner"), ("oracle", "Knew every floor (upper limit)")):
        saved = tot["contract"] - tot[name]
        rows.append({"strategy": label, "paid_usd": tot[name], "saved_usd": saved,
                     "saved_pct": (saved / tot["contract"] * 100).quantize(Decimal("0.1")),
                     "accept_pct": (Decimal(accepted[name]) / labels * 100).quantize(Decimal("0.1"))
                     if name in accepted else None})
    captured = ((tot["contract"] - tot["learner"]) / (tot["contract"] - tot["oracle"]) * 100).quantize(Decimal("0.1"))
    return {"labels": labels, "seed": seed, "rows": rows, "learner_share_of_possible_pct": captured}
