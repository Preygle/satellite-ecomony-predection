"""Urban Growth & Economic Activity Intelligence — dashboard.

    streamlit run dashboard/app.py

Reads the pipeline's outputs (grid GeoJSON + summary JSON); it does not
recompute anything, so it starts instantly and stays honest about what the
pipeline actually produced — including what it had to skip.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from urbanintel.analysis.ghost import TYPE_COLOURS, TYPE_LABELS  # noqa: E402
from urbanintel.config import load_config  # noqa: E402

# --------------------------------------------------------------------------
# Design tokens — from the validated reference palette.
# --------------------------------------------------------------------------
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"

SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#104281"]
DIVERGING = ["#104281", "#3987e5", "#9ec5f4", "#f0efec", "#eda100", "#d03b3b", "#8a1f1f"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "critical": "#d03b3b"}

st.set_page_config(
    page_title="Urban Growth Intelligence",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2rem; max-width: 1500px; }}
      [data-testid="stMetricValue"] {{ font-size: 1.9rem; }}
      .ui-caption {{ color: {INK_MUTED}; font-size: 0.82rem; line-height: 1.45; }}
      .legend-row {{ display:flex; align-items:center; gap:8px; margin:3px 0;
                     font-size:0.85rem; color:{INK_SECONDARY}; }}
      .legend-sw {{ width:14px; height:14px; border-radius:3px;
                    border:1px solid rgba(11,11,11,0.10); flex:none; }}
      .finding {{ border-left:3px solid {STATUS['critical']}; padding:8px 14px;
                  background:rgba(208,59,59,0.05); margin:6px 0; border-radius:0 4px 4px 0; }}
      .note {{ border-left:3px solid {GRIDLINE}; padding:8px 14px;
               background:rgba(0,0,0,0.02); margin:6px 0; border-radius:0 4px 4px 0;
               font-size:0.86rem; color:{INK_SECONDARY}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
def outputs_stamp(slug: str, outputs_dir: str) -> float:
    """Newest mtime across the pipeline outputs, or 0.0 if none exist.

    Passed into ``load_outputs`` purely to take part in its cache key. Without
    it the key is ``(slug, outputs_dir)``, neither of which changes when the
    pipeline re-runs — so a dashboard left open serves the previous run's
    summary indefinitely and no amount of reloading corrects it. That is how a
    stale "Needs Earth Engine" notice survived a run in which Earth Engine had
    in fact produced every layer.
    """
    out = Path(outputs_dir)
    stamps = [p.stat().st_mtime
              for p in (out / f"{slug}_summary.json", out / f"{slug}_grid.geojson")
              if p.exists()]
    return max(stamps) if stamps else 0.0


@st.cache_data(show_spinner=False)
def load_outputs(slug: str, outputs_dir: str, stamp: float):  # noqa: ARG001
    # `stamp` is deliberately unused in the body — it exists to invalidate the
    # cache when the outputs change. Do not remove it as a dead parameter.
    out = Path(outputs_dir)
    summary_p = out / f"{slug}_summary.json"
    grid_p = out / f"{slug}_grid.geojson"
    if not summary_p.exists():
        return None, None
    summary = json.loads(summary_p.read_text(encoding="utf-8"))
    gdf = None
    if grid_p.exists():
        import geopandas as gpd

        gdf = gpd.read_file(grid_p)
    return summary, gdf


MODEL_LAYERS = ("growth_suitability", "pred_new_urban_2025", "pred_new_urban_2030")


def model_stamp(rdir: str) -> float:
    """Newest mtime of the growth-model rasters — keys the cache like outputs_stamp."""
    ps = [Path(rdir) / f"{n}.tif" for n in MODEL_LAYERS]
    return max((p.stat().st_mtime for p in ps if p.exists()), default=0.0)


@st.cache_data(show_spinner=False)
def model_layers(rdir: str, factor: int, stamp: float):  # noqa: ARG001
    """Growth-model rasters (100 m) averaged onto the 500 m reporting grid.

    The pipeline's grid does not carry them: the growth model runs after the
    pipeline, as its own script. `stamp` only keys the cache.
    """
    import rasterio

    from urbanintel.analysis.zonal import block_reduce

    out = {}
    for name in MODEL_LAYERS:
        p = Path(rdir) / f"{name}.tif"
        if p.exists():
            with rasterio.open(p) as ds:
                out[name] = block_reduce(ds.read(1).astype("float64"), factor, "mean")
    return out


def load_json(name: str) -> dict:
    p = cfg.outputs_dir / f"{cfg.city_slug}_{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


cfg = load_config()
summary, gdf = load_outputs(cfg.city_slug, str(cfg.outputs_dir),
                            outputs_stamp(cfg.city_slug, str(cfg.outputs_dir)))
if summary is not None and gdf is not None and {"row", "col"} <= set(gdf.columns):
    _rdir = str(cfg.processed_dir / "rasters")
    _factor = int(round(summary["aoi"]["reporting_res_m"] / summary["aoi"]["analysis_res_m"]))
    for _name, _arr in model_layers(_rdir, _factor, model_stamp(_rdir)).items():
        _r = gdf["row"].astype(int).clip(0, _arr.shape[0] - 1).to_numpy()
        _c = gdf["col"].astype(int).clip(0, _arr.shape[1] - 1).to_numpy()
        gdf[_name] = _arr[_r, _c]
GM = load_json("growth_model")
TV = load_json("typology_validation")
CC = load_json("cross_checks")
PV = load_json("population_validation")
EV = load_json("economy_validation")
FIGDIR = ROOT / "docs" / "figures"

if summary is None:
    st.title("Urban Growth & Economic Activity Intelligence")
    st.error("No pipeline output found.")
    st.code("python -m urbanintel.pipeline --no-gee", language="bash")
    st.caption(f"Expected: {cfg.outputs_dir / (cfg.city_slug + '_summary.json')}")
    st.stop()

stats = summary.get("stats", {})
skipped = summary.get("skipped", {})
B = stats.get("builtup", {})
G = stats.get("ghost", {})
V = stats.get("vegetation", {})
T = stats.get("thermal", {})
N = stats.get("nightlights", {})

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.title(f"{summary['city']} — Urban Growth & Economic Activity")
period = B.get("period", "")
_ep = summary.get("epochs", {})
st.markdown(
    f"<div class='ui-caption'>Observed epochs "
    f"{', '.join(str(y) for y in _ep.get('observational', B.get('epochs', [])))} &middot; "
    f"{summary['aoi']['area_km2']} km² AOI &middot; "
    f"analysis {summary['aoi']['analysis_res_m']} m, reporting {summary['aoi']['reporting_res_m']} m "
    f"&middot; generated {summary['generated'][:10]}</div>",
    unsafe_allow_html=True,
)
st.write("")

# ---- headline stat row ----------------------------------------------------
# Every headline figure comes from observed GHSL epochs. GHSL 2025 is the
# GHSL model's own projection and appears only where labelled as such.
c1, c2, c3, c4, c5 = st.columns(5)
built = B.get("built_surface_km2", {})
epochs = B.get("epochs", [])
if epochs:
    y0, y1 = str(min(epochs)), str(max(epochs))
    b0, b1 = built.get(y0, 0), built.get(y1, 0)
    c1.metric(f"Built-up surface {y1} (observed)", f"{b1:,.1f} km²",
              f"{b1 - b0:+,.1f} km² since {y0}")
pop = B.get("population_total", {})
if pop and epochs:
    p0, p1 = pop.get(y0, 0), pop.get(y1, 0)
    c2.metric(f"Population {y1} (GHS-POP)", f"{p1/1e6:,.2f} M",
              f"{(p1 - p0)/1e3:+,.0f} k since {y0}",
              help="GHS-POP is 10% above the 2011 Census for Varanasi district; WorldPop "
                   "shows faster growth. See the Validation tab.")
c3.metric("Urban extent growth", f"{B.get('annual_urban_growth_pct', float('nan')):.2f} %/yr",
          help="Compound annual growth rate of land above the 20% built-up threshold, "
               "observed epochs only")
if G:
    c4.metric("Ghost-growth area", f"{G.get('ghost_area_km2', 0):,.2f} km²",
              f"{G.get('n_zones', 0)} zones", delta_color="inverse")
if V:
    c5.metric("Green lost to built-up", f"{V.get('lost_to_builtup_km2', 0):,.2f} km²",
              f"{V.get('lost_to_builtup_share_pct', 0)}% of all green loss",
              delta_color="inverse")
elif T:
    c5.metric("Heat-island hotspots", f"{T.get('hotspot_area_km2', 0):,.1f} km²",
              f"peak +{T.get('max_intensity_c', 0):.1f} °C")

_proj = B.get("projection")
if _proj:
    _pb = _proj.get("built_surface_km2", {})
    st.markdown(
        "<div class='ui-caption'>For comparison only — GHSL's own model projection for "
        + ", ".join(f"{y}: {v:,.1f} km² built surface" for y, v in _pb.items())
        + ". It is not an observation and is not used in any figure above.</div>",
        unsafe_allow_html=True)

# ---- coverage notice ------------------------------------------------------
if skipped:
    with st.expander(f"⚠ {len(skipped)} layer(s) unavailable in this run", expanded=False):
        for k, v in skipped.items():
            st.markdown(f"**{k}** — {v}")
        st.markdown(
            "<div class='ui-caption'>Earth Engine layers (nightlights, NDVI, land "
            "surface temperature) need a one-time <code>earthengine authenticate</code>. "
            "See docs/SETUP.md.</div>", unsafe_allow_html=True)

st.divider()

# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
LAYERS = {
    "Growth typology": ("typology", "categorical",
                        "Where growth is healthy, filling up, or built-but-inactive"),
    "Ghost-growth score": ("ghost_score", "sequential",
                           "Built-up but underperforming on activity, weighted by how new it is"),
    "Built-up change": ("builtup_delta_frac", "diverging",
                        f"Change in built-up fraction, {period}"),
    "Growth intensity": ("growth_intensity", "sequential",
                         "Smoothed surface of new built-up area"),
    "Activity index": ("activity_index", "sequential",
                       "Composite of nightlights, POI density and population per unit built-up"),
    "Commercial POI density": ("poi_commercial", "sequential",
                               "Retail, hospitality and finance/office points"),
    "Road density": ("road_density", "sequential", "Class-weighted road centreline length"),
    "Population": (f"population_{cfg.epoch_current}", "sequential",
                   f"Residential population, {cfg.epoch_current} (GHS-POP)"),
    "Nightlights": ("nightlights", "sequential", "VIIRS annual mean radiance, latest year"),
    "Heat island (SUHI)": ("suhi_intensity", "diverging",
                           "Land surface temperature minus rural reference, March-May"),
    "Heat-island change 2013-2024": ("suhi_change", "diverging",
                                     "Change in heat-island intensity, same reference cells"),
    "Growth suitability (model)": ("growth_suitability", "sequential",
                                   "Probability that a non-urban cell becomes urban, from "
                                   "the better growth model, 2020 state"),
    "Predicted new urban by 2025": ("pred_new_urban_2025", "sequential",
                                    "Share of the cell predicted to become urban 2020-2025 "
                                    "— a prediction, not an observation"),
    "Predicted new urban by 2030": ("pred_new_urban_2030", "sequential",
                                    "Share of the cell predicted to become urban 2020-2030 "
                                    "— a prediction, not an observation"),
    "Heat vulnerability": ("heat_vulnerability", "sequential",
                           "Heat exposure weighted by resident population"),
    "Green deficit": ("green_deficit", "sequential",
                      "Built-up cells with little vegetation"),
}
available = {k: v for k, v in LAYERS.items() if gdf is not None and v[0] in gdf.columns}

with st.sidebar:
    st.header("Map layer")
    if not available:
        st.warning("No grid layers available.")
        layer_name = None
    else:
        layer_name = st.radio("Layer", list(available), label_visibility="collapsed")
        st.markdown(f"<div class='ui-caption'>{available[layer_name][2]}</div>",
                    unsafe_allow_html=True)

    st.divider()
    st.header("Filters")
    show_only_urban = st.checkbox("Urban cells only", value=False,
                                  help="Cells above the 20% built-up threshold")
    basemap = st.selectbox("Basemap", ["CartoDB positron", "OpenStreetMap", "CartoDB dark_matter"])
    opacity = st.slider("Layer opacity", 0.3, 1.0, 0.75, 0.05)

    st.divider()
    st.markdown("<div class='ui-caption'><b>Data sources</b></div>", unsafe_allow_html=True)
    for k, v in summary.get("provenance", {}).items():
        st.markdown(f"<div class='ui-caption'>{k}: {v.get('source','')}</div>",
                    unsafe_allow_html=True)

# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------
tab_map, tab_growth, tab_ghost, tab_env, tab_val, tab_data, tab_src = st.tabs(
    ["Map", "Growth", "Ghost growth", "Environment", "Validation", "Data", "Sources"]
)


def _quantile_bins(series: pd.Series, n: int = 7) -> list[float]:
    """Quantile breaks, de-duplicated. Robust to the heavy right skew of
    every one of these variables — equal-interval bins would put 95% of
    cells in the first class."""
    s = series.replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return [0, 1]
    qs = np.linspace(0, 1, n + 1)
    bins = sorted(set(np.quantile(s, qs).round(6)))
    return bins if len(bins) >= 3 else [float(s.min()), float(s.max())]


with tab_map:
    if gdf is None or layer_name is None:
        st.info("Run the pipeline to generate the grid.")
    else:
        import branca.colormap as cm
        import folium
        from streamlit_folium import st_folium

        col, mode, desc = available[layer_name]
        data = gdf.copy()
        _frac_col = f"builtup_frac_{cfg.epoch_current}"
        if show_only_urban and _frac_col in data.columns:
            data = data[data[_frac_col] >= 0.20]

        mcol, lcol = st.columns([4, 1])

        with mcol:
            centre = cfg.centre
            m = folium.Map(location=[centre[1], centre[0]], zoom_start=12,
                           tiles=basemap, control_scale=True)

            if mode == "categorical":
                def style(feat):
                    v = feat["properties"].get(col)
                    code = int(v) if v is not None and np.isfinite(v) else 0
                    return {"fillColor": TYPE_COLOURS.get(code, "#e1e0d9"),
                            "color": "#ffffff", "weight": 0.3,
                            "fillOpacity": opacity}
                tooltip_fields = [col]
                if "ghost_score" in data.columns:
                    tooltip_fields.append("ghost_score")
                folium.GeoJson(
                    data.to_json(), style_function=style,
                    tooltip=folium.GeoJsonTooltip(
                        fields=tooltip_fields,
                        aliases=["Type code", "Ghost score"][:len(tooltip_fields)],
                        localize=True),
                ).add_to(m)
            else:
                vals = data[col].replace([np.inf, -np.inf], np.nan).dropna()
                if vals.empty:
                    st.warning(f"Layer '{layer_name}' has no data.")
                else:
                    if mode == "diverging":
                        lim = float(max(abs(vals.quantile(0.02)), abs(vals.quantile(0.98)))) or 1.0
                        cmap = cm.LinearColormap(DIVERGING, vmin=-lim, vmax=lim)
                    else:
                        bins = _quantile_bins(vals)
                        cmap = cm.LinearColormap(
                            SEQ_BLUE, vmin=float(bins[0]), vmax=float(bins[-1])
                        )
                    cmap.caption = f"{layer_name}"

                    def style(feat):
                        v = feat["properties"].get(col)
                        if v is None or not np.isfinite(v):
                            return {"fillColor": "#00000000", "color": "#00000000",
                                    "weight": 0, "fillOpacity": 0}
                        return {"fillColor": cmap(v), "color": "#ffffff",
                                "weight": 0.2, "fillOpacity": opacity}

                    folium.GeoJson(
                        data.to_json(), style_function=style,
                        tooltip=folium.GeoJsonTooltip(fields=[col], aliases=[layer_name],
                                                      localize=True),
                    ).add_to(m)
                    cmap.add_to(m)

            # Ghost zone markers, always on — they are the headline finding.
            for z in G.get("zones", [])[:15]:
                if "lat" not in z:
                    continue
                folium.CircleMarker(
                    location=[z["lat"], z["lon"]],
                    radius=5 + 3 * min(z["area_km2"], 3),
                    color="#ffffff", weight=1.5,
                    fill=True, fill_color=STATUS["critical"], fill_opacity=0.85,
                    tooltip=(f"Ghost zone {z['zone_id']} — {z['area_km2']} km²<br>"
                             f"score {z['mean_ghost_score']}"),
                ).add_to(m)

            st_folium(m, height=620, use_container_width=True,
                      returned_objects=[], key=f"map_{col}")

        with lcol:
            st.markdown("**Legend**")
            if mode == "categorical":
                present = set(data[col].dropna().astype(int)) if col in data else set()
                for code, label in TYPE_LABELS.items():
                    if code not in present:
                        continue
                    n_cells = int((data[col] == code).sum())
                    st.markdown(
                        f"<div class='legend-row'>"
                        f"<span class='legend-sw' style='background:{TYPE_COLOURS[code]}'></span>"
                        f"<span>{label.replace('_',' ')} <b>({n_cells})</b></span></div>",
                        unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='ui-caption'>{desc}</div>", unsafe_allow_html=True)
                vals = data[col].replace([np.inf, -np.inf], np.nan).dropna()
                if not vals.empty:
                    st.markdown(
                        f"<div class='ui-caption' style='margin-top:8px'>"
                        f"min {vals.min():,.3g}<br>median {vals.median():,.3g}<br>"
                        f"p90 {vals.quantile(0.9):,.3g}<br>max {vals.max():,.3g}</div>",
                        unsafe_allow_html=True)
            st.markdown("<div class='ui-caption' style='margin-top:12px'>"
                        "Red circles mark the largest ghost-growth zones.</div>",
                        unsafe_allow_html=True)

with tab_growth:
    import plotly.graph_objects as go

    LAYOUT = dict(
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif",
                  color=INK_SECONDARY, size=12),
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(gridcolor=GRIDLINE, linecolor="#c3c2b7", zeroline=False),
        yaxis=dict(gridcolor=GRIDLINE, linecolor="#c3c2b7", zeroline=False),
        hoverlabel=dict(bgcolor=SURFACE, font_size=12),
    )

    left, right = st.columns(2)

    with left:
        st.subheader("Built-up surface by epoch")
        if built:
            yrs = sorted(built, key=int)
            fig = go.Figure(go.Bar(
                x=yrs, y=[built[y] for y in yrs],
                marker_color=SEQ_BLUE[4], marker_line_width=0,
                text=[f"{built[y]:,.1f}" for y in yrs],
                textposition="outside", textfont=dict(color=INK_SECONDARY),
                hovertemplate="%{x}: %{y:.2f} km²<extra></extra>",
            ))
            _pb = (B.get("projection") or {}).get("built_surface_km2", {})
            if _pb:
                # Drawn hollow and labelled: GHSL's projection, not an observation.
                fig.add_trace(go.Bar(
                    x=[f"{y} (projection)" for y in _pb], y=list(_pb.values()),
                    marker=dict(color="rgba(0,0,0,0)",
                                line=dict(color=SEQ_BLUE[4], width=1.5)),
                    text=[f"{v:,.1f}" for v in _pb.values()], textposition="outside",
                    textfont=dict(color=INK_MUTED),
                    hovertemplate="%{x}: %{y:.2f} km² — GHSL model projection<extra></extra>",
                ))
            fig.update_layout(**LAYOUT, height=330, showlegend=False,
                              yaxis_title="km²", bargap=0.45)
            st.plotly_chart(fig, width='stretch')

    with right:
        st.subheader("Population by epoch")
        if pop:
            yrs = sorted(pop, key=int)
            fig = go.Figure(go.Bar(
                x=yrs, y=[pop[y] / 1e6 for y in yrs],
                marker_color=SEQ_BLUE[2], marker_line_width=0,
                text=[f"{pop[y]/1e6:,.2f}" for y in yrs],
                textposition="outside", textfont=dict(color=INK_SECONDARY),
                hovertemplate="%{x}: %{y:.2f} M<extra></extra>",
            ))
            fig.update_layout(**LAYOUT, height=330, showlegend=False,
                              yaxis_title="million", bargap=0.45)
            st.plotly_chart(fig, width='stretch')

    st.subheader("Form of new development")
    st.markdown(
        "<div class='ui-caption'>Infill is cheapest to service; leapfrog development "
        "sits detached from the existing fabric and is where built-but-inactive land "
        "concentrates.</div>", unsafe_allow_html=True)
    form = B.get("urban_form", {})
    rows = [(k, v) for k, v in form.items() if not k.startswith("_")]
    if rows:
        fc = st.columns(len(rows))
        for (label, v), c in zip(rows, fc):
            c.metric(label.replace("_", " ").title(), f"{v['area_km2']:,.2f} km²",
                     f"{v['share_pct']}% of new")
        fig = go.Figure(go.Bar(
            x=[v["area_km2"] for _, v in rows],
            y=[k.replace("_", " ").title() for k, _ in rows],
            orientation="h", marker_color=SEQ_BLUE[4], marker_line_width=0,
            text=[f"{v['share_pct']}%" for _, v in rows],
            textposition="outside", textfont=dict(color=INK_SECONDARY),
            hovertemplate="%{y}: %{x:.2f} km²<extra></extra>",
        ))
        fig.update_layout(**LAYOUT, height=240, showlegend=False, xaxis_title="km²")
        st.plotly_chart(fig, width='stretch')

    if GM:
        st.subheader("Where the city grows next — growth models")
        st.markdown(
            "<div class='ui-caption'>Both models learn from the conversions observed "
            f"{GM.get('train_period', '')} and are tested on {GM.get('test_period', '')}, a period "
            "they never saw. Figure of Merit scores only the places where change happened, so "
            "the land that simply stayed rural cannot inflate it.</div>", unsafe_allow_html=True)
        _rows = []
        for _k, _m in GM.get("models", {}).items():
            _rows.append({
                "Model": _k.replace("_", " "),
                "AUC, training period": _m.get("auc_train", _m.get("auc_train_out_of_bag")),
                "AUC, held-out period": _m.get("auc_test"),
                "Figure of Merit": _m["validation"]["figure_of_merit"],
                "× random": GM.get("skill_vs_random", {}).get(_k)})
        _rows.append({"Model": "random allocation", "AUC, training period": None,
                      "AUC, held-out period": 0.5,
                      "Figure of Merit": GM["random_baseline"]["mean_figure_of_merit"],
                      "× random": 1.0})
        st.dataframe(pd.DataFrame(_rows), hide_index=True, width='stretch')
        _pr = GM.get("projections", {})
        if _pr:
            for (_y, _v), _col in zip(_pr.items(), st.columns(len(_pr))):
                _col.metric(f"Predicted new urban land by {_y}", f"+{_v['demand_km2']:.1f} km²",
                            f"{_v['horizon_years']} years from {_v['from_year']}",
                            delta_color="off",
                            help="A prediction, not an observation: the amount follows the "
                                 "2010-2020 trend, the location comes from the better model.")
        st.markdown(f"<div class='ui-caption'>Better model on the held-out period: "
                    f"<b>{GM.get('best_model', '').replace('_', ' ')}</b>. Map layers "
                    "'Predicted new urban by 2025 / 2030' show where it puts the growth.</div>",
                    unsafe_allow_html=True)

    if N.get("sum_of_lights"):
        st.subheader("Economic activity — Sum of Lights")
        sol = N["sum_of_lights"]
        yrs = sorted(sol, key=int)
        fig = go.Figure(go.Scatter(
            x=yrs, y=[sol[y] for y in yrs], mode="lines+markers",
            line=dict(color=SEQ_BLUE[4], width=2),
            marker=dict(size=8, color=SEQ_BLUE[4],
                        line=dict(color=SURFACE, width=2)),
            hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
        ))
        fig.update_layout(**LAYOUT, height=320, showlegend=False,
                          yaxis_title="total radiance (nW/cm²/sr)")
        st.plotly_chart(fig, width='stretch')
        st.markdown(
            "<div class='ui-caption'>Sum of Lights is a proxy for economic activity, "
            "not a measurement of it. The light-to-output elasticity is well below 1 "
            "and varies by sector (Henderson, Storeygard &amp; Weil 2012).</div>",
            unsafe_allow_html=True)

with tab_ghost:
    st.subheader("Ghost growth — development without activity")
    st.markdown(
        "<div class='ui-caption'>A cell is flagged when substantial <b>new</b> built-up "
        "area coincides with activity far below what comparably developed land in this "
        "same city achieves. The comparison is empirical, not a fixed threshold.</div>",
        unsafe_allow_html=True)
    st.write("")

    if not G:
        st.info("Ghost-growth analysis not available in this run.")
    else:
        srcs = G.get("activity_sources", [])
        st.markdown(
            f"<div class='note'><b>Evidence base:</b> activity index built from "
            f"{len(srcs)} signal(s) — {', '.join(srcs)}. "
            f"Weights: {G.get('activity_weights', {})}.</div>",
            unsafe_allow_html=True)
        if "caveat" in G:
            st.markdown(f"<div class='note'>⚠ {G['caveat']}</div>", unsafe_allow_html=True)
        if G.get("rising_rule") and G["rising_rule"] != "none":
            st.markdown(
                f"<div class='note'><b>Rule for 'activity rising':</b> "
                f"{G['rising_rule'].replace('_', ' ')} (α = {G.get('trend_alpha')}). A new, "
                "low-activity cell counts as <i>emerging</i> only if its night-time light rose "
                "significantly faster than the established city; otherwise it is "
                f"<i>ghost growth</i>. Development {G.get('development_period', '')}; activity "
                f"level from {G.get('nightlight_level_years', '')}.</div>",
                unsafe_allow_html=True)

        areas = G.get("typology_areas_km2", {})
        if areas:
            order = ["ghost_growth", "emerging", "healthy_growth",
                     "declining", "established_active", "undeveloped"]
            rows = [(k, areas[k]) for k in order if k in areas]
            fig = go.Figure(go.Bar(
                x=[v for _, v in rows],
                y=[k.replace("_", " ") for k, _ in rows],
                orientation="h",
                marker_color=[TYPE_COLOURS[[c for c, l in TYPE_LABELS.items() if l == k][0]]
                              for k, _ in rows],
                marker_line_width=0,
                text=[f"{v:,.2f} km²" for _, v in rows],
                textposition="outside", textfont=dict(color=INK_SECONDARY),
                hovertemplate="%{y}: %{x:.2f} km²<extra></extra>",
            ))
            fig.update_layout(**LAYOUT, height=300, showlegend=False, xaxis_title="km²")
            st.plotly_chart(fig, width='stretch')

        if TV:
            _r = TV["results"][TV["primary_rule"]]
            _c, _b = _r["emerging_vs_ghost_cells"], _r["emerging_vs_ghost_500m_blocks"]
            st.markdown(
                "<div class='note'><b>Hold-out test.</b> Classified again using only the "
                "2013-2020 night lights, cells called <i>emerging</i> went on to brighten "
                "relative to the city more than cells called <i>ghost growth</i> "
                f"(median {_c['median_x']:+.3f} vs {_c['median_y']:+.3f}; one-sided Mann-Whitney "
                f"p = {_c['p_value']:.3f} on 100 m cells, {_b['p_value']:.3f} on 500 m blocks). "
                "The split carries real information, though the effect is modest "
                f"(an emerging cell out-brightened a ghost cell {100 * _c['prob_superiority']:.0f}% "
                "of the time).</div>", unsafe_allow_html=True)

        zones = G.get("zones", [])
        if zones:
            st.subheader(f"Priority zones ({len(zones)} shown)")
            zdf = pd.DataFrame(zones)
            cols = [c for c in ["zone_id", "area_km2", "flagged_km2", "mean_ghost_score",
                                "mean_activity", "mean_residual", "mean_new_share", "lat", "lon"]
                    if c in zdf.columns]
            st.dataframe(
                zdf[cols].rename(columns={
                    "zone_id": "Zone", "area_km2": "Zone area (km²)",
                    "flagged_km2": "Flagged (km²)",
                    "mean_ghost_score": "Ghost score", "mean_activity": "Activity",
                    "mean_residual": "Residual", "mean_new_share": "Share new since 2010",
                    "lat": "Lat", "lon": "Lon"}),
                width='stretch', hide_index=True)
            top = zones[0]
            st.markdown(
                f"<div class='finding'><b>Largest zone:</b> {top['area_km2']} km² at "
                f"{top.get('lat','?')}, {top.get('lon','?')} — activity "
                f"{abs(top['mean_residual']):.2f} below the level expected for its "
                f"built-up intensity.</div>", unsafe_allow_html=True)
        else:
            st.success("No contiguous ghost-growth zones above the minimum size.")

with tab_env:
    ec1, ec2 = st.columns(2)
    with ec1:
        st.subheader("Green cover")
        if V:
            st.metric("Green lost", f"{V['green_lost_km2']:,.2f} km²")
            st.metric("Of which converted to built-up",
                      f"{V['lost_to_builtup_km2']:,.2f} km²",
                      f"{V['lost_to_builtup_share_pct']}%")
            st.metric("Green cover", f"{V['green_cover_pct_to']}%",
                      f"{V['green_cover_pct_to'] - V['green_cover_pct_from']:+.1f} pp")
            st.markdown(
                f"<div class='ui-caption'>NDVI decline {V.get('period', '')} is counted as "
                "lost to built-up only where Dynamic World shows built-up gain over the same "
                "years. Varanasi sits in intensively cropped plain, where raw NDVI change "
                "mostly tracks the cropping calendar.</div>", unsafe_allow_html=True)
        else:
            st.info("Needs Earth Engine (Sentinel-2 NDVI).")

    with ec2:
        st.subheader(f"Surface heat island, March-May {T.get('year', '')}")
        if T and "max_intensity_c" in T:
            _mu = T.get("mean_urban_intensity_c")
            st.metric("Mean intensity over urban cells",
                      "n/a" if _mu is None else f"{_mu:+.2f} °C",
                      help="Land surface temperature of cells at least 20% built, minus the "
                           "rural reference. Negative means cooler than the surroundings.")
            _hs = (CC.get("heat_island_by_class") or {}).get("hotspot_km2_by_setting", {})
            st.metric(f"Hotspot area (≥ +{T.get('hotspot_threshold_c', 3)} °C)",
                      f"{T.get('hotspot_area_km2', 0):,.1f} km²",
                      (f"{_hs.get('urban (>=20% built)', 0):.2f} km² of it in urban cells"
                       if _hs else None), delta_color="off")
            st.metric("Peak intensity", f"+{T['max_intensity_c']:.1f} °C")
            st.markdown(
                f"<div class='ui-caption'>Rural reference {T.get('rural_reference_c', '?')} °C "
                f"— {T.get('rural_reference_rule', '')}.</div>", unsafe_allow_html=True)
            st.markdown(
                "<div class='note'>In the pre-monsoon daytime the built-up city is on average "
                "<b>cooler</b> than the bare, dry farmland around it — a surface cool island. "
                "The independent MODIS sensor shows no daytime heat island either. The hottest "
                "surfaces are rural, so hotspot area is not a measure of urban heat; the Heat "
                "vulnerability layer, which weights heat by residents, is the one to use for "
                "planning.</div>", unsafe_allow_html=True)
        else:
            st.info("Needs Earth Engine (Landsat thermal).")

with tab_val:
    st.subheader("How far can these results be trusted?")
    st.markdown(
        "<div class='ui-caption'>Independent checks run for Review 3: a hold-out test of the "
        "typology, six built-up datasets compared cell by cell, Landsat against MODIS, and "
        "Indian census and economic data. Regenerate with <code>python scripts/make_figures.py"
        "</code>; the corrections log is in docs/REVIEW3_REPORT.md.</div>",
        unsafe_allow_html=True)

    def _fig(name: str, caption: str) -> None:
        p = FIGDIR / name
        if p.exists():
            st.image(str(p), caption=caption, use_container_width=True)
        else:
            st.info(f"{name} not generated yet — run scripts/make_figures.py")

    _v1, _v2, _v3, _v4 = st.columns(4)
    if PV:
        _d = PV["districts"]["datasets"]
        _v1.metric("GHS-POP vs Census 2011", f"{_d['ghs_pop_2011']['median_error_pct']:+.1f}%",
                   "median district error, 71 UP districts", delta_color="off")
        _v2.metric("WorldPop vs Census 2011", f"{_d['worldpop_2011']['median_error_pct']:+.1f}%",
                   "median district error", delta_color="off")
    if EV:
        _g = EV["districts"]["gddp"]
        _last = _g[sorted(_g)[0]]["levels"] if _g else None
        _t = EV["towns_and_villages_2013"]["lights_vs_employment"]
        if _last:
            _v3.metric("Lights vs district GDP", f"ρ = {_last['spearman_rho']}",
                       f"R² {_last['r2_loglog']} (log-log), 71 districts", delta_color="off")
        _v4.metric("Lights vs village jobs (EC 2013)", f"ρ = {_t['spearman_rho']}",
                   f"{_t['n']:,} towns and villages", delta_color="off")

    st.markdown("#### Ghost growth: does the emerging / ghost split hold up?")
    _fig("F04_rule_sensitivity.png", "The typology under four definitions of 'rising'")
    _fig("F05_holdout.png", "Hold-out: classified with 2013-2020 lights, checked on 2022-2024")
    st.markdown("#### Growth model")
    _a, _b2 = st.columns(2)
    with _a:
        _fig("F06_toc.png", "TOC curves on the held-out 2015-2020 period")
    with _b2:
        _fig("F07_figure_of_merit.png", "Figure of Merit against random and a published benchmark")
    _fig("F08_drivers.png", "What drives new urban land")
    _fig("F09_projection_map.png", "Predicted new urban land — predictions, not observations")
    st.markdown("#### Satellite cross-checks")
    _fig("F11_builtup_definitions.png", "Six datasets' answers to 'how much is built?'")
    _fig("F12_land_surface_temperature.png", "Landsat against MODIS; where the hottest surfaces are")
    _fig("F14_open_buildings.png", "Open Buildings on the typology classes")
    st.markdown("#### Indian data")
    _fig("F10_population.png", "Gridded population against the Census of India")
    _fig("F13_lights_vs_economy.png", "Night lights against the 2013 Economic Census and district GDP")

    st.markdown("#### Zone evidence cards")
    _zdir = FIGDIR / "zones"
    _cards = sorted(_zdir.glob("zone_*.png")) if _zdir.exists() else []
    if _cards:
        _pick = st.selectbox("Zone", [int(p.stem.split("_")[1]) for p in _cards],
                             format_func=lambda k: f"Zone {k}")
        st.image(str(_zdir / f"zone_{_pick:02d}.png"), use_container_width=True)
        st.markdown(
            "<div class='ui-caption'>Evidence for a human reader, not a validation: without "
            "ground or image labels, how often a flagged zone is truly vacant is "
            "unmeasured.</div>", unsafe_allow_html=True)
    else:
        st.info("No zone cards yet — run scripts/make_zone_cards.py")


with tab_data:
    st.subheader("Reporting grid")
    if gdf is not None:
        show = gdf.drop(columns="geometry")
        st.markdown(f"<div class='ui-caption'>{len(show):,} cells &times; "
                    f"{len(show.columns)} attributes</div>", unsafe_allow_html=True)
        st.dataframe(show.head(1000), width='stretch', height=420)
        st.download_button("Download grid CSV", show.to_csv(index=False),
                           f"{cfg.city_slug}_grid.csv", "text/csv")
    st.subheader("Full summary")
    st.json(summary, expanded=False)


with tab_src:
    st.subheader("Datasets and when their imagery was acquired")
    st.markdown(
        "<div class='ui-caption'>Acquisition windows are read back from the image "
        "collections themselves, not assumed from a filename. Regenerate with "
        "<code>python scripts/collect_layer_dates.py</code>.</div>",
        unsafe_allow_html=True)

    dates_p = cfg.outputs_dir / "layer_dates.json"
    if not dates_p.exists():
        st.info("No acquisition record yet. Run `python scripts/collect_layer_dates.py`.")
    else:
        import json as _json
        recs = _json.loads(dates_p.read_text(encoding="utf-8"))
        rows = [{
            "Layer": r.get("label", k),
            "Dataset": r.get("dataset", "—"),
            "Provider": r.get("provider", "—"),
            "Imagery dates": r.get("window", "—"),
            "Built from": r.get("composite", "—"),
        } for k, r in recs.items()]
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True, height=430)

        st.subheader("Why each season was chosen")
        for k, r in recs.items():
            with st.expander(f"{r.get('label', k)} — {r.get('window', '')}"):
                st.markdown(
                    f"**Dataset** `{r.get('dataset','—')}` · {r.get('provider','—')}\n\n"
                    f"**Built from** {r.get('composite','—')}\n\n"
                    f"**Season** {r.get('season','—')}\n\n"
                    f"**Export** {r.get('export','—')}")

