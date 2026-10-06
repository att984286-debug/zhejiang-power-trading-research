"""Thin visual helpers; all business tables are explicit Chinese projections."""
from copy import deepcopy
from decimal import Decimal
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from decision_core.errors import ContractError
from decision_core.presets import storage_quick, generation_quick, preset_record
from decision_core.storage import normalize_storage
from decision_core.generation import normalize_generation
from .state import Submitted, quick_differences, quick_payload

BOUNDARY="本次情景测算，不属于历史冻结研究结果。没有实际成交或执行认证，已算金额不是企业完整利润。"
MODES={"quick":"快速测算","advanced":"高级情景测算"}


def table(rows):
    if not rows:
        st.info("此范围没有可展示的业务明细；不是零，也不自动换用其他资料。")
        return
    st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch",height=min(380,60+35*len(rows)))


def chart(series,unit,height=230):
    fig=go.Figure()
    for i,(label,x,y) in enumerate(series):
        fig.add_trace(go.Scatter(x=x,y=[None if v is None else float(v) for v in y],name=label,
            customdata=[str(v).replace("T"," ").replace("+08:00","")[:16] for v in x],
            mode="lines",line={"width":2,"color":["#087f75","#db843b","#5b6f9e"][i%3]},
            hovertemplate="%{customdata}（北京时间）<br>"+label+"：%{y:.2f} "+unit+"<extra></extra>"))
    fig.update_layout(height=height,margin={"l":8,"r":8,"t":12,"b":8},yaxis_title=unit,
        xaxis_title="时刻",font={"family":"Arial, PingFang SC, sans-serif"},
        paper_bgcolor="white",plot_bgcolor="white",legend={"orientation":"h"})
    fig.update_yaxes(gridcolor="#edf1f3")
    fig.update_xaxes(tickformat="%H:%M",hoverformat="%Y-%m-%d %H:%M")
    return fig


def bars(labels,values,unit="元"):
    fig=go.Figure(go.Bar(x=labels,y=[None if v is None else float(v) for v in values],
        marker_color="#087f75",hovertemplate="%{x}<br>金额：%{y:,.2f} "+unit+"<extra></extra>"))
    fig.update_layout(height=260,margin={"l":8,"r":8,"t":10,"b":8},yaxis_title=unit)
    return fig


def initial(case):
    if case=="storage":
        from datetime import datetime,timedelta
        start=datetime.fromisoformat("2026-10-06T17:00:00+08:00")
        rows=[{"interval_start":(start+timedelta(hours=i)).isoformat(),
            "interval_end":(start+timedelta(hours=i+1)).isoformat(),"forecast_price_yuan_per_mwh":str(price)}
            for i,price in enumerate([380,420,500,620,570,400])]
        return storage_quick({"current_soc_percent":"65","remaining_cycles":"0.6","prices":rows,
            "wait_until":"2026-10-06T20:00:00+08:00","accept_preset":True}).editable_payload()
    return generation_quick({"scenario_month":"2026-11","rule_reference_date":"2026-08-01",
        "expected_net_mwh":"20000","downside_percent":"20","existing_contract_mwh":"2000",
        "contract_energy_price":"380","spot_prices":{"low":"200","base":"300","high":"500"},
        "custom_new_mwh":None,"accept_preset":True}).editable_payload()


def clear_widgets(case):
    for key in list(st.session_state):
        if key.startswith(case+"_i_") or key.startswith(case+"_stress_"):
            del st.session_state[key]


def mode_change(case):
    target=st.session_state[case+"_mode_requested"]
    current=st.session_state[case+"_mode"]
    if target==current:return
    payload=st.session_state[case+"_drafts"][current]
    if target=="quick":
        differences=quick_differences(case,payload)
        if differences:
            st.session_state[case+"_pending"]=differences
            return
        payload=quick_payload(case,payload)
    if target=="advanced":
        st.session_state[case+"_previous_advanced"]=deepcopy(st.session_state[case+"_drafts"][target])
    st.session_state[case+"_drafts"][target]=deepcopy(payload)
    st.session_state[case+"_mode"]=target
    st.session_state[case+"_pending"]=None
    st.session_state[case+"_restore_error"]=False
    clear_widgets(case)


