from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.aoi import AnalysisFrame  # noqa: E402
from urbanintel.deep import analytics as AN  # noqa: E402
from urbanintel.deep import stacks as ST  # noqa: E402
from urbanintel.deep import tiles as TL  # noqa: E402


def frame(res: float = 100.0, w: int = 60, h: int = 50) -> AnalysisFrame:
    return AnalysisFrame(crs="EPSG:32644", res=res, minx=0.0, miny=0.0,
                         maxx=res * w, maxy=res * h, width=w, height=h)


def test_transition_labels_exclude_already_urban():
    b0 = np.array([[0.0, 0.5], [0.1, 0.25]])
    b1 = np.array([[0.3, 0.6], [0.1, 0.9]])
    label, eligible = ST.transition_labels(b0, b1, urban_threshold=0.20)
    assert eligible.tolist() == [[True, False], [True, False]]
    # the cell that crossed the threshold is a conversion; the two cells that
    # were already urban are neither eligible nor labelled
    assert label.tolist() == [[1, 0], [0, 0]]


def test_driver_maps_match_the_tabular_design_matrix():
    f = frame()
    rng = np.random.default_rng(0)
    built = rng.random(f.shape).astype("float32") * 0.4
    dist = rng.random(f.shape).astype("float32") * 10

    from urbanintel.analysis import growth_model as GM

    X, names = GM.build_drivers(built, f, distance_km=dist)
    maps, map_names = ST.driver_maps(built, f, distance_km=dist)
    assert names == map_names
    for i in range(len(names)):
        assert np.allclose(maps[i].ravel(), np.nan_to_num(X[:, i]), atol=1e-5), names[i]


def test_normaliser_uses_only_the_stacks_it_was_fitted_on():
    f = frame()
    a = ST.TemporalStack(np.ones((1, 2, f.height, f.width), dtype="float32"),
                         ["x", "y"], [2010], "drivers")
    a.data[0, 1] *= 3.0
    n = ST.Normaliser.fit([a])
    out = n.apply(a).data
    assert np.allclose(n.mean, [1.0, 3.0])
    # constant channels have zero spread, which must not divide by zero
    assert np.all(np.isfinite(out))


def test_tile_origins_cover_the_right_and_bottom_edges():
    o = TL.tile_origins((50, 60), size=32, stride=16)
    assert (0, 0) in o
    assert max(r for r, _ in o) == 50 - 32
    assert max(c for _, c in o) == 60 - 32


def test_validation_tiles_never_touch_training_tiles():
    shape = (50, 60)
    f = frame()
    ids = TL.block_ids(shape, f, block_m=1600.0)          # 16-cell blocks
    val_mask, _ = TL.block_split(ids, val_fraction=0.3, seed=1)
    origins = TL.tile_origins(shape, size=8, stride=4)
    tr = TL.select_origins(origins, 8, val_mask, want="train")
    va = TL.select_origins(origins, 8, val_mask, want="val")
    assert tr and va
    assert not (set(tr) & set(va))
    covered = np.zeros(shape, dtype=bool)
    for r, c in tr:
        covered[r:r + 8, c:c + 8] = True
    # not one training pixel may sit inside a validation block
    assert not (covered & val_mask).any()


def test_block_folds_are_disjoint_and_complete():
    ids = TL.block_ids((50, 60), frame(), block_m=1000.0)
    folds = TL.block_folds(ids, n_folds=5, seed=0)
    total = np.zeros((50, 60), dtype=int)
    for f_ in folds:
        total += f_.astype(int)
    assert total.max() == 1 and total.min() == 1


def test_dihedral_is_reversible_and_keeps_the_label_aligned():
    x = np.arange(2 * 3 * 4 * 4, dtype="float32").reshape(2, 3, 4, 4)
    y = np.zeros((4, 4), dtype="uint8")
    y[0, 3] = 1
    m = np.ones((4, 4), dtype=bool)
    for k in range(8):
        xa, ya, ma = TL.dihedral(x, y, m, k)
        assert xa.shape == x.shape and ya.shape == y.shape and ma.all()
        assert int(ya.sum()) == 1
        # the marked pixel must follow the same corner of the input
        pos = np.argwhere(ya == 1)[0]
        assert xa[0, 0][tuple(pos)] == x[0, 0][0, 3]


def test_cell_lookup_assigns_every_pixel_to_one_cell():
    cells = frame(res=100.0, w=6, h=5)
    pixels = frame(res=50.0, w=12, h=10)
    lut = TL.cell_lookup(pixels, cells)
    assert lut.shape == pixels.shape
    counts = np.bincount(lut.ravel(), minlength=cells.width * cells.height)
    assert counts.min() == 4 and counts.max() == 4          # 2 x 2 pixels per cell


