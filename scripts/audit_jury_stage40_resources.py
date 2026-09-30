"""Offline raw-usage audit; no API calls and no changes to the budget ledger."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".private_evidence/jury_stage39_large_live"
PRIOR = ROOT / "artifacts/jury_revision_stage39_2026-09-29/analysis.json"
RATES = {"peak": (0.006, 0.30, 1.20), "off_peak": (0.003, 0.15, 0.60)}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def price(usage, created):
    inp, out = usage["prompt_tokens"], usage["completion_tokens"]
    hit, miss = usage["prompt_cache_hit_tokens"], usage["prompt_cache_miss_tokens"]
    assert all(type(v) is int and v >= 0 for v in (inp, out, hit, miss))
    assert hit + miss == inp and usage["total_tokens"] == inp + out
    if "cached_tokens" in usage.get("prompt_tokens_details", {}):
        assert usage["prompt_tokens_details"]["cached_tokens"] == hit
    dt = datetime.fromtimestamp(created, UTC)
    peak = dt.weekday() < 5 and (1 <= dt.hour < 4 or 6 <= dt.hour < 10)
    rate_name = "peak" if peak else "off_peak"
    a, b, c = RATES[rate_name]
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "rate_period": rate_name,
        "created_utc": dt.isoformat(),
        "cache_aware_tariff_estimate_usd": (hit * a + miss * b + out * c) / 1e6,
        "peak_cache_aware_estimate_usd": (hit * 0.006 + miss * 0.30 + out * 1.20) / 1e6,
        "old_uncached_peak_upper_usd": (inp * 0.30 + out * 1.20) / 1e6,
    }


def main(output):
    prior = read(PRIOR)
    for name, expected in prior["source_hashes"].items():
        assert sha(Path(name)) == expected, name
    if output.exists():
        raise ValueError("Use a new output directory")
    sources = {str(PRIOR): sha(PRIOR), str(Path(__file__)): sha(Path(__file__))}
    rows, all_calls = [], []
    for old in prior["rows"]:
        key = old["case_id"] + "__" + old["method"]
        folder = DATA / "runs" / key
        native = old["method"] == "OPENCODE_BUILD_TYPED"
        paths = (
            sorted((folder / "cli/gateway").glob("*-native-response.bin"))
            if native
            else sorted((folder / "raw").glob("*-response.json"))
        )
        calls = []
        for p in paths:
            response = read(p)
            if not response.get("usage"):
                raise ValueError(f"Missing usage: {p}")
            row = price(response["usage"], response["created"])
            row.update(source_file=str(p), case_id=old["case_id"], method=old["method"])
            sources[str(p)] = sha(p)
            calls.append(row)
        assert len(calls) == old["calls"], (key, len(calls), old["calls"])
        fields = [
            "input_tokens",
            "output_tokens",
            "cache_hit_tokens",
            "cache_miss_tokens",
            "cache_aware_tariff_estimate_usd",
            "peak_cache_aware_estimate_usd",
            "old_uncached_peak_upper_usd",
        ]
        totals = {f: sum(r[f] for r in calls) for f in fields}
        assert totals["input_tokens"] + totals["output_tokens"] == old["tokens"]
        assert abs(totals["old_uncached_peak_upper_usd"] - old["cost_usd"]) < 1e-8
        details = dict(
            input_share=totals["input_tokens"] / old["tokens"],
            input_cache_hit_share=totals["cache_hit_tokens"] / totals["input_tokens"],
            first_prompt_tokens=calls[0]["input_tokens"],
            last_prompt_tokens=calls[-1]["input_tokens"],
            max_prompt_tokens=max(r["input_tokens"] for r in calls),
            rate_periods=dict(Counter(r["rate_period"] for r in calls)),
        )
        if native:
            ep = folder / "cli/events.jsonl"
            sources[str(ep)] = sha(ep)
            events = [json.loads(s) for s in ep.read_text().splitlines()]
            tools = [e["part"] for e in events if e.get("type") == "tool_use"]
            details["tool_counts"] = dict(Counter(t["tool"] for t in tools))
            details["tool_statuses"] = dict(Counter(t["state"]["status"] for t in tools))
            details["event_types"] = dict(Counter(e["type"] for e in events))
        rows.append(
            dict(
                case_id=old["case_id"],
                method=old["method"],
                status=old["status"],
                fr_count=old["fr_count"],
                calls=len(calls),
                **totals,
                **details,
            )
        )
        all_calls.extend(calls)
    # Select the same requirements for each method before inspecting their texts.
    groups = {}
    for r in prior["rows"]:
        groups.setdefault(r["case_id"], []).append(r)
    eligible = sorted(
        c
        for c, rs in groups.items()
        if len(rs) == 2 and all(r["readable"] and r["status"] != "series_cost_limit" for r in rs)
    )
    inputs = read(DATA / "inputs.json")
    sources[str(DATA / "inputs.json")] = sha(DATA / "inputs.json")
    cards, selection = [], {}
    for cid in eligible:
        frs = inputs[cid]["request"]["functional_requirements"]
        sampled = sorted(
            frs,
            key=lambda f: hashlib.sha256(
                ("stage40-chain-review-v1:" + cid + ":" + f["id"]).encode()
            ).hexdigest(),
        )[:3]
        selection[cid] = [f["id"] for f in sampled]
        for fr in sampled:
            for row in sorted(groups[cid], key=lambda r: r["method"]):
                key = cid + "__" + row["method"]
                cp = PRIOR.parent / "chains" / (key + ".json")
                audit = read(cp)
                sources[str(cp)] = sha(cp)
                chains = [
                    x
                    for x in audit["chains"]
                    if x["fr_id"] == fr["id"] and x["element_type"] == "action"
                ]
                cards.append(
                    dict(
                        card_id=key + "__" + fr["id"],
                        case_id=cid,
                        method=row["method"],
                        fr=fr,
                        action_chains=chains,
                        reviewer="unreviewed",
                        label=None,
                    )
                )
    out = dict(
        paid_calls=0,
        ledger_changed=False,
        bank_statement=False,
        tariff_source="https://api-docs.deepseek.com/quick_start/pricing/",
        tariff_checked_date="2026-09-29",
        rates_per_million=RATES,
        tariff_assumption="provider-created UTC timestamp; published rate, not billing receipt",
        eligible_case_ids=eligible,
        source_hashes=sources,
        rows=rows,
        review_selection=selection,
        review_scope="3 FR per eligible project, paired; convenience projects, AI review only",
    )
    output.mkdir(parents=True)
    for name, value in [
        ("resource_audit.json", out),
        ("calls.json", all_calls),
        ("review_cards.json", cards),
    ]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                calls=len(all_calls),
                eligible=eligible,
                selection=selection,
                costs=[
                    {
                        k: r[k]
                        for k in (
                            "case_id",
                            "method",
                            "old_uncached_peak_upper_usd",
                            "cache_aware_tariff_estimate_usd",
                        )
                    }
                    for r in rows
                ],
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    main(parser.parse_args().output)
