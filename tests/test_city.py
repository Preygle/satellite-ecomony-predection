from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pyproj import Transformer  # noqa: E402

from urbanintel.aoi import AnalysisFrame  # noqa: E402
from urbanintel.city import economy as EC  # noqa: E402
from urbanintel.city import fetch as F  # noqa: E402
from urbanintel.city import llm as L  # noqa: E402
from urbanintel.city import model as M  # noqa: E402
from urbanintel.city import news as N  # noqa: E402
from urbanintel.city import opportunity as OP  # noqa: E402
from urbanintel.city.catalog import City  # noqa: E402
from urbanintel.city.progress import Status, read_status  # noqa: E402


def city(lon=77.2, lat=28.6, box=(76.84, 28.40, 77.35, 28.88)) -> City:
    return City(name="Delhi", display="Delhi, India", lon=lon, lat=lat, boundary=box,
                osm="relation/1", kind="city")


def frame(w=530, h=470) -> AnalysisFrame:
    return AnalysisFrame(crs="EPSG:32643", res=100.0, minx=700_000.0, miny=3_140_000.0,
                         maxx=700_000.0 + 100 * w, maxy=3_140_000.0 + 100 * h, width=w, height=h)


def test_utm_zone_follows_longitude_and_hemisphere():
    assert city().utm_epsg == 32643
    assert city(lon=82.97, lat=25.3).utm_epsg == 32644
    assert city(lon=-46.6, lat=-23.5).utm_epsg == 32723


def test_buffer_is_clamped_and_large_areas_are_cropped():
    small = city(box=(76.70, 30.66, 76.85, 30.80))
    assert small.buffer_km() == 3.0
    big = city(box=(76.0, 28.0, 78.0, 29.6))
    assert big.buffer_km() == 8.0
    w, h = big.aoi_km()
    assert w <= 80.5 and h <= 80.5


def test_frame_tiles_cover_every_cell_exactly_once():
    fr = frame(530, 470)
    hits = np.zeros(fr.shape, dtype=int)
    for r0, c0, h, w in F.frame_tiles(fr):
        hits[r0:r0 + h, c0:c0 + w] += 1
    assert hits.min() == 1 and hits.max() == 1


def test_ghsl_window_contains_the_whole_frame():
    fr = frame()
    tr, w, h = F.ghsl_window(fr)
    t = Transformer.from_crs(fr.crs, F.MOLLWEIDE, always_xy=True)
    x0, y1 = tr[2], tr[5]
    x1, y0 = x0 + 100 * w, y1 - 100 * h
    for x, y in [(fr.minx, fr.miny), (fr.minx, fr.maxy), (fr.maxx, fr.miny), (fr.maxx, fr.maxy)]:
        mx, my = t.transform(x, y)
        assert x0 < mx < x1 and y0 < my < y1
    # The window sits on the 100 m GHSL grid
    assert (x0 - F.GHSL_ORIGIN[0]) % 100 == 0 and (F.GHSL_ORIGIN[1] - y1) % 100 == 0


def test_estimate_counts_only_what_is_not_cached():
    with tempfile.TemporaryDirectory() as d:
        have = Path(d) / "a.tif"
        have.write_bytes(b"x")
        items = [F.Item("a", "A", "X/1", "g", 1000, have, True),
                 F.Item("b", "B", "X/2", "g", 2000, Path(d) / "b.tif", True)]
        est = F.estimate(items)
        assert est["cached"] == 1
        assert est["total_bytes"] == 2000 + F.EE_OVERHEAD
        assert "X/1" in est["rows"][0]["dataset"] and "X/2" in est["rows"][0]["dataset"]


def test_trainer_epoch_lines_are_parsed():
    m = M.EPOCH_LINE.search("  epoch  86/250   loss 0.0406   stop AP 0.4541   1.5s")
    assert m and m.group(1) == "86" and m.group(2) == "250" and m.group(4) == "0.4541"


def ext(**kw):
    base = {"is_development_event": True, "event_type": "metro_rail", "direction": "positive",
            "status": "under_construction", "basis": "official_decision", "scope": "locality",
            "location": "Sector 5", "expected_completion_year": 0, "summary": "metro line"}
    base.update(kw)
    return base


def test_setbacks_score_negative_whatever_the_model_says():
    assert N.impact(ext(status="delayed", direction="positive"), 0) < 0
    assert N.impact(ext(status="cancelled", direction="neutral"), 0) < 0


def test_political_claims_carry_no_weight():
    assert N.impact(ext(basis="political_claim_or_promise"), 0) == 0.0
    assert N.impact(ext(is_development_event=False), 0) == 0.0


def test_recency_halves_after_the_half_life():
    a, b = N.impact(ext(), 0), N.impact(ext(), N.HALF_LIFE_MONTHS)
    assert abs(b / a - 0.5) < 1e-9


def test_scoring_is_symmetric_for_good_and_bad_news():
    up = N.impact(ext(event_type="industrial_or_manufacturing", status="completed"), 3)
    down = N.impact(ext(event_type="industrial_or_manufacturing", status="completed",
                        direction="negative"), 3)
    assert up == -down


def test_party_names_are_redacted_and_ordinary_words_kept():
    out, flagged = N.redact("BJP and AAP both welcome the Delhi metro; Congress Party too")
    assert flagged and "BJP" not in out and "AAP" not in out and "metro" in out
    assert N.redact("New flyover opens in Sector 62")[1] is False


