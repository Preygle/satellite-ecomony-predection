from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from urbanintel.config import load_config  # noqa: E402

# The Review 3 forest, re-run on this machine. The recorded Review 3 value was
# 0.1031 on an earlier scikit-learn; see docs/DEEP_MODELS.md section 8.
BASELINE = {"model": "random forest (Review 3)", "figure_of_merit": 0.1016,
            "auc": 0.8331, "hits": 224}


def usage() -> str:
    return "Tabulate every image-model run that has been recorded, side by side."


def main() -> int:
    cfg = load_config()
    rows = []
    for p in sorted(cfg.outputs_dir.glob(f"{cfg.city_slug}_image_model*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        m, a = d["model"], d["analytics"]
        rows.append({
            "run": p.stem.replace(f"{cfg.city_slug}_image_model", "").lstrip("_") or "primary",
            "source": m["source"],
            "resolution_m": int(d.get("working_grid", {}).get("resolution_m", 100)),
            "stopping": d.get("validation_design", "spatial blocks"),
            "trained_on": ", ".join(d.get("training_transitions", [])),
            "widths": m["config"]["widths"],
            "dropout": m["config"]["dropout"],
            "parameters": m["parameters"],
            "epochs_run": len(m["history"]),
            "best_epoch": m["best_epoch"],
            "val_average_precision": m["validation_average_precision"],
            "test_auc": a["auc_test"],
            "test_average_precision": a["average_precision"],
            "test_figure_of_merit": a["validation"]["figure_of_merit"],
            "test_hits": a["validation"]["hits"],
            "runtime_min": round(d["runtime_s"] / 60, 1),
        })

    out = {
        "runs": rows,
        "baseline": BASELINE,
        "caveat": ("The 2015-2020 period has been scored once per run listed here. "
                   "That makes it a fair measure of any single pre-specified design "
                   "and NOT a clean hold-out for choosing between designs. The "
                   "stopping rule was chosen on principle and the capacity on the "
                   "validation score; everything else in this table is exploratory "
                   "and should be reported as such."),
    }
    dest = cfg.outputs_dir / f"{cfg.city_slug}_image_runs.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("=" * 118)
    print("IMAGE MODEL RUNS - every configuration recorded, scored on the held-out "
          "2015-2020")
    print("=" * 118)
    print(f"  {'run':18s} {'res':>4s} {'stopping':>22s} {'params':>9s} {'ep':>4s} "
          f"{'val AP':>7s} {'AUC':>7s} {'AP':>7s} {'FoM':>7s} {'hits':>5s}")
    for r in sorted(rows, key=lambda x: -(x["test_figure_of_merit"] or 0)):
        print(f"  {r['run']:18s} {r['resolution_m']:4d} {str(r['stopping'])[:22]:>22s} "
              f"{r['parameters']:9,d} {r['best_epoch']:4d} "
              f"{(r['val_average_precision'] or 0):7.4f} {(r['test_auc'] or 0):7.4f} "
              f"{(r['test_average_precision'] or 0):7.4f} "
              f"{(r['test_figure_of_merit'] or 0):7.4f} {(r['test_hits'] or 0):5d}")
    print(f"  {BASELINE['model']:18s} {100:4d} {'':>22s} {'':9s} {'':4s} {'':7s} "
          f"{BASELINE['auc']:7.4f} {'':7s} {BASELINE['figure_of_merit']:7.4f} "
          f"{BASELINE['hits']:5d}")
    print(f"\n  {out['caveat']}")
    print(f"\n  written to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