def test_aggregate_to_cells_averages_pixels():
    cells = frame(res=100.0, w=3, h=2)
    pixels = frame(res=50.0, w=6, h=4)
    lut = TL.cell_lookup(pixels, cells)
    vals = np.arange(24, dtype="float32").reshape(4, 6)
    out = TL.aggregate_to_cells(vals, lut, cells)
    assert out.shape == cells.shape
    assert np.isclose(out[0, 0], np.mean([vals[0, 0], vals[0, 1], vals[1, 0], vals[1, 1]]))


def test_rank_only_allocation_takes_exactly_the_demand():
    score = np.linspace(0, 1, 100).reshape(10, 10)
    eligible = np.ones((10, 10), dtype=bool)
    eligible[0] = False
    observed = np.zeros((10, 10), dtype=bool)
    observed[9, -3:] = True
    m = AN.rank_only_allocation(score, observed, eligible, demand=5)
    assert m["hits"] + m["false_alarms"] == 5
    assert m["hits"] == 3                                  # the top five include all three


def test_precision_at_k_and_random_baseline_agree_on_the_base_rate():
    rng = np.random.default_rng(0)
    eligible = np.ones((100, 100), dtype=bool)
    observed = rng.random((100, 100)) < 0.01
    score = rng.random((100, 100))                         # no skill
    rows = AN.precision_at_k(score, observed, eligible, fractions=(0.1,))
    base = AN.random_allocation_baseline(observed, eligible, n_draws=5)
    assert abs(rows[0]["precision"] - observed.mean()) < 0.01
    assert base["demand"] == int(observed.sum())


def test_calibration_is_perfect_when_the_probability_is_the_truth():
    rng = np.random.default_rng(0)
    p = rng.random(20000) * 0.4
    obs = rng.random(20000) < p
    out = AN.calibration(p.reshape(200, 100), obs.reshape(200, 100),
                         np.ones((200, 100), dtype=bool))
    assert out["expected_calibration_error"] < 0.02


def test_symmetry_keeps_feature_maps_and_labels_aligned():
    a = np.zeros((2, 4, 4), dtype="float32")
    a[:, 0, 3] = 1.0
    y = np.zeros((4, 4), dtype="uint8")
    y[0, 3] = 1
    for k in range(8):
        fa, fy = TL.symmetry([a, y], k)
        assert fa.shape == a.shape and fy.shape == y.shape
        # the marked corner must land in the same place in both
        assert tuple(np.argwhere(fa[0] == 1.0)[0]) == tuple(np.argwhere(fy == 1)[0])


def test_tiles_cut_lazily_and_match_a_manual_slice():
    f = frame(res=100.0, w=64, h=64)
    rng = np.random.default_rng(0)
    stack = ST.TemporalStack(rng.random((1, 3, 64, 64)).astype("float32"),
                             ["a", "b", "c"], [2010], "drivers")
    label = np.zeros((64, 64), dtype="uint8")
    label[10:12, 10:12] = 1
    elig = np.ones((64, 64), dtype=bool)
    tr = TL.Transition(stack, label, elig, (2010, 2015))
    origins = TL.tile_origins(f.shape, 16, 16)
    tiles = TL.build_tiles([tr], origins, size=16)

    assert len(tiles) == len(origins)
    x, y, m = tiles.get(0)
    r, c = origins[0]
    assert np.array_equal(x, stack.data[:, :, r:r + 16, c:c + 16])
    assert np.array_equal(y, label[r:r + 16, c:c + 16])
    # only the tiles holding the marked cells are upweighted
    w = tiles.sample_weights(oversample=4.0)
    assert set(np.unique(w)) <= {1.0, 4.0}
    assert int((w == 4.0).sum()) == int(sum(
        1 for (rr, cc) in origins if label[rr:rr + 16, cc:cc + 16].any()))


def test_tiles_index_every_transition():
    f = frame(res=100.0, w=32, h=32)
    def make(year):
        stack = ST.TemporalStack(np.zeros((1, 2, 32, 32), dtype="float32"),
                                 ["a", "b"], [year], "drivers")
        return TL.Transition(stack, np.zeros((32, 32), dtype="uint8"),
                             np.ones((32, 32), dtype=bool), (year, year + 5))
    origins = TL.tile_origins(f.shape, 16, 16)
    tiles = TL.build_tiles([make(2005), make(2010)], origins, size=16)
    assert len(tiles) == 2 * len(origins)
    assert set(tiles.periods) == {(2005, 2010), (2010, 2015)}


def test_prithvi_position_encoding_is_deterministic_and_sized():
    from urbanintel.deep.prithvi import sincos_3d

    pos = sincos_3d(1024, (2, 14, 14))
    assert pos.shape == (2 * 14 * 14, 1024)
    assert np.allclose(pos, sincos_3d(1024, (2, 14, 14)))
    # the encoding has to distinguish positions, or the transformer cannot
    # tell one patch from another
    assert not np.allclose(pos[0], pos[1])


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
