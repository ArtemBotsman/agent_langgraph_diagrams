"""Read-only full-chain structure audit, independent of pipeline acceptance.

These are referential coverage rates, NOT semantic precision or Gold F1.
Source IDs may have been inherited by the importer; never certify them as
explicit model evidence. Export the text of each chain for separate review.
"""

from collections import Counter


def steps_of(uc):
    scenarios = [
        uc["main_success_scenario"],
        *uc.get("alternative_scenarios", []),
        *uc.get("exception_scenarios", []),
    ]
    return [s for scenario in scenarios for s in scenario["steps"]]


def reach(starts, adjacency):
    seen, todo = set(), list(starts)
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo.extend(adjacency.get(node, ()))
    return seen


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


def audit_chain(spec):
    """Audit saved declared references without modifying or filling any field."""
    fr = {r["id"]: r["text"] for r in spec["request"]["functional_requirements"]}
    ucs = (spec.get("use_case_set") or {}).get("use_cases", [])
    diagrams = [
        r["activity_diagram"]
        for r in spec.get("activity_results", [])
        if r.get("activity_diagram") is not None
    ]
    uc_counts = Counter(u["id"] for u in ucs)
    step_counts = Counter(s["id"] for u in ucs for s in steps_of(u))
    diagram_counts = Counter(d["use_case_id"] for d in diagrams)
    elements = [n["id"] for d in diagrams for n in [*d["nodes"], *d["edges"]]]
    element_counts = Counter(elements)
    issues, chains, step_rows = [], [], []
    fr_uc, fr_chain, covered_steps = set(), set(), set()
    business_total = business_traced = 0
    for uc in ucs:
        uid = uc["id"]
        steps = {s["id"]: s for s in steps_of(uc) if step_counts[s["id"]] == 1}
        scoped_fr = set(uc.get("source_fr_ids", [])) & fr.keys()
        if uc_counts[uid] == 1:
            fr_uc.update(scoped_fr)
        ds = [d for d in diagrams if d["use_case_id"] == uid]
        if len(ds) != 1:
            issues.append(dict(kind="diagram_count", uc_id=uid, actual=len(ds), expected=1))
        for d in ds:
            nodes = {n["id"]: n for n in d["nodes"]}
            forward, reverse = {}, {}
            for edge in d["edges"]:
                a, b = edge["source_node_id"], edge["target_node_id"]
                if a in nodes and b in nodes:
                    forward.setdefault(a, []).append(b)
                    reverse.setdefault(b, []).append(a)
                else:
                    issues.append(dict(kind="dangling_edge", element_id=edge["id"]))
            reachable = reach([n["id"] for n in d["nodes"] if n["kind"] == "initial"], forward)
            terminating = reach([n["id"] for n in d["nodes"] if n["kind"] == "final"], reverse)
            for element in [*d["nodes"], *d["edges"]]:
                is_node = "kind" in element
                business = (
                    element["kind"] in {"action", "decision", "object"}
                    if is_node
                    else bool(element.get("guard") or element.get("label"))
                )
                if not business:
                    continue
                business_total += 1
                endpoints = (
                    [element["id"]]
                    if is_node
                    else [element["source_node_id"], element["target_node_id"]]
                )
                path_ok = all(x in reachable and x in terminating for x in endpoints)
                refs = element.get("related_step_ids", [])
                refs_ok = bool(refs) and all(s in steps for s in refs)
                unique = (
                    uc_counts[uid] == 1
                    and diagram_counts[uid] == 1
                    and element_counts[element["id"]] == 1
                )
                valid_chain = False
                for sid in refs:
                    if sid not in steps:
                        issues.append(
                            dict(
                                kind="wrong_step_owner_or_id", element_id=element["id"], step_id=sid
                            )
                        )
                        continue
                    step = steps[sid]
                    declared = set(step.get("source_fr_ids", []))
                    sources_ok = bool(declared) and declared <= scoped_fr
                    if not (unique and path_ok and refs_ok and sources_ok) or element.get(
                        "unsupported"
                    ):
                        continue
                    valid_chain = True
                    for fid in sorted(declared):
                        chains.append(
                            dict(
                                fr_id=fid,
                                fr_text=fr[fid],
                                uc_id=uid,
                                uc_name=uc["name"],
                                step_id=sid,
                                step_text=step["action"],
                                expected_result=step.get("expected_result"),
                                diagram_id=d["id"],
                                element_id=element["id"],
                                element_type=element.get("kind", "edge"),
                                element_text=element.get("name")
                                or element.get("label")
                                or element.get("guard"),
                                semantic_support="not_reviewed",
                                source_provenance="saved_artifact_may_include_inherited_references",
                            )
                        )
                        # A mere decision/edge is not an implementation action.
                        if is_node and element["kind"] == "action":
                            fr_chain.add(fid)
                            covered_steps.add(sid)
                business_traced += int(valid_chain)
                if not valid_chain:
                    issues.append(
                        dict(kind="untraced_business_element", element_id=element["id"], uc_id=uid)
                    )
        for s in steps_of(uc):
            ok = s["id"] in covered_steps
            step_rows.append(
                dict(
                    uc_id=uid,
                    step_id=s["id"],
                    action=s["action"],
                    has_action_chain=ok,
                    source_fr_ids=s.get("source_fr_ids", []),
                )
            )
    for d in diagrams:
        if d["use_case_id"] not in uc_counts:
            issues.append(dict(kind="orphan_diagram", diagram_id=d["id"]))
            orphan_business = sum(n["kind"] in {"action", "decision", "object"} for n in d["nodes"])
            orphan_business += sum(bool(e.get("guard") or e.get("label")) for e in d["edges"])
            business_total += orphan_business
    return dict(
        version="chain-structure-audit-v1",
        semantic_truth_verified=False,
        fr_count=len(fr),
        uc_count=len(ucs),
        diagram_count=len(diagrams),
        fr_with_uc=len(fr_uc),
        fr_with_action_chain=len(fr_chain),
        fr_uc_coverage=rate(len(fr_uc), len(fr)),
        fr_action_chain_coverage=rate(len(fr_chain), len(fr)),
        steps_total=len(step_rows),
        steps_with_action_chain=sum(s["has_action_chain"] for s in step_rows),
        step_action_coverage=rate(sum(s["has_action_chain"] for s in step_rows), len(step_rows)),
        business_elements_total=business_total,
        business_elements_traced=business_traced,
        reverse_business_chain_coverage=rate(business_traced, business_total),
        missing_fr_chain_ids=sorted(fr.keys() - fr_chain),
        issues=issues,
        duplicate_step_ids=sorted(k for k, v in step_counts.items() if v > 1),
        chains=chains,
        steps=step_rows,
    )
