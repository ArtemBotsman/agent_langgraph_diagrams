"""Verify that a saved experiment reproduces its aggregate metrics offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from traceable_spec.evaluation.reproducibility import verify_saved_experiment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dir", type=Path)
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    report = verify_saved_experiment(args.experiment_dir)
    if args.write_report:
        (args.experiment_dir / "reproducibility_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
