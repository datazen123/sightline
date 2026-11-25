"""Target-price bidding: the learner must stay under contract and beat a fixed bid."""

from decimal import Decimal as D

from corpora.parcel_invoices.floor import FloorLearner, Segment, band, simulate

SEG = Segment("GROUND", 5, "Wed", "3-5 lb")


def test_never_bids_at_or_above_contract():
    fl = FloorLearner()
    for _ in range(50):  # decline everything: the level climbs but must stop under contract
        b = fl.bid(SEG, D("10.00"))
        assert b < D("10.00")
        fl.record(SEG, b, D("10.00"), accepted=False)
    assert fl.bid(SEG, D("10.00")) <= D("9.99")


def test_converges_just_above_a_fixed_floor():
    fl, contract, floor = FloorLearner(), D("20.00"), D("16.40")   # true floor 18% below contract
    paid = []
    for _ in range(80):
        b = fl.bid(SEG, contract)
        ok = b >= floor
        fl.record(SEG, b, contract, ok)
        paid.append(b if ok else contract)
    tail = paid[-30:]
    accepted = [p for p in tail if p < contract]
    assert len(accepted) >= 20                              # mostly accepted once settled
    assert max(accepted) <= floor + D("0.80")               # within ~4% of contract above the floor


def test_readapts_when_capacity_tightens():
    fl, contract = FloorLearner(), D("20.00")
    for floor in (D("16.00"), D("18.60")):                  # floor jumps up halfway (less spare capacity)
        outcomes = []
        for _ in range(60):
            b = fl.bid(SEG, contract)
            ok = b >= floor
            fl.record(SEG, b, contract, ok)
            outcomes.append(ok)
        assert sum(outcomes[-20:]) >= 12                     # back to mostly accepted after the change


def test_new_lane_borrows_its_zone_level():
    fl = FloorLearner()
    for _ in range(10):
        fl.record(SEG, D("17.00"), D("20.00"), accepted=True)
    fresh = Segment("GROUND", 5, "Fri", "3-5 lb")
    assert fl.bid(fresh, D("20.00")) < D("18.00")            # starts from what zone 5 already learned


def test_learner_beats_fixed_discount_in_simulation():
    pool = [(Segment(svc, z, "", band(w)), D(p)) for svc, z, w, p in
            [("GROUND", 2, 3, "9.80"), ("GROUND", 5, 8, "16.40"), ("GROUND", 8, 15, "31.20"),
             ("2DAY", 4, 4, "28.10"), ("NEXTDAY", 6, 2, "61.50")]]
    for seed in (1, 2, 3):
        res = simulate(pool, labels=3000, seed=seed)
        saved = {r["strategy"]: r["saved_usd"] for r in res["rows"]}
        assert saved["Floor learner"] > saved["Fixed bid 10% below contract"]
        assert saved["Floor learner"] < saved["Knew every floor (upper limit)"]
