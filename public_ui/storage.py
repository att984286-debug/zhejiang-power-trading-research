import streamlit as st
from .package import get_package
from .common import table,evidence,line_chart,bars,money,show_downloads

STRATEGIES={'A_no_operation':'不操作','B_forecast_threshold':'预测阈值','C_lag_milp':'历史基线优化',
            'C_ridge_milp':'Ridge日前优化','D_rolling_rt':'滚动RT重优化','S_static_once_rt':'单次RT调整',
            'E_oracle_reference':'DA全知参照（不可执行）','F_rt_oracle_remaining_reference':'剩余RT全知参照（不可执行）'}
NODES={'RESEARCH_JIANGDONG':'江东热电 · 主案例','RESEARCH_BAIYI':'百益站#1机组','RESEARCH_LANXI':'兰溪厂#1机组','RESEARCH_YUHUAN':'玉环厂#1机组'}
VIEWS=['资产与口径','日前计划','滚动更新','账本与复盘']

def power_series(rows):
    return [r.get('interval_start',r.get('timestamp')) for r in rows],[r.get('net_injection_mw',float(r.get('discharge_power_mw',0))-float(r.get('charge_power_mw',0))) for r in rows]

def render():
    p=get_package();index=p.read('storage/index.json')
    st.caption('CASE A / 独立储能 / 公共冻结结果')
    st.title('有限电池，什么时候充、放、等？')
    st.write('价格机会 → 物理约束 → SOC → 充放电 → 剩余策略更新 → 贡献与风险')
    c1,c2,c3=st.columns([1.1,1,1.6])
    nodes=sorted({r['node_id'] for r in index['rows']})
    node=c1.selectbox('价格环境',nodes,index=nodes.index('RESEARCH_JIANGDONG'),format_func=NODES.get,key='a_node')
    dates=sorted({r['market_date'] for r in index['rows'] if r['node_id']==node})
    date=c2.selectbox('数据日',dates,index=dates.index('2025-09-02'),key='a_date')
    strategy=c3.selectbox('冻结策略',list(STRATEGIES),index=list(STRATEGIES).index('D_rolling_rt'),format_func=STRATEGIES.get,key='a_strategy')
    day=p.read(f'storage/{node}/{date}.json.gz');d=next(s for s in day['strategies'] if s['strategy']==strategy)
    st.info(f"研究情景｜数据日 {date} · 规则参考日 {day['context']['rule_reference_date']} · 15分钟动作 / 30分钟结算 · 非真实成交认证")
    if d['summary']['reference_only']:st.warning('Oracle使用未来实际价格：仅为事后参照，不可执行。')
    view=st.radio('储能研究链路',VIEWS,horizontal=True,key='a_view')
    if view==VIEWS[0]:
        st.subheader('为未来机会保留多少电量？')
        cols=st.columns(4)
        for c,label,val in zip(cols,['最大功率','额定容量','SOC范围','期初 / 期末SOC'],['100 MW','200 MWh','10%—90%','50% / 50%']):c.metric(label,val)
        st.write('充放效率各95%；日等效循环上限1次；模拟衰减30元/MWh毛吞吐。')
        table([{'参数':k,'冻结值':v} for k,v in index['asset'].items()])
        st.warning('严格历史资格阻断：真实received_at/available_at不可验证，不是严格历史可执行认证。')
        table([r for r in index['strict'] if r['date']==date and r['node_id']==node])
        with st.expander('八月框架与缺实时价诊断'):
            st.write('8月1—8日只验证框架；8月9日缺实时价，不可评价≠0收益。');table(index['missing_rt'])
        st.caption('四节点是价格环境对照，不证明真实储能选址/220kV接网身份；2025为2026规则参考下反事实研究。')
    elif view==VIEWS[1]:
        st.subheader('价格判断怎样成为原日前计划？')
        st.info('私有原生行情及完整预测价格序列不在公网范围。原计划、采用动作和SOC读取原冻结结果，没有用新数据替代。')
        x,y=power_series(d['original_plan']);st.plotly_chart(line_chart([('原日前净功率：放+ / 充−',x,y)],'MW',230),width='stretch')
        rows=d['original_plan'];st.plotly_chart(line_chart([('原计划SOC边界',[rows[0]['interval_start']]+[r['interval_end'] for r in rows],
            [100*rows[0]['soc_before_ratio']]+[100*r['soc_after_ratio'] for r in rows])],'SOC %',220),width='stretch')
        i=st.selectbox('检查采用执行中的一个动作',range(len(d['actions'])),format_func=lambda j:d['actions'][j]['interval_start'][11:16],key='a_action')
        table([d['actions'][i]])
        if d['explanations']:table([d['explanations'][i]])
        else:st.info('全知参照没有普通策略事前动作解释。')
        st.caption('只解释采用版本、状态和约束事实，不证明某个约束是唯一最优原因；不根据事后高价补写动机。')
    elif view==VIEWS[2]:
        st.subheader('更新剩余策略，不抹掉已执行前缀')
        events=d['events']
        if not events:st.info('当前策略无逐小时滚动事件；可选择滚动RT重优化。')
        else:
            i=st.selectbox('冻结更新时点',range(len(events)),format_func=lambda j:events[j]['decision_asof'][11:16],key='a_event');e=events[i]
            cols=st.columns(4)
            for c,label,key in zip(cols,['当前电量 MWh','已用吞吐 MWh','剩余预算 MWh','已验证当日新观测'],['current_energy_mwh','used_throughput_mwh','remaining_budget_mwh','current_day_observed_intervals']):c.metric(label,str(e[key]))
            proposal=next((r['actions'] for r in d['proposals'] if r['proposal_sha256']==e['proposal_sha256']),[])
            series=[]
            for label,rows in [('原计划',d['original_plan']),('本次剩余建议',proposal),('实际模拟采用',d['actions'])]:
                x,y=power_series(rows);series.append((label,x,y))
            st.plotly_chart(line_chart(series,'MW',350),width='stretch')
            st.write('当前SOC＋已执行前缀＋剩余预算＋原DA承诺＋原终端目标 → 剩余策略建议。')
            table([e]);st.warning('已验证当日新行情数为0，假定许可不是真实调度；滚动更新不等于随时重新交易。')
        st.metric('额外滚动贡献 − 单次调整 / 元',money(d['attribution'].get('additional_rolling_yuan')))
    else:
        st.subheader('这次亏在哪里，而不是只看一个收益数字')
        r=d['summary'];cols=st.columns(4)
        for c,label,key in zip(cols,['DA电费 / 元','RT偏差 / 元','模拟衰减 / 元','已评价贡献 / 元'],['da_amount_yuan','rt_amount_yuan','degradation_cost_yuan','simulated_contribution_yuan']):c.metric(label,money(r[key]))
        ordinary=[s['summary'] for s in day['strategies'] if not s['summary']['reference_only']]
        st.plotly_chart(bars([STRATEGIES[r['strategy']] for r in ordinary],[r['simulated_contribution_yuan'] for r in ordinary]),width='stretch')
        with st.expander('同日策略与不可执行参照'):table([s['summary'] for s in day['strategies']])
        st.caption('效率损耗已经体现在电量和SOC，不重复扣费；完整利润未建模，未知费用不填0。')
        pack='august_2026' if date.startswith('2026-08') else 'counterfactual_2025'
        split='august_framework_only' if pack=='august_2026' else 'test'
        source_row=next(r for r in index['rows'] if r['node_id']==node and r['market_date']==date and r['strategy']==strategy)
        risks=[c for c in index['comparisons'] if c['record']['split']==split and c['record']['strategy']==strategy
               and c['record']['group']==source_row['comparison_group'] and c['record']['pack']==pack]
        st.write('原冻结窗口风险，不按当前选择重估CVaR。');table([{**r['record'],**r['risk']} for r in risks])
        with st.expander('固定动作压力与受控归因'):
            table([r for r in index['stress'] if r['market_date']==date and r['node_id']==node and r['strategy']==strategy]);table([d['attribution']])
        st.info('分时电量＋电费可反推私有价格，公网不发布原48点金融账本。通用口径：DA承诺×DA价＋实际偏差×RT价−模拟衰减；原逐行追溯保留在本地。')
    evidence(d['evidence'])
    with st.expander('Case A 公开结果导出'):show_downloads('A',strategy,day,index)
