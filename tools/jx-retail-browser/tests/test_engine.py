import copy
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import build_report, compute_customer, slot_prices
from readers import InputError, number, read_contracts, read_prices, reject_answer_table


def prices(month="2026-09"):
    return {"month":month,"categories":["平段"]*48,
            "vectors":{"日前市场均价（分时）":[D(300)]*48,"上限价（分时）":[D(500)]*48},
            "regular":{"省内现货实时市场加权平均价":D(350),
                       "市场化用户中长期交易平段合同加权平均价":D(400)}}


def fixed(**extra):
    return {"mode":"固定价格+联动价格+浮动价（分时）",
            "params":"平段固定价:400,联动电量比例:10,联动价格:日前市场均价（分时）,浮动费价:2",
            "source":"独立合同","start":"2026-09","end":"",**extra}


class EngineTests(unittest.TestCase):
    def test_zero_not_missing(self):
        self.assertEqual(number(0),D(0))
        with self.assertRaises(InputError):number(None)

    def test_fixed_service_fee_is_full_unit_fee(self):
        self.assertEqual(slot_prices(fixed(),prices()),[D(392)]*48)

    def test_spread_share_and_fee(self):
        c={"mode":"价差分成+浮动价（分时）",
           "params":"参考价:上限价（分时）,约定价差:60,分成比例:95,浮动价:2"}
        self.assertEqual(slot_prices(c,prices()),[D(445)]*48)

    def test_three_reference_prices_from_note(self):
        c={"mode":"价差分成+浮动价（分时）",
           "params":"参考价1:上限价（分时）,参考价2:上限价（分时）,参考价3:日前市场均价（分时）,价差分成比例:50,浮动价:2"}
        self.assertEqual(slot_prices(c,prices()),[D(402)]*48)

    def test_missing_market_indicator_is_not_replaced(self):
        p=prices();p["vectors"]={}
        with self.assertRaises(InputError):slot_prices(fixed(),p)

    def test_out_of_range_share(self):
        c=fixed();c["params"]=c["params"].replace("比例:10","比例:110")
        with self.assertRaises(InputError):slot_prices(c,prices())

    def test_zero_link_ratio_needs_no_price(self):
        c=fixed();c["params"]=c["params"].replace("比例:10","比例:0")
        p=prices();p["vectors"]={}
        self.assertEqual(slot_prices(c,p),[D(402)]*48)

    def test_default_cap_enabled(self):
        c=fixed();c["params"]=c["params"].replace("价:400","价:600")
        r=compute_customer([D(1)]*48,D(48),c,prices())
        self.assertTrue(r["cap_applied"])
        self.assertEqual(r["price"],"440.000")

    def test_explicit_no_cap(self):
        c=fixed(cap_override="否");c["params"]=c["params"].replace("价:400","价:600")
        self.assertEqual(compute_customer([D(1)]*48,D(48),c,prices())["price"],"572.000")

    def test_balancing_uses_monthly_rt(self):
        r=compute_customer([D(1)]*48,D(50),fixed(),prices())
        self.assertEqual(r["balance_fee"],"700.00")
        self.assertEqual(r["price"],"390.320")

    def test_negative_balancing(self):
        r=compute_customer([D(1)]*48,D(47),fixed(),prices())
        self.assertEqual(r["balance_fee"],"-350.00")

    def test_total_zero_unavailable(self):
        with self.assertRaises(InputError):compute_customer([D(0)]*48,D(0),fixed(),prices())

    def test_unrecognized_parameter_not_ignored(self):
        c=fixed();c["params"]+=",绿色环境价值:3"
        with self.assertRaises(InputError):slot_prices(c,prices())

    def test_completed_report_rejected_including_zero_price(self):
        for p in (123,0):
            with self.assertRaises(InputError):
                reject_answer_table({"Sheet1":[["零售用户交易价格"],[p]]})
        reject_answer_table({"Sheet1":[["零售用户交易价格"],[None]]})

    def test_overlap_contract_rejected(self):
        headers=["客户名称","生效月份","截止月份","套餐类型","套餐参数","参数来源"]
        row=["A","2026-09","","固定","平段固定价:400","独立合同"]
        with patch("readers.workbook_rows",return_value={"客户套餐":[headers,row,row]}):
            with self.assertRaises(InputError):read_contracts("unused.xlsx","2026-09")

    def test_expired_contract_not_carried_forward(self):
        headers=["客户名称","生效月份","截止月份","套餐类型","套餐参数","参数来源"]
        row=["A","2026-09","2026-09","固定","平段固定价:400","独立合同"]
        with patch("readers.workbook_rows",return_value={"客户套餐":[headers,row]}):
            self.assertEqual(read_contracts("unused.xlsx","2026-10"),{})

    def test_confirmed_carry_forward_uses_latest_snapshot(self):
        h=["客户名称","生效月份","截止月份","套餐类型","套餐参数","参数来源"]
        a=["A","2026-09","2026-09","固定","平段固定价:400","独立合同"]
        b=["A","2026-10","2026-10","固定","平段固定价:410","独立合同"]
        with patch("readers.workbook_rows",return_value={"客户套餐":[h,a,b]}):
            result=read_contracts("unused.xlsx","2026-11",allow_prior=True)
        self.assertEqual(result["A"]["params"],"平段固定价:410")
        self.assertTrue(result["A"]["continued"])

    def test_one_customer_multiple_user_numbers_not_double_counted(self):
        meters=[{"name":"A","uid":str(i),"meter":str(i),"quantity":"24","unit_name":"","category":"","voltage":""} for i in range(2)]
        dates={date(2026,9,1)+timedelta(days=i) for i in range(30)}
        curves={"A":{"q":[D(1)]*48,"dates":dates}}
        r=build_report(meters,curves,{"A":fixed()},prices())
        self.assertEqual(r["summary"]["official_q"],"48")
        self.assertEqual(len(r["customers"]),1)
        self.assertEqual(r["rows"][0][14],r["rows"][1][14])

    def test_missing_customer_does_not_become_zero(self):
        m={"name":"A","uid":"1","meter":"1","quantity":"48","unit_name":"","category":"","voltage":""}
        curves={"A":{"q":[D(1)]*48,"dates":{date(2026,9,1)+timedelta(days=i) for i in range(30)}}}
        r=build_report([m],curves,{},prices())
        self.assertIsNone(r["rows"][0][14])
        self.assertEqual(r["summary"]["pending"],1)

    def test_incomplete_days_blocks_only_affected_customer(self):
        m={"name":"A","uid":"1","meter":"1","quantity":"48","unit_name":"","category":"","voltage":""}
        r=build_report([m],{"A":{"q":[D(1)]*48,"dates":{date(2026,9,1)}}},{"A":fixed()},prices())
        self.assertIn("只有1天",r["customers"][0]["status"])

    def test_october_has_31_days(self):
        m={"name":"A","uid":"1","meter":"1","quantity":"48","unit_name":"","category":"","voltage":""}
        curves={"A":{"q":[D(1)]*48,"dates":{date(2026,10,1)+timedelta(days=i) for i in range(31)}}}
        r=build_report([m],curves,{"A":fixed()},prices("2026-10"))
        self.assertEqual(r["summary"]["calculated"],1)

    def test_new_market_prices_change_result(self):
        p=prices();a=compute_customer([D(1)]*48,D(48),fixed(),p)
        p["vectors"]["日前市场均价（分时）"]=[D(310)]*48
        b=compute_customer([D(1)]*48,D(48),fixed(),p)
        self.assertEqual(D(b["price"])-D(a["price"]),D(1))


if __name__=="__main__":
    unittest.main()
