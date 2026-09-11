"""Download the Indian government and research datasets used for validation.

    python scripts/fetch_indian_data.py

Files land in ``data/raw/india/`` and every download is recorded — source,
size, SHA-256 and date — in ``data/raw/india/MANIFEST.json``.

| Dataset                                             | Publisher                                                   | Licence          |
|-----------------------------------------------------|-------------------------------------------------------------|------------------|
| SHRUG v2 — 2013 Economic Census, shrid level        | Development Data Lab, from the 6th Economic Census (MoSPI)  | CC BY-NC-SA 4.0  |
| SHRUG v2 — 2011 Population Census Abstract, shrid   | Development Data Lab, from Census of India 2011             | CC BY-NC-SA 4.0  |
| SHRUG v2 — shrid location names and keys            | Development Data Lab                                        | CC BY-NC-SA 4.0  |
| SHRUG v2 — shrid polygons, 2011 district polygons   | Development Data Lab                                        | CC BY-NC-SA 4.0  |
| District Domestic Product (base year 2011-12)       | Directorate of Economics & Statistics, Govt. of Uttar Pradesh | Government data |

SHRUG must be cited as: Asher, S., Lunt, T., Matsuura, R. and Novosad, P.
(2021). Development research at high geographic resolution: an analysis of
night-lights, firms, and poverty in India using the SHRUG open data platform.
*The World Bank Economic Review* 35(4).

SHRUG's download links are signed and expire after a short time, so they are
read fresh from the SHRUG download page's data feed on every run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "india"
log = logging.getLogger("fetch_india")

SHRUG_FEED = "https://www.devdatalab.org/shrug_download/data"
SHRUG_FILES = {
    "shrug-ec13-csv.zip": "2013 Economic Census (establishments, employment) by shrid",
    "shrug-pca11-csv.zip": "2011 Population Census Abstract by shrid",
    "shrug-pca01-csv.zip": "2001 Population Census Abstract by shrid (for 2001-2011 growth)",
    "shrug-shrid-keys-csv.zip": "shrid location names (state, district, subdistrict)",
    "shrug-pc11dist-poly-gpkg.zip": "2011 Census district polygons",
    "shrug-shrid-poly-gpkg.zip": "shrid (town / village) polygons",
}

UPDES_BASE = "https://updes.up.nic.in/updes/data/annual_stats/ddp"
UPDES_FILES = [(year, kind) for year in ("2021_22", "2020_21")
               for kind in ("GDDP Current", "GDDP Constant", "NDDP Current", "NDDP Constant")]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, *, verify: bool = True) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        log.info("cached      %s", dest.name)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with requests.get(url, stream=True, timeout=600, verify=verify) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    tmp.replace(dest)
    log.info("downloaded  %s  %.1f MB in %.0f s", dest.name, dest.stat().st_size / 1e6, time.time() - t0)
    return dest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    manifest_p = OUT / "MANIFEST.json"
    manifest = json.loads(manifest_p.read_text(encoding="utf-8")) if manifest_p.exists() else {}
    failed = []

    # --- SHRUG -------------------------------------------------------------
    rows = requests.get(SHRUG_FEED, timeout=60).json()
    links: dict[str, str] = {}
    for r in rows:
        for key in ("primary_download", "secondary_download"):
            m = re.search(r"/([^/?]+\.zip)\?", r.get(key) or "")
            if m:
                links.setdefault(m.group(1), r[key])
    for name, what in SHRUG_FILES.items():
        if name not in links:
            log.error("not in the SHRUG feed: %s", name)
            failed.append(name)
            continue
        try:
            p = download(links[name], OUT / "shrug" / name)
            manifest[f"shrug/{name}"] = {
                "dataset": f"SHRUG v2 — {what}",
                "publisher": "Development Data Lab",
                "source": links[name].split("?")[0],
                "licence": "CC BY-NC-SA 4.0",
                "bytes": p.stat().st_size, "sha256": sha256(p),
                "downloaded": manifest.get(f"shrug/{name}", {}).get("downloaded", date.today().isoformat()),
            }
        except Exception as exc:  # noqa: BLE001
            log.error("failed %s: %s", name, exc)
            failed.append(name)

    # --- UP District Domestic Product --------------------------------------
    # The DES site serves an incomplete certificate chain, which Python's
    # certificate check rejects. The files are fetched without that check and
    # their SHA-256 hashes are recorded instead, so a copy can be verified.
    requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
    for year, kind in UPDES_FILES:
        name = f"{year}_{kind.replace(' ', '_')}.xlsx"
        url = f"{UPDES_BASE}/{year}/{kind.replace(' ', '%20')}.xlsx"
        try:
            p = download(url, OUT / "updes" / name, verify=False)
            manifest[f"updes/{name}"] = {
                "dataset": f"District Domestic Product of Uttar Pradesh — {kind}, release {year.replace('_', '-')}",
                "publisher": "Directorate of Economics & Statistics, Government of Uttar Pradesh",
                "source": url,
                "licence": "Government of Uttar Pradesh published statistics",
                "bytes": p.stat().st_size, "sha256": sha256(p),
                "downloaded": manifest.get(f"updes/{name}", {}).get("downloaded", date.today().isoformat()),
            }
        except Exception as exc:  # noqa: BLE001
            log.error("failed %s: %s", name, exc)
            failed.append(name)

    OUT.mkdir(parents=True, exist_ok=True)
    manifest_p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("manifest -> %s (%d files)", manifest_p, len(manifest))
    if failed:
        log.error("%d download(s) failed: %s", len(failed), ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
