"""Release-only qualification: no private directories and unchanged inputs."""
import hashlib
import io
import json
from pathlib import Path
import ast
import pytest
from openpyxl import load_workbook

from scripts.audit_sandbox_release import inspect_release
from public_ui.package import PublicPackage
from sandbox_ui.exports import workbook

ROOT = Path(__file__).resolve().parents[1]


def test_public_replay_still_205_and_not_recalculated():
    p = PublicPackage(ROOT)
    assert p.all_valid() == 205
    assert p.manifest["business_recalculated"] is False
    assert p.anchor["manifest_sha256"] == "71b96f80cb9c62d306c5585391357fdbde6ced29fdc287233b938baf8db1578b"


def test_new_compute_files_identical_to_frozen_source():
    m = json.loads((ROOT / "SANDBOX_SOURCE_MAP.json").read_text())
    for row in m["frozen_source_mapping"]:
        assert hashlib.sha256((ROOT / row["destination"]).read_bytes()).hexdigest() == row["published_sha256"]
        if row["destination"].startswith(("decision_core/", "sandbox_compute/", "sandbox_display/", "sandbox_ui/")):
            assert row["source_sha256"] == row["published_sha256"]


def test_release_audits_old_and_new_boundaries_together():
    assert inspect_release()["findings"] == []


def test_entry_has_no_local_directory_binding():
    s = (ROOT / "app.py").read_text()
    assert "sys.path" not in s
    assert "power-trading-research-web" not in s
    assert not any((ROOT / p).exists() for p in ("src", "presentation", "data", "private", "knowledge_base"))


@pytest.mark.parametrize("text", ["=SUM(A1:A5)", "+cmd", "@SUM(A1)", "-10", "0"])
def test_download_strings_never_become_excel_formulas(text):
    data = workbook({"业务": [{"内容": text}]})
    sheet = load_workbook(io.BytesIO(data), data_only=False).active
    assert sheet["A2"].data_type == "s"
    assert sheet["A2"].value == text


def test_compute_has_no_files_network_or_case_replay_imports():
    for folder in ("decision_core", "sandbox_compute"):
        for p in (ROOT / folder).glob("*.py"):
            for node in ast.walk(ast.parse(p.read_text())):
                if isinstance(node, ast.Import):
                    names = [x.name.split(".")[0] for x in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                assert not (set(names) & {"public_ui", "src", "presentation", "requests", "streamlit"})
