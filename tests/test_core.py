"""Tests for the load-bearing geometry and analysis maths.

Run with:  python -m pytest tests/ -v      (or: python tests/test_core.py)

These target the places where a silent error would corrupt every downstream
number: frame alignment, area conservation under aggregation, and the
expected-activity model that the ghost-growth screen depends on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.analysis import builtup as A_built  # noqa: E402
from urbanintel.analysis import ghost as A_ghost  # noqa: E402
from urbanintel.analysis import nightlights as A_ntl  # noqa: E402
from urbanintel.analysis import zonal as A_zonal  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import ghsl  # noqa: E402

CFG = load_config()
AOI_ = AOI(CFG)


# --------------------------------------------------------------- geometry --

def test_frame_pair_tiles_exactly():
    """The analysis and reporting frames must tile each other exactly.

    Two independent frame() calls do NOT achieve this — each snaps outward to
    its own resolution — and the mismatch silently misaligns every zonal
    aggregate. frame_pair derives one from the other.
    """
    fine, coarse = AOI_.frame_pair(100, 500)
    assert coarse.res / fine.res == 5.0
    assert fine.minx == coarse.minx and fine.maxy == coarse.maxy
    assert fine.width == coarse.width * 5
    assert fine.height == coarse.height * 5
    # a 5x5 block reduce of the fine frame must land exactly on the coarse one
    reduced = A_zonal.block_reduce(np.zeros(fine.shape), 5, "sum")
    assert reduced.shape == coarse.shape


def test_frame_pair_rejects_non_integer_ratio():
    try:
        AOI_.frame_pair(100, 250)
    except ValueError:
        return
    raise AssertionError("expected ValueError for non-integer resolution ratio")


def test_frame_covers_aoi():
    f = AOI_.frame(100)
    minx, miny, maxx, maxy = AOI_.bounds_m
    assert f.minx <= minx and f.miny <= miny
    assert f.maxx >= maxx and f.maxy >= maxy


def test_roundtrip_projection():
    lon, lat = CFG.centre
    x, y = AOI_.to_metres(lon, lat)
    lon2, lat2 = AOI_.to_lonlat(x, y)
    assert abs(lon - lon2) < 1e-9 and abs(lat - lat2) < 1e-9


def test_ghsl_tile_for_varanasi():
    """Varanasi must resolve to a single Mollweide tile, R6_C26."""
    tiles = ghsl.tiles_for_bbox(CFG.bbox)
    assert len(tiles) == 1
    assert str(tiles[0]) == "R6_C26"


# ------------------------------------------------------------ aggregation --

def test_block_reduce_conserves_sum():
    """Extensive quantities must survive 100 m -> 500 m aggregation."""
    rng = np.random.default_rng(0)
    arr = rng.random((20, 25)) * 1000
    out = A_zonal.block_reduce(arr, 5, "sum")
    assert out.shape == (4, 5)
    assert np.isclose(out.sum(), arr.sum())


def test_block_reduce_pads_ragged():
    """A frame not divisible by the factor must not lose its edge."""
    arr = np.ones((7, 8))
    out = A_zonal.block_reduce(arr, 5, "sum")
    assert out.shape == (2, 2)
    assert np.isclose(out.sum(), arr.sum())  # padding is zero for sums


def test_block_reduce_priority_preserves_minority_findings():
    """A findings class must survive aggregation even as a tiny minority.

    Regression: aggregating the typology by `majority` erased every
    ghost-growth cell from the 500 m reporting grid, because findings are by
    nature a minority of cells. `priority` reports the most significant class
    present instead.
    """
    arr = np.zeros((5, 5), dtype=float)
    arr[2, 2] = 4                       # one ghost cell among 24 undeveloped
    maj = A_zonal.block_reduce(arr, 5, "majority", n_classes=5)
    pri = A_zonal.block_reduce(arr, 5, "priority", priority=[4, 5, 3, 2, 1, 0])
    assert maj[0, 0] == 0               # majority erases it
    assert pri[0, 0] == 4               # priority keeps it


def test_block_reduce_priority_respects_order():
    arr = np.zeros((5, 5), dtype=float)
    arr[0, 0] = 2       # healthy
    arr[4, 4] = 4       # ghost — higher priority
    out = A_zonal.block_reduce(arr, 5, "priority", priority=[4, 5, 3, 2, 1, 0])
    assert out[0, 0] == 4


def test_block_reduce_majority():
    arr = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [3, 3, 3, 0], [3, 3, 0, 0]], dtype=float)
    out = A_zonal.block_reduce(arr, 2, "majority", n_classes=4)
    assert out.shape == (2, 2)
    assert out[0, 0] == 1 and out[0, 1] == 2 and out[1, 0] == 3


# ---------------------------------------------------------------- builtup --

def _frame(res=100, h=40, w=40):
    from urbanintel.aoi import AnalysisFrame

    return AnalysisFrame(crs="EPSG:32644", res=res, minx=0, miny=0,
                         maxx=w * res, maxy=h * res, width=w, height=h)


def test_change_detects_new_urban():
    fr = _frame()
    cell = fr.res**2
    b0 = np.zeros(fr.shape, dtype="float32")
    b1 = np.zeros(fr.shape, dtype="float32")
    b1[10:15, 10:15] = 0.5 * cell           # 50% built -> crosses 20%
    chg = A_built.change(b0, b1, fr, year_from=2010, year_to=2025)
    assert chg.new_urban.sum() == 25
    assert np.isclose(chg.total_new_km2, 25 * 0.5 * cell / 1e6)


def test_change_ignores_subthreshold_drift():
    """Noise-level gain in a marginal cell must not count as development."""
    fr = _frame()
    cell = fr.res**2
    b0 = np.full(fr.shape, 0.19 * cell, dtype="float32")
    b1 = np.full(fr.shape, 0.205 * cell, dtype="float32")   # crosses 20% but gains only 150 m2
    chg = A_built.change(b0, b1, fr, year_from=2010, year_to=2025, min_delta_m2=1000)
    assert chg.new_urban.sum() == 0


def test_expansion_form_separates_infill_from_leapfrog():
    fr = _frame(res=100, h=60, w=60)
    cell = fr.res**2
    b0 = np.zeros(fr.shape, dtype="float32")
    b0[5:25, 5:25] = cell                    # a solid existing block
    b1 = b0.copy()
    b1[14:16, 14:16] = cell                  # inside the block (already built)
    b1[25:27, 10:12] = cell                  # attached to the edge
    b1[50:52, 50:52] = cell                  # far away
    chg = A_built.change(b0, b1, fr, year_from=2010, year_to=2025)
    form = A_built.expansion_form(chg, fr, neighbourhood_m=1000)

    assert (form[25:27, 10:12] == A_built.FORM_EDGE).all()
    assert (form[50:52, 50:52] == A_built.FORM_LEAPFROG).all()


# ------------------------------------------------------------ nightlights --

def test_trend_recovers_known_slope():
    stack = {y: np.full((6, 6), 2.0 * (y - 2013) + 1.0, dtype="float32")
             for y in range(2013, 2023)}
    tr = A_ntl.trend(stack)
    assert np.allclose(tr.slope, 2.0, atol=1e-4)
    assert np.allclose(tr.intercept, 1.0 - 2.0 * 2013, atol=1e-2)


def test_trend_flags_significance():
    rng = np.random.default_rng(1)
    years = range(2013, 2025)
    rising = {y: np.full((4, 4), 0.5 * (y - 2013), dtype="float32") for y in years}
    tr = A_ntl.trend(rising)
    assert tr.significant_growth().all()

    flat = {y: rng.normal(5, 0.1, (4, 4)).astype("float32") for y in years}
    tr2 = A_ntl.trend(flat)
    assert not tr2.significant_growth().any()


def test_activity_per_builtup_masks_empty_cells():
    r = np.full((4, 4), 10.0, dtype="float32")
    b = np.zeros((4, 4), dtype="float32")
    b[0, 0] = 100_000
    out = A_ntl.activity_per_builtup(r, b, min_builtup_m2=5000)
    assert np.isfinite(out[0, 0])
    assert np.isnan(out[1, 1])          # would otherwise be a huge ratio


# ------------------------------------------------------------------ ghost --

def test_expected_activity_tracks_builtup():
    """Expected activity must rise with built-up intensity."""
    rng = np.random.default_rng(2)
    n = 4000
    bf = rng.uniform(0.05, 1.0, n).astype("float32")
    act = (bf * 0.8 + rng.normal(0, 0.05, n)).astype("float32")
    exp = A_ghost.expected_activity(act, bf)
    lo = exp[bf < 0.2].mean()
    hi = exp[bf > 0.8].mean()
    assert hi > lo


def test_ghost_flags_builtup_without_activity():
    """A newly built, dark, POI-less block must be flagged; a busy one must not."""
    fr = _frame(res=100, h=60, w=60)
    cell = fr.res**2

    builtup = np.full(fr.shape, 0.6 * cell, dtype="float32")
    ntl = np.full(fr.shape, 30.0, dtype="float32")
    poi = np.full(fr.shape, 8.0, dtype="float32")
    pop = np.full(fr.shape, 400.0, dtype="float32")

    # A dark, empty, newly built block
    ntl[40:50, 40:50] = 0.2
    poi[40:50, 40:50] = 0.0
    pop[40:50, 40:50] = 5.0

    new_frac = np.zeros(fr.shape, dtype="float32")
    new_frac[40:50, 40:50] = 0.5       # newly built
    new_frac[10:20, 10:20] = 0.5       # also newly built, but active

    act = A_ghost.activity_index(builtup, fr, nightlights=ntl,
                                 poi_density=poi, population=pop, smooth_m=0)
    g = A_ghost.analyse(act, builtup / cell, new_frac, fr)

    ghost_core = g.typology[43:47, 43:47]
    active_core = g.typology[13:17, 13:17]
    assert (ghost_core == A_ghost.TYPE_GHOST_GROWTH).all()
    assert (active_core != A_ghost.TYPE_GHOST_GROWTH).all()


def test_ghost_degrades_without_nightlights():
    """Pipeline must still work when Earth Engine is unavailable."""
    fr = _frame(res=100, h=30, w=30)
    cell = fr.res**2
    builtup = np.full(fr.shape, 0.5 * cell, dtype="float32")
    poi = np.full(fr.shape, 3.0, dtype="float32")
    act = A_ghost.activity_index(builtup, fr, poi_density=poi, smooth_m=0)
    assert act.sources == ["poi"]
    assert np.isclose(sum(act.weights.values()), 1.0)


def test_activity_index_requires_a_signal():
    fr = _frame(res=100, h=10, w=10)
    try:
        A_ghost.activity_index(np.ones(fr.shape) * 1e4, fr)
    except ValueError:
        return
    raise AssertionError("expected ValueError with no signals")


# ----------------------------------------------------------- growth model --

def test_change_metrics_confines_all_quadrants_to_eligible():
    """Regression: every confusion quadrant must respect the eligible mask.

    Counting `~predicted & ~observed` over the full array credits the model
    for every already-urban cell it left alone, inflating correct rejections
    and driving overall accuracy toward 1 regardless of skill.
    """
    from urbanintel.analysis import growth_model as GM

    eligible = np.zeros((10, 10), dtype=bool)
    eligible[:5, :] = True                 # only half the array can change
    observed = np.zeros((10, 10), dtype=bool)
    observed[0, :4] = True                 # 4 real conversions
    predicted = np.zeros((10, 10), dtype=bool)
    predicted[0, :2] = True                # 2 correct
    predicted[1, :2] = True                # 2 false alarms

    m = GM.change_metrics(predicted, observed, eligible)
    assert m.hits == 2
    assert m.misses == 2
    assert m.false_alarms == 2
    # Correct rejections must not count the 50 ineligible cells.
    assert m.correct_rejections == 50 - 2 - 2 - 2
    assert m.hits + m.misses + m.false_alarms + m.correct_rejections == int(eligible.sum())


def test_figure_of_merit_formula():
    from urbanintel.analysis import growth_model as GM

    eligible = np.ones((10, 10), dtype=bool)
    observed = np.zeros((10, 10), dtype=bool); observed[0, :10] = True
    predicted = np.zeros((10, 10), dtype=bool); predicted[0, :5] = True; predicted[1, :5] = True
    m = GM.change_metrics(predicted, observed, eligible)
    # hits 5, misses 5, false alarms 5 -> 5/15
    assert abs(m.figure_of_merit - 5 / 15) < 1e-9


def test_allocate_respects_demand_and_skips_urban():
    from urbanintel.analysis import growth_model as GM

    fr = _frame(res=100, h=40, w=40)
    built = np.zeros(fr.shape, dtype="float32")
    built[:10, :10] = 1.0                       # already urban block
    suit = np.random.default_rng(0).random(fr.shape).astype("float32")
    new = GM.allocate(suit, built, 100, fr, urban_threshold=0.20, iterations=4)
    assert new.sum() == 100
    assert not (new & (built >= 0.20)).any()    # never re-converts urban land


def test_extrapolate_demand_positive_for_growing_city():
    from urbanintel.analysis import growth_model as GM

    fr = _frame(res=100, h=50, w=50)
    built = {}
    for i, y in enumerate((2010, 2015, 2020)):
        a = np.zeros(fr.shape, dtype="float32")
        a[: 10 + i * 3, :10] = 1.0              # steadily growing
        built[y] = a
    d = GM.extrapolate_demand(built, fr, target_year=2030)
    assert d > 0


def test_model_learns_a_planted_driver():
    """A synthetic city where conversion depends only on distance."""
    from urbanintel.analysis import growth_model as GM

    fr = _frame(res=100, h=80, w=80)
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:80, 0:80]
    dist = np.sqrt((xx - 40) ** 2 + (yy - 40) ** 2).astype("float32") * 0.1

    t0 = np.zeros(fr.shape, dtype="float32")
    t0[dist < 1.5] = 1.0                         # urban core
    # conversion probability falls off with distance
    p = np.clip(1.0 - (dist - 1.5) / 2.0, 0, 1) * 0.6
    t1 = t0.copy()
    convert = (rng.random(fr.shape) < p) & (t0 < 0.2)
    t1[convert] = 1.0

    X, names = GM.build_drivers(t0, fr, distance_km=dist)
    m = GM.fit(t0, t1, X, names, fr, period=(2010, 2015))
    # Distance to centre must carry a negative weight: nearer converts more.
    assert m.coefficients["distance_centre_km"] < 0
    assert m.auc > 0.7


# ------------------------------------------------------- Review 3 fixes --

def test_config_current_epoch_is_observed():
    """Regression (D1): 'current' must be a measured GHSL epoch, never the 2025 projection."""
    from urbanintel.config import GHSL_LAST_OBSERVED_EPOCH

    CFG.check_epochs()
    assert CFG.epoch_current <= GHSL_LAST_OBSERVED_EPOCH
    assert CFG.epoch_current in CFG.observational_epochs
    assert not set(CFG.observational_epochs) & set(CFG.projected_epochs)


def test_check_epochs_rejects_a_projection():
    import copy

    from urbanintel.config import Config, ConfigError

    bad_current = copy.deepcopy(CFG.raw)
    bad_current["epochs"]["current"] = 2025
    bad_list = copy.deepcopy(CFG.raw)
    bad_list["sources"]["ghsl"]["epochs"] = [2010, 2015, 2020, 2025]
    for raw in (bad_current, bad_list):
        try:
            Config(raw=raw, path=CFG.path).check_epochs()
        except ConfigError:
            continue
        raise AssertionError("a projected epoch used as a measurement must be rejected")


def test_allocate_places_non_divisible_demand_exactly():
    """Regression (D5): demand % iterations cells used to be silently dropped."""
    from urbanintel.analysis import growth_model as GM

    fr = _frame(res=100, h=60, w=60)
    built = np.zeros(fr.shape, dtype="float32")
    suit = np.random.default_rng(1).random(fr.shape).astype("float32")
    for demand in (1214, 7, 101):
        new = GM.allocate(suit, built, demand, fr, iterations=8)
        assert int(new.sum()) == demand, (demand, int(new.sum()))


def test_relative_trend_separates_catching_up_from_citywide_brightening():
    """Regression (D4): when the whole city brightens, a raw positive slope means nothing."""
    shape = (10, 10)
    ref = np.zeros(shape, dtype=bool)
    ref[:5, :] = True                                     # the established city
    stack = {}
    for y in range(2013, 2025):
        a = np.full(shape, 20.0 * 1.06 ** (y - 2013), dtype="float32")   # city +6%/yr
        a[8, 8] = 2.0 * 1.25 ** (y - 2013)                               # catching up fast
        a[9, 9] = 3.0                                                    # flat
        stack[y] = a
    raw = A_ntl.trend(stack)
    rel = A_ntl.relative_trend(stack, ref)
    assert raw.slope[5, 5] > 0 and rel.slope[5, 5] < 1e-3   # brightening only at city pace
    assert rel.slope[8, 8] > 0.05 and rel.p_value[8, 8] < 0.01
    assert raw.slope[9, 9] == 0 and rel.slope[9, 9] < 0     # flat = falling behind the city


def test_relative_trend_cancels_a_scene_wide_step():
    """A version change that lifts every bright cell alike must not look like growth."""
    shape = (10, 10)
    ref = np.zeros(shape, dtype=bool)
    ref[:5, :] = True
    base, stepped = {}, {}
    for y in range(2013, 2025):
        a = np.full(shape, 30.0, dtype="float32")
        a[9, 9] = 20.0 * 1.04 ** (y - 2013)
        base[y] = a
        stepped[y] = a * (1.3 if y >= 2022 else 1.0)       # V2.1 -> V2.2 style step
    r0 = A_ntl.relative_trend(base, ref).slope[9, 9]
    r1 = A_ntl.relative_trend(stepped, ref).slope[9, 9]
    assert abs(float(r1 - r0)) < 0.005


def test_rising_rules_follow_their_definitions():
    s = np.array([0.5, 0.5, -0.2, 0.0])
    p = np.array([0.01, 0.50, 0.01, 0.90])
    ev = A_ghost.TrendEvidence(slope=s, p_value=p, rel_slope=s, rel_p_value=p)
    r, f = A_ghost.rising_masks(ev, "raw")
    assert r.tolist() == [True, True, False, False] and f.tolist() == [False, False, True, True]
    r, f = A_ghost.rising_masks(ev, "relative_significant", alpha=0.10)
    assert r.tolist() == [True, False, False, False]
    assert f.tolist() == [False, False, True, False]    # flat and uncertain is not "declining"


def test_rural_reference_excludes_water_and_recent_building():
    """Regression (D2): the Ganga must not sit in the heat-island rural baseline."""
    fr = _frame(res=100, h=10, w=10)
    built = np.zeros(fr.shape, dtype="float32")
    built[0, :] = 0.5 * fr.res**2                       # urban row
    water = np.zeros(fr.shape, dtype=bool)
    water[5, :] = True
    recent = np.zeros(fr.shape, dtype=bool)
    recent[7, 0] = True
    m = ghsl.rural_reference_mask_from_builtup(built, fr, water=water, exclude=recent)
    assert not m[0].any() and not m[5].any() and not m[7, 0]
    assert m[3].all()


def test_suhi_mean_urban_uses_urban_cells_only():
    """Regression (D3): the old 'mean urban intensity' averaged every warm cell."""
    from urbanintel.analysis import thermal as A_th

    fr = _frame(res=100, h=20, w=20)
    lst = np.full(fr.shape, 40.0, dtype="float32")
    rural = np.zeros(fr.shape, dtype=bool)
    rural[10:, :] = True                                # 200 rural cells at 40 C
    urban = np.zeros(fr.shape, dtype=bool)
    urban[:5, :] = True
    lst[:5, :] = 42.0                                   # urban cells: +2 C
    lst[5:10, :] = 39.0
    lst[5, 0] = 50.0                                    # one hot cell that is not urban
    s = A_th.compute_suhi(lst, rural, year=2024, urban_mask=urban)
    assert abs(s.mean_urban_intensity_c - 2.0) < 1e-6
    assert s.mean_positive_intensity_c > 2.0


def test_built_gain_needs_rise_and_end_level():
    from urbanintel.analysis import vegetation as A_veg

    before = np.array([0.10, 0.10, 0.30, 0.45])
    after = np.array([0.35, 0.20, 0.50, 0.50])
    gain = A_veg.built_gain(before, after, min_rise=0.15, min_end=0.30)
    assert gain.tolist() == [True, False, True, False]


def test_window_mean_uses_only_requested_years():
    stack = {2013: np.full((2, 2), 100.0), 2022: np.full((2, 2), 1.0),
             2023: np.full((2, 2), 2.0), 2024: np.full((2, 2), 6.0)}
    assert np.allclose(A_ntl.window_mean(stack, [2022, 2023, 2024]), 3.0)


def test_random_forest_learns_a_planted_driver():
    """Smoke test: the forest ranks conversions well on a synthetic city."""
    from urbanintel.analysis import growth_model as GM

    fr = _frame(res=100, h=80, w=80)
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:80, 0:80]
    dist = np.sqrt((xx - 40) ** 2 + (yy - 40) ** 2).astype("float32") * 0.1
    t0 = np.zeros(fr.shape, dtype="float32")
    t0[dist < 1.5] = 1.0
    p = np.clip(1.0 - (dist - 1.5) / 2.0, 0, 1) * 0.6
    t1 = t0.copy()
    t1[(rng.random(fr.shape) < p) & (t0 < 0.2)] = 1.0

    X, names = GM.build_drivers(t0, fr, distance_km=dist)
    m = GM.fit_forest(t0, t1, X, names, fr, period=(2010, 2015), n_estimators=50)
    assert m.auc > 0.7                                   # out-of-bag
    s = m.suitability(X, fr.shape)
    assert s.shape == fr.shape and 0.0 <= float(s.min()) and float(s.max()) <= 1.0


def test_toc_curve_of_a_perfect_ranking():
    from urbanintel.analysis import growth_model as GM

    eligible = np.ones(1000, dtype=bool)
    observed = np.zeros(1000, dtype=bool)
    observed[:100] = True
    t = GM.toc_curve(observed.astype(float), observed, eligible, n_points=50)
    assert t["flagged"][-1] == 1000 and t["hits"][-1] == 100
    assert all(h == min(x, 100) for x, h in zip(t["flagged"], t["hits"]))


def test_agreement_kappa_identical_and_independent():
    from urbanintel.analysis import validation as VAL

    rng = np.random.default_rng(0)
    a = rng.random(20000) < 0.3
    b = rng.random(20000) < 0.3
    assert abs(VAL.agreement(a, a)["kappa"] - 1.0) < 1e-9
    assert abs(VAL.agreement(a, b)["kappa"]) < 0.05


def test_mann_whitney_detects_a_shift_in_one_direction():
    from urbanintel.analysis import validation as VAL

    rng = np.random.default_rng(1)
    x, y = rng.normal(1.0, 1.0, 300), rng.normal(0.0, 1.0, 300)
    r = VAL.mann_whitney_greater(x, y)
    assert r["p_value"] < 1e-3 and r["prob_superiority"] > 0.6
    assert VAL.mann_whitney_greater(y, x)["p_value"] > 0.5


def test_loglog_fit_recovers_elasticity():
    from urbanintel.analysis import validation as VAL

    rng = np.random.default_rng(2)
    x = np.exp(rng.normal(0, 1, 500))
    y = 3.0 * x**0.7 * np.exp(rng.normal(0, 0.05, 500))
    assert abs(VAL.loglog_fit(x, y)["elasticity"] - 0.7) < 0.02


def test_local_config_overrides_paths_and_never_touches_the_tracked_file():
    """Each machine can keep its data somewhere else.

    `config/local.yaml` is not tracked by git, so one member's data location
    cannot collide with another member's merge; an environment variable wins
    over both. See scripts/external_data.py.
    """
    import os
    import tempfile

    import yaml

    from urbanintel import config as C

    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "local.yaml"
        out = (Path(tmp) / "out").as_posix()

        local.write_text(yaml.safe_dump({"paths": {"outputs": out}}), encoding="utf-8")
        original = C.LOCAL_CONFIG
        C.LOCAL_CONFIG = local
        try:
            cfg = C.load_config()
            assert cfg.outputs_dir == Path(tmp) / "out"
            assert cfg.city == "Varanasi"          # everything else still comes from the tracked file
        finally:
            C.LOCAL_CONFIG = original

        os.environ["URBANINTEL_OUTPUTS"] = str(Path(tmp) / "from_env")
        try:
            assert load_config().outputs_dir == Path(tmp) / "from_env"
        finally:
            del os.environ["URBANINTEL_OUTPUTS"]


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())
