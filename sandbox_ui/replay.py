"""New Chinese reader of old validated PUBLIC projections. No business kernels."""
import json
import streamlit as st
from public_ui.package import get_package
from public_ui.export import export_bytes
from sandbox_display.zh import generation_tail_caption,missing_price_description
from sandbox_display.business_s4 import (project,number_text,percent,safe_enum,
    STRATEGIES,NODES,COMPONENTS)
from .common import table,chart,bars
from .exports import workbook

AVIEWS=["电池有什么限制","原来怎么安排","后来怎么调整","钱和风险在哪"]
BVIEWS=["有哪些条件","签多少报多少","钱怎么算","结果为什么变了"]
GROUPS={"synthetic_2026-08":"完整合成的2026年8月",
    "private_2026-09":"非同期映射：九月少量资料日","private_2026-10":"非同期映射：十月少量资料日"}
CASES={"normal":"正常路径","low_production":"少发压力","delivery_basis":"合同计费与卖电价不同的压力"}


def storage_sheets(index,day,d,node,date,strategy):
    summaries=project("a_summary",[s["summary"] for s in day["strategies"]])
    risks=[r["risk"] for r in index["comparisons"] if r["record"]["strategy"]==strategy and
        r["record"]["group"]==d["summary"]["comparison_group"] and
        r["record"]["pack"]==("august_2026" if date.startswith("2026-08") else "counterfactual_2025") and
        r["record"]["split"]==("august_framework_only" if date.startswith("2026-08") else "test")]
    return {"研究范围":[{"项目":"数据日期","内容":date},{"项目":"价格环境","内容":NODES[node]},
        {"项目":"研究类型","内容":"较新规则下的2025反事实研究" if date.startswith("2025") else "八月少量样本框架验证"},
        {"项目":"信息与利润边界","内容":"无法验证当时收到数据的时间；已算项目不等于完整利润"}],
        "电池参数":[{"参数":k,"内容":v} for k,v in project("asset",[index["asset"]])[0].items()],
        "历史资格检查":project("a_strict",[r for r in index["strict"] if r["date"]==date and r["node_id"]==node]),
        "同日研究方法":summaries,"采用动作":project("a_action",d["actions"]),
        "原事前计划":project("a_action",d["original_plan"]),"剩余计划更新":project("a_event",d["events"]),
        "原窗口风险":project("a_risk",risks),"固定动作压力":project("a_summary",[r for r in index["stress"]
            if r["market_date"]==date and r["node_id"]==node and r["strategy"]==strategy])}


def generation_sheets(payload,d):
    cand=[]
    for row in d["candidates"]:
        cand.append({**project("b_candidate",[row["record"]])[0],**project("b_score",[row["risk_score"]])[0]})
    return {"研究范围":[{"项目":"资料关系","内容":"非同期少量日研究" if payload["private_details_omitted"] else "完整合成交易月"},
        {"项目":"资料日数","内容":str(payload["sample_days"])},{"项目":"边界","内容":"非真实出清、非严格历史认证、非完整利润"}],
        "月前决策":project("b_decision",[d["decision"]]),"原研究候选":cand,
        "申报接受与净量":project("b_input",d["inputs"]),"分项覆盖":project("b_coverage",d["coverage"]),
        "日月账务":project("b_line",d["lines"]),"模型内风险":project("b_risk",[d["risk"]]),
        "金额差额分解":project("b_component",d["attribution_components"])}


