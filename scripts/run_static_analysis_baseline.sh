#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd "$script_dir/.." && pwd)
output_dir="$project_dir/artifacts/baselines/static_analysis_pyreverse"

mkdir -p "$output_dir"

cd "$project_dir"
poetry run pyreverse \
  --output mmd \
  --project traceable_spec_code_baseline \
  --source-roots src \
  --output-directory "$output_dir" \
  src/traceable_spec

echo "Static-analysis diagrams written to: $output_dir"
