import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys

from public_ui.package import get_package
from sandbox_display.business_s4 import project,language_defects,number_text
from sandbox_ui.replay import storage_sheets,generation_sheets,power


class BusinessTests(unittest.TestCase):
    def test_legacy_blank_profit_is_not_zero_and_source_unchanged(self):
        row={"strategy":"A_no_operation","full_profit_yuan":"","simulated_contribution_yuan":"0.00","evaluation_status":"evaluable"}
        before=deepcopy(row)
        value=project("a_summary",[row])[0]
        self.assertEqual(row,before)
        self.assertEqual(value["企业完整利润"],"本版未计算")
        self.assertIn("0.00",value["这次已算项目的收支合计"])

    def test_all_replay_projections_whitelisted_chinese(self):
        p=get_package()
        aindex=p.read("storage/index.json")
        for name in p.files:
            if name.startswith("storage/") and name.endswith(".gz"):
                day=p.read(name)
                for d in day["strategies"]:
                    # day stores identity in summaries, not top-level fields.
                    row=d["summary"]
                    sheets=storage_sheets(aindex,day,d,row["node_id"],row["market_date"],row["strategy"])
                    strings=[v for rows in sheets.values() for r in rows for v in (*r.keys(),*r.values())]
                    self.assertEqual(language_defects(strings),[],name)
            if name.startswith("generation/") and name.endswith(".gz"):
                payload=p.read(name)
                for d in payload["strategies"]:
                    sheets=generation_sheets(payload,d)
                    strings=[v for rows in sheets.values() for r in rows for v in (*r.keys(),*r.values())]
                    self.assertEqual(language_defects(strings),[],name)

    def test_zero_negative_unknown_distinct(self):
        self.assertEqual(number_text(None),"暂缺依据")
        self.assertEqual(number_text(0),"0.00")
        self.assertEqual(number_text(-12),"-12.00")

    def test_machine_fields_do_not_fall_through(self):
        value=project("a_event",[{"strict_profile_sha256":"a"*64,"source_id":"PRIVATE","current_energy_mwh":0}])
        self.assertEqual(len(value[0]),1)

    def test_historical_roundoff_not_new_input_validation(self):
        value=project("a_action",[{"remaining_throughput_mwh":5.684341886080802e-14}])[0]
        self.assertIn("0.000000000000056",value["还允许累计充放多少电"])

    def test_proposal_power_uses_original_charge_and_discharge(self):
        x,y=power([{"timestamp":"2025-09-02T01:00:00","charge_power_mw":10,"discharge_power_mw":0}])
        self.assertEqual(x,["2025-09-02T01:00:00"])
        self.assertEqual(y,[-10])


if __name__=="__main__":unittest.main()
