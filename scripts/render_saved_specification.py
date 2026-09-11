"""Re-render Mermaid files from a saved GeneratedSpecification artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from traceable_spec.entities import GeneratedSpecification
from traceable_spec.mermaid import render_mermaid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("specification", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    specification = GeneratedSpecification.model_validate(
        json.loads(args.specification.read_text(encoding="utf-8"))
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for result in specification.activity_results:
        if result.activity_diagram is None:
            continue
        path = args.output_dir / f"{result.activity_diagram.id}.mmd"
        path.write_text(render_mermaid(result.activity_diagram), encoding="utf-8")
        written += 1
    print(f"Rendered {written} Mermaid sources into {args.output_dir}")


if __name__ == "__main__":
    main()
