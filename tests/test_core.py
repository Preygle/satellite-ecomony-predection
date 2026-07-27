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
