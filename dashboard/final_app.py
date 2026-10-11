from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import folium
import pandas as pd
import plotly.graph_objects as go
import psutil
import streamlit as st
from streamlit_folium import st_folium

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from urbanintel.city import catalog  # noqa: E402
from urbanintel.city.progress import read_status  # noqa: E402

st.set_page_config(page_title="Urban Growth Intelligence", page_icon="🛰️", layout="wide")

INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8984"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"
BASEMAP = ("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/"
           "MapServer/tile/{z}/{y}/{x}")
BASEMAP_ATTR = "Base map: Esri, HERE, Garmin, (c) OpenStreetMap contributors"
UP, DOWN = "#2a78d6", "#e34948"
PLOT_CONFIG = {"displayModeBar": False}
NEWS_MIN = 0.0005
TYPE_LABEL = {
    "metro_rail": ("🚇", "Metro rail"), "suburban_rail_or_station": ("🚆", "Suburban rail or station"),
    "airport": ("✈️", "Airport"), "expressway_or_ring_road": ("🛣️", "Expressway or ring road"),
    "flyover_or_road_widening": ("🌉", "Flyover or road widening"),
    "bus_or_electric_transit": ("🚌", "Buses or electric transit"), "it_park_or_offices": ("🏢", "IT park or offices"),
    "industrial_or_manufacturing": ("🏭", "Industry or manufacturing"), "data_centre": ("🖥️", "Data centre"),
    "retail_or_commercial": ("🛍️", "Retail or commercial"), "housing_or_township": ("🏘️", "Housing or township"),
    "utilities_water_power_sewage": ("💧", "Water, power or sewage"),
    "health_or_education_campus": ("🏥", "Hospital or campus"), "flood_or_disaster": ("🌊", "Flood or disaster"),
    "business_closure_or_layoffs": ("📉", "Closure or layoffs"),
    "environmental_or_construction_restriction": ("🚫", "Construction or pollution restriction"),
    "water_or_power_shortage": ("🚱", "Water or power shortage"), "other": ("📰", "Other development"),
}
BASIS_LABEL = {"reported_fact": "reported fact", "official_decision": "official decision",
               "announcement_or_plan": "announcement or plan",
               "political_claim_or_promise": "political claim (carries no weight)", "opinion": "opinion"}
