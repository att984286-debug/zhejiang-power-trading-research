from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from decision_core.contracts import RunStatus, canonical
from decision_core.presets import storage_quick
from sandbox_compute import storage_runner
from tests.decision_sandbox.support import ROOT, storage_input


def slow_worker(connection, request, run_id, at):
    time.sleep(10)
    connection.close()


def broken_worker(connection, request, run_id, at):
    connection.close()


def partial_message_worker(connection, request, run_id, at):
    import os, struct
    os.write(connection.fileno(), struct.pack("!i",1000000))
    time.sleep(10)
    connection.close()


class RunnerAndIsolation(unittest.TestCase):
    def test_spawn_computes_and_returns_input_bound_result(self):
        r=storage_quick(storage_input())
        out=storage_runner.run_storage(r)
        self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(out.output.metadata.input_sha256,r.input_sha256)
        self.assertTrue(out.advice.available)
        self.assertTrue(all(p.plan.physical_check_passed for p in out.computed_plans))

    def test_wall_timeout_terminates_owned_process_no_zero_result(self):
        r=storage_quick(storage_input())
        start=time.monotonic()
        out=storage_runner._isolated(r,"timeout-test",datetime.now(timezone.utc),worker=slow_worker,wall_time=0.2)
        self.assertLess(time.monotonic()-start,3)
        self.assertEqual(out.output.metadata.status,RunStatus.TIME_LIMIT)
        self.assertFalse(out.advice.available)
        self.assertFalse(out.output.plans)

    def test_child_exit_is_not_zero_or_old_result(self):
        out=storage_runner._isolated(storage_quick(storage_input()),"child-error",datetime.now(timezone.utc),worker=broken_worker,wall_time=1)
        self.assertEqual(out.output.metadata.status,RunStatus.SOLVER_ERROR)
        self.assertFalse(out.output.plans)
        self.assertNotIn("/Users",canonical(out))

    def test_partial_ipc_message_cannot_bypass_wall_limit(self):
        r=storage_quick(storage_input())
        start=time.monotonic()
        out=storage_runner._isolated(r,"partial-message",datetime.now(timezone.utc),worker=partial_message_worker,wall_time=0.2)
        self.assertLess(time.monotonic()-start,3)
        self.assertEqual(out.output.metadata.status,RunStatus.TIME_LIMIT)
        self.assertFalse(out.output.plans)

    def test_busy_gate_returns_without_process_or_cross_session_result(self):
        r=storage_quick(storage_input())
        self.assertTrue(storage_runner._GATE.acquire(False))
        self.assertTrue(storage_runner._GATE.acquire(False))
        try:
            out=storage_runner.run_storage(r)
            self.assertEqual(out.output.metadata.status,RunStatus.BUSY)
            self.assertFalse(out.output.plans)
            self.assertFalse(out.advice.available)
        finally:
            storage_runner._GATE.release(); storage_runner._GATE.release()

    def test_two_different_sessions_no_shared_input_or_result(self):
        a=storage_quick(storage_input())
        value=storage_input(); value["current_soc_percent"]="40"
        b=storage_quick(value)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second=list(pool.map(storage_runner.run_storage,(a,b)))
        self.assertEqual(first.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(second.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(first.output.metadata.input_sha256,a.input_sha256)
        self.assertEqual(second.output.metadata.input_sha256,b.input_sha256)
        self.assertNotEqual(first.output.metadata.input_sha256,second.output.metadata.input_sha256)
        self.assertNotEqual(first.output.metadata.run_id,second.output.metadata.run_id)

    def test_clean_core_and_adapter_compute_without_private_files_or_network(self):
        with tempfile.TemporaryDirectory(prefix="sandbox-s2-clean-") as folder:
            clean=Path(folder)
            for name in ("decision_core","sandbox_compute"):
                (clean/name).mkdir()
                for p in (ROOT/name).glob("*.py"):
                    shutil.copyfile(p,clean/name/p.name)
            payload=json.dumps(storage_input())
            code=r'''
import sys, pathlib, json, socket, os
from datetime import datetime,timezone
from unittest.mock import patch
root,payload=sys.argv[1],json.loads(sys.argv[2])
sys.path.insert(0,root)
import pulp, highspy
def deny(*a,**kw): raise AssertionError("private/network access prohibited")
allowed=[str(pathlib.Path(root).resolve()),str(pathlib.Path(sys.prefix).resolve()),str(pathlib.Path(sys.base_prefix).resolve())]
def audit(event,args):
    if event.startswith("socket."): deny()
    if event == "open" and isinstance(args[0],str):
        p=str(pathlib.Path(args[0]).resolve())
        if not any(p.startswith(a+os.sep) for a in allowed): deny()
sys.addaudithook(audit)
with patch("os.getenv",deny),patch.object(os,"environ",{}),patch("socket.create_connection",deny):
    from decision_core.presets import storage_quick
    from decision_core.storage_calculation import calculate_storage
    from sandbox_compute.highs_adapter import highs_backend
    result=calculate_storage(storage_quick(payload),highs_backend,run_id="clean-s2",computed_at_utc=datetime.now(timezone.utc))
    assert result.advice.available, result.advice
    assert "src" not in sys.modules and "presentation" not in sys.modules
    print("clean-actual-compute-pass")
'''
            run=subprocess.run([sys.executable,"-I","-B","-c",code,str(clean),payload],cwd=clean,
                               capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr+run.stdout)
            self.assertIn("clean-actual-compute-pass",run.stdout)


if __name__=="__main__":
    unittest.main()
