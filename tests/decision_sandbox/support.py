from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]


def fixture(name):
    return json.loads((ROOT / "sandbox_specs" / name).read_text(encoding="utf-8"))


def storage_input():
    return fixture("synthetic_storage_v1.json")["quick_input"]


def generation_input():
    return fixture("synthetic_generation_v1.json")["quick_input"]

