from __future__ import annotations

import json

import numpy as np
from scipy import ndimage, stats

from ..analysis import nightlights as NL
from ..aoi import AnalysisFrame
from ..config import REPO_ROOT, Config
from .prepare import read, write

HORIZON = 4
TRAIN_ORIGIN = 2016
TEST_ORIGIN = 2020
LIT = 0.5
FEATURES = ["relative_level", "log_level", "past_relative_trend", "builtup_fraction",
            "builtup_growth_5y", "log_population_density", "population_growth_5y",
            "distance_centre_km", "road_km_per_km2", "log_poi_per_km2", "urban_growth_probability",
            "neighbourhood_relative_level"]
STATIC_OSM = ["road_km_per_km2", "log_poi_per_km2"]


def block(arr: np.ndarray, factor: int, how: str = "mean") -> np.ndarray:
    h, w = arr.shape
    a = np.nan_to_num(arr.astype("float64"), nan=0.0).reshape(h // factor, factor, w // factor, factor)
    return (a.sum(axis=(1, 3)) if how == "sum" else a.mean(axis=(1, 3))).astype("float32")


def epoch_at(year: int) -> int:
    return min(2020, (year // 5) * 5)


class Zones:
    def __init__(self, cfg: Config, fine: AnalysisFrame, coarse: AnalysisFrame):
        self.cfg, self.fine, self.coarse = cfg, fine, coarse
        self.f = int(round(coarse.res / fine.res))
        rdir = cfg.processed_dir / "rasters"
        self.rdir = rdir
        self.ntl = {int(p.stem.split("_")[1]): block(read(p), self.f)
                    for p in sorted(rdir.glob("ntl_*.tif"))}
        self.built = {y: block(read(rdir / f"builtup_m2_{y}.tif"), self.f) / fine.res ** 2
                      for y in range(2000, 2021, 5) if (rdir / f"builtup_m2_{y}.tif").exists()}
        km2 = coarse.res ** 2 / 1e6
        self.km2 = km2
        self.pop = {y: block(read(rdir / f"population_{y}.tif"), self.f, "sum") / km2
                    for y in range(2000, 2021, 5) if (rdir / f"population_{y}.tif").exists()}
        self.dist = block(read(rdir / "distance_km.tif"), self.f)
        self.roads = block(read(rdir / "road_density.tif"), self.f, "sum") / 1000.0 / km2
        poi = read(rdir / "poi_density.tif")
        self.poi = block(poi, self.f, "sum") / km2 if poi is not None else np.zeros(coarse.shape, "float32")
        self.urban_prob = {}
        thr = float(cfg.get("thresholds.builtup.surface_fraction_urban"))
        for origin, name in ((2015, "growth_suitability_image_v5_ensemble"),
                             (2020, "growth_forecast_2020_2025")):
            s = read(rdir / f"{name}.tif")
            b = read(rdir / f"builtup_m2_{origin}.tif")
            if s is not None and b is not None:
                elig = (b / fine.res ** 2) < thr
                num = block(np.where(elig, s, 0.0), self.f, "sum")
                den = block(elig.astype("float32"), self.f, "sum")
                self.urban_prob[origin] = np.where(den > 0, num / np.maximum(den, 1), 0.0).astype("float32")
        core = self.built.get(2015, next(iter(self.built.values()))) >= thr
        lit = self.level(2015) >= np.log1p(LIT)
        self.reference = core & lit
        if self.reference.sum() < 30:
            self.reference = self.level(2015) >= np.quantile(self.level(2015), 0.9)

    def level(self, year: int) -> np.ndarray:
        return np.log1p((self.ntl[year - 1] + self.ntl[year]) / 2.0).astype("float32")

    def relative(self, year: int) -> np.ndarray:
        lv = self.level(year)
        return (lv - np.median(lv[self.reference])).astype("float32")

    def relative_series(self, years) -> dict[int, np.ndarray]:
        out = {}
        for y in years:
            lv = np.log1p(self.ntl[y])
            out[y] = (lv - np.median(lv[self.reference])).astype("float32")
        return out

    def features(self, t: int) -> np.ndarray:
        e = epoch_at(t)
        rel = self.relative(t)
        trend = NL.trend(self.relative_series(range(t - 3, t + 1))).slope
        pop_now = self.pop.get(e, np.zeros(self.coarse.shape, "float32"))
        pop_prev = self.pop.get(e - 5, pop_now)
        prob = self.urban_prob.get(e, self.urban_prob.get(2020, np.zeros(self.coarse.shape, "float32")))
        nb = ndimage.uniform_filter(rel, size=3, mode="nearest")
        cols = [rel, self.level(t), trend, self.built[e], self.built[e] - self.built.get(e - 5, self.built[e]),
                np.log1p(pop_now), np.log1p(pop_now) - np.log1p(pop_prev), self.dist, self.roads,
                np.log1p(self.poi), prob, nb]
        return np.stack([np.nan_to_num(c, nan=0.0).ravel() for c in cols], axis=1)

    def target(self, t: int) -> np.ndarray:
        return (self.relative(t + HORIZON) - self.relative(t)).ravel()

    def mask(self, t: int) -> np.ndarray:
        e = epoch_at(t)
        return ((self.level(t) >= np.log1p(LIT)) | (self.built[e] >= 0.05)).ravel()


def _metrics(pred: np.ndarray, obs: np.ndarray) -> dict:
    rho, p = stats.spearmanr(pred, obs)
    ss_res = float(((obs - pred) ** 2).sum())
    ss_tot = float(((obs - obs.mean()) ** 2).sum())
    k = max(1, int(round(0.2 * len(obs))))
    top_p = set(np.argsort(-pred)[:k])
    top_o = set(np.argsort(-obs)[:k])
    return {"spearman_rho": round(float(rho), 4), "spearman_p": float(p),
            "r2": round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None,
            "mae": round(float(np.abs(obs - pred).mean()), 4),
            "top_quintile_precision": round(len(top_p & top_o) / k, 4), "random_expectation": 0.2}


def _models():
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {"gradient_boosting": HistGradientBoostingRegressor(
                max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
                l2_regularization=1.0, random_state=0),
            "ridge": make_pipeline(StandardScaler(), Ridge(alpha=1.0))}


def analyse(cfg: Config, fine: AnalysisFrame, coarse: AnalysisFrame) -> dict:
    z = Zones(cfg, fine, coarse)
    years = sorted(z.ntl)
    last = years[-1]
    cut = int(cfg.get("sources.gee.assets.viirs_annual_legacy_last_year", 2021))
    out: dict = {"grid_m": coarse.res, "zones": int(coarse.width * coarse.height),
                 "years": years, "horizon_years": HORIZON}

    sol = {y: float(z.ntl[y].sum() * z.km2) for y in years}
    lit = {y: round(float((z.ntl[y] >= LIT).mean()), 4) for y in years}
    out["sum_of_lights"] = [{"year": y, "sol": round(sol[y], 1), "lit_share": lit[y],
                             "product": "ANNUAL_V21" if y <= cut else "ANNUAL_V22"} for y in years]
    v21 = [y for y in years if y <= cut]
    v22 = [y for y in years if y > cut]

    def cagr(a, b):
        return round((sol[b] / sol[a]) ** (1 / (b - a)) - 1, 4) if sol[a] > 0 and b > a else None

    out["citywide_growth"] = {"v21_cagr": cagr(v21[0], v21[-1]) if len(v21) > 1 else None,
                              "v21_span": f"{v21[0]}-{v21[-1]}" if v21 else None,
                              "v22_cagr": cagr(v22[0], v22[-1]) if len(v22) > 1 else None,
                              "v22_span": f"{v22[0]}-{v22[-1]}" if len(v22) > 1 else None}

    tr = NL.trend(z.relative_series(years))
    trend_class = np.zeros(coarse.shape, dtype="float32")
    sig = tr.p_value <= 0.10
    trend_class[sig & (tr.slope > 0)] = 1
    trend_class[sig & (tr.slope < 0)] = -1
    active = z.level(last) >= np.log1p(LIT)
    write_coarse = lambda name, arr: write(cfg.processed_dir / "rasters" / f"{name}.tif", arr, coarse)
    write_coarse("econ_relative_trend", np.where(active, tr.slope, np.nan))
    write_coarse("econ_trend_class", np.where(active, trend_class, np.nan))
    write_coarse(f"econ_level_{last}", z.level(last))
    out["trend_classes"] = {"faster_than_core": int(((trend_class == 1) & active).sum()),
                            "in_step": int(((trend_class == 0) & active).sum()),
                            "slower_than_core": int(((trend_class == -1) & active).sum()),
                            "rule": "relative log-radiance trend over all years, p <= 0.10"}

    out["proxy_validation"] = proxy_validation()
    can_validate = (TEST_ORIGIN + HORIZON) <= last and (TRAIN_ORIGIN - 3) >= years[0]
    if not can_validate:
        out["forecast"] = {"skipped": f"needs VIIRS {TRAIN_ORIGIN - 3}-{TEST_ORIGIN + HORIZON}"}
        return out

    Xtr, ytr, mtr = z.features(TRAIN_ORIGIN), z.target(TRAIN_ORIGIN), z.mask(TRAIN_ORIGIN)
    Xte, yte, mte = z.features(TEST_ORIGIN), z.target(TEST_ORIGIN), z.mask(TEST_ORIGIN)
    keep = [i for i, n in enumerate(FEATURES) if n not in STATIC_OSM]
    results, preds = {}, {}
    obs = yte[mte]
    ss_tot = float(((obs - obs.mean()) ** 2).sum())
    # A constant prediction has no ranking, so only its error is defined
    results["no_change"] = {"spearman_rho": None, "r2": round(1 - float((obs ** 2).sum()) / ss_tot, 4),
                            "mae": round(float(np.abs(obs).mean()), 4), "top_quintile_precision": None,
                            "random_expectation": 0.2}
    trend_pred = Xte[mte, FEATURES.index("past_relative_trend")] * HORIZON
    results["trend_extrapolation"] = _metrics(trend_pred, yte[mte])
    for name, model in _models().items():
        model.fit(Xtr[mtr], ytr[mtr])
        preds[name] = model.predict(Xte[mte])
        results[name] = _metrics(preds[name], yte[mte])
    gb = _models()["gradient_boosting"].fit(Xtr[mtr][:, keep], ytr[mtr])
    results["gradient_boosting_without_osm"] = _metrics(gb.predict(Xte[mte][:, keep]), yte[mte])

    deciles = []
    order = np.argsort(preds["gradient_boosting"])
    for d, idx in enumerate(np.array_split(order, 10)):
        deciles.append({"decile": d + 1, "predicted": round(float(preds["gradient_boosting"][idx].mean()), 4),
                        "observed": round(float(yte[mte][idx].mean()), 4)})

    from sklearn.inspection import permutation_importance

    final = _models()["gradient_boosting"]
    final.fit(np.vstack([Xtr[mtr], Xte[mte]]), np.concatenate([ytr[mtr], yte[mte]]))
    imp = permutation_importance(_models()["gradient_boosting"].fit(Xtr[mtr], ytr[mtr]),
                                 Xte[mte], yte[mte], n_repeats=5, random_state=0, scoring="r2")
    importance = sorted(({"feature": n, "importance": round(float(m), 4)}
                         for n, m in zip(FEATURES, imp.importances_mean)), key=lambda r: -r["importance"])

    origin = last
    Xf, mf = z.features(origin), z.mask(origin)
    pred = np.full(coarse.width * coarse.height, np.nan, dtype="float32")
    pred[mf] = final.predict(Xf[mf])
    pred = pred.reshape(coarse.shape)
    write_coarse(f"econ_growth_forecast_{origin}_{origin + HORIZON}", pred)
    out["forecast"] = {
        "target": "change in log night-light radiance over four years, relative to the established core",
        "train": f"{TRAIN_ORIGIN}-{TRAIN_ORIGIN + HORIZON}", "test": f"{TEST_ORIGIN}-{TEST_ORIGIN + HORIZON}",
        "forecast": f"{origin}-{origin + HORIZON}", "zones_train": int(mtr.sum()),
        "zones_test": int(mte.sum()), "zones_forecast": int(mf.sum()), "models": results,
        "deciles": deciles, "importance": importance, "features": FEATURES,
        "primary_model": "gradient_boosting",
        "note": ("The test period crosses the VIIRS product change (ANNUAL_V21 to ANNUAL_V22); differencing "
                 "against the established core each year removes the citywide step. Roads and points of "
                 "interest are a present-day OpenStreetMap snapshot; the without-OSM row shows their effect."),
    }
    return out


def proxy_validation() -> dict | None:
    p = REPO_ROOT / "outputs" / "varanasi_economy_validation.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    g = d.get("districts", {}).get("gddp", {})
    key = sorted(g)[-1] if g else None
    t = d.get("towns_and_villages_2013", {}).get("lights_vs_employment", {})
    return {"districts": d.get("districts", {}).get("n"),
            "gddp_year": key, "gddp_spearman_rho": g[key]["levels"]["spearman_rho"] if key else None,
            "gddp_elasticity": g[key]["levels"]["elasticity"] if key else None,
            "town_village_units": d.get("towns_and_villages_2013", {}).get("n_units"),
            "employment_spearman_rho": t.get("spearman_rho"),
            "scope": "Uttar Pradesh districts (Gross District Domestic Product) and Varanasi-region "
                     "towns and villages (Economic Census 2013 employment, via SHRUG)"}
