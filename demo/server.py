"""Live demo of the Varanasi urban-growth system, served from this laptop.

    python demo/server.py            then open http://127.0.0.1:8765
    run_demo.bat                     does both
    python demo/server.py --port 9000 --no-browser

Runs offline, on the data the analysis pipeline has already processed. Three
things happen live when the page asks for them:

1. the growth model is trained on 2010-2015, tested on 2015-2020 and used to
   predict 2025 and 2030 - logistic regression or random forest, with or
   without the road driver (a 300-tree forest takes about 6 s);
2. the ghost-growth typology is re-classified under any of the four
   definitions of "activity rising" (under a second);
3. maps of the inputs and of every result are drawn from the rasters.

Only the Python standard library serves the page; no web framework is needed.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import warnings
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import matplotlib  # noqa: E402
import rasterio  # noqa: E402

from run_growth_model import random_baseline  # noqa: E402
from urbanintel.analysis import ghost as GH  # noqa: E402
from urbanintel.analysis import growth_model as GM  # noqa: E402
from urbanintel.aoi import AOI  # noqa: E402
from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import gee  # noqa: E402

HERE = Path(__file__).resolve().parent
ZONES = ROOT / "docs" / "figures" / "zones"
HOST, PORT = "127.0.0.1", 8765

# Map colours: the same palette as the report figures.
GREY = "#c3c2b7"
FORM_COLOURS = {1: "#2a78d6", 2: "#1baf7a", 3: "#eb6834"}          # infill, edge, leapfrog
TEST_COLOURS = {"hit": "#0ca30c", "miss": "#2a78d6", "false_alarm": "#eb6834"}
PRED_COLOURS = {2025: "#eda100", 2030: "#d03b3b"}
TYPE_COLOURS = dict(GH.TYPE_COLOURS)
TYPE_COLOURS[GH.TYPE_UNDEVELOPED] = "#ffffff"

DRIVER_LABELS = {
    "distance_centre_km": "Distance to city centre",
    "neighbourhood_built_500m": "Built-up within 500 m",
    "neighbourhood_built_1500m": "Built-up within 1.5 km",
    "distance_to_urban_edge_km": "Distance to urban edge",
    "road_density": "Road density",
    "population_density": "Population",
    "builtup_fraction": "Built-up fraction",
    "slope_deg": "Terrain slope",
}
RULE_LABELS = {
    "raw": "Light trend above zero (Review 2 rule)",
    "significant": "Light rising, statistically significant",
    "relative": "Light rising faster than the city",
    "relative_significant": "Rising faster than the city, significant (Review 3 rule)",
}
MODEL_LABELS = {"random_forest": "Random forest", "logistic_regression": "Logistic regression"}


# ------------------------------------------------------------------ images ---

def rgb_of(colour: str) -> np.ndarray:
    return np.array([int(colour[i:i + 2], 16) for i in (1, 3, 5)], dtype="uint8")


def blank(shape) -> np.ndarray:
    return np.full(tuple(shape) + (3,), 255, dtype="uint8")


def paint(rgb: np.ndarray, mask: np.ndarray, colour: str) -> np.ndarray:
    rgb[mask] = rgb_of(colour)
    return rgb


def shade(arr, cmap: str, lo: float, hi: float, show=None) -> np.ndarray:
    """Continuous layer through a colour map; cells outside `show` stay white."""
    a = np.nan_to_num(np.asarray(arr, dtype="float64"), nan=lo)
    t = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
    rgb = (matplotlib.colormaps[cmap](t)[..., :3] * 255).astype("uint8")
    if show is not None:
        rgb[~show] = 255
    return rgb


def categorical(codes, colours: dict) -> np.ndarray:
    c = np.nan_to_num(np.asarray(codes, dtype="float64")).astype(int)
    rgb = blank(c.shape)
    for k, colour in colours.items():
        rgb[c == k] = rgb_of(colour)
    return rgb


def png(rgb: np.ndarray, scale: int = 2) -> bytes:
    im = Image.fromarray(rgb, "RGB")
    im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# -------------------------------------------------------------------- demo ---

class Demo:
    """Everything the page needs, loaded once at start-up."""

    def __init__(self) -> None:
        t = time.time()
        cfg = self.cfg = load_config()
        cfg.check_epochs()
        self.frame, _ = AOI(cfg).frame_pair(cfg.get("sources.ghsl.resolution_m"), cfg.cell_size_m)
        self.rdir = cfg.processed_dir / "rasters"
        self.years = [int(y) for y in cfg.observational_epochs]          # 2010, 2015, 2020
        base, cur = self.years[0], self.years[-1]

        needed = ([f"builtup_m2_{y}" for y in self.years] + [f"population_{y}" for y in self.years]
                  + ["distance_km", "road_density", "expansion_form", "nightlights_level",
                     "suhi_intensity", "poi_density", "nightlights_slope", "nightlights_pvalue",
                     "nightlights_rel_slope", "nightlights_rel_pvalue", f"builtup_frac_{cur}",
                     "builtup_delta_frac", "typology"])
        missing = [n for n in needed if not (self.rdir / f"{n}.tif").exists()]
        if missing:
            raise SystemExit(
                "Missing processed rasters: " + ", ".join(missing) + "\n"
                "Run the analysis pipeline first (python -m urbanintel.pipeline), or copy in "
                "the data bundle (python scripts/external_data.py import <folder>).")

        cell = self.frame.res ** 2
        self.cell_km2 = cell / 1e6
        self.thr = float(cfg.get("thresholds.builtup.surface_fraction_urban"))
        self.built = {y: self.read(f"builtup_m2_{y}") / cell for y in self.years}
        self.pop = {y: self.read(f"population_{y}") for y in self.years}
        self.dist = self.read("distance_km")
        self.roads = self.read("road_density")
        sp = cfg.raw_dir / "gee" / "slope.tif"
        self.slope = np.nan_to_num(gee.to_frame(sp, self.frame), nan=0.0) if sp.exists() else None

        # Inputs of the ghost-growth screen, built exactly as the pipeline builds them.
        self.activity = GH.activity_index(
            self.read(f"builtup_m2_{cur}"), self.frame,
            nightlights=self.read("nightlights_level"),
            poi_density=self.read("poi_density"),
            population=self.pop[cur],
            min_builtup_m2=cfg.get("grid.min_builtup_fraction_for_analysis") * cell)
        self.evidence = GH.TrendEvidence(
            slope=self.read("nightlights_slope"), p_value=self.read("nightlights_pvalue"),
            rel_slope=self.read("nightlights_rel_slope"),
            rel_p_value=self.read("nightlights_rel_pvalue"))
        self.frac_now = self.read(f"builtup_frac_{cur}")
        self.new_frac = np.clip(self.read("builtup_delta_frac"), 0, None)

        def gg(key, default=None):
            return cfg.get(f"thresholds.ghost_growth.{key}", default)

        self.ghost_kw = dict(min_new_share=gg("min_new_share"),
                             min_new_builtup_frac=gg("min_new_builtup_fraction"),
                             residual_percentile=gg("max_activity_percentile"),
                             urban_threshold=self.thr)
        self.alpha = float(gg("trend_alpha", 0.10))
        self.zone_kw = dict(min_area_km2=gg("zone_min_area_km2", 0.25),
                            neighbourhood_m=gg("zone_neighbourhood_m", 600.0),
                            density_ratio=gg("zone_density_ratio", 2.0))
        self.default_rule = gg("trend_rule", "relative_significant")

        zp = ZONES / "index.json"
        self.zones = json.loads(zp.read_text(encoding="utf-8")) if zp.exists() else []
        self.maps: dict[str, bytes] = {}
        self.lock = threading.Lock()
        self._overview(base, cur)
        self.load_s = round(time.time() - t, 1)

    def read(self, name: str) -> np.ndarray:
        with rasterio.open(self.rdir / f"{name}.tif") as ds:
            return ds.read(1)

    # ---- the maps and numbers shown before anything is run -----------------
    def _overview(self, base: int, cur: int) -> None:
        b = self.built
        urban = {y: b[y] >= self.thr for y in self.years}
        form = np.nan_to_num(self.read("expansion_form")).astype(int)
        typ = self.read("typology")

        self.maps["built"] = png(shade(b[cur], "Greys", 0.0, 1.0, show=b[cur] > 0.005))
        rgb = paint(blank(form.shape), urban[base], GREY)
        for k, colour in FORM_COLOURS.items():
            paint(rgb, form == k, colour)
        self.maps["growth"] = png(rgb)
        lights = np.log1p(np.clip(np.nan_to_num(self.read("nightlights_level")), 0, None))
        self.maps["lights"] = png(shade(lights, "inferno", 0.0, float(np.percentile(lights, 99.5))))
        heat = self.read("suhi_intensity")
        self.maps["heat"] = png(shade(heat, "RdBu_r", -6.0, 6.0, show=np.isfinite(heat)))
        self.maps["typology"] = png(categorical(typ, TYPE_COLOURS))

        u0, u1 = int(urban[base].sum()), int(urban[cur].sum())
        n_form = {k: int((form == k).sum()) for k in FORM_COLOURS}
        n_new = sum(n_form.values()) or 1
        ty = np.nan_to_num(typ).astype(int)
        self.overview = {
            "built_km2": {y: round(float(np.nansum(b[y])) * self.cell_km2, 2) for y in self.years},
            "urban_km2": {y: round(int(urban[y].sum()) * self.cell_km2, 2) for y in self.years},
            "urban_growth_pct_per_year": round(((u1 / u0) ** (1 / (cur - base)) - 1) * 100, 2),
            "new_urban_km2": round(n_new * self.cell_km2, 2),
            "form_pct": {"infill": round(100 * n_form[1] / n_new, 1),
                         "edge": round(100 * n_form[2] / n_new, 1),
                         "leapfrog": round(100 * n_form[3] / n_new, 1)},
            "ghost_km2": round(int((ty == GH.TYPE_GHOST_GROWTH).sum()) * self.cell_km2, 2),
            "emerging_km2": round(int((ty == GH.TYPE_EMERGING).sum()) * self.cell_km2, 2),
        }

    def info(self) -> dict:
        h, w = self.frame.shape
        return {
            "load_s": self.load_s,
            "grid": {"rows": h, "cols": w, "cell_m": round(self.frame.res),
                     "area_km2": round(h * w * self.cell_km2)},
            "years": self.years,
            "has_slope": self.slope is not None,
            "overview": self.overview,
            "zones": self.zones,
            "rules": RULE_LABELS,
            "default_rule": self.default_rule,
        }

    # ---- live: growth model -------------------------------------------------
    def drivers(self, year: int, roads: bool):
        return GM.build_drivers(self.built[year], self.frame, distance_km=self.dist,
                                road_density=self.roads if roads else None,
                                population=self.pop[year], slope=self.slope,
                                urban_threshold=self.thr)

    def run_model(self, kind: str, roads: bool, trees: int) -> dict:
        (t0, t1, t2) = self.years
        start = time.time()
        log: list[str] = []

        def note(msg: str) -> None:
            log.append(f"{time.time() - start:5.1f} s   {msg}")

        X_tr, names = self.drivers(t0, roads)
        X_te, _ = self.drivers(t1, roads)
        note(f"Measured {len(names)} drivers for all {X_tr.shape[0]:,} grid cells, "
             f"in {t0} (training) and {t1} (test).")
        if kind == "logistic_regression":
            m = GM.fit(self.built[t0], self.built[t1], X_tr, names, self.frame,
                       period=(t0, t1), urban_threshold=self.thr)
        else:
            m = GM.fit_forest(self.built[t0], self.built[t1], X_tr, names, self.frame,
                              period=(t0, t1), urban_threshold=self.thr, n_estimators=trees)
        note(f"Trained {MODEL_LABELS[kind].lower()} on the {m.n_train_total:,} cells that were "
             f"not urban in {t0}; {m.n_train_positive:,} of them became urban by {t1}.")

        _, pred, obs, elig = GM.validate(m, self.built, X_te, self.frame, test=(t1, t2),
                                         urban_threshold=self.thr)
        v = m.validation
        demand = int(obs.sum())
        note(f"Tested on {t1}-{t2}, which the model never saw: placed the {demand:,} cells that "
             f"really converted; {v.hits:,} landed in the right place.")
        base = random_baseline(obs, elig)
        note(f"Random placement of the same {demand:,} cells, 20 draws: "
             f"{base['mean_hits']} right on average.")

        demands = {y: GM.extrapolate_demand(self.built, self.frame, target_year=y,
                                            urban_threshold=self.thr) for y in (2025, 2030)}
        steps = GM.project_steps(m, self.built[t2], self.frame, demands=demands,
                                 distance_km=self.dist,
                                 road_density=self.roads if roads else None,
                                 population=self.pop[t2], slope=self.slope,
                                 urban_threshold=self.thr)
        note(f"Predicted {demands[2025]:,} new urban cells by 2025 and {demands[2030]:,} by 2030, "
             f"in two five-year steps from {t2}.")

        # Maps: suitability now, the test, the prediction.
        urban_now = self.built[t2] >= self.thr
        suit_now = steps[2025][0]
        rgb = shade(suit_now, "YlOrRd", 0.0, 1.0, show=~urban_now)
        self.maps["suit"] = png(paint(rgb, urban_now, GREY))
        rgb = paint(blank(obs.shape), self.built[t1] >= self.thr, GREY)
        paint(rgb, obs & pred, TEST_COLOURS["hit"])
        paint(rgb, obs & ~pred, TEST_COLOURS["miss"])
        paint(rgb, pred & ~obs, TEST_COLOURS["false_alarm"])
        self.maps["test"] = png(rgb)
        new25, new30 = steps[2025][1], steps[2030][1]
        rgb = paint(blank(obs.shape), urban_now, GREY)
        paint(rgb, new30 & ~new25, PRED_COLOURS[2030])
        paint(rgb, new25, PRED_COLOURS[2025])
        self.maps["pred"] = png(rgb)
        note("Drew the three maps.")

        if kind == "logistic_regression":
            imp_title = "Weight of each driver (per standard deviation; + raises the chance)"
            imp = {n: round(float(c), 3) for n, c in m.coefficients.items()}
        else:
            imp_title = "Importance of each driver (share of the forest's splitting gain)"
            imp = {n: round(float(x), 3) for n, x in zip(names, m.estimator.feature_importances_)}
        rf = kind == "random_forest"
        return {
            "model": MODEL_LABELS[kind],
            "roads": roads,
            "trees": trees if rf else None,
            "drivers": [DRIVER_LABELS.get(n, n) for n in names],
            "train_period": f"{t0}-{t1}",
            "test_period": f"{t1}-{t2}",
            "train_cells": m.n_train_total,
            "train_positive": m.n_train_positive,
            "auc_train": round(m.auc, 3),
            "auc_train_kind": "out-of-bag" if rf else "on the training cells",
            "auc_test": round(m.test_auc, 3),
            "demand": demand,
            "hits": v.hits,
            "misses": v.misses,
            "false_alarms": v.false_alarms,
            "figure_of_merit": round(v.figure_of_merit, 4),
            "producers_accuracy": round(v.producers_accuracy * 100, 1),
            "kappa": round(v.kappa, 3),
            "overall_accuracy": round(v.overall_accuracy * 100, 1),
            "null_accuracy": round(v.null_overall_accuracy * 100, 1),
            "random_hits": base["mean_hits"],
            "random_fom": base["mean_figure_of_merit"],
            "skill": (round(v.figure_of_merit / base["mean_figure_of_merit"], 1)
                      if base["mean_figure_of_merit"] else None),
            "demand_2025": demands[2025],
            "demand_2030": demands[2030],
            "pred_2025_km2": round(int(new25.sum()) * self.cell_km2, 2),
            "pred_2030_km2": round(int(new30.sum()) * self.cell_km2, 2),
            "importance_title": imp_title,
            "importance": [[DRIVER_LABELS.get(n, n), x] for n, x in
                           sorted(imp.items(), key=lambda kv: -abs(kv[1]))],
            "log": log,
            "seconds": round(time.time() - start, 1),
        }

    # ---- live: ghost-growth typology ----------------------------------------
    def classify(self, rule: str) -> dict:
        if rule not in GH.RISING_RULES:
            raise ValueError(f"unknown rule {rule!r}")
        start = time.time()
        g = GH.analyse(self.activity, self.frac_now, self.new_frac, self.frame,
                       activity_trend=self.evidence, rising_rule=rule, trend_alpha=self.alpha,
                       **self.ghost_kw)
        _, zones = GH.cluster_zones(g, self.frame, **self.zone_kw)
        areas = g.areas_km2(self.frame)
        cand = areas["emerging"] + areas["ghost_growth"]
        self.maps["rule"] = png(categorical(g.typology, TYPE_COLOURS))
        return {
            "rule": rule,
            "rule_label": RULE_LABELS[rule],
            "areas": {k: round(v, 2) for k, v in areas.items()},
            "candidates_km2": round(cand, 2),
            "filling_up_pct": round(100 * areas["emerging"] / cand, 1) if cand else None,
            "n_zones": len(zones),
            "seconds": round(time.time() - start, 2),
        }


DEMO: Demo | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):        # keep the console quiet during the talk
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0]
        if path in ("/", "/index.html"):
            return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/info":
            return self._json(DEMO.info())
        if path.startswith("/map/") and path.endswith(".png"):
            data = DEMO.maps.get(path[len("/map/"):-len(".png")])
            if data is None:
                return self._json({"error": "That map has not been made yet."}, 404)
            return self._send(200, data, "image/png")
        if path.startswith("/zone/") and path.endswith(".png"):
            try:
                n = int(path[len("/zone/"):-len(".png")])
            except ValueError:
                return self._json({"error": "bad zone number"}, 400)
            p = ZONES / f"zone_{n:02d}.png"
            if not p.exists():
                return self._json({"error": "no evidence card for that zone"}, 404)
            return self._send(200, p.read_bytes(), "image/png")
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/api/model", "/api/typology"):
            return self._json({"error": "not found"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "The request body must be JSON."}, 400)
        if not DEMO.lock.acquire(blocking=False):
            return self._json({"error": "Another run is still going. Wait for it to finish."}, 409)
        try:
            if path == "/api/model":
                kind = body.get("model", "random_forest")
                if kind not in MODEL_LABELS:
                    return self._json({"error": f"unknown model {kind!r}"}, 400)
                trees = min(max(int(body.get("trees", 300)), 10), 1000)
                out = DEMO.run_model(kind, bool(body.get("roads", True)), trees)
            else:
                out = DEMO.classify(body.get("rule", DEMO.default_rule))
            return self._json(out)
        except Exception as exc:                  # show the reason on the page
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        finally:
            DEMO.lock.release()


def main() -> int:
    global DEMO
    port = PORT
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    print("Loading the processed rasters ...")
    DEMO = Demo()
    h, w = DEMO.frame.shape
    print(f"Loaded in {DEMO.load_s} s: {h} x {w} cells of {DEMO.frame.res:.0f} m, "
          f"slope driver {'available' if DEMO.slope is not None else 'missing'}.")
    url = f"http://{HOST}:{port}/"
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(f"Demo running at {url}   (close this window or press Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
