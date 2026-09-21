from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urbanintel.config import load_config  # noqa: E402
from urbanintel.data import osm  # noqa: E402

log = logging.getLogger("poi_detail")


def usage() -> str:
    return ("Re-fetch OpenStreetMap points of interest keeping their tags, so a "
            "supermarket can be told apart from a kiosk.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=usage())
    ap.add_argument("--force", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    dest = cfg.raw_dir / "osm" / "pois_detailed.json"
    if dest.exists() and not args.force:
        d = json.loads(dest.read_text(encoding="utf-8"))
        log.info("cached: %s (%d points)", dest.name, len(d["features"]))
        return 0

    bbox = osm._bbox_str(cfg.bbox)
    feats: list[dict] = []
    for group, selectors in osm.POI_GROUPS.items():
        parts = "".join(f"{sel}({bbox});" for sel in selectors)
        # `out center tags` returns the tags as well as one representative
        # coordinate, which is what distinguishes a mall from a corner shop.
        query = f"[out:json][timeout:180];({parts});out center tags;"
        try:
            payload = osm._run_query(cfg, query)
        except Exception as exc:                                  # noqa: BLE001
            log.warning("%s: %s", group, exc)
            continue
        n = 0
        for el in payload.get("elements", []):
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            if lon is None or lat is None:
                continue
            feats.append({"group": group, "lon": float(lon), "lat": float(lat),
                          "tags": el.get("tags", {})})
            n += 1
        log.info("  %-18s %5d points", group, n)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"features": feats}), encoding="utf-8")

    kinds: dict[str, int] = {}
    for f in feats:
        t = f["tags"]
        key = (t.get("shop") or t.get("amenity") or t.get("office")
               or t.get("tourism") or t.get("railway") or t.get("landuse") or "other")
        kinds[key] = kinds.get(key, 0) + 1
    top = sorted(kinds.items(), key=lambda kv: -kv[1])[:20]
    print(f"\n{len(feats)} points of interest, {len(kinds)} distinct kinds")
    print("  most common:", ", ".join(f"{k} {v}" for k, v in top))
    print(f"  written to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
