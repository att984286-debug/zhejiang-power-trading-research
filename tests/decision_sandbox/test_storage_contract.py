from copy import deepcopy
from decimal import Decimal
import unittest

from decision_core.errors import ContractError
from decision_core.presets import storage_quick
from decision_core.storage import normalize_storage
from tests.decision_sandbox.support import storage_input


class StorageContracts(unittest.TestCase):
    def request(self):
        return storage_quick(storage_input())

    def test_quick_advanced_exact_equivalence(self):
        a = self.request()
        b = normalize_storage(a.editable_payload())
        self.assertEqual(a.business_payload(), b.business_payload())
        self.assertEqual(a.input_sha256, b.input_sha256)

    def test_percent_not_double_divided(self):
        a = self.request()
        self.assertEqual(a.current_soc_ratio, Decimal("0.65"))
        self.assertEqual(a.terminal_soc_ratio, a.current_soc_ratio)

    def test_unknown_usage_not_invented(self):
        a = self.request()
        self.assertIsNone(a.budget_record.total_cycles)
        self.assertIsNone(a.budget_record.used_cycles)
        self.assertEqual(a.remaining_throughput_mwh, Decimal("240"))

    def test_equivalent_budget_same_business_hash(self):
        a = self.request()
        value = a.editable_payload()
        value["budget"] = {"mode": "total_minus_used", "total_cycles": "1", "used_cycles": "0.4"}
        b = normalize_storage(value)
        self.assertNotEqual(a.budget_record, b.budget_record)
        self.assertEqual(a.input_sha256, b.input_sha256)

    def test_capacity_change_recalculates_budget(self):
        value = self.request().editable_payload()
        value["energy_capacity_mwh"] = "400"
        self.assertEqual(normalize_storage(value).remaining_throughput_mwh, Decimal("480"))

    def test_end_is_23_not_22_or_midnight(self):
        self.assertEqual(self.request().prices[-1].interval_end.hour, 23)

    def test_no_preset_without_explicit_acceptance(self):
        value = storage_input()
        value["accept_preset"] = False
        with self.assertRaises(ContractError):
            storage_quick(value)

    def test_no_hidden_field(self):
        value = self.request().editable_payload()
        value["source_path"] = "not-supported"
        with self.assertRaises(ContractError):
            normalize_storage(value)

    def test_illegal_numeric_fields(self):
        for key, bads in {
            "energy_capacity_mwh": [0, -1, True, None, "nan", "1e50"],
            "charge_power_limit_mw": [0, -1, "Infinity", "10001"],
            "discharge_efficiency": [0, "0.009", "1.01", False],
            "degradation_cost_yuan_per_mwh_throughput": [-1, None, "NaN"],
            "current_soc_ratio": ["0.09", "0.91", 65],
        }.items():
            for bad in bads:
                with self.subTest(key=key, bad=bad):
                    value = self.request().editable_payload()
                    value[key] = bad
                    with self.assertRaises(ContractError):
                        normalize_storage(value)

    def test_bad_soc_boundaries(self):
        for low, high in (("0.9", "0.1"), ("0.5", "0.5")):
            value = self.request().editable_payload()
            value.update(min_soc_ratio=low, max_soc_ratio=high)
            with self.assertRaises(ContractError):
                normalize_storage(value)

    def test_budget_modes_cannot_conflict(self):
        value = self.request().editable_payload()
        value["budget"]["total_cycles"] = "1"
        with self.assertRaises(ContractError):
            normalize_storage(value)

    def test_overused_budget_is_not_clipped(self):
        value = self.request().editable_payload()
        value["budget"] = {"mode": "total_minus_used", "total_cycles": "0.4", "used_cycles": "0.5"}
        with self.assertRaises(ContractError):
            normalize_storage(value)

    def test_zero_budget_is_valid_not_auto_success(self):
        value = self.request().editable_payload()
        value["budget"]["remaining_cycles"] = "0"
        value["terminal_soc_ratio"] = "0.5"
        a = normalize_storage(value)
        self.assertEqual(a.remaining_throughput_mwh, 0)
        # Algebraic input validity is not optimization feasibility. S2 must reject this plan.
        self.assertNotEqual(a.current_soc_ratio, a.terminal_soc_ratio)

    def test_negative_price_and_real_zero_price_preserved(self):
        value = self.request().editable_payload()
        value["prices"][0]["forecast_price_yuan_per_mwh"] = "-100"
        value["prices"][1]["forecast_price_yuan_per_mwh"] = "0"
        a = normalize_storage(value)
        self.assertEqual(a.prices[0].forecast_price_yuan_per_mwh, -100)
        self.assertEqual(a.prices[1].forecast_price_yuan_per_mwh, 0)

    def test_missing_price_not_zero(self):
        value = self.request().editable_payload()
        value["prices"][0]["forecast_price_yuan_per_mwh"] = None
        with self.assertRaises(ContractError):
            normalize_storage(value)

    def test_bad_grid_duplicate_gap_order_and_length(self):
        a = self.request().editable_payload()
        mutations = [a["prices"][:-2] + a["prices"][-1:], [a["prices"][0]] * 2, list(reversed(a["prices"]))]
        for rows in mutations:
            value = deepcopy(a)
            value["prices"] = rows
            with self.assertRaises(ContractError):
                normalize_storage(value)
        a["prices"] = a["prices"] * 17
        with self.assertRaises(ContractError):
            normalize_storage(a)

    def test_interval_mismatch_rejected(self):
        value = self.request().editable_payload()
        for interval in (15, 30, 0, True, "60", 20):
            value["interval_minutes"] = interval
            with self.assertRaises(ContractError):
                normalize_storage(value)

    def test_midnight_end_allowed_not_cross_day_reset(self):
        value = self.request().editable_payload()
        value.update(prices=[{"interval_start": "2026-10-05T23:00:00+08:00", "interval_end": "2026-10-06T00:00:00+08:00", "forecast_price_yuan_per_mwh": "200"}], wait_until=None)
        self.assertEqual(normalize_storage(value).prices[-1].interval_end.day, 6)
        value["prices"].append({"interval_start": "2026-10-06T00:00:00+08:00", "interval_end": "2026-10-06T01:00:00+08:00", "forecast_price_yuan_per_mwh": "200"})
        with self.assertRaises(ContractError):
            normalize_storage(value)

    def test_timezone_seconds_and_wait_boundary(self):
        for start in ("2026-10-05T17:00:00", "2026-10-05T17:00:00+00:00", "2026-10-05T17:00:01+08:00"):
            value = self.request().editable_payload()
            value["prices"][0]["interval_start"] = start
            with self.assertRaises(ContractError):
                normalize_storage(value)
        value = self.request().editable_payload()
        value["wait_until"] = "2026-10-05T20:30:00+08:00"
        with self.assertRaises(ContractError):
            normalize_storage(value)