def test_corroboration_rewards_independent_sources():
    now = datetime.now(timezone.utc)
    pub = (now - timedelta(days=30)).isoformat()

    def row(src):
        return {"article": {"title": f"Metro work in Sector 5 {src}", "source": src, "url": f"https://{src}/x",
                            "published": pub, "snippet": "", "query": "metro", "retrieval": "t"},
                "extraction": ext(), "error": None}

    one = N.cluster_events([row("a")], now)
    two = N.cluster_events([row("a"), row("b")], now)
    assert len(two) == 1 and two[0]["n_sources"] == 2
    assert two[0]["impact"] > one[0]["impact"]


def test_metrics_perfect_ranking():
    obs = np.linspace(-1, 1, 100)
    m = EC._metrics(obs.copy(), obs)
    assert m["spearman_rho"] == 1.0 and m["top_quintile_precision"] == 1.0 and m["r2"] == 1.0


def test_block_aggregation():
    a = np.arange(100, dtype="float32").reshape(10, 10)
    assert EC.block(a, 5, "sum").sum() == a.sum()
    assert EC.block(a, 5).shape == (2, 2)


def test_rank_normalisation_bounds():
    v = np.random.default_rng(0).random((20, 20))
    mask = v > 0.3
    r = OP._rank(v, mask)
    assert np.nanmin(r) == 0.0 and np.nanmax(r) == 1.0 and np.isnan(r[~mask]).all()


def test_listed_sites_are_spaced_apart():
    fr = AnalysisFrame(crs="EPSG:32643", res=500.0, minx=0.0, miny=0.0, maxx=10_000.0, maxy=10_000.0,
                       width=20, height=20)
    v = np.random.default_rng(1).random((20, 20))
    picks = OP.spaced(v, fr, 10, spacing_m=1500.0)
    rc = [divmod(i, 20) for i in picks]
    for i, (a, b) in enumerate(rc):
        for c, d in rc[i + 1:]:
            assert ((a - c) ** 2 + (b - d) ** 2) ** 0.5 * 500 >= 1500
    assert picks[0] == int(np.argmax(v))


def test_gemini_schema_is_the_openapi_subset():
    g = L.to_gemini_schema(N.SCHEMA)
    assert g["type"] == "OBJECT" and "additionalProperties" not in g
    assert g["properties"]["event_type"]["type"] == "STRING"
    assert g["properties"]["event_type"]["enum"] == N.EVENT_TYPES
    assert g["propertyOrdering"] == list(N.SCHEMA["properties"]) and g["required"] == N.SCHEMA["required"]


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload
        self.text = json.dumps(payload)
        self.content = self.text.encode()
        self.request = type("R", (), {"body": b"{}"})()

    def json(self):
        return self._p


def _gemini(models):
    g = L.GeminiExtractor.__new__(L.GeminiExtractor)
    g.key, g.models, g.model = "k", models, models[0]
    g.exhausted, g.no_thinking, g.next_slot = set(), set(), {}
    g.lock = __import__("threading").Lock()
    g.payload_bytes, g.calls = 0, 0
    return g


def test_gemini_settings_follow_the_model_family():
    g = _gemini(["gemini-3.8-flash", "gemini-2.5-flash"])
    b3 = g.body("gemini-3.8-flash", "sys", "user", N.SCHEMA)["generationConfig"]
    b2 = g.body("gemini-2.5-flash", "sys", "user", N.SCHEMA)["generationConfig"]
    assert "temperature" not in b3 and b3["thinkingConfig"] == {"thinkingLevel": "low"}
    assert b2["temperature"] == 0 and "thinkingConfig" not in b2
    assert b3["responseMimeType"] == "application/json"


def test_gemini_retries_then_moves_to_the_next_model_on_daily_quota():
    g = _gemini(["gemini-3.8-flash", "gemini-3.6-flash"])
    ok = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(ext())}]}}]}
    replies = [_Resp(429, {"error": {"message": "Quota exceeded for GenerateRequestsPerDayPerProjectPerModel"}}),
               _Resp(429, {"error": {"details": [{"retryDelay": "0s"}]}}), _Resp(200, ok)]
    used = []
    real_post, real_sleep = L.requests.post, L.time.sleep

    def post(url, **kw):
        used.append(url.rsplit("/", 1)[1].split(":")[0])
        return replies.pop(0)

    L.requests.post, L.time.sleep = post, (lambda s: None)
    old_rpm = L.GEMINI_RPM
    L.GEMINI_RPM = 1e9
    try:
        out = g.extract("sys", "user", N.SCHEMA)
    finally:
        L.requests.post, L.time.sleep, L.GEMINI_RPM = real_post, real_sleep, old_rpm
    assert out["event_type"] == "metro_rail"
    assert used == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.6-flash"]
    assert g.exhausted == {"gemini-3.8-flash"}


def test_audit_separates_swap_effect_from_rerun_noise():
    class Fixed:
        def extract(self, system, user, schema):
            return ext()

    now = datetime.now(timezone.utc).isoformat()
    rows = [{"article": {"title": "BJP opens Sector 5 metro station", "source": "s", "url": "u",
                         "published": now, "snippet": "", "query": "q", "retrieval": "t"},
             "extraction": ext(), "error": None}]
    a = N.counterfactual_audit(rows, "Delhi", Fixed())
    assert a["tested"] == 1 and a["score_invariance"] == 1.0 and a["rerun_same_score"] == 1.0


def test_status_round_trip():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "status.json"
        s = Status(p, city="X", run_id="r")
        s.begin("download", total=45, module="m")
        s.update("download", advance=3, detail="Landsat 2015")
        s.add_bytes(1234)
        s.write(force=True)
        got = read_status(p)
        dl = next(x for x in got["stages"] if x["key"] == "download")
        assert dl["done"] == 3 and dl["total"] == 45 and got["bytes_downloaded"] == 1234
        s.end("download")
        s.finish("done")
        assert json.loads(p.read_text())["state"] == "done"


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
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
