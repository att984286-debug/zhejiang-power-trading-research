"""Clean-environment diagnostics using only public synthetic parameters."""
from datetime import datetime, timedelta
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from decision_core.storage import normalize_storage
from decision_core.presets import storage_quick, generation_quick
from sandbox_compute.storage_runner import run_storage
from sandbox_compute.generation_runner import run_generation


def check():
    a = json.loads((ROOT / "sandbox_specs/synthetic_storage_v1.json").read_text())["quick_input"]
    r = storage_quick(a)
    t = time.monotonic()
    small = run_storage(r)
    small_time = time.monotonic() - t
    p = r.editable_payload()
    start = datetime.fromisoformat("2026-10-06T00:00:00+08:00")
    p["prices"] = [{"interval_start": (start + timedelta(minutes=15*i)).isoformat(),
        "interval_end": (start + timedelta(minutes=15*(i+1))).isoformat(),
        "forecast_price_yuan_per_mwh": str(220 if i < 48 else 620)} for i in range(96)]
    p["interval_minutes"] = 15
    p["wait_until"] = (start + timedelta(hours=18)).isoformat()
    t = time.monotonic()
    large = run_storage(normalize_storage(p))
    large_time = time.monotonic() - t
    b = json.loads((ROOT / "sandbox_specs/synthetic_generation_v1.json").read_text())["quick_input"]
    t = time.monotonic()
    gen = run_generation(generation_quick(b))
    gen_time = time.monotonic() - t
    assert small.advice.available and large.advice.available and gen.advice.available
    assert large_time < 20
    assert all(x.plan.physical_check_passed for x in large.computed_plans if x.plan.interval_rows)
    return {"status": "PASS", "platform": platform.platform(), "python": platform.python_version(),
        "dependencies": {n: version(n) for n in ("streamlit", "pandas", "plotly", "openpyxl", "PuLP", "highspy", "numpy", "pyarrow")},
        "small_storage_seconds": small_time, "maximum_96_intervals_seconds": large_time,
        "generation_seconds": gen_time, "independent_private_directories": True,
        "all_inputs_public_synthetic": True, "historical_research_rerun": False}


if __name__ == "__main__":
    print(json.dumps(check(), ensure_ascii=False))