ICON = {"done": ("✓", GOOD), "running": ("◐", BLUE), "pending": ("○", MUTED),
        "skipped": ("–", MUTED), "failed": ("✕", CRIT)}

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1350px;}
.stage {display:flex; gap:.6rem; align-items:baseline; padding:.28rem 0; border-bottom:1px solid #eeede9;}
.stage .ic {width:1.2rem; font-weight:700; text-align:center;}
.stage .lb {flex:0 0 18rem; color:#0b0b0b;}
.stage .nt {color:#52514e; font-size:.86rem;}
.mod {font-family: ui-monospace, Consolas, monospace; font-size:.82rem; color:#52514e;
      background:#f4f3f0; padding:.15rem .4rem; border-radius:4px;}
.kpi {border:1px solid #e6e5e0; border-radius:8px; padding:.7rem .9rem; background:#fcfcfb;}
.kpi .v {font-size:1.55rem; font-weight:650; color:#0b0b0b; line-height:1.2;}
.kpi .l {font-size:.8rem; color:#52514e;}
.kpi .s {font-size:.78rem; color:#8a8984;}
.note {color:#52514e; font-size:.85rem;}
.ev {border:1px solid #e6e5e0; border-radius:8px; padding:.55rem .75rem; margin-bottom:.5rem; background:#fcfcfb;}
.ev .hd {display:flex; gap:.5rem; align-items:center; color:#0b0b0b; font-weight:600;}
.ev .ln {color:#52514e; font-size:.86rem; margin-top:.15rem;}
.badge {display:inline-block; min-width:2.1rem; text-align:center; color:#ffffff; border-radius:10px;
        padding:.05rem .4rem; font-weight:700; font-size:.78rem;}
[data-testid="stHeaderActionElements"] {display:none;}
.site {display:inline-block; min-width:1.4rem; text-align:center; border:2px solid #0b0b0b; border-radius:50%;
       font-weight:700; font-size:.72rem; color:#0b0b0b; background:#fff;}
</style>""", unsafe_allow_html=True)


def human(n) -> str:
    n = float(n or 0)
    return f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{n / 1e3:.0f} KB"


def mmss(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def kpi(col, value, label, sub=""):
    col.markdown(f"<div class='kpi'><div class='v'>{value}</div><div class='l'>{label}</div>"
                 f"<div class='s'>{sub}</div></div>", unsafe_allow_html=True)


def alive(pid) -> bool:
    try:
        return bool(pid) and psutil.pid_exists(int(pid)) and psutil.Process(int(pid)).is_running()
    except psutil.Error:
        return False


def launch(city: str, *, seeds: int, news: bool, llm: str, estimate: bool, start: str = "start") -> None:
    args = [sys.executable, "-u", "-m", "urbanintel.city.run", "--city", city]
    if estimate:
        args.append("--estimate-only")
    else:
        args += ["--seeds", str(seeds), "--llm", llm, "--from", start] + ([] if news else ["--no-news"])
    d = catalog.city_dir(catalog.resolve(city))
    log = open(d / "process.log", "w", encoding="utf-8")
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
    subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=env,
                     creationflags=flags)


@st.cache_data(show_spinner=False)
def resolve_cached(name: str) -> dict:
    return catalog.resolve(name).as_dict()


# ------------------------------------------------------------------ header
st.markdown("## Urban growth and economic activity intelligence")
st.markdown("<div class='note'>Choose a city. The system finds and downloads the satellite, census-grid "
            "and map data for it, trains the image model on its own history, tests it on a period it "
            "never saw, forecasts urban and economic-activity growth, reads recent development news, "
            "and ranks the zones best placed for a new branch.</div>", unsafe_allow_html=True)
st.write("")

c1, c2, c3, c4 = st.columns([2.2, 1.2, 1.2, 1.4])
names = list(catalog.CITIES) + ["Other Indian city..."]
pick = c1.selectbox("City", names, index=names.index("Bengaluru"))
city_name = c1.text_input("City name", placeholder="e.g. Mysuru") if pick.startswith("Other") else pick
seeds = c2.slider("Model seeds", 1, 5, 5, help="Five independently trained networks are averaged")
news_on = c3.toggle("Development news", value=True)
llm = c3.selectbox("News reader", ["auto", "gemini", "ollama", "claude"], label_visibility="collapsed",
                   disabled=not news_on,
                   help="auto: the free Gemini API if GEMINI_API_KEY is saved, otherwise a local Ollama model")

if not city_name:
    st.stop()
try:
    info = resolve_cached(city_name)
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not resolve '{city_name}': {exc}")
    st.stop()

cdir = catalog.CITIES_ROOT / info["slug"]
status = read_status(cdir / "status.json")
running = bool(status and status.get("state") == "running" and alive(status.get("pid")))

with c4:
    st.write("")
    b1, b2 = st.columns(2)
    if b1.button("Estimate", use_container_width=True, disabled=running,
                 help="Checks archives and counts features; downloads only metadata"):
        launch(city_name, seeds=seeds, news=news_on, llm=llm, estimate=True)
        time.sleep(1.5)
        st.rerun()
    if b2.button("Run", type="primary", use_container_width=True, disabled=running):
        launch(city_name, seeds=seeds, news=news_on, llm=llm, estimate=False)
        time.sleep(1.5)
        st.rerun()
    if (not running and news_on and (cdir / "results" / "results.json").exists()
            and st.button("Refresh news only", use_container_width=True,
                          help="Keeps this city's data, model and economy; re-reads the news")):
        launch(city_name, seeds=seeds, news=True, llm=llm, estimate=False, start="news")
        time.sleep(1.5)
        st.rerun()
    if running and st.button("Stop run", use_container_width=True):
        try:
            p = psutil.Process(int(status["pid"]))
            for ch in p.children(recursive=True):
                ch.kill()
            p.kill()
        except psutil.Error:
            pass
        st.rerun()

st.markdown(f"<div class='note'><b>{info['display']}</b> &middot; study area {info['aoi_km'][0]:.0f} x "
            f"{info['aoi_km'][1]:.0f} km (city boundary plus {info['buffer_km']:.1f} km growth belt) "
            f"&middot; EPSG:{info['utm_epsg']} &middot; OpenStreetMap {info['osm']}</div>",
            unsafe_allow_html=True)


# ------------------------------------------------------------ live progress
@st.fragment(run_every=1.0)
def progress_panel():
    s = read_status(cdir / "status.json")
    if not s:
        st.info("No run yet for this city. Press Estimate to see the data plan and internet use, "
                "then Run.")
        return
    live = s["state"] == "running" and alive(s.get("pid"))
    stages = s["stages"]
    weight = {"download": 3, "train": 5, "news_process": 2}
    tot = sum(weight.get(x["key"], 1) for x in stages if x["state"] != "skipped")
    got = 0.0
    for x in stages:
        w = weight.get(x["key"], 1)
        if x["state"] == "done":
            got += w
        elif x["state"] == "running" and x.get("total"):
            got += w * min(1.0, (x["done"] or 0) / x["total"])
    end = s.get("finished") or (time.time() if live else s.get("updated", time.time()))
    head = {"done": "Finished", "estimated": "Estimate ready", "failed": "Stopped with an error",
            "running": "Running" if live else "Interrupted"}[s["state"]]
    st.markdown(f"**{head}** &middot; {s['city']} &middot; run {s['run_id']} &middot; elapsed "
                f"{mmss(end - s['started'])} &middot; downloaded {human(s['bytes_downloaded'])}"
                + (f" of about {human(s['estimated_bytes'])} estimated" if s.get("estimated_bytes") else ""),
                unsafe_allow_html=True)
    st.progress(min(1.0, got / max(tot, 1)))
    rows = []
    for x in stages:
        state = "failed" if (x["state"] == "running" and not live) else x["state"]
        ic, col = ICON[state]
        note = x.get("note") or ""
        if state == "failed" and x["state"] == "running":
            note = f"stopped during: {x.get('detail') or ''}"
        elif x["state"] == "running":
            frac = f" &middot; {x['done']}/{x['total']} completed" if x.get("total") else ""
            note = f"{x.get('detail') or ''}{frac}"
        dur = ""
        if x.get("started") and x["state"] in ("done", "running", "failed"):
            dur = mmss((x.get("ended") or (time.time() if live else s.get("updated", time.time())))
                       - x["started"])
        rows.append(f"<div class='stage'><span class='ic' style='color:{col}'>{ic}</span>"
                    f"<span class='lb'>{x['label']}</span><span class='nt'>{note}</span>"
                    f"<span class='nt' style='margin-left:auto'>{dur}</span></div>")
    st.markdown("".join(rows), unsafe_allow_html=True)
    cur = next((x for x in stages if x["state"] == "running"), None)
    if cur and live:
        if cur.get("total"):
            st.progress(min(1.0, (cur["done"] or 0) / cur["total"]),
                        text=f"{cur['label']}: {cur['done']}/{cur['total']}")
        if cur.get("module"):
            st.markdown(f"running <span class='mod'>{cur['module']}</span>", unsafe_allow_html=True)
    if s.get("error"):
        st.error(s["error"])
    if s.get("plan_rows"):
        with st.expander("Data plan and internet estimate", expanded=s["state"] == "estimated"):
            df = pd.DataFrame(s["plan_rows"])
            df["estimate"] = df["bytes"].map(human)
            st.dataframe(df[["group", "dataset", "items", "cached", "estimate"]], hide_index=True,
                         use_container_width=True)
            st.caption(f"Total about {human(s['estimated_bytes'])}. Map tiles in this dashboard and "
                       "package installs are not included.")
    with st.expander("Log"):
        st.code("\n".join(s.get("log_tail", [])) or "(empty)", language=None)
    if s["state"] == "done" and st.session_state.get("seen_run") != s["run_id"]:
        st.session_state["seen_run"] = s["run_id"]
        st.rerun()


progress_panel()

res_path = cdir / "results" / "results.json"
if not res_path.exists():
    st.stop()
R = json.loads(res_path.read_text(encoding="utf-8"))
OV = json.loads((cdir / "results" / "overlays.json").read_text(encoding="utf-8"))
st.divider()
data_bytes = (R.get("downloads") or {}).get("bytes", 0)
refresh = (f"refreshed in run {R['run_id']} ({R['runtime_s'] / 60:.0f} min, {human(R['bytes_downloaded'])}) "
           f"from run {R['resumed_from']}; " if R.get("resumed_from") else
           f"run {R['run_id']}, {R['runtime_s'] / 60:.0f} min; ")
st.markdown(f"### Results for {R['city']['name']} <span class='note'>({refresh}data download "
            f"{human(data_bytes)})</span>", unsafe_allow_html=True)


def kind(e: dict) -> tuple[str, str]:
    return TYPE_LABEL.get(e.get("event_type"), TYPE_LABEL["other"])


def strength(v: float) -> str:
    a = abs(v)
    return "strong" if a >= 0.5 else ("moderate" if a >= 0.2 else "mild")


def km_between(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    h = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(h))


def news_effects(located: list[dict], sites: list[dict], *, scale: float, weight: float) -> list[dict]:
    # The same arithmetic as the pipeline: each event fades as exp(-(d/r)^2); the site's change is
    # weight x tanh(sum / scale), shared among events in proportion to their part of the sum
    out = []
    for s_ in sites:
        if "lat" not in s_:
            continue
        terms = [(i, e["impact"] * math.exp(-(km_between(s_["lat"], s_["lon"], e["lat"], e["lon"])
                                                 / e["radius_km"]) ** 2)) for i, e in enumerate(located)]
        total = sum(t for _, t in terms)
        adj = weight * math.tanh(total / scale)
        parts = sorted(((i, adj * t / total) for i, t in terms if total and abs(adj * t / total) >= NEWS_MIN),
                       key=lambda x: -abs(x[1]))
        out.append({**s_, "news_change": adj, "drivers": parts})
    return out


def layout(fig, h=300, title=""):
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=36 if title else 10, b=10),
                      title=dict(text=title, font=dict(size=14, color=INK)), plot_bgcolor="#fcfcfb",
                      paper_bgcolor="#ffffff", font=dict(color=INK2, size=12),
                      legend=dict(orientation="h", y=-0.2), hoverlabel=dict(bgcolor="white"))
    fig.update_xaxes(gridcolor="#eeede9", zeroline=False)
    fig.update_yaxes(gridcolor="#eeede9", zeroline=False)
    return fig


@st.cache_data(show_spinner=False)
def data_uri(path: str) -> str:
    import base64

    # folium treats a plain string as a URL, so the PNG is embedded in the page instead
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def overlay_map(keys: list[str], key: str, markers: list[dict] | None = None):
    avail = [k for k in keys if k in OV]
    if not avail:
        st.caption("No map layer for this section.")
        return
    choice = st.radio("Layer", avail, format_func=lambda k: OV[k]["title"], key=f"r_{key}",
                      horizontal=False, label_visibility="collapsed")
    o = OV[choice]
    (s0, w0), (n0, e0) = o["bounds"]
    # Zoom from the extent: tabs are drawn hidden, where fit_bounds would see a zero-size map
    zoom = int(min(13, max(8, math.floor(math.log2(360.0 / max(e0 - w0, n0 - s0, 1e-3) * 2.2)))))
    m = folium.Map(location=[(s0 + n0) / 2, (w0 + e0) / 2], zoom_start=zoom, control_scale=True,
                   tiles=BASEMAP, attr=BASEMAP_ATTR)
    folium.raster_layers.ImageOverlay(data_uri(str(cdir / "results" / o["file"])), bounds=o["bounds"],
                                      opacity=1.0, interactive=False).add_to(m)
    for mk in markers or []:
        if mk["label"] == "":
            folium.CircleMarker([mk["lat"], mk["lon"]], radius=5, color="#0b0b0b", weight=1,
                                fill=True, fill_color="#ffffff", fill_opacity=0.9,
                                tooltip=mk["tip"]).add_to(m)
            continue
        folium.Marker([mk["lat"], mk["lon"]], tooltip=mk["tip"], icon=folium.DivIcon(
            icon_size=(22, 22), icon_anchor=(11, 11),
            html=(f"<div style='width:22px;height:22px;border-radius:50%;background:#ffffff;"
                  f"border:2px solid #0b0b0b;font:700 11px sans-serif;color:#0b0b0b;display:flex;"
                  f"align-items:center;justify-content:center'>{mk['label']}</div>"))).add_to(m)
    st_folium(m, height=470, use_container_width=True, returned_objects=[], key=f"m_{key}_{choice}")
    if o["kind"] == "categorical":
        st.markdown(" &nbsp; ".join(f"<span style='display:inline-block;width:.8rem;height:.8rem;"
                                    f"background:{c['color']};border:1px solid #bbb;vertical-align:middle'>"
                                    f"</span> {c['label']}" for c in o["classes"]), unsafe_allow_html=True)
    else:
        grad = ", ".join(o["colors"])
        st.markdown(f"<div style='display:flex;align-items:center;gap:.5rem'><span class='note'>"
                    f"{o['vmin']:.2g}</span><div style='flex:0 0 220px;height:10px;background:"
                    f"linear-gradient(90deg,{grad});border:1px solid #ddd'></div><span class='note'>"
                    f"{o['vmax']:.2g}</span></div>", unsafe_allow_html=True)


ev, fc = R.get("evaluation", {}), R.get("forecast", {})
econ, opp, nw = R.get("economy", {}), R.get("opportunity", {}), R.get("news")
tabs = st.tabs(["Overview", "Urban growth", "Economic activity", "News & developments",
                "Expansion opportunities", "Method & data"])

with tabs[0]:
    k = st.columns(5)
    e = ev.get("ensemble", {})
    kpi(k[0], f"{e.get('figure_of_merit', 0):.3f}", "Figure of Merit, held-out 2015-2020",
        f"{ev.get('skill_vs_random')}x random placement")
    kpi(k[1], f"{e.get('auc', 0):.3f}", "AUC (area under the ROC curve), held-out",
        f"{ev.get('conversions', 0):,} cells converted")
    ue = fc.get("urban_extent_km2", {})
    kpi(k[2], f"{ue.get('2025', ue.get(2025, 0)):,.0f} km²", "Urban extent 2025 (prediction)",
        f"from {ue.get('2020', ue.get(2020, 0)):,.0f} km² observed in 2020")
    cg = econ.get("citywide_growth", {})
    kpi(k[3], f"{(cg.get('v22_cagr') or cg.get('v21_cagr') or 0) * 100:+.1f}%/yr",
        "Citywide night-light growth", f"VIIRS {cg.get('v22_span') or cg.get('v21_span')} (activity proxy)")
    has_news = bool(nw and nw.get("events"))
    top = ((opp.get("top_with_news") if has_news else None) or opp.get("top") or [])[:1]
    kpi(k[4], (top[0].get("locality") or f"zone {top[0]['rank']}") if top else "-",
        "Top expansion zone", "with development-news adjustment" if has_news else "satellite and census evidence")
    st.write("")
    a, b = st.columns([1.1, 1])
    with a:
        overlay_map(["opportunity", "forecast", "new_urban_2025", "activity_growth"], "ov",
                    markers=[{"lat": r["lat"], "lon": r["lon"], "label": r["rank"],
                              "tip": f"#{r['rank']} {r.get('locality') or ''}"} for r in opp.get("top", [])[:10]
                             if "lat" in r])
    with b:
        st.markdown("**What the run found**")
        lines = []
        if e:
            lines.append(f"- The image model placed {e['hits']:,} of {ev['conversions']:,} observed conversions "
                         f"correctly on a period it never saw (Figure of Merit {e['figure_of_merit']:.3f}, "
                         f"{ev['skill_vs_random']}x random; logistic regression "
                         f"{ev['logistic_regression']['figure_of_merit']:.3f}).")
        if fc:
            lines.append(f"- About **{fc['new_urban_km2']} km²** of new urban land is predicted by 2025, "
                         f"assuming 2010-2020 growth continues.")
        f = econ.get("forecast", {})
        gb = f.get("models", {}).get("gradient_boosting")
        if gb:
            lines.append(f"- Four-year night-light growth is predictable to a degree: Spearman "
                         f"{gb['spearman_rho']:.2f} on {f['test']}, top-quintile precision "
                         f"{gb['top_quintile_precision']:.2f} against 0.20 by chance.")
        if nw:
            loc_top = sorted([e for e in nw["events"] if e.get("placed") == "located"], key=lambda e: -abs(e["impact"]))
            if loc_top:
                e0 = loc_top[0]
                lines.append(f"- The most influential mapped development: {kind(e0)[0]} {e0['summary']} "
                             f"({e0['location']}, {'raises' if e0['impact'] > 0 else 'lowers'} the outlook within "
                             f"about {e0['radius_km']:g} km). See the News tab for where each development lands.")
            au = nw["audit"]
            check = (f"name-swap neutrality test: same score in {au['score_invariance'] * 100:.0f}% of "
                     f"{au['tested']} re-tests"
                     + (f" against {au['rerun_same_score'] * 100:.0f}% for an unchanged re-read"
                        if au.get("rerun_same_score") is not None else "")
                     if au.get("tested") else "no article named a party, so the name-swap test had "
                     "nothing to re-test")
            lines.append(f"- {len(nw['events'])} development events from {nw['development_articles']} "
                         f"articles ({nw['positive_events']} positive, {nw['negative_events']} negative); "
                         f"{check}.")
        st.markdown("\n".join(lines))
        if opp.get("top"):
            df = pd.DataFrame(opp.get("top_with_news") or opp["top"])[:10]
            cols = [c for c in ["rank", "locality", "score_with_news", "score", "news_adjustment"] if c in df]
            st.dataframe(df[cols], hide_index=True, use_container_width=True)

with tabs[1]:
    a, b = st.columns([1.15, 1])
    with a:
        overlay_map(["test_outcome", "forecast", "new_urban_2025", "urban_change"], "ug")
    with b:
        rows = [{"model": "Image model, ensemble of seeds", "Figure of Merit": e.get("figure_of_merit"),
                 "AUC": e.get("auc"), "kappa": e.get("kappa")}]
        for s_ in ev.get("seeds", []):
            rows.append({"model": f"  seed {s_['seed']} (best epoch {s_['best_epoch']})",
                         "Figure of Merit": s_["figure_of_merit"], "AUC": s_["auc"], "kappa": s_.get("kappa")})
        lr = ev.get("logistic_regression", {})
        rows.append({"model": "Logistic regression, 8 drivers", "Figure of Merit": lr.get("figure_of_merit"),
                     "AUC": lr.get("auc"), "kappa": lr.get("kappa")})
        rows.append({"model": "Random placement", "Figure of Merit": ev.get("random_baseline", {}).get(
            "figure_of_merit"), "AUC": 0.5, "kappa": 0.0})
        st.markdown(f"**Held-out test {ev.get('test_period')}** &middot; trained on "
                    f"{ev.get('design', {}).get('train')}, early stopping on {ev.get('design', {}).get('stop')}")
        st.dataframe(pd.DataFrame(rows).fillna("-"), hide_index=True, use_container_width=True)
        toc = ev.get("toc") or {}
        if toc.get("flagged"):
            n_e, n_o = toc["n_eligible"], toc["n_observed"]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=toc["flagged"], y=toc["hits"], name="image model",
                                     line=dict(color=BLUE, width=2)))
            fig.add_trace(go.Scatter(x=[0, n_e], y=[0, n_o], name="random", line=dict(color=MUTED, dash="dot", width=2)))
            fig.add_trace(go.Scatter(x=[0, n_o, n_e], y=[0, n_o, n_o], name="perfect",
                                     line=dict(color=INK2, dash="dash", width=1)))
            fig.update_xaxes(range=[0, min(n_e, 6 * n_o)], title_text="cells flagged, most suitable first")
            fig.update_yaxes(title_text="conversions found")
            st.plotly_chart(layout(fig, 280, "Total Operating Characteristic (first part of the curve)"),
                            use_container_width=True, config=PLOT_CONFIG)
        ux = fc.get("urban_extent_km2", {})
        if ux:
            yrs = sorted(int(y) for y in ux)
            fig = go.Figure()
            obs = [y for y in yrs if y <= 2020]
            fig.add_trace(go.Scatter(x=obs, y=[ux[str(y)] if str(y) in ux else ux[y] for y in obs],
                                     name="observed (GHSL)", mode="lines+markers", line=dict(color=BLUE, width=2)))
            fig.add_trace(go.Scatter(x=[2020, 2025], y=[ux.get("2020", ux.get(2020)), ux.get("2025", ux.get(2025))],
                                     name="prediction", mode="lines+markers",
                                     line=dict(color=ORANGE, width=2, dash="dash")))
            st.plotly_chart(layout(fig, 240, "Urban extent, km²"), use_container_width=True, config=PLOT_CONFIG)
        sa = fc.get("seed_agreement") or {}
        if sa:
            st.caption(f"Of the cells predicted to urbanise by 2025, {sa.get('majority', 0) * 100:.0f}% are "
                       f"chosen by most seeds. Demand rule: {fc.get('demand_rule')}.")

with tabs[2]:
    a, b = st.columns([1.15, 1])
    with a:
        overlay_map(["activity_growth", "night_lights"], "ec")
        tc = econ.get("trend_classes", {})
        if tc:
            st.caption(f"Lit zones 2013-{econ['years'][-1]}: {tc['faster_than_core']} brightening faster than "
                       f"the established core, {tc['in_step']} in step, {tc['slower_than_core']} slower "
                       f"({tc['rule']}).")
    with b:
        sol = econ.get("sum_of_lights", [])
        if sol:
            fig = go.Figure()
            for prod, colr in (("ANNUAL_V21", BLUE), ("ANNUAL_V22", ORANGE)):
                pts = [r for r in sol if r["product"] == prod]
                fig.add_trace(go.Scatter(x=[r["year"] for r in pts], y=[r["sol"] for r in pts],
                                         name=f"NOAA/VIIRS/DNB/{prod}", mode="lines+markers",
                                         line=dict(color=colr, width=2)))
            st.plotly_chart(layout(fig, 250, "Sum of Lights (radiance x km²); product change marked by colour"),
                            use_container_width=True, config=PLOT_CONFIG)
        f = econ.get("forecast", {})
        if f.get("models"):
            names_ = {"no_change": "No change (baseline)", "trend_extrapolation": "Past trend x 4 (baseline)",
                      "ridge": "Ridge regression", "gradient_boosting": "Gradient boosting (primary)",
                      "gradient_boosting_without_osm": "Gradient boosting without OSM roads/POIs"}
            df = pd.DataFrame([{"model": names_.get(k, k), **v} for k, v in f["models"].items()])
            st.markdown(f"**Four-year growth model** &middot; trained {f['train']}, tested once on {f['test']} "
                        f"({f['zones_test']:,} zones of {econ['grid_m']:.0f} m)")
            df = df.rename(columns={"spearman_rho": "Spearman ρ", "r2": "R²", "mae": "MAE",
                                    "top_quintile_precision": "top-20% precision"})
            st.dataframe(df[["model", "Spearman ρ", "R²", "MAE", "top-20% precision"]],
                         hide_index=True, use_container_width=True)
            st.caption("Top-20% precision: share of the zones predicted to grow most that really were in "
                       "the top fifth; 0.20 by chance. R² near zero with a positive Spearman ρ means the "
                       "model ranks places better than it predicts amounts.")
            dec = pd.DataFrame(f["deciles"])
            fig = go.Figure()
            fig.add_trace(go.Bar(x=dec["decile"], y=dec["observed"], name="observed", marker_color=BLUE))
            fig.add_trace(go.Scatter(x=dec["decile"], y=dec["predicted"], name="predicted",
                                     mode="lines+markers", line=dict(color=ORANGE, width=2)))
            st.plotly_chart(layout(fig, 240, "Held-out growth by predicted decile"), use_container_width=True, config=PLOT_CONFIG)
            st.caption(f["note"])
        pv = econ.get("proxy_validation")
        if pv:
            st.caption(f"Night lights are a proxy for economic activity, not a measurement of it. In this "
                       f"project's own check across {pv['districts']} Uttar Pradesh districts they track "
                       f"Gross District Domestic Product with Spearman {pv['gddp_spearman_rho']} "
                       f"(elasticity {pv['gddp_elasticity']}), and Economic Census 2013 employment across "
                       f"{pv['town_village_units']:,} towns and villages with Spearman "
                       f"{pv['employment_spearman_rho']}.")

with tabs[3]:
    if not nw:
        st.info("The news layer was not run. It needs a language model: save a free Gemini API key as "
                "GEMINI_API_KEY (https://aistudio.google.com/apikey), or start Ollama with a model pulled, "
                "then press Refresh news only.")
    else:
        sc = nw.get("scoring", {})
        scale = float(sc.get("scale", 1.5))
        weight = float((opp.get("news") or {}).get("weight", 0.10))
        located = sorted([e for e in nw["events"] if e.get("placed") == "located"], key=lambda e: -abs(e["impact"]))
        citywide = sorted([e for e in nw["events"] if e.get("placed", "citywide") == "citywide"],
                          key=lambda e: -e["impact"])
        away = [e for e in nw["events"] if e.get("placed") == "elsewhere"]
        sites = [r for r in opp.get("top", [])[:10] if "lat" in r]
        effects = news_effects(located, sites, scale=scale, weight=weight)
        st.markdown(
            f"**{len(located) + len(citywide)} developments** found in {nw['development_articles']} news "
            f"articles (of {nw['unique_articles']} read). **{len(located)}** happen at a place we can map, and "
            f"their effect fades with distance: a metro station reaches about 2 km, an airport about 10 km. "
            f"**{len(citywide)}** concern the whole city. Blue raises a place's outlook, red lowers it. "
            f"News moves a site's score by at most {weight:.2f} on a 0 to 1 scale, and the satellite "
            f"evidence decides the rest.")
        if away:
            st.caption(f"{len(away)} more stories were about other places ("
                       + ", ".join(sorted({e['location'] for e in away})) + ") and score nothing here.")

        a1, b1 = st.columns([1.2, 1])
        with a1:
            st.markdown("##### Where the news lands")
            if located or sites:
                pts = [(e["lat"], e["lon"]) for e in located] + [(r["lat"], r["lon"]) for r in sites]
                lats, lons = [p_[0] for p_ in pts], [p_[1] for p_ in pts]
                # Open on the part of the city that holds the news and the sites, not the whole study area
                ext = max(max(lats) - min(lats), max(lons) - min(lons)) + 0.03
                zoom = int(min(14, max(9, math.floor(math.log2(360.0 / ext * 2.4)))))
                m = folium.Map(location=[(min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2],
                               zoom_start=zoom, tiles=BASEMAP, attr=BASEMAP_ATTR, control_scale=True)
                for i, e in enumerate(located, start=1):
                    col = UP if e["impact"] > 0 else DOWN
                    icon, label = kind(e)
                    links = "".join(f"<li><a href='{x['url']}' target='_blank'>{x['title'][:90]}</a> "
                                    f"<span style='color:#8a8984'>({x['source']}, {x['published']})</span></li>"
                                    for x in e["articles"][:4])
                    pop = (f"<b>N{i} {icon} {label}</b>, {e['status'].replace('_', ' ')}<br>{e['summary']}<br>"
                           f"<i>{e['location']}</i> - reaches about {e['radius_km']:g} km - "
                           f"{strength(e['impact'])} ({e['impact']:+.2f}) - {e['n_sources']} source(s)"
                           f"<ul style='padding-left:1rem;margin:.3rem 0'>{links}</ul>")
                    folium.Circle([e["lat"], e["lon"]], radius=e["radius_km"] * 1000, color=col, weight=1.5,
                                  dash_array="5 4", fill=True, fill_color=col, fill_opacity=0.12,
                                  tooltip=f"N{i}: {e['summary']}").add_to(m)
                    folium.Marker([e["lat"], e["lon"]], tooltip=f"N{i} {label}: {e['summary']}",
                                  popup=folium.Popup(pop, max_width=360),
                                  icon=folium.DivIcon(icon_size=(34, 20), icon_anchor=(17, 10), html=(
                                      f"<div style='background:{col};color:#fff;border-radius:10px;"
                                      f"font:700 11px sans-serif;text-align:center;padding:2px 0;"
                                      f"border:1.5px solid #fff'>N{i}</div>"))).add_to(m)
                for r in sites:
                    folium.Marker([r["lat"], r["lon"]], tooltip=f"Site #{r['rank']} {r.get('locality') or ''}",
                                  icon=folium.DivIcon(icon_size=(22, 22), icon_anchor=(11, 11), html=(
                                      f"<div style='width:22px;height:22px;border-radius:50%;background:#fff;"
                                      f"border:2px solid #0b0b0b;font:700 11px sans-serif;color:#0b0b0b;"
                                      f"display:flex;align-items:center;justify-content:center'>{r['rank']}"
                                      f"</div>"))).add_to(m)
                st_folium(m, height=540, use_container_width=True, returned_objects=[], key="newsmap")
                st.markdown(f"<span class='badge' style='background:{UP}'>N</span> development that raises "
                            f"the outlook &nbsp; <span class='badge' style='background:{DOWN}'>N</span> one that "
                            f"lowers it &nbsp; dashed circle: how far it reaches &nbsp; "
                            f"<span class='site'>1</span> expansion site, by rank", unsafe_allow_html=True)
        with b1:
            st.markdown("##### What each development does")
            if not located:
                st.caption("No development in these articles could be placed on the map.")
            near: dict[int, list[str]] = {}
            for eff in effects:
                for i, v in eff["drivers"]:
                    near.setdefault(i, []).append(f"#{eff['rank']} {eff.get('locality') or ''} ({v:+.3f} to its score)")
            for i, e in enumerate(located, start=1):
                col = UP if e["impact"] > 0 else DOWN
                icon, label = kind(e)
                verb = "raises" if e["impact"] > 0 else "lowers"
                touched = near.get(i - 1, [])
                st.markdown(
                    f"<div class='ev'><div class='hd'><span class='badge' style='background:{col}'>N{i}</span>"
                    f"{icon} {label}, {e['status'].replace('_', ' ')}</div>"
                    f"<div class='ln'><b>{e['location']}</b>: {e['summary']}</div>"
                    f"<div class='ln'>{'▲' if e['impact'] > 0 else '▼'} {verb} the outlook within about "
                    f"{e['radius_km']:g} km ({strength(e['impact'])}, {e['impact']:+.2f}); "
                    f"{e['n_sources']} source(s); {BASIS_LABEL.get(e['basis'], e['basis'])}</div>"
                    f"<div class='ln'>{'Top sites it reaches: ' + ', '.join(touched[:3]) if touched else 'No top-10 site is close enough to feel it.'}</div>"
                    f"</div>", unsafe_allow_html=True)

        st.markdown("##### News about the whole city")
        cni = nw.get("city_news_index")
        if citywide:
            pos = sum(1 for e in citywide if e["impact"] > 0)
            st.markdown(
                f"City news climate **{cni:+.2f}** (from -1 to +1): {pos} of {len(citywide)} citywide "
                f"developments are positive. These shift every part of the city by the same amount, so they "
                f"cannot change which site ranks first, but they matter when comparing one city with another.")
            show = citywide[:12]
            fig = go.Figure(go.Bar(
                x=[e["impact"] for e in show], orientation="h",
                y=[f"{kind(e)[0]} {e['summary'][:70]}" for e in show],
                marker_color=[UP if e["impact"] > 0 else DOWN for e in show],
                customdata=[[kind(e)[1], e["status"].replace("_", " "), e["n_sources"],
                             BASIS_LABEL.get(e["basis"], e["basis"])] for e in show],
                hovertemplate="%{customdata[0]}, %{customdata[1]}<br>effect %{x:+.2f}<br>"
                              "%{customdata[2]} source(s), %{customdata[3]}<extra></extra>"))
            fig.update_yaxes(autorange="reversed", tickfont=dict(size=11))
            fig.update_xaxes(zeroline=True, zerolinecolor="#8a8984", title_text="effect on the city outlook")
            st.plotly_chart(layout(fig, 60 + 34 * len(show)), use_container_width=True, config=PLOT_CONFIG)
        else:
            st.caption("No citywide development was found.")

        st.markdown("##### How the news changes the ranking of the top sites")
        if effects:
            ranked = sorted(effects, key=lambda r: -(r["score"] + r["news_change"]))
            after = {r["rank"]: i for i, r in enumerate(ranked, start=1)}
            rows = []
            for r in effects:
                d = r["drivers"][0] if r["drivers"] else None
                move = r["rank"] - after[r["rank"]]
                rows.append({"site": r["rank"], "place": r.get("locality") or "",
                             "satellite score": round(r["score"], 3),
                             "news change": f"{r['news_change']:+.3f}" if abs(r["news_change"]) >= NEWS_MIN else "none",
                             "score with news": round(r["score"] + r["news_change"], 3),
                             "rank with news": f"{after[r['rank']]} ({'up ' + str(move) if move > 0 else 'down ' + str(-move) if move < 0 else 'same'})",
                             "main reason": (f"N{d[0] + 1} {kind(located[d[0]])[1]} at {located[d[0]]['location']}"
                                             if d else "no mapped news nearby")})
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.caption("Ranks here are among the ten sites shown. Each site's news change is shared among the "
                       "developments near it in proportion to their pull; 'main reason' is the largest.")

        st.markdown("##### How the reading is kept neutral")
        k = st.columns(4)
        au = nw["audit"]
        inv, base = au.get("score_invariance"), au.get("rerun_same_score")
        kpi(k[0], nw["extractor"].split(":", 1)[-1] or "-", "news reader", nw["extractor"].split(":", 1)[0])
        kpi(k[1], f"{nw['positive_events']} / {nw['negative_events']}", "positive / negative developments",
            "same scoring table for both")
        kpi(k[2], "not tested" if inv is None else f"{inv * 100:.0f}%", "same score after party names swapped",
            (f"unchanged re-read {base * 100:.0f}%, {au['tested']} articles" if base is not None
             else f"{au['tested']} articles"))
        kpi(k[3], len(nw.get("evidence_overrides", [])), "labels set to neutral",
            "the article text did not support them")
        st.caption("The language model only fills in a fixed form for each article; it never sets a score. "
                   "Political claims and promises carry zero weight, party names are removed from every "
                   "output, and good and bad news pass the same evidence check.")
        with st.expander("Every article read, with what the model extracted"):
            st.dataframe(pd.DataFrame([{"published": x["published"], "source": x["source"], "title": x["title"],
                                        "development": (x["extraction"] or {}).get("is_development_event"),
                                        "type": kind(x["extraction"] or {})[1] if x["extraction"] else None,
                                        "status": (x["extraction"] or {}).get("status"),
                                        "effect": x["impact"], "url": x["url"]} for x in nw["articles"]]),
                         hide_index=True, use_container_width=True,
                         column_config={"url": st.column_config.LinkColumn("article")})
        if nw.get("evidence_overrides"):
            with st.expander(f"Labels set to neutral by the evidence check ({len(nw['evidence_overrides'])})"):
                st.dataframe(pd.DataFrame(nw["evidence_overrides"]), hide_index=True, use_container_width=True)
        with st.expander("Scoring table and audit details"):
            st.json({"scoring": nw["scoring"], "audit": nw["audit"], "per_query": nw["per_query"],
                     "top_sources": nw["top_sources"], "max_source_share": nw["max_source_share"]})

with tabs[4]:
    a, b = st.columns([1.15, 1])
    top = opp.get("top", [])
    with a:
        overlay_map(["opportunity", "news", "forecast"], "op", markers=[
            {"lat": r["lat"], "lon": r["lon"], "label": r["rank"],
             "tip": f"#{r['rank']} {r.get('locality') or ''} score {r['score']:.3f}"} for r in top[:10] if "lat" in r])
    with b:
        st.markdown(f"**{opp.get('candidates', 0):,} candidate zones of {opp.get('zone_m', 500):.0f} m** "
                    f"&middot; {opp.get('candidate_rule', '')}")
        st.caption("Components (each ranked 0 to 1 among candidates, equal weights): "
                   + "; ".join(f"{k.replace('_', ' ')} = {v}" for k, v in opp.get("components", {}).items()))
        if top:
            df = pd.DataFrame(top)[["rank", "locality", "score", "top10_share_under_random_weights",
                                    "market_now", "activity_now", "activity_growth", "urban_growth", "access"]]
            df = df.rename(columns={"top10_share_under_random_weights": "top-10 under random weights"})
            st.dataframe(df, hide_index=True, use_container_width=True, height=420)
            st.caption("'top-10 under random weights' is the share of 2,000 random weightings of the five "
                       "components in which the zone stays in the top ten: near 1 means the ranking does "
                       "not depend on how the components are weighted.")
        if opp.get("top_with_news") and nw:
            loc_ev = sorted([e for e in nw["events"] if e.get("placed") == "located"], key=lambda e: -abs(e["impact"]))
            eff = news_effects(loc_ev, [r for r in opp["top_with_news"][:10] if "lat" in r],
                               scale=float(nw.get("scoring", {}).get("scale", 1.5)),
                               weight=float((opp.get("news") or {}).get("weight", 0.10)))
            st.markdown("**With the development-news adjustment** (the News tab shows each development on the map)")
            st.dataframe(pd.DataFrame([{
                "rank": r["rank"], "place": r.get("locality") or "", "score with news": r["score_with_news"],
                "news change": f"{r['news_change']:+.3f}" if abs(r["news_change"]) >= NEWS_MIN else "none",
                "main reason": (f"N{r['drivers'][0][0] + 1} {kind(loc_ev[r['drivers'][0][0]])[1]} at "
                                f"{loc_ev[r['drivers'][0][0]]['location']}" if r["drivers"] else "no mapped news nearby")}
                for r in eff]), hide_index=True, use_container_width=True)

with tabs[5]:
    d = ev.get("design", {})
    st.markdown(f"""
**Study area.** {R['aoi']['km'][0]} x {R['aoi']['km'][1]} km around the OpenStreetMap boundary of
{R['city']['name']}, on a 100 m grid in EPSG:{R['aoi']['epsg']} ({R['aoi']['cells']:,} cells). Economic
activity and opportunity are scored on 500 m zones, close to the VIIRS pixel size.

**Urban-growth model.** The Review 4 image model (115,345 parameters, 45 input channels: 30 Landsat
imagery channels and 15 place features) is trained from scratch on this city's own history: weights on
{d.get('train')}, early stopping on {d.get('stop')}, and one score on {d.get('test')}, which it never saw.
Urban means a GHS-BUILT-S built-up fraction of at least 0.20. Five seeds are averaged, and new urban cells
are placed by the same constrained cellular automaton used throughout the project.

**Economic activity.** VIIRS (Visible Infrared Imaging Radiometer Suite) annual night-time radiance,
from NOAA/VIIRS/DNB/ANNUAL_V21 and NOAA/VIIRS/DNB/ANNUAL_V22, is used as a proxy for economic activity. The four-year
growth model predicts change relative to the established core, which removes the citywide
product-version step between ANNUAL_V21 and ANNUAL_V22.

**News.** Headlines and snippets only (no full text is stored). An LLM fills a fixed schema; a fixed
table turns each event into a score. Promises and political claims carry no weight.

**Limits.** GHS-BUILT-S is itself a model product, so accuracy means agreement with GHSL. OpenStreetMap
roads and points of interest are present-day snapshots. The 2025 forecast assumes 2010-2020 growth
continues. The news index is qualitative and not validated against outcomes.
""")
    st.dataframe(pd.DataFrame(R.get("datasets", [])), hide_index=True, use_container_width=True)
    dl = R.get("downloads", {})
    st.caption(f"Downloaded {human(R['bytes_downloaded'])} in this run; optional downloads that failed: "
               f"{', '.join(dl.get('failed', {})) or 'none'}.")
