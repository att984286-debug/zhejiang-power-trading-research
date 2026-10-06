import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.decision_sandbox.support import ROOT, storage_input, generation_input


class Isolation(unittest.TestCase):
    def test_imports_have_no_old_runtime_or_optional_dependencies(self):
        bad = ("src", "presentation", "streamlit", "pandas", "numpy", "pulp", "highspy", "requests")
        for folder in ("decision_core", "sandbox_display"):
            for path in (ROOT / folder).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules = [n.name for n in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        modules = [node.module or ""]
                    else:
                        continue
                    self.assertFalse(any(m.split(".")[0] in bad for m in modules), (path.name, modules))

    def test_clean_directory_import_and_normalization_with_io_blocked(self):
        with tempfile.TemporaryDirectory(prefix="sandbox-s1-isolation-") as folder:
            clean = Path(folder)
            for name in ("decision_core", "sandbox_display"):
                target = clean / name
                target.mkdir()
                for path in (ROOT / name).glob("*.py"):
                    shutil.copyfile(path, target / path.name)
            payload = json.dumps({"storage": storage_input(), "generation": generation_input()})
            code = r'''
import sys, os, pathlib, json, dataclasses, decimal, datetime, enum, hashlib, re, typing, socket
from unittest.mock import patch
root, payload = sys.argv[1], json.loads(sys.argv[2])
sys.path[:] = [root] + [p for p in sys.path if p and "site-packages" not in p]
def deny(*a, **k): raise AssertionError("forbidden data/environment/network access")
def audit(event, args):
    if event.startswith("socket."): deny()
    if event == "open":
        path = args[0]
        if not isinstance(path, str) or not path.startswith(root + os.sep) or not path.endswith((".py", ".pyc")):
            deny()
sys.addaudithook(audit)
with patch("builtins.open", deny), patch("pathlib.Path.open", deny), patch("os.getenv", deny), patch.object(os, "environ", {}):
    from decision_core.presets import storage_quick, generation_quick
    from sandbox_display.zh import STRATEGIES
    a, b = storage_quick(payload["storage"]), generation_quick(payload["generation"])
    assert len(a.prices) == 6 and len(b.scenarios) == 6
    assert a.budget_record.used_cycles is None
    assert "src" not in sys.modules and "pulp" not in sys.modules and "highspy" not in sys.modules
    print("isolated-normalization-pass")
'''
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(clean), payload],
                                    cwd=clean, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("isolated-normalization-pass", result.stdout)

    def test_publication_whitelist_is_not_whole_project(self):
        data = json.loads((ROOT / "sandbox_specs/publication_v1.json").read_text())
        self.assertTrue(data["deny_anything_else"])
        self.assertNotIn("src/*.py", data["allow_source_globs"])
        self.assertIn("public_ui/schema.py", data["existing_public_objects_immutable"])
        self.assertEqual(data["runtime"]["storage_solver"], "HiGHS_only_no_fallback")