def confirm_quick(case):
    try:
        payload=quick_payload(case,st.session_state[case+"_drafts"]["advanced"])
    except (ValueError,TypeError):
        # Do not reinterpret half-hour prices as hourly inputs.
        st.session_state[case+"_restore_error"]=True
        return
    st.session_state[case+"_drafts"]["quick"]=payload
    st.session_state[case+"_mode"]="quick"
    st.session_state[case+"_mode_requested"]="quick"
    st.session_state[case+"_pending"]=None
    st.session_state[case+"_result"]=None
    st.session_state[case+"_restore_error"]=False
    clear_widgets(case)


def restore_advanced(case):
    st.session_state[case+"_drafts"]["advanced"]=deepcopy(st.session_state[case+"_previous_advanced"])
    st.session_state[case+"_result"]=None
    clear_widgets(case)


def cancel_switch(case):
    st.session_state[case+"_mode_requested"]="advanced"
    st.session_state[case+"_pending"]=None


def reset(case):
    for key in list(st.session_state):
        if key.startswith(case+"_"):del st.session_state[key]


def sandbox(case,input_renderer,runner):
    """Only explicit compute clicks invoke a core. No persistent visitor storage."""
    if case+"_mode" not in st.session_state:
        p=initial(case)
        st.session_state[case+"_mode"]="quick"
        st.session_state[case+"_mode_requested"]="quick"
        st.session_state[case+"_drafts"]={"quick":deepcopy(p),"advanced":deepcopy(p)}
        st.session_state[case+"_result"]=None
        st.session_state[case+"_pending"]=None
    st.info(BOUNDARY)
    st.radio("选择测算方式",list(MODES),format_func=MODES.get,horizontal=True,
        key=case+"_mode_requested",on_change=mode_change,args=(case,))
    pending=st.session_state[case+"_pending"]
    if pending:
        st.warning("转回快速测算会恢复这些研究预设："+ "、".join(pending)+"。确认前保留高级条件，旧结果不当成快速结果。")
        c1,c2=st.columns(2)
        c1.button("确认恢复快速预设",key=case+"_confirm_quick",on_click=confirm_quick,args=(case,))
        c2.button("继续高级测算",key=case+"_cancel_quick",on_click=cancel_switch,args=(case,))
    if st.session_state.get(case+"_restore_error"):
        st.warning("当前时间表不符合快速模式每段一小时的条件；请先修正起止时间，或继续高级测算。")
    mode=st.session_state[case+"_mode"]
    st.caption("当前实际采用："+MODES[mode]+"。高级只是可控制条件更多，不是更精确的真实预测。")
    if mode=="advanced" and case+"_previous_advanced" in st.session_state:
        st.caption("当前继承刚才的条件；上一次高级草稿仍单独保留，恢复需主动点击并重新计算。")
        st.button("恢复上次高级草稿",key=case+"_restore_advanced",on_click=restore_advanced,args=(case,))
    raw,accepted=input_renderer(st.session_state[case+"_drafts"][mode],mode,case+"_i_")
    st.session_state[case+"_drafts"][mode]=deepcopy(raw)
    request,error=None,None
    try:
        request=(normalize_storage if case=="storage" else normalize_generation)(raw)
    except ContractError as exc:error=str(exc)
    except (ValueError,TypeError,ArithmeticError):error="条件尚未填全或时间、数值格式不正确，请修正后计算。"
    saved=st.session_state[case+"_result"]
    c1,c2=st.columns([2,1])
    compute=c1.button("计算剩余时段策略" if case=="storage" else "按以上假设比较",type="primary",key=case+"_compute",disabled=bool(pending))
    c2.button("重置本案例的测算",key=case+"_reset",on_click=reset,args=(case,))
    if error:st.error(error)
    if compute:
        st.session_state[case+"_result"]=None
        saved=None
        if not accepted:
            st.error("请先勾选确认本次研究条件；没有进行计算。")
        elif request is None:
            st.error("输入校验未通过；没有返回零收益或旧研究结果。")
        else:
            with st.spinner("正在按本次条件计算，不读取历史私有输入…"):
                result=runner(request)
            saved=Submitted(request,result,mode,preset_record(case)["id"] if mode=="quick" else None,deepcopy(raw))
            st.session_state[case+"_result"]=saved
    if saved is not None and not saved.matches(request):
        st.warning("条件已修改，请重新计算。旧结果及旧下载暂不展示。")
    return saved if saved is not None and saved.matches(request) and not pending else None
