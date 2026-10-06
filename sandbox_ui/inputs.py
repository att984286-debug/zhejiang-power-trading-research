"""Chinese quick/advanced controls. Normalization and formulas stay in S1 cores."""
from copy import deepcopy
from decimal import Decimal
import pandas as pd
import streamlit as st

from decision_core.presets import STORAGE_ASSUMPTIONS_ZH, GENERATION_ASSUMPTIONS_ZH


def num(prefix, field, label, value, *, help=None):
    key = prefix+field
    if key not in st.session_state:
        st.session_state[key] = float(value)
    return str(st.number_input(label, key=key, step=1.0, help=help, format="%.4f"))


def choice(prefix, field, label, options, value, labels):
    key = prefix+field
    if key not in st.session_state:
        st.session_state[key] = value
    return st.selectbox(label, options, key=key, format_func=lambda v:labels[v])


def flag(prefix, field, label, value=False, help=None):
    key = prefix+field
    if key not in st.session_state:
        st.session_state[key] = value
    return st.checkbox(label,key=key,help=help)


def pct(prefix,field,label,value):
    return str(Decimal(num(prefix,field,label,Decimal(str(value))*100))/100)


def storage_inputs(payload, mode, prefix):
    p = deepcopy(payload)
    st.subheader("先告诉我这块电池的条件")
    cols = st.columns(2)
    with cols[0]:
        p["current_soc_ratio"] = pct(prefix,"current","现在电池还剩多少电？（%）",p["current_soc_ratio"])
    with cols[1]:
        if mode == "quick":
            p["budget"] = {"mode":"remaining", "remaining_cycles":num(prefix,"remaining","今天还允许用多少充放额度？（次）",p["budget"]["remaining_cycles"])}
            p["terminal_soc_ratio"] = p["current_soc_ratio"]
        else:
            budget_mode = choice(prefix,"budget_mode","额度怎么填写？",["remaining","total_minus_used"],p["budget"]["mode"],
                {"remaining":"直接填写剩余量", "total_minus_used":"今日总量减去已用量"})
            if budget_mode == "remaining":
                value = p["budget"].get("remaining_cycles",float(p["budget"].get("total_cycles",1))-float(p["budget"].get("used_cycles",0)))
                p["budget"]={"mode":budget_mode,"remaining_cycles":num(prefix,"remaining","剩余充放额度（次）",value)}
            else:
                p["budget"]={"mode":budget_mode,"total_cycles":num(prefix,"total","今天总额度（次）",p["budget"].get("total_cycles",1)),
                    "used_cycles":num(prefix,"used","今天已用额度（次）",p["budget"].get("used_cycles",0))}
    st.caption("1次额度＝充入与放出累计达到额定容量的两倍；200兆瓦时电池对应400兆瓦时累计充放电量。")
    if mode == "advanced":
        with st.expander("电池、效率和结束目标",expanded=True):
            columns = st.columns(3)
            fields=[("energy_capacity_mwh","电池能装多少电？（兆瓦时）"),
                ("charge_power_limit_mw","最快充电速度（兆瓦）"),("discharge_power_limit_mw","最快放电速度（兆瓦）"),
                ("degradation_cost_yuan_per_mwh_throughput","模拟电池损耗计价（元/兆瓦时）")]
            for i,(f,label) in enumerate(fields):
                with columns[i%3]:p[f]=num(prefix,f,label,p[f])
            for i,(f,label) in enumerate([("min_soc_ratio","最少要留多少电？（%）"),("max_soc_ratio","最多可以充到多少？（%）"),
                ("terminal_soc_ratio","本次计划结束时要剩多少电？（%）"),("charge_efficiency","充电效率（%）"),("discharge_efficiency","放电效率（%）")]):
                with columns[i%3]:p[f]=pct(prefix,f,label,p[f])
            key=prefix+"interval"
            if key not in st.session_state:st.session_state[key]=p["interval_minutes"]
            p["interval_minutes"]=st.selectbox("每一步算多长时间？（分钟）",[15,30,60],key=key)
            st.caption("改时间间隔后，请同时修改下方时段起止；系统不插值、补价或偷偷改时刻。")
    else:
        st.write("**当前按标准研究电池测算**")
        for line in STORAGE_ASSUMPTIONS_ZH:st.caption(line)
    st.subheader("接下来各时段的电价大概是多少？")
    # Editor deltas must always apply to one seed, not recursively to their own
    # previous edited output (which would duplicate added rows on every rerun).
    seed_key=prefix+"price_seed"
    if seed_key not in st.session_state:st.session_state[seed_key]=deepcopy(p["prices"])
    frame=pd.DataFrame([{"时段开始（北京时间）":r["interval_start"], "时段结束（北京时间）":r["interval_end"],
        "预测价格（元/兆瓦时）":float(r["forecast_price_yuan_per_mwh"])} for r in st.session_state[seed_key]])
    edited=st.data_editor(frame,hide_index=True,num_rows="dynamic",key=prefix+"prices",width="stretch",
        column_config={"预测价格（元/兆瓦时）":st.column_config.NumberColumn(format="%.2f")})
    p["prices"]=[{"interval_start":r["时段开始（北京时间）"],"interval_end":r["时段结束（北京时间）"],
        "forecast_price_yuan_per_mwh":None if pd.isna(r["预测价格（元/兆瓦时）"]) else str(r["预测价格（元/兆瓦时）"])} for r in edited.to_dict("records")]
    key=prefix+"wait"
    if key not in st.session_state:st.session_state[key]=p["wait_until"] or ""
    wait=st.text_input("留到哪个时刻再安排？（对照方案）",key=key,
        help="填写表内明确的时段边界，含北京时间时区；不是事后自动挑最高价时刻。")
    p["wait_until"]=wait or None
    accepted=flag(prefix,"accept","我确认以上电池条件、预测价格和研究假设",False)
    return p,accepted


