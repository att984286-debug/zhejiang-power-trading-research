"""Storage UI only; mature S2 math and worker stay immutable."""
from decimal import Decimal
from copy import deepcopy
import streamlit as st

from decision_core.storage import normalize_storage
from decision_core.storage_calculation import revalue_fixed_plan
from decision_core.contracts import RunStatus
from sandbox_compute.storage_runner import run_storage
from sandbox_display.business_s4 import (amount,number_text,percent,METHODS,safe_enum,
    action_rows,storage_snapshot)
from .common import sandbox,table,chart
from .inputs import storage_inputs,num
from .exports import business_bytes,technical_bytes


def render():
    saved=sandbox("storage",storage_inputs,run_storage)
    if saved is None:return
    request,result=saved.request,saved.result
    st.divider()
    st.caption("以下结果仅对应最近一次已提交的条件；尚未离开编辑框的修改可能未送达服务器。")
    st.subheader("现在应该充、放，还是等？")
    if not result.advice.available:
        st.warning(safe_enum(result.output.metadata.status.value))
        for line in result.advice.explanation_zh:st.write(line)
    else:
        st.success("当前安排："+result.advice.action_zh+"，速度 "+number_text(result.advice.power_mw)+" 兆瓦")
        best=result.computed_plans[0]
        cols=st.columns(3)
        cols[0].metric("按给定电价预计收支差额（元）",amount(best.plan.contribution))
        cols[1].metric("当前 → "+request.prices[-1].interval_end.strftime("%H:%M")+" 留电目标",
            percent(request.current_soc_ratio)+" → "+percent(request.terminal_soc_ratio))
        cols[2].metric("电池库存变化（兆瓦时）",number_text(best.evaluation.totals.inventory_delta_mwh))
        st.caption("放电收入减去充电成本和模拟损耗；若期末电量不同，金额含库存释放或补充，不是新增套利利润。")
        for line in result.advice.explanation_zh[:2]:st.write(line)
        rows=best.plan.interval_rows
        x=[r.interval_start.isoformat() for r in rows]
        st.plotly_chart(chart([("自己判断的电价",x,[r.forecast_price_yuan_per_mwh for r in request.prices])],"元/兆瓦时"),width="stretch")
        st.plotly_chart(chart([("放电速度",x,[r.discharge_power_mw for r in rows]),
            ("充电速度",x,[r.charge_power_mw for r in rows])],"兆瓦"),width="stretch")
        st.plotly_chart(chart([("电池电量比例",[rows[0].interval_start.isoformat()]+[r.interval_end.isoformat() for r in rows],
            [request.current_soc_ratio*100]+[r.stored_energy_after_mwh/request.energy_capacity_mwh*100 for r in rows])],"%"),width="stretch")
    with st.expander("为什么这样安排／三个办法怎样比较"):
        for line in result.advice.explanation_zh:st.write(line)
        table([{"办法":METHODS[p.plan.method],"状态":safe_enum(p.plan.status.value),
            "预计收支差额（元）":amount(p.plan.contribution),"说明":p.diagnostic_zh} for p in result.computed_plans])
        st.caption("“现在满放”强制第一整段满功率；“留到指定时刻”此前不充不放，随后各自优化。三方案使用同样结束电量和预算。")
        which=st.selectbox("查看一个办法的后续计划",range(len(result.computed_plans)),
            format_func=lambda i:METHODS[result.computed_plans[i].plan.method],key="storage_plan_detail") if result.computed_plans else None
        computed=result.computed_plans[which] if which is not None else None
        if computed is None:st.info("本次没有已验证计划；不是不操作或零收益。")
        if computed:table(action_rows(request,computed))
        if computed and computed.evaluation:
            table([{"收支项目":label,"金额（元）":amount(value)} for label,value in [
                ("放电收入",computed.evaluation.totals.discharge_revenue),
                ("充电成本",computed.evaluation.totals.charge_cost),
                ("模拟电池损耗",computed.evaluation.totals.degradation_cost),
                ("实际贡献（没有真实实际电价）",computed.evaluation.totals.actual_contribution),
                ("期初库存成本",computed.evaluation.totals.inventory_cost)]])
            for row in computed.decision_log:st.caption(row.reason_zh)
    with st.expander("本次用到的条件"):
        table(storage_snapshot(request))
        table([{"开始":r.interval_start.isoformat(),"结束":r.interval_end.isoformat(),"预测价格（元/兆瓦时）":number_text(r.forecast_price_yuan_per_mwh)} for r in request.prices])
    if result.advice.available:
        pressure(saved)
    st.download_button("下载本次测算中文工作簿",business_bytes(saved),"储能_本次情景测算.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key="storage_business_download",on_click="ignore")
    with st.expander("查看技术证据"):
        st.json(__import__("json").loads(technical_bytes(saved)))
        st.download_button("下载本次测算技术记录",technical_bytes(saved),"储能_本次情景测算_技术.json",
            "application/json",key="storage_technical_download",on_click="ignore")


def pressure(saved):
    request,result=saved.request,saved.result
    with st.expander("如果晚间价格没有涨起来？"):
        start=st.selectbox("从哪个时段开始降价？",range(len(request.prices)),
            format_func=lambda i:request.prices[i].interval_start.strftime("%H:%M"),key="storage_stress_start")
        cut=num("storage_stress_","cut","这些时段预测价下调多少？（元/兆瓦时）",200)
        new_prices=[r.forecast_price_yuan_per_mwh-(Decimal(cut) if i>=start else 0) for i,r in enumerate(request.prices)]
        marker=(request.input_sha256,tuple(map(str,new_prices)))
        if st.button("保持原动作，只重新估价",key="storage_stress_fixed"):
            try:
                value=revalue_fixed_plan(request,result.computed_plans[0],new_prices)
                st.session_state["storage_pressure"]=(marker,value)
            except ValueError:st.error("压力价格不符合范围；没有显示零金额。")
        state=st.session_state.get("storage_pressure")
        if state and state[0]==marker:
            st.write(state[1].label_zh)
            table([{"原预测收支（元）":amount(state[1].original_contribution),
                "新价格下原动作收支（元）":amount(state[1].stressed_contribution),
                "金额变化（元）":amount(state[1].difference)}])
        elif state:st.caption("压力条件已改变，请重新估价；原动作不会自动变化。")
        if st.button("按新预测重新优化（另列新结果）",key="storage_stress_reopt"):
            p=request.editable_payload()
            p["prices"]=[{**r,"forecast_price_yuan_per_mwh":str(v)} for r,v in zip(p["prices"],new_prices)]
            try:st.session_state["storage_pressure_new"]=(marker,run_storage(normalize_storage(p)))
            except ValueError:st.error("新预测条件没有通过校验；没有替换原方案。")
        new=st.session_state.get("storage_pressure_new")
        if new and new[0]==marker:
            st.write("下列是新预测下重新计算的计划，不是原计划抵御价格错误的收益。")
            if new[1].advice.available:st.write("新安排："+new[1].advice.action_zh)
            else:
                st.warning("新预测下暂不能给出安排；原测算没有被替换。")
                for line in new[1].advice.explanation_zh:st.write(line)
            st.write("新预测下收支差额："+amount(new[1].output.plans[0].contribution) if new[1].output.plans else "新计划不可评价")
        st.caption("没有真实成交或执行，这只是两种不同研究动作；不自动推进电池状态。")
