from decimal import Decimal
import unittest

from decision_core.errors import ContractError
from decision_core.generation import normalize_generation
from decision_core.presets import generation_quick
from tests.decision_sandbox.support import generation_input


class GenerationContracts(unittest.TestCase):
    def request(self):
        return generation_quick(generation_input())

    def test_same_core_both_modes(self):
        a = self.request()
        b = normalize_generation(a.editable_payload())
        self.assertEqual(a, b)
        self.assertEqual(a.input_sha256, b.input_sha256)

    def test_existing_contracts_kept(self):
        a = self.request()
        self.assertEqual(a.existing_contract_mwh, 2000)
        self.assertEqual(a.existing_contract_price, 380)

    def test_six_unique_scenarios_no_fake_upside(self):
        a = self.request()
        self.assertEqual(len(a.scenarios), 6)
        self.assertEqual({r.net_mwh for r in a.scenarios}, {Decimal(20000), Decimal(16000)})

    def test_duplicate_scenarios_not_counted_twice(self):
        value = generation_input()
        value["downside_percent"] = "0"
        value["spot_prices"] = dict(low="300", base="300", high="300")
        self.assertEqual(len(generation_quick(value).scenarios), 1)

    def test_dedup_retains_normal_and_pressure_card_roles(self):
        value = generation_input()
        value["downside_percent"] = "0"
        value["spot_prices"] = dict(low="300", base="300", high="300")
        row = generation_quick(value).scenarios[0]
        self.assertEqual((row.quantity_label, row.price_label), ("base", "base"))
        self.assertIn(("base", "high"), row.aliases)
        self.assertIn(("low", "base"), row.aliases)
        self.assertFalse(any(q == "high" for q,p in row.aliases))

    def test_advanced_has_up_to_nine_scenarios(self):
        value = self.request().editable_payload()
        value["upside_ratio"] = "0.2"
        a = normalize_generation(value)
        self.assertEqual(len(a.scenarios), 9)
        self.assertEqual({r.net_mwh for r in a.scenarios}, {Decimal(16000), Decimal(20000), Decimal(24000)})

    def test_quick_requires_assumption_acceptance(self):
        value = generation_input()
        value["accept_preset"] = False
        with self.assertRaises(ContractError):
            generation_quick(value)

    def test_unknown_mechanism_not_coerced_to_zero(self):
        value = self.request().editable_payload()
        value["mechanism"] = {"mode": "unknown", "ratio": None, "cap_mode": "unknown", "remaining_cap_mwh": None, "price_yuan_per_mwh": None}
        a = normalize_generation(value)
        self.assertEqual(a.eligibility_state, "mechanism_quantity_unresolved")
        self.assertIsNone(a.mechanism.ratio)
        self.assertIsNone(a.mechanism.remaining_cap_mwh)

    def test_known_quantity_missing_mechanism_price_preserved(self):
        value = self.request().editable_payload()
        value["mechanism"] = {"mode": "ratio_assumed", "ratio": "0.4", "cap_mode": "known_remaining", "remaining_cap_mwh": "5000", "price_yuan_per_mwh": None}
        a = normalize_generation(value)
        self.assertTrue(a.mechanism.quantity_known)
        self.assertIsNone(a.mechanism.price_yuan_per_mwh)
        self.assertIsNone(a.mechanism_reference_prices)

    def test_unknown_cap_stays_unknown(self):
        value = self.request().editable_payload()
        value["mechanism"] = {"mode": "ratio_assumed", "ratio": "0.4", "cap_mode": "unknown", "remaining_cap_mwh": None, "price_yuan_per_mwh": "400"}
        self.assertFalse(normalize_generation(value).mechanism.quantity_known)

    def test_different_existing_price_only_advanced(self):
        value = self.request().editable_payload()
        value["existing_contract_price"] = "360"
        a = normalize_generation(value)
        self.assertEqual(a.existing_contract_price, 360)
        self.assertEqual(a.new_contract_price, 380)

    def test_existing_overcommitment_not_hidden(self):
        value = self.request().editable_payload()
        value["existing_contract_mwh"] = "30000"
        self.assertEqual(normalize_generation(value).existing_contract_mwh, 30000)

    def test_positive_existing_needs_price_zero_existing_does_not(self):
        value = self.request().editable_payload()
        value["existing_contract_price"] = None
        with self.assertRaises(ContractError):
            normalize_generation(value)
        value["existing_contract_mwh"] = "0"
        self.assertIsNone(normalize_generation(value).existing_contract_price)

    def test_no_bundled_green_price_masquerade(self):
        value = self.request().editable_payload()
        value["contract_price_scope"] = "energy_plus_environment"
        with self.assertRaises(ContractError):
            normalize_generation(value)

    def test_separate_prices_not_forced_equal(self):
        value = self.request().editable_payload()
        value["price_linkage"] = "separate_assumed"
        value["delivery_prices"] = {"low": "250", "base": "350", "high": "550"}
        a = normalize_generation(value)
        self.assertNotEqual(a.asset_prices, a.delivery_prices)

    def test_inconsistent_same_price_proxy_rejected(self):
        value = self.request().editable_payload()
        value["delivery_prices"]["base"] = "350"
        with self.assertRaises(ContractError):
            normalize_generation(value)

    def test_negative_prices_and_optional_custom(self):
        value = generation_input()
        value["spot_prices"]["low"] = "-50"
        value["custom_new_mwh"] = "7000"
        a = generation_quick(value)
        self.assertEqual(a.asset_prices[0], -50)
        self.assertEqual(a.custom_new_mwh, 7000)

    def test_bad_values(self):
        for key, bad in (("expected_net_mwh", 0), ("expected_net_mwh", "100000001"), ("downside_ratio", "1.1"), ("new_contract_price", "NaN"), ("existing_contract_mwh", True)):
            value = self.request().editable_payload()
            value[key] = bad
            with self.assertRaises(ContractError):
                normalize_generation(value)

    def test_bad_month_date_extra_and_missing(self):
        for key, bad in (("scenario_month", "2026-13"), ("rule_reference_date", "2026-02-30")):
            value = self.request().editable_payload()
            value[key] = bad
            with self.assertRaises(ContractError):
                normalize_generation(value)
        value = self.request().editable_payload()
        value["received_at"] = "invented"
        with self.assertRaises(ContractError):
            normalize_generation(value)
        value = self.request().editable_payload()
        del value["existing_contract_mwh"]
        with self.assertRaises(ContractError):
            normalize_generation(value)

    def test_2026_reference_not_downgraded_to_2025_history(self):
        value = self.request().editable_payload()
        value["scenario_month"] = "2025-09"
        self.assertEqual(normalize_generation(value).rule_relation, "counterfactual_research")