def path_inputs(prefix,field,title,values):
    st.write(title)
    cols=st.columns(3)
    out={}
    for c,key,label in zip(cols,["low","base","high"],["较低时","通常","较高时"]):
        with c:out[key]=num(prefix,field+key,title+" · "+label+"（元/兆瓦时）",values[key])
    return out


def optional_num(prefix,field,label,value,default):
    known=flag(prefix,field+"_known","已知或显式假设："+label,value is not None)
    return num(prefix,field,label,value if value is not None else default) if known else None


def generation_inputs(payload,mode,prefix):
    p=deepcopy(payload)
    st.subheader("先明确发电量和已签合同")
    c1,c2,c3=st.columns(3)
    with c1:p["expected_net_mwh"]=num(prefix,"quantity","下个月预计能卖多少电？（兆瓦时）",p["expected_net_mwh"])
    with c2:p["downside_ratio"]=pct(prefix,"down","最多可能少发多少？（%）",p["downside_ratio"])
    with c3:p["existing_contract_mwh"]=num(prefix,"existing","已经承诺卖出多少电？（兆瓦时）",p["existing_contract_mwh"])
    c1,c2=st.columns(2)
    with c1:p["new_contract_price"]=num(prefix,"new_price","新合同电能量部分卖多少钱？（元/兆瓦时）",p["new_contract_price"])
    with c2:p["custom_new_mwh"]=optional_num(prefix,"custom","我还想试的新增合同量（兆瓦时）",p["custom_new_mwh"],0)
    st.caption("可卖电量是扣除厂内用电、损耗后的研究估计；少发范围不是统计置信区间。合同单价仅填电能量部分，不强拆绿电总价。")
    p["asset_prices"]=path_inputs(prefix,"asset","下个月电站卖电参考价",p["asset_prices"])
    if mode=="quick":
        p["existing_contract_price"]=p["new_contract_price"]
        p["delivery_prices"]=deepcopy(p["asset_prices"])
        st.write("**这次怎么假设**")
        for line in GENERATION_ASSUMPTIONS_ZH:st.caption(line)
        st.caption("研究月份："+p["scenario_month"]+"；规则参考日："+p["rule_reference_date"]+"。不是实时行情、真实合同或企业完整利润。")
    else:
        st.subheader("更多研究条件（输入更多，不代表更真实）")
        cols=st.columns(3)
        with cols[0]:
            key=prefix+"month"
            if key not in st.session_state:st.session_state[key]=p["scenario_month"]
            p["scenario_month"]=st.text_input("研究哪一个月？（年-月）",key=key)
            p["upside_ratio"]=pct(prefix,"up","最多可能多发多少？（%）",p["upside_ratio"])
        with cols[1]:
            key=prefix+"ref"
            if key not in st.session_state:st.session_state[key]=p["rule_reference_date"]
            p["rule_reference_date"]=st.text_input("采用哪一天的规则口径作参考？",key=key)
            p["existing_contract_price"]=optional_num(prefix,"old_price","原合同电能量均价（元/兆瓦时）",p["existing_contract_price"],380)
        with cols[2]:
            p["subject_scenario"]=choice(prefix,"subject","主体研究身份",["unspecified_research","existing_renewable_assumed","incremental_renewable_assumed"],p["subject_scenario"],
                {"unspecified_research":"不认证真实身份", "existing_renewable_assumed":"假设存量新能源", "incremental_renewable_assumed":"假设增量新能源"})
            p["risk_preference"]=choice(prefix,"risk","这次优先照顾哪一种结果？",["robust","base"],p["risk_preference"],
                {"robust":"优先这些不利情况的最低金额", "base":"优先正常情况的金额"})
        m=p["mechanism"]
        mode_m=choice(prefix,"mechanism","机制怎么处理？",["not_applicable_assumed","ratio_assumed","unknown"],m["mode"],
            {"not_applicable_assumed":"明确研究假设不适用", "ratio_assumed":"按声明比例研究", "unknown":"资格或数量尚未确认"})
        cap_mode="not_binding_assumed"
        cap=ratio=mp=None
        if mode_m=="ratio_assumed":
            ratio=pct(prefix,"mechanism_ratio","研究机制比例（%）",m["ratio"] if m["ratio"] is not None else 0.4)
            cap_mode=choice(prefix,"cap_mode","年度剩余机制额度",["known_remaining","not_binding_assumed","unknown"],m["cap_mode"],
                {"known_remaining":"填写明确剩余量", "not_binding_assumed":"显式假设本次不触顶", "unknown":"未确认"})
            if cap_mode=="known_remaining":cap=num(prefix,"cap","年度剩余机制额度（兆瓦时）",m["remaining_cap_mwh"] if m["remaining_cap_mwh"] is not None else 8000)
            mp=optional_num(prefix,"mechanism_price","机制研究价（元/兆瓦时）",m["price_yuan_per_mwh"],400)
        if mode_m=="unknown":cap_mode="unknown"
        p["mechanism"]={"mode":mode_m,"ratio":ratio,"cap_mode":cap_mode,"remaining_cap_mwh":cap,"price_yuan_per_mwh":mp}
        p["price_linkage"]=choice(prefix,"linkage","几类价格之间是什么关系？",["asset_delivery_same_assumed","all_same_assumed","separate_assumed"],p["price_linkage"],
            {"asset_delivery_same_assumed":"电站与合同参考价同价代理", "all_same_assumed":"三类参考价都同价代理", "separate_assumed":"分别填写三类价格"})
        if p["price_linkage"]=="separate_assumed":
            p["delivery_prices"]=path_inputs(prefix,"delivery","合同计费参考价",p["delivery_prices"])
        else:p["delivery_prices"]=deepcopy(p["asset_prices"])
        if p["price_linkage"]=="all_same_assumed":p["mechanism_reference_prices"]=deepcopy(p["asset_prices"])
        else:
            known=flag(prefix,"refs_known","机制结算参考价已知或有明确研究假设",p["mechanism_reference_prices"] is not None)
            p["mechanism_reference_prices"]=path_inputs(prefix,"refs","机制结算参考价",p["mechanism_reference_prices"] or p["asset_prices"]) if known else None
        limit=p["new_contract_limit"]
        lm=choice(prefix,"limit_mode","新增合同额度如何处理？",["not_binding_assumed","known_remaining","unknown"],limit["mode"],
            {"not_binding_assumed":"显式假设本范围不触顶", "known_remaining":"填写明确剩余量", "unknown":"额度尚未确认"})
        lv=num(prefix,"limit","还允许新增多少合同？（兆瓦时）",limit["remaining_mwh"] if limit["remaining_mwh"] is not None else 20000) if lm=="known_remaining" else None
        p["new_contract_limit"]={"mode":lm,"remaining_mwh":lv}
        p["enforce_minimum_fulfillment"]=flag(prefix,"safe","不新增超过声明最少可履约量的承诺",p["enforce_minimum_fulfillment"],"这是研究约束，不是浙江统一法定限额；关闭后只作条件排名。")
        st.caption("机制数量影响研究权益与履约口径，不从物理市场电量中移除。环境价值与履约补偿本版未计算。")
    accepted=flag(prefix,"accept","我确认以上发电量、合同和价格研究假设",False)
    return p,accepted
