from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from urbanintel.config import load_config  # noqa: E402

log = logging.getLogger("ablations")

# Each run changes exactly one thing against the run above it, so the table
# reads as a sequence of single questions rather than a pile of settings.
RUNS = [
    ("drivers_1transition_1date",
     ["--source", "drivers", "--single-transition"],
     "the first run: driver maps, one transition, one date"),
    ("drivers_alltransitions",
     ["--source", "drivers"],
     "does another labelled transition help?"),
    ("landsat_1transition",
     ["--source", "landsat", "--single-transition"],
     "does real imagery beat derived driver maps?"),
    ("landsat_alltransitions",
     ["--source", "landsat"],
     "imagery and every transition together"),
    ("landsat_prithvi",
     ["--source", "landsat", "--encoder", "prithvi", "--cache-encoder"],
     "does a pretrained satellite transformer beat one trained from scratch?"),
]


def usage() -> str:
    return "Run the image model across its ablations and tabulate the results."


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=usage())
    ap.add_argument("--only", nargs="+", default=None,
                    help="run just these named configurations")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--skip-existing", action="store_true",
                    help="keep results already on disk instead of re-running")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = load_config()
    runs = [r for r in RUNS if not args.only or r[0] in args.only]

    rows = []
    for name, flags, question in runs:
        out = cfg.outputs_dir / f"{cfg.city_slug}_image_model_{name}.json"
        if args.skip_existing and out.exists():
            log.info("%s: keeping the result already on disk", name)
        else:
            cmd = [sys.executable, str(ROOT / "scripts" / "train_image_model.py"),
                   *flags, "--epochs", str(args.epochs), "--seed", str(args.seed),
                   "--tag", name]
            log.info("%s — %s", name, question)
            t0 = time.time()
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            if proc.returncode != 0:
                tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-3:]
                log.error("%s failed: %s", name, " | ".join(tail))
                rows.append({"run": name, "question": question, "failed": True})
                continue
            log.info("  finished in %.1f min", (time.time() - t0) / 60)
        if not out.exists():
            continue
        d = json.loads(out.read_text(encoding="utf-8"))
        a, m = d["analytics"], d["model"]
        rows.append({
            "run": name,
            "question": question,
            "source": m["source"],
            "encoder": m["config"]["encoder"],
            "resolution_m": d["working_grid"]["resolution_m"],
            "training_transitions": d["training_transitions"],
            "input_dates": m["n_dates"],
            "parameters": m["parameters"],
            "trainable": m["trainable_parameters"],
            "auc_test": a["auc_test"],
            "average_precision": a["average_precision"],
            "figure_of_merit": a["validation"]["figure_of_merit"],
            "figure_of_merit_rank_only": a["ranking_only"]["figure_of_merit"],
            "hits": a["validation"]["hits"],
            "runtime_min": round(d["runtime_s"] / 60, 1),
        })

    payload = {"runs": rows,
               "baseline": {"random_forest_figure_of_merit": 0.1016,
                            "random_forest_auc": 0.8331,
                            "note": ("the Review 3 forest, re-run on this machine; the "
                                     "recorded Review 3 value was 0.1031 on an earlier "
                                     "scikit-learn")}}
    dest = cfg.outputs_dir / f"{cfg.city_slug}_ablations.json"
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n" + "=" * 104)
    print("ABLATIONS - image model, held-out 2015-2020")
    print("=" * 104)
    print(f"  {'run':32s} {'res':>5s} {'dates':>6s} {'trans':>6s} {'params':>10s} "
          f"{'AUC':>7s} {'AP':>7s} {'FoM':>7s} {'rank':>7s} {'min':>6s}")
    for r in rows:
        if r.get("failed"):
            print(f"  {r['run']:32s} failed")
            continue
        print(f"  {r['run']:32s} {int(r['resolution_m']):5d} {r['input_dates']:6d} "
              f"{len(r['training_transitions']):6d} {r['parameters']:10,d} "
              f"{r['auc_test']:7.4f} {r['average_precision']:7.4f} "
              f"{r['figure_of_merit']:7.4f} {r['figure_of_merit_rank_only']:7.4f} "
              f"{r['runtime_min']:6.1f}")
    print(f"  {'random forest (Review 3 design)':32s} {100:5d} {1:6d} {1:6d} "
          f"{'':10s} {0.8331:7.4f} {0.1270:7.4f} {0.1016:7.4f} {0.1087:7.4f}")
    print(f"\n  summary  {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
