"""Local Streamlit integration; fresh AppTest sessions and synthetic inputs only."""
import unittest
from pathlib import Path
import sys
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from sandbox_ui.replay import AVIEWS,BVIEWS
from sandbox_display.business_s4 import language_defects

APP=str(Path(__file__).resolve().parents[2]/"app.py")


class UITests(unittest.TestCase):
    def app(self,case=None):
        a=AppTest.from_file(APP,default_timeout=45).run()
        if case:
            a.radio(key="sandbox_nav").set_value("案例 A · 独立储能" if case=="storage" else "案例 B · 新能源发电企业").run()
            a.radio(key="a_entry_s4" if case=="storage" else "b_entry_s4").set_value("决策沙盒" if case=="storage" else "头寸沙盒").run()
        self.clean(a);return a

    def clean(self,a):
        self.assertEqual(list(a.exception),[])
        self.assertFalse(any("显示或输入结构" in x.value for x in a.error))

    def calc(self,a,case):
        a.checkbox(key=case+"_i_accept").check().run()
        a.button(key=case+"_compute").click().run();self.clean(a)
        return a.session_state[case+"_result"]

    def test_all_replay_subviews(self):
        a=self.app()
        for label,key,views in (("案例 A · 独立储能","a_view_s4",AVIEWS),("案例 B · 新能源发电企业","b_view_s4",BVIEWS)):
            a.radio(key="sandbox_nav").set_value(label).run()
            for view in views:a.radio(key=key).set_value(view).run();self.clean(a);self.assertEqual(list(a.error),[])

    def test_generation_compute_and_stale(self):
        a=self.app("generation");s=self.calc(a,"generation");self.assertTrue(s.result.advice.available)
        a.number_input(key="generation_i_new_price").set_value(450.0).run()
        self.assertTrue(any("条件已修改" in x.value for x in a.warning))
        self.assertFalse(any("本次选择" in x.value for x in a.success))
        t=self.calc(a,"generation");self.assertNotEqual(s.request.input_sha256,t.request.input_sha256)
        self.assertFalse(any("条件已修改" in x.value for x in a.warning))

    def test_storage_real_runner_and_second_conditions(self):
        a=self.app("storage");s=self.calc(a,"storage");self.assertTrue(s.result.advice.available)
        a.number_input(key="storage_i_current").set_value(35.0).run()
        t=self.calc(a,"storage");self.assertTrue(t.result.advice.available)
        self.assertNotEqual(s.request.input_sha256,t.request.input_sha256)
        self.assertNotEqual(s.result.output.plans[0].contribution,t.result.output.plans[0].contribution)
        self.assertFalse(any("条件已修改" in x.value for x in a.warning))

    def test_equal_mode_switch_no_auto_compute(self):
        a=self.app("generation");s=self.calc(a,"generation")
        a.radio(key="generation_mode_requested").set_value("advanced").run();self.clean(a)
        self.assertEqual(s.request.input_sha256,a.session_state["generation_result"].request.input_sha256)
        self.assertEqual(a.session_state["generation_drafts"]["advanced"]["existing_contract_mwh"],"2000.0")

    def test_pending_and_restore_advanced_draft(self):
        a=self.app("storage");a.radio(key="storage_mode_requested").set_value("advanced").run()
        a.number_input(key="storage_i_energy_capacity_mwh").set_value(250.0).run()
        a.radio(key="storage_mode_requested").set_value("quick").run()
        self.assertTrue(a.session_state["storage_pending"])
        self.assertTrue(a.button(key="storage_compute").disabled)
        a.button(key="storage_cancel_quick").click().run()
        self.assertEqual(a.number_input(key="storage_i_energy_capacity_mwh").value,250.0)
        a.radio(key="storage_mode_requested").set_value("quick").run()
        a.button(key="storage_confirm_quick").click().run()
        a.radio(key="storage_mode_requested").set_value("advanced").run()
        self.assertEqual(a.number_input(key="storage_i_energy_capacity_mwh").value,200.0)
        a.button(key="storage_restore_advanced").click().run()
        self.assertEqual(a.number_input(key="storage_i_energy_capacity_mwh").value,250.0)

    def test_unknown_mechanism_no_advice(self):
        a=self.app("generation");a.radio(key="generation_mode_requested").set_value("advanced").run()
        a.selectbox(key="generation_i_mechanism").set_value("unknown").run()
        s=self.calc(a,"generation");self.assertFalse(s.result.advice.available)
        self.assertEqual(len(s.result.diagnostic_rows),6)

    def test_reset_isolated_case_and_sessions(self):
        a=self.app("generation");self.calc(a,"generation")
        b=self.app("generation");self.assertIsNone(b.session_state["generation_result"])
        a.button(key="generation_reset").click().run()
        self.assertIsNone(a.session_state["generation_result"])
        self.assertIsNone(b.session_state["generation_result"])

    def test_unaccepted_no_core_called(self):
        a=self.app("generation")
        with patch("sandbox_ui.generation.run_generation") as run:
            a.button(key="generation_compute").click().run();run.assert_not_called()
        self.assertIsNone(a.session_state["generation_result"])

    def test_invalid_efficiency_and_time(self):
        a=self.app("storage");a.radio(key="storage_mode_requested").set_value("advanced").run()
        a.number_input(key="storage_i_charge_efficiency").set_value(0.0).run()
        self.assertTrue(a.error);self.assertIsNone(a.session_state["storage_result"])
        a.number_input(key="storage_i_charge_efficiency").set_value(95.0).run()
        a.selectbox(key="storage_i_interval").set_value(15).run()
        self.assertTrue(any("起止" in x.value for x in a.error))

    def test_editor_negative_and_duplicate_time(self):
        a=self.app("storage")
        # AppTest cannot emit DataEditor front-end deltas. Exercise the same
        # renderer boundary here; real canvas editing is separately browser QA.
        frame=a.dataframe[0].value.copy();frame.loc[0,"预测价格（元/兆瓦时）"]=-100.0
        with patch("sandbox_ui.inputs.st.data_editor",return_value=frame):
            a.run();s=self.calc(a,"storage")
        self.assertEqual(str(s.request.prices[0].forecast_price_yuan_per_mwh),"-100.0")
        frame.loc[1,"时段开始（北京时间）"]="2026-10-06T17:00:00+08:00"
        with patch("sandbox_ui.inputs.st.data_editor",return_value=frame):a.run()
        self.assertTrue(a.error)
        self.assertFalse(any("当前安排" in x.value for x in a.success))

    def test_editor_added_row_not_readded_each_rerun(self):
        a=self.app("storage")
        import pandas as pd
        seeds=[]
        def edit(frame,**kwargs):
            seeds.append(len(frame))
            return pd.concat([frame,pd.DataFrame([{"时段开始（北京时间）":"2026-10-06T23:00:00+08:00","时段结束（北京时间）":"2026-10-07T00:00:00+08:00","预测价格（元/兆瓦时）":300}])],ignore_index=True)
        with patch("sandbox_ui.inputs.st.data_editor",side_effect=edit):
            a.run();a.number_input(key="storage_i_current").set_value(60.0).run()
        self.assertEqual(len(a.session_state["storage_drafts"]["quick"]["prices"]),7)
        self.assertEqual(seeds,[6,6])

    def test_fixed_stress_and_new_plan_do_not_replace_original(self):
        a=self.app("storage");s=self.calc(a,"storage")
        a.button(key="storage_stress_fixed").click().run();self.clean(a)
        self.assertFalse(a.session_state["storage_pressure"][1].reoptimized)
        a.button(key="storage_stress_reopt").click().run();self.clean(a)
        self.assertEqual(a.session_state["storage_result"].request,s.request)
        self.assertNotEqual(a.session_state["storage_pressure_new"][1].output.metadata.input_sha256,s.request.input_sha256)

    def test_language_actual_rendered_business_tables(self):
        a=self.app()
        for label,key,views in (("案例 A · 独立储能","a_view_s4",AVIEWS),("案例 B · 新能源发电企业","b_view_s4",BVIEWS)):
            a.radio(key="sandbox_nav").set_value(label).run()
            for v in views:
                a.radio(key=key).set_value(v).run();self.clean(a)
                text=[]
                for kind in ("markdown","caption","info","warning","error","subheader","title"):
                    text.extend(e.value for e in a.get(kind))
                for frame in a.dataframe:
                    text.extend(map(str,frame.value.columns));text.extend(map(str,frame.value.to_numpy().flatten()))
                self.assertEqual(language_defects(text),[],v)

    def test_timeout_result_no_plan_is_not_zero(self):
        from sandbox_compute.storage_runner import _failure
        from decision_core.contracts import RunStatus
        from datetime import datetime,timezone
        def failed(r):return _failure(r,"s4-timeout-test",datetime.now(timezone.utc),RunStatus.TIME_LIMIT,"本次计算超时，不能给出动作，也不是零收益。","WALL_TIME_LIMIT")
        a=self.app("storage")
        with patch("sandbox_ui.storage.run_storage",side_effect=failed):
            s=self.calc(a,"storage")
        self.assertFalse(s.result.advice.available);self.assertEqual(s.result.output.plans,())
        self.assertTrue(any("超时" in x.value for x in a.markdown));self.clean(a)


if __name__=="__main__":unittest.main()
