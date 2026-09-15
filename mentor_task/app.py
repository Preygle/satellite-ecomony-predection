from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
import streamlit as st  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import extract as X  # noqa: E402

st.set_page_config(page_title="Sentinel & Landsat Extraction", page_icon="🛰️",
                   layout="wide")

st.title("Sentinel-2 and Landsat Extraction")
st.caption("Varanasi · pick a date window, check what imagery exists in it, "
           "then extract both sensors for the same window")

# --------------------------------------------------------------- controls ---
with st.sidebar:
    st.header("Date window")
    c1, c2 = st.columns(2)
    start = c1.date_input("From", date(2024, 10, 1),
                          min_value=date(2013, 4, 1), max_value=date.today())
    end = c2.date_input("To", date(2025, 3, 31),
                        min_value=date(2013, 4, 1), max_value=date.today())

    st.header("Cloud limit")
    s_cloud = st.slider("Sentinel-2 — maximum cloud %", 5, 90, 35, 5)
    l_cloud = st.slider("Landsat — maximum cloud %", 5, 90, 40, 5)

    st.header("Export scale")
    s_scale = st.select_slider("Sentinel-2 (m)", [10, 15, 20, 30, 60], value=20)
    l_scale = st.select_slider("Landsat (m)", [30, 60, 90], value=30)

    st.caption("Sentinel-2 is 10 m natively and Landsat 30 m. A finer scale "
               "gives a sharper image but Earth Engine caps a direct download "
               "at about 50 MB, so very fine scales over a large window may "
               "step down automatically.")

if start >= end:
    st.error("The start date must be before the end date.")
    st.stop()

s_from, s_to = start.isoformat(), end.isoformat()

# ------------------------------------------------------------ availability --
st.subheader("1 · What imagery exists in this window")
st.caption("Checked before anything is downloaded, because a window that is "
           "too short produces a composite from one or two passes, which is a "
           "single observation rather than a seasonal median.")

if st.button("Check availability", type="primary"):
    with st.spinner("Querying Earth Engine…"):
        try:
            _, s_av = X.sentinel(s_from, s_to, s_cloud)
            _, l_av = X.landsat(s_from, s_to, l_cloud)
            st.session_state["avail"] = (s_av, l_av)
        except Exception as exc:
            st.error(f"Earth Engine query failed: {exc}")

if "avail" in st.session_state:
    s_av, l_av = st.session_state["avail"]
    a, b = st.columns(2)
    for col, name, av, ident in [
        (a, "Sentinel-2", s_av, X.SENTINEL),
        (b, "Landsat 8 & 9", l_av, f"{X.LANDSAT8} + {X.LANDSAT9}"),
    ]:
        with col:
            st.markdown(f"**{name}**")
            st.code(ident, language=None)
            if av["scenes"]:
                m1, m2 = st.columns(2)
                m1.metric("Scenes", av["scenes"])
                m2.metric("Distinct days", av["days"])
                st.caption(f"{av['first']} – {av['last']}")
                if av["days"] < 5:
                    st.warning("Very few distinct days. The composite will "
                               "carry one or two days' weather and haze rather "
                               "than averaging them out.")
            else:
                st.error("No scenes in this window.")

st.divider()

# --------------------------------------------------------------- extraction --
st.subheader("2 · Extract")

tag = f"{s_from}_{s_to}".replace("-", "")
c1, c2 = st.columns(2)

if c1.button("Extract Sentinel-2", width='stretch'):
    with st.spinner("Building composite and downloading…"):
        try:
            imgs, av = X.sentinel(s_from, s_to, s_cloud)
            if not imgs:
                st.error("No Sentinel-2 scenes in this window.")
            else:
                paths = X.download(imgs, s_scale, tag)
                st.session_state["s_paths"] = paths
                st.success(f"Wrote {len(paths)} file(s) from {av['scenes']} scenes.")
        except Exception as exc:
            st.error(f"Extraction failed: {exc}")

if c2.button("Extract Landsat", width='stretch'):
    with st.spinner("Building composite and downloading…"):
        try:
            imgs, av = X.landsat(s_from, s_to, l_cloud)
            if not imgs:
                st.error("No Landsat scenes in this window.")
            else:
                paths = X.download(imgs, l_scale, tag)
                st.session_state["l_paths"] = paths
                st.success(f"Wrote {len(paths)} file(s) from {av['scenes']} scenes.")
        except Exception as exc:
            st.error(f"Extraction failed: {exc}")

st.divider()

# ------------------------------------------------------------------ preview --
st.subheader("3 · Preview")


def show(path: Path):
    """Render a GeoTIFF: three bands as true colour, one band as a colour map."""
    with rasterio.open(path) as ds:
        n = ds.count
        if n >= 3:
            arr = np.dstack([ds.read(i).astype("float32") for i in (1, 2, 3)])
            out = np.zeros_like(arr)
            for i in range(3):
                c = arr[..., i]
                fin = c[np.isfinite(c)]
                if fin.size:
                    lo, hi = np.percentile(fin, [2, 98])
                    out[..., i] = np.clip((c - lo) / max(hi - lo, 1e-9), 0, 1)
            fig, ax = plt.subplots(figsize=(6, 6))
            ax.imshow(out)
        else:
            c = ds.read(1).astype("float32")
            c[c == ds.nodata] = np.nan
            fin = c[np.isfinite(c)]
            lo, hi = np.percentile(fin, [2, 98]) if fin.size else (0, 1)
            cmap = "turbo" if "lst" in path.stem else "RdYlGn"
            fig, ax = plt.subplots(figsize=(6, 6))
            im = ax.imshow(c, cmap=cmap, vmin=lo, vmax=hi)
            fig.colorbar(im, ax=ax, fraction=0.04)
    ax.set_xticks([]); ax.set_yticks([])
    st.pyplot(fig, clear_figure=True)


existing = sorted(X.OUT.glob("*.tif"))
if not existing:
    st.info("Nothing extracted yet. Use the buttons above.")
else:
    pick = st.multiselect("Files in output/", [p.name for p in existing],
                          default=[p.name for p in existing[:2]])
    cols = st.columns(min(len(pick), 2) or 1)
    for i, name in enumerate(pick):
        with cols[i % len(cols)]:
            st.markdown(f"**{name}**")
            p = X.OUT / name
            st.caption(f"{p.stat().st_size/1e6:.1f} MB")
            try:
                show(p)
            except Exception as exc:
                st.error(f"Could not render: {exc}")
            with open(p, "rb") as fh:
                st.download_button("Download GeoTIFF", fh, name,
                                   key=f"dl_{name}")
