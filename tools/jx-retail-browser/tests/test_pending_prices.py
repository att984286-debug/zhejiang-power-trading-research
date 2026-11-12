import sys
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from readers import read_prices,InputError
from engine import reference,compute_customer

def sheets(pending_vector=False):
    header=["月份","时段","463号定义时段类型","日前市场均价（分时）","上限价（分时）"]
    slots=[["2026-10",i,"平段","待定" if pending_vector and i==2 else 300,500] for i in range(1,49)]
    return {
      "零售套餐_常规价格定义":[["月份","价格类型","价格"],
        ["2026-10","售电公司月度结算加权价","待定"],
        ["2026-10","省内现货实时市场加权平均价",350],
        ["2026-10","市场化用户中长期交易平段合同加权平均价",400],
        ["2026-10","真实零价",0]],
      "零售套餐_分时价格":[header,*slots]}

class PendingPriceTests(unittest.TestCase):
    def parse(self,data):
        with patch("readers.workbook_rows",return_value=data),patch("readers.file_info",return_value={}):
            return read_prices("test.xlsx")

    def test_unused_pending_price_does_not_block(self):
        p=self.parse(sheets())
        c={"mode":"固定价格+联动价格","params":"平段固定价:400,联动电量比例:10,联动价格:日前市场均价（分时）,浮动费价:0"}
        r=compute_customer([D(1)]*48,D(48),c,p)
        self.assertEqual(r["price"],"390.000")
        self.assertNotIn("售电公司月度结算加权价",p["regular"])
        self.assertEqual(p["unavailable"]["regular"]["售电公司月度结算加权价"],"待定")
        self.assertEqual(p["regular"]["真实零价"],D(0))

    def test_selected_pending_price_is_explicit_not_zero(self):
        p=self.parse(sheets())
        with self.assertRaisesRegex(InputError,"待定"):
            reference(p,"售电公司月度结算加权价")

    def test_pending_vector_blocks_only_that_reference(self):
        p=self.parse(sheets(True))
        self.assertEqual(reference(p,"上限价（分时）"),[D(500)]*48)
        with self.assertRaisesRegex(InputError,"时段2"):
            reference(p,"日前市场均价（分时）")

    def test_zero_share_does_not_use_pending_difference_references(self):
        p=self.parse(sheets())
        c={"mode":"价差分成","params":"参考价1:上限价（分时）,参考价2:尚未公布甲,参考价3:尚未公布乙,价差分成比例:0,浮动价:2","cap_override":"否"}
        r=compute_customer([D(1)]*48,D(48),c,p)
        self.assertEqual(r["price"],"502.000")

    def test_negative_fee_and_spread_rejected(self):
        p=self.parse(sheets())
        for tail in ("约定价差:10,分成比例:100,浮动价:-1","约定价差:-1,分成比例:100,浮动价:0"):
            with self.assertRaisesRegex(InputError,"不能为负"):
                compute_customer([D(1)]*48,D(48),{"mode":"价差分成","params":"参考价:上限价（分时）,"+tail},p)

if __name__=="__main__":
    unittest.main()
