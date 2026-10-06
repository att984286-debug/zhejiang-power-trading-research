"""Second boundary for live user scenarios; does not relax the replay schema."""
from pathlib import Path
import ast
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_public import inspect_tree


def inspect_release():
    original = inspect_tree(ROOT)
    findings = list(original["findings"])
    mapping = json.loads((ROOT / "SANDBOX_SOURCE_MAP.json").read_text())
    for row in mapping["frozen_source_mapping"]:
        p = ROOT / row["destination"]
        if hashlib.sha256(p.read_bytes()).hexdigest() != row["published_sha256"]:
            findings.append({"file": row["destination"], "reason": "published_source_hash_changed"})
        if row["destination"].startswith(("decision_core/", "sandbox_compute/", "sandbox_display/", "sandbox_ui/")):
            if row["source_sha256"] != row["published_sha256"]:
                findings.append({"file": row["destination"], "reason": "frozen_runtime_was_modified"})
    blocked = {"src", "presentation", "data", "private", "knowledge_base", "manifests"}
    for name in blocked:
        if (ROOT / name).exists():
            findings.append({"file": name, "reason": "private_runtime_directory"})
    for folder in ("decision_core", "sandbox_compute"):
        for p in (ROOT / folder).glob("*.py"):
            for node in ast.walk(ast.parse(p.read_text())):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    modules = [x.name for x in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    if any(x.split(".")[0] in {"src", "presentation", "requests", "streamlit"} for x in modules):
                        findings.append({"file": str(p.relative_to(ROOT)), "reason": "compute_data_or_ui_coupling"})
    text = (ROOT / "app.py").read_text()
    if "sys.path.append" in text or "power-trading-research-web" in text:
        findings.append({"file": "app.py", "reason": "local_sibling_binding"})
    return {"status": "PASS" if not findings else "FAIL", "files_checked": original["files"],
        "frozen_source_files": len(mapping["frozen_source_mapping"]), "findings": findings,
        "replay_artifacts": 205, "replay_business_recalculated": False,
        "sandbox_inputs": "bounded_user_supplied_scenario_only", "formal_non_inference_claim": False}


if __name__ == "__main__":
    report = inspect_release()
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)