def downloads(case,selection,payload,index,sheets,evidence):
    st.download_button("下载研究回放中文工作簿",workbook(sheets),"案例"+case+"_研究回放_中文.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key=case+"_reader_download",on_click="ignore")
    with st.expander("查看技术证据"):
        st.json({"公开白名单元数据":payload["meta"],"当前选择":selection,"来源定位":evidence})
        if st.button("生成原格式研究导出",key=case+"_machine_prepare"):
            raw,record=export_bytes(case,selection,payload,index)
            st.download_button("下载原格式研究工作簿",raw,"案例"+case+"_原格式研究.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key=case+"_machine_download",on_click="ignore")
            st.download_button("下载原格式追溯记录",json.dumps(record,ensure_ascii=False).encode(),"案例"+case+"_原格式追溯.json",
                "application/json",key=case+"_machine_json",on_click="ignore")
        st.caption("只读原白名单结果；技术导出保留原字段，原金额和资格不改写。")


def power(rows):
    return [r["interval_start"] if "interval_start" in r else r["timestamp"] for r in rows],[
        r["net_injection_mw"] if "net_injection_mw" in r else r["discharge_power_mw"]-r["charge_power_mw"] for r in rows]


def storage():
    p=get_package();index=p.read("storage/index.json")
    cols=st.columns([1,1,2])
    nodes=sorted({r["node_id"] for r in index["rows"]})
    node=cols[0].selectbox("选择价格环境",nodes,index=nodes.index("RESEARCH_JIANGDONG"),format_func=NODES.get,key="a_node")
    dates=sorted({r["market_date"] for r in index["rows"] if r["node_id"]==node})
    date=cols[1].selectbox("资料日期",dates,index=dates.index("2025-09-02") if "2025-09-02" in dates else 0,key="a_date")
    ids=list(k for k in STRATEGIES if k not in ["no_contract","fixed","risk_neutral","risk_averse"])
    strategy=cols[2].selectbox("选择一种交易方法（研究回放）",ids,index=ids.index("D_rolling_rt"),format_func=STRATEGIES.get,key="a_strategy")
    day=p.read(f"storage/{node}/{date}.json.gz")
    d=next(r for r in day["strategies"] if r["strategy"]==strategy)
    st.info("只读旧研究：数据日 "+date+"；规则参考日 "+day["context"]["rule_reference_date"]+
        "。每15分钟安排动作，每30分钟结算；没有真实成交认证。")
    if d["summary"]["reference_only"]:st.warning("这条方法提前使用了未来真实价格，只能作为事后参照，不能实际执行。")
    sheets=storage_sheets(index,day,d,node,date,strategy)
    view=st.radio("储能研究链路",AVIEWS,horizontal=True,key="a_view_s4")
    if view==AVIEWS[0]:
        st.subheader("为未来机会留多少电？")
        table(sheets["电池参数"])
        st.caption("兆瓦表示充放速度，兆瓦时表示电量。1次额度按额定容量两倍的累计充放计；损耗只是研究计价。")
        st.subheader("这份历史资料能证明当时就能这样交易吗？")
        st.warning("无法确认当时是否已收到这些数据，所以不能认证严格历史可执行；下方仅是资格检查，不抹掉研究情景的已算金额。")
        table(sheets["历史资格检查"])
        with st.expander("2026-08-09为什么不能评价收益？"):
            for row in index["missing_rt"]:
                st.write(NODES[row["node_id"]])
                for line in missing_price_description(row):st.write(line)
                st.caption("日前记录48行；实时也可能有48行记录，但没有完整有效价格，行数不代表价格可用。")
        st.caption("四节点只是价格环境，不证明真实储能接网身份；八月样本不代表完整月份。")
    elif view==AVIEWS[1]:
        st.subheader("原来的价格判断怎样变成充放计划？")
        x,y=power(d["original_plan"])
        st.plotly_chart(chart([("原计划净送出速度（负数是充电）",x,y)],"兆瓦"),width="stretch")
        rows=d["original_plan"]
        st.plotly_chart(chart([("原计划电量比例",[rows[0]["interval_start"]]+[r["interval_end"] for r in rows],
            [100*rows[0]["soc_before_ratio"]]+[100*r["soc_after_ratio"] for r in rows])],"%"),width="stretch")
        i=st.selectbox("检查模拟采用的一个动作",range(len(d["actions"])),format_func=lambda i:d["actions"][i]["interval_start"][11:16],key="a_action")
        table(project("a_action",[d["actions"][i]]))
        st.caption("只展示原采用动作与电量事实；不是重新求解。原始行情和完整预测价未公开，不用别的价格补写动作动机。")
        with st.expander("为什么这样解释"):
            if d["explanations"]:
                r=d["explanations"][i]
                st.write("原解释采用的判断时刻："+r["forecast_asof"])
                shown={"hold":"等待","charge":"充电","discharge":"放电"}.get(r["action"],r["action"] if not r["action"].isascii() else "请查看技术证据")
                st.write("动作："+shown+"；没有根据事后高价改写当时动机。")
            else:st.write("事后全知参照没有可执行策略的事前解释。")
            table(sheets["原事前计划"])
    elif view==AVIEWS[2]:
        st.subheader("后来调整什么，又保留了什么？")
        events=d["events"]
        if not events:st.info("这条方法没有逐时滚动更新事件。可选择运行中更新剩余计划的方法。")
        else:
            i=st.selectbox("查看一次原研究更新",range(len(events)),format_func=lambda i:events[i]["decision_asof"][11:16],key="a_event")
            e=events[i];table(project("a_event",[e]))
            proposal=next((r["actions"] for r in d["proposals"] if r["proposal_sha256"]==e["proposal_sha256"]),[])
            series=[]
            for label,rows in [("原计划",d["original_plan"]),("本次剩余建议",proposal),("模拟采用动作",d["actions"])]:
                x,y=power(rows);series.append((label,x,y))
            st.plotly_chart(chart(series,"兆瓦",320),width="stretch")
            st.warning("当日已验证新行情数为0；假定许可不是真实调度，更新计划不等于随时重新交易。已执行部分和剩余额度不重置。")
        st.metric("相比只调整一次，原研究额外金额（元）",number_text(d["attribution"].get("additional_rolling_yuan")))
    else:
        st.subheader("钱和风险在哪，而不只看总数？")
        cols=st.columns(2)
        for i,(label,key) in enumerate([("按事前计划计算的钱","da_amount_yuan"),("实际偏离原计划增减的钱","rt_amount_yuan"),
            ("模拟电池损耗","degradation_cost_yuan"),("已算项目收支合计","simulated_contribution_yuan")]):
            cols[i%2].metric(label+"（元）",number_text(d["summary"][key]))
        st.caption("前两项分别按日前市场价和实时市场价计；效率已体现在电量，不再重复扣费。未知费用不填零，完整利润未计算。")
        ordinary=[s["summary"] for s in day["strategies"] if not s["summary"]["reference_only"]]
        st.plotly_chart(bars([STRATEGIES[r["strategy"]] for r in ordinary],[r["simulated_contribution_yuan"] for r in ordinary]),width="stretch")
        with st.expander("方法比较、原窗口风险和固定动作压力"):
            table(sheets["同日研究方法"]);table(sheets["原窗口风险"])
            st.caption("风险来自原样本日金额，不是未来亏损概率；最差一批日的平均亏损不是最大可能损失，少量尾部样本不能证明安全。")
            table(sheets["固定动作压力"])
            table([{"对照":"原剩余策略调整相对不调整","差额（元）":number_text(d["attribution"].get("contribution_delta_yuan"))},
                {"对照":"多次更新相对单次更新","差额（元）":number_text(d["attribution"].get("additional_rolling_yuan"))}])
        st.info("原48点分时金融账本没有公开；量与金额组合能还原私有价格。这里只读已发布聚合结果。")
    downloads("A",strategy,day,index,sheets,d["evidence"])


def generation():
    p=get_package();index=p.read("generation/index.json")
    c1,c2=st.columns(2)
    group=c1.selectbox("选择一份研究情景",list(GROUPS),format_func=GROUPS.get,key="b_group")
    ids=["risk_averse","fixed","no_contract","risk_neutral"]
    strategy=c2.selectbox("选择一种签约方法（研究回放）",ids,format_func=STRATEGIES.get,key="b_strategy")
    payload=p.read(f"generation/{group}.json.gz");d=next(r for r in payload["strategies"] if r["strategy"]==strategy)
    sheets=generation_sheets(payload,d)
    if payload["private_details_omitted"]:
        st.warning("非同期研究：2022功率、2025价格、2026规则；仅"+str(payload["sample_days"])+"个有资料日，不是完整月或同一电站真实交易历史。私有分时输入未公开。")
    else:st.info("完整合成交易月：虚拟208兆瓦风电，研究假定接受与计费净量；不是卖方风场实盘。")
    st.caption("真实收到数据的时刻未知，严格历史信息资格未认证；只读旧结果，不是本次重新测算。")
    view=st.radio("发电研究链路",BVIEWS,horizontal=True,key="b_view_s4")
    if view==BVIEWS[0]:
        st.subheader("发电量、固定合同与机制是什么关系？")
        st.write("全部净上网量先参加市场；机制是按资格另外补扣的结算权益，不是另一个物理电量桶。合同差额和环境价值不能重复算。")
        table([{"项目":"虚拟研究资产","内容":"风电；"+payload["identity"]["capacity_mw"]+" 兆瓦；不认证真实场站对应"},
            {"项目":"机制资格","内容":"声明研究假设，不是企业资格认证"},
            {"项目":"发电出力","内容":"外生生产，不能像电池一样随意移时"},
            {"项目":"合同","内容":"事先承诺；少发和涨跌时不重签"},
            {"项目":"企业完整利润","内容":"本版未计算"}])
        with st.expander("规则关系与可核对的业务边界"):
            for row in index["rules"]:
                text=row["fact"]["assertion"]
                # Source assertions remain unmodified in technical evidence.
                for token,replacement in [("available_at","实际可用时刻"),("DA","日前"),("RT","实时"),("Demo","研究样例"),("unknown","暂缺依据")]:
                    text=text.replace(token,replacement)
                st.write(text)
            st.caption("上述是已冻结证据支持的事实与限定；没有为展示自动认证新主体或新日期。")
    elif view==BVIEWS[1]:
        st.subheader("当时签多少，后来报多少？")
        selected=next(r for r in d["candidates"] if r["record"]["chosen"])
        cols=st.columns(2)
        cols[0].metric("原研究签约覆盖率",percent(selected["record"]["coverage"]))
        cols[1].metric("原固定月合同量（兆瓦时）",number_text(selected["record"]["total_mwh"]))
        st.caption("分母：研究预测的机制外合格量 "+number_text(d["decision"]["expected_mechanism_outside_mwh"])+" 兆瓦时，不是全发电量。")
        st.write(generation_tail_caption(d["risk"]["confidence"]))
        st.metric("原模型尾部平均目标缺口（元）",number_text(selected["risk_score"]["budget_shortfall_cvar"]))
        table(sheets["原研究候选"])
        st.caption("原100%不可行来自研究履约缓冲，不是浙江普遍禁止全签。")
        if d["details_available"]:
            dates=sorted({r["interval_start"][:10] for r in d["inputs"]})
            date=st.selectbox("查看合成运行日",dates,key="b_date")
            rows=[r for r in d["inputs"] if r["interval_start"].startswith(date)]
            st.plotly_chart(chart([(label,[r["interval_start"] for r in rows],[r[key] for r in rows]) for label,key in
                [("报给市场的电量","q_declared_mwh"),("研究假定被接受的电量","q_awarded_mwh"),("研究计费净上网量","q_net_mwh")]],"兆瓦时"),width="stretch")
            with st.expander("预测、申报、接受、执行不能混为一谈"):
                table(project("b_input",rows))
                submission=next(s for s in d["submissions"] if s["record"]["market_date"]==date)
                r=submission["record"]
                table([{"资料日":r["market_date"],"预测签发时刻":r["issued_at"],"提交时刻":r["submitted_at"]}])
                st.caption("原96点预测和申报结构保留；不把研究接受代理认证为真实出清，不把厂内功率认证为结算计量。")
        else:st.info("这个分支只有聚合结果公开，不用合成分时数据冒充真实明细。")
    elif view==BVIEWS[2]:
        st.subheader("这些钱各从哪里来？")
        st.metric("本窗口已算项目合计（元）",number_text(d["evaluated_contribution_yuan"]))
        table(sheets["分项覆盖"])
        st.warning("税费、经营和资本成本、返还及补偿仍有未知或未计算；局部金额合计不是企业完整利润。")
        with st.expander("月机制、环境价值与风险详情"):
            table(project("b_line",[r for r in d["lines"] if len(r["period"])==7]))
            table(sheets["模型内风险"])
            st.write(generation_tail_caption(d["risk"]["confidence"]))
            st.caption("缺资料的日不能补零连接成整月；月度费用不重复摊到每天。")
            st.write("原连续日差额的最大回撤："+number_text(d["chronological"]["max_contiguous_increment_drawdown_yuan"])+" 元；只针对已观察连续段。")
        if d["details_available"]:
            with st.expander("合成日账务分项"):table(sheets["日月账务"])
        else:st.info("原私有分时账本不公开；不能由电量、价格和金额组合还原私有输入。")
    else:
        st.subheader("为什么降低模型风险，这次金额还少了？")
        st.metric("原策略相比不签合同的已算差额（元）",number_text(d["attribution"].get("difference_yuan")))
        table(sheets["金额差额分解"])
        case=st.selectbox("查看一条固定压力路径",list(CASES),format_func=CASES.get,key="b_case")
        pressure=next(r for r in payload["stress"] if r["case"]==case)
        st.plotly_chart(bars([STRATEGIES[r["strategy"]] for r in pressure["rows"]],[r["common_mask_contribution_yuan"] for r in pressure["rows"]]),width="stretch")
        st.caption("固定原承诺及动作后评价压力，不是提前知道冲击再签约。金额分解不是唯一因果证明。")
        with st.expander("事后参照与未知科目"):
            st.write("原有限候选的事后参照："+number_text(payload["reference"]["contribution_yuan"])+" 元；不可执行，也不是全局理论最优。")
            st.write("已知科目下原策略与不签合同差额："+number_text(payload["unknown"]["risk_averse_minus_no_contract_known_yuan"])+" 元。")
            st.write("尚未观察科目还需补充的差额："+number_text(payload["unknown"]["additional_unobserved_difference_for_tie_yuan"])+" 元才到并列；不假设它确实存在。")
        with st.expander("预测方法和受控对照"):
            rows=[]
            for r in d["controls"]:
                rows.append({label:number_text(r[key]) for key,label in [
                    ("difference_yuan","已算金额差额（元）"),("mean_daily_mae","原样本平均绝对预测误差"),
                    ("mean_daily_rmse","原样本均方预测误差"),("days","资料日数")] if key in r})
            table(rows);st.caption("仅为原冻结研究对照，预测误差不保证交易贡献；完整字段在技术证据。")
    downloads("B",strategy,payload,index,sheets,d["evidence"])
