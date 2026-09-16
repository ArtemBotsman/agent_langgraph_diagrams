"""Create two independent, output-blind review packages for the Gold candidate."""

from __future__ import annotations

import argparse
import csv
import html
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmark" / "size_scaling_v1"
FIELDS = (
    "expert_id",
    "case_id",
    "size_group",
    "project_name",
    "domain_plausibility_1_5",
    "actor_uc_boundaries_1_5",
    "scenario_completeness_1_5",
    "branch_correctness_1_5",
    "trace_correctness_1_5",
    "assumption_discipline_1_5",
    "decision_approve_or_revise",
    "comments",
)


def _list(items: list[str]) -> str:
    if not items:
        return '<p class="empty">Нет ожидаемых элементов.</p>'
    return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def _review_book(
    labels: list[dict[str, object]],
    benchmark_dir: Path,
    *,
    expert_number: int,
) -> str:
    sections: list[str] = []
    for item in labels:
        case_id = str(item["case_id"])
        input_path = next((benchmark_dir / "inputs").glob(f"*{case_id.split('-')[-1]}*.json"), None)
        if input_path is None:
            manifest = json.loads((benchmark_dir / "manifest.json").read_text(encoding="utf-8"))
            file_name = next(
                case["file"] for case in manifest["cases"] if case["case_id"] == case_id
            )
            input_path = benchmark_dir / "inputs" / file_name
        request = json.loads(input_path.read_text(encoding="utf-8"))
        gold = item["gold"]
        if not isinstance(gold, dict):
            raise TypeError(f"Gold must be an object for {case_id}")
        actors = [
            str(slot.get("canonical", ""))
            for slot in gold.get("actor_slots", [])
            if isinstance(slot, dict)
        ]
        uc_cards: list[str] = []
        for slot in gold.get("use_case_slots", []):
            if not isinstance(slot, dict):
                continue
            branches = [
                " / ".join(
                    [
                        str(branch.get("condition", "")),
                        *map(str, branch.get("required_outcomes", [])),
                    ]
                )
                for branch in slot.get("required_branches", [])
                if isinstance(branch, dict)
            ]
            uc_cards.append(
                "".join(
                    [
                        '<article class="uc">',
                        f"<h4>{html.escape(str(slot.get('slot_id', '')))} — "
                        f"{html.escape(str(slot.get('name', '')))}</h4>",
                        "<p><b>Основной актор:</b> "
                        f"{html.escape(str(slot.get('primary_actor', '')))}</p>",
                        "<p><b>ФТ:</b> "
                        f"{html.escape(', '.join(map(str, slot.get('source_fr_ids', []))))}</p>",
                        "<p><b>Обязательные этапы:</b></p>",
                        _list(list(map(str, slot.get("required_milestones", [])))),
                        "<p><b>Альтернативные/ошибочные ветви:</b></p>",
                        _list(branches),
                        "</article>",
                    ]
                )
            )
        functional = [str(value) for value in request.get("functional_requirements", [])]
        non_functional = [
            str(value) for value in request.get("non_functional_requirements", [])
        ]
        sections.append(
            "".join(
                [
                    f'<section id="{html.escape(case_id)}">',
                    f"<h2>{html.escape(case_id)} — {html.escape(str(item['project_name']))}</h2>",
                    f"<p><b>Группа:</b> {html.escape(str(item['size_group']))}; "
                    f"<b>ФТ:</b> {len(functional)}; <b>НФТ:</b> {len(non_functional)}</p>",
                    f"<p><b>Цель:</b> {html.escape(str(request.get('project_goal', '')))}</p>",
                    "<details><summary>Исходные функциональные требования</summary>",
                    _list(functional),
                    "</details>",
                    "<details><summary>Исходные нефункциональные требования</summary>",
                    _list(non_functional),
                    "</details>",
                    "<h3>Gold-кандидат</h3>",
                    "<p><b>Ожидаемые акторы:</b></p>",
                    _list(actors),
                    *uc_cards,
                    "<p><b>Известные неоднозначности:</b></p>",
                    _list(list(map(str, gold.get("known_ambiguity", [])))),
                    "<p><b>Запрещённые предположения:</b></p>",
                    _list(list(map(str, gold.get("forbidden_assumptions", [])))),
                    "</section>",
                ]
            )
        )
    body = "\n".join(sections)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Проверка Gold</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1100px;margin:32px auto;
line-height:1.45;color:#172033}}
h1,h2{{border-bottom:2px solid #1769aa;padding-bottom:8px}}
section{{margin:48px 0;page-break-before:always}}
.uc{{border:1px solid #aab4c3;border-left:5px solid #1769aa;padding:10px 16px;margin:12px 0}}
summary{{cursor:pointer;font-weight:700;margin:8px 0}}
.empty{{color:#687386}}li{{margin:4px 0}}
@media print{{details{{display:block}}details>summary{{display:none}}
details>*{{display:block!important}}}}
</style></head><body>
<h1>Независимая проверка Gold-кандидата</h1>
<p><b>Эксперт: EXPERT-{expert_number}.</b> В документе нет результатов one-shot или FULL и нет
названий сравниваемых условий. Проверяйте разметку только по исходным требованиям.</p>
<p>Итоговые оценки и комментарии внесите в CSV-форму из того же пакета.</p>
{body}
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    args = parser.parse_args()
    labels = json.loads(
        (args.benchmark_dir / "gold_candidate.json").read_text(encoding="utf-8")
    )
    output_dir = args.benchmark_dir / "expert_review"
    output_dir.mkdir(parents=True, exist_ok=True)
    for expert_number in (1, 2):
        path = output_dir / f"expert_{expert_number}_blank.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for item in labels:
                writer.writerow(
                    {
                        "expert_id": f"EXPERT-{expert_number}",
                        "case_id": item["case_id"],
                        "size_group": item["size_group"],
                        "project_name": item["project_name"],
                    }
                )
        package_dir = output_dir / f"expert_{expert_number}_package"
        package_dir.mkdir(parents=True, exist_ok=True)
        book_path = package_dir / "01_REVIEW_BOOK.html"
        book_path.write_text(
            _review_book(labels, args.benchmark_dir, expert_number=expert_number),
            encoding="utf-8",
        )
        guide_copy = package_dir / "00_INSTRUCTION_RU.md"
        guide_copy.write_text(
            (args.benchmark_dir / "GOLD_REVIEW_GUIDE_RU.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        form_copy = package_dir / f"02_EXPERT_{expert_number}_FORM.csv"
        form_copy.write_bytes(path.read_bytes())
        zip_path = output_dir / f"size_scaling_gold_review_expert_{expert_number}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member in sorted(package_dir.iterdir()):
                archive.write(member, arcname=member.name)
        print(path)
        print(zip_path)


if __name__ == "__main__":
    main()
