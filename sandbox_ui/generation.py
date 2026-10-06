"""Monthly contract-position UI; common S3 core, never a fictional real month."""
import streamlit as st
from sandbox_compute.generation_runner import run_generation
from sandbox_display.business_s4 import (amount,number_text,percent,candidates,scenario_rows,
    generation_snapshot,GEN_COMPONENTS,scenario_name,diagnostic_rows,price_snapshot)
from .common import sandbox,table,bars
from .inputs import generation_inputs
from .exports import business_bytes,technical_bytes


def render():
    saved=sandbox("generation",generation_inputs,run_generation)
    if saved is None:return
    request,result=saved.request,saved.result
    st.divider()
    st.caption("以下结果对应最近一次已提交的条件；研究数据和旧结果没有参与本次计算。")
    st.subheader("按这些条件，建议再签多少电？")
    if not result.advice.available:
        st.warning(result.advice.headline_zh)
        for line in result.advice.explanation_zh:st.write(line)
        if result.diagnostic_rows:
            table(diagnostic_rows(result))
    else:
        chosen=result.assessments[result.advice.selected_index]
        st.success("本次选择：新增 "+number_text(chosen.candidate.new_contract_mwh)+" 兆瓦时")
        st.write("占全部预测电量 "+percent(chosen.new_share_of_total_forecast)+"；已有 "+
            number_text(request.existing_contract_mwh)+" 兆瓦时合同另行保留。")
        st.caption("覆盖率基数：扣除研究机制量和已有承诺后的剩余 "+number_text(result.quantity_basis.new_available_mwh)+
            " 兆瓦时。是权益／履约研究口径，不是从市场移除机制电量，也不是浙江统一合同禁限额。")
        cols=st.columns(3)
        for c,(label,i,value) in zip(cols*2,chosen.cards):c.metric(label+"（元）",amount(value))
        st.write(chosen.selection_notes_zh[0] if request.risk_preference=="base" else chosen.selection_notes_zh[1])
        st.caption("最低金额从所有联合情况取；不是最大亏损、现实概率或企业完整利润。")
        with st.expander("为什么这个方案更稳／付出了什么代价"):
            for line in result.advice.explanation_zh:st.write(line)
            st.write("实际唯一联合情况数："+str(result.unique_scenario_count))
            table([{"偏好":"正常金额优先","选择": "无可推荐方案" if result.baseline_selection.candidate_index is None else
                number_text(result.assessments[result.baseline_selection.candidate_index].candidate.new_contract_mwh)+" 兆瓦时"},
                {"偏好":"最低联合金额优先","选择":"无可推荐方案" if result.robust_selection.candidate_index is None else
                number_text(result.assessments[result.robust_selection.candidate_index].candidate.new_contract_mwh)+" 兆瓦时"}])
    with st.expander("所有候选与联合情况"):
        table(candidates(result))
        if result.assessments:
            index=st.selectbox("查看哪个新增方案？",range(len(result.assessments)),
                format_func=lambda i:"／".join(l.label_zh for l in result.assessments[i].labels),key="generation_candidate_detail")
            assessment=result.assessments[index]
            table(scenario_rows(assessment))
            for line in assessment.reasons_zh+assessment.selection_notes_zh:st.write(line)
            st.caption("履约缺额未包含真实补偿费用。原合同及新合同在少发、涨跌情景中保持不变。")
            table([{"共同评价项目":GEN_COMPONENTS[c]} for c in assessment.candidate.evaluated_components])
            st.caption("未算项目：环境价值、履约补偿、税费、经营及资本成本、企业完整利润。未知不填零。")
    with st.expander("本次用到的条件与机制口径"):
        table(generation_snapshot(request))
        for line in result.assumptions_zh:st.write(line)
        table(price_snapshot(request))
    st.download_button("下载本次测算中文工作簿",business_bytes(saved),"发电_本次情景测算.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key="generation_business_download",on_click="ignore")
    with st.expander("查看技术证据"):
        st.json(__import__("json").loads(technical_bytes(saved)))
        st.download_button("下载本次测算技术记录",technical_bytes(saved),"发电_本次情景测算_技术.json",
            "application/json",key="generation_technical_download",on_click="ignore")
