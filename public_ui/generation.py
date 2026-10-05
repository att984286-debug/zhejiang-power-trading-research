import streamlit as st
from .package import get_package
from .common import table,evidence,line_chart,bars,money,COMPONENTS,show_downloads

STRATEGIES={'risk_averse':'风险约束覆盖','fixed':'固定50%覆盖','no_contract':'无合约','risk_neutral':'期望贡献优先'}
GROUPS={'synthetic_2026-08':'完整合成2026年8月','private_2026-09':'非同期映射 · 9月25日','private_2026-10':'非同期映射 · 10月12日'}
CASES={'normal':'正常路径','low_production':'低出力压力','delivery_basis':'交割基差压力'}
VIEWS=['场景与口径','头寸与申报','账本与风险','交易复盘']

def render():
    p=get_package();index=p.read('generation/index.json')
    st.caption('CASE B / 新能源发电企业 / 公共冻结结果')
    st.title('发电不确定，这个月应该承诺多少？')
    st.write('预测不确定性 → 合约头寸 → 申报/接受 → 外生执行 → 现货敞口 → 权益与结算')
    c1,c2=st.columns([1.5,1]);group=c1.selectbox('冻结场景',list(GROUPS),format_func=GROUPS.get,key='b_group')
    strategy=c2.selectbox('冻结合约策略',list(STRATEGIES),format_func=STRATEGIES.get,key='b_strategy')
    payload=p.read(f'generation/{group}.json.gz');d=next(s for s in payload['strategies'] if s['strategy']==strategy)
    if not payload['private_details_omitted']:st.info('完整合成月｜虚拟208MW存量风电 · 研究接受/净量假设 · 不是卖方风场实盘')
    else:st.warning(f"非同期研究｜2022功率＋2025价格＋2026规则 · {payload['sample_days']}个有资料日 · 非完整月、非同一资产同期交易历史。私有分时输入未公开。")
    st.caption('真实收到时间未知，strict未认证；只读冻结研究情景，已评价贡献不是完整利润。')
    view=st.radio('发电研究链路',VIEWS,horizontal=True,key='b_view')
    if view==VIEWS[0]:
        st.subheader('机制权益不是脱离市场的物理电量桶')
        cols=st.columns(3);cols[0].metric('研究主体容量',payload['identity']['capacity_mw']+' MW');cols[1].metric('有资料日',payload['sample_days']);cols[2].metric('完整利润','未建模')
        st.write('电量先参加市场形成分项电费，机制按资格和月量计差价。合同差价、机制差价、环境权益不重复计算同一价值。')
        table([{'角色':'发电出力','口径':'外生生产，不是可移时库存'}, {'角色':'合约量','口径':'月前固定承诺，不随事后价格重签'},
               {'角色':'机制量','口径':'月度权益/结算量，不是独立物理电量桶'}, {'角色':'接受/净量','口径':'研究代理，不认证真实出清/关口计量'}])
        with st.expander('主体、机制资格与日期化规则'):table([payload['identity']]);table(payload['entitlements']);table([payload['rule_selection']])
        with st.expander('GF事实与官方原文定位'):
            for r in index['rules']:st.write(r['fact']['id']+'｜'+r['fact']['assertion']);table(r['refs'])
    elif view==VIEWS[1]:
        st.subheader('为什么没有把可覆盖量全部签完？')
        candidate=next(c['record'] for c in d['candidates'] if c['record']['chosen']);selected=next(c for c in d['candidates'] if c['record']['chosen'])
        cols=st.columns(3);cols[0].metric('选定覆盖率',f"{100*float(candidate['coverage']):.0f}%");cols[1].metric('固定月合约 / MWh',candidate['total_mwh']);cols[2].metric('原200情景预算短缺CVaR / 元',money(selected['risk_score'].get('budget_shortfall_cvar')))
        st.caption(f"分母：预测机制外合格量 {d['decision']['expected_mechanism_outside_mwh']} MWh；不是全发电量。签发：{d['decision']['decided_at']}。")
        candidates=[{**r['record'],**r['risk_score'],'infeasible_reasons':str(r['infeasible_reasons'])} for r in d['candidates']]
        st.plotly_chart(bars([f"{float(r['record']['coverage'])*100:.0f}%" for r in d['candidates']],[r['risk_score'].get('budget_shortfall_cvar') for r in d['candidates']]),width='stretch');table(candidates)
        st.caption('100%不可行源于本研究履约缓冲假设，不是浙江普遍禁止全签；风险目标不保证每条事后路径多赚钱。')
        if d['details_available']:
            dates=sorted({r['interval_start'][:10] for r in d['inputs']});date=st.selectbox('运行日',dates,key='b_date');rows=[r for r in d['inputs'] if r['interval_start'].startswith(date)]
            st.subheader('申报、接受与发出来的电，是三件不同的事')
            st.plotly_chart(line_chart([(label,[r['interval_start'] for r in rows],[r[key] for r in rows]) for label,key in [('申报','q_declared_mwh'),('接受','q_awarded_mwh'),('净量代理','q_net_mwh')]],'MWh / 30min',300),width='stretch');table(rows)
            with st.expander('原合成96点预测与申报时点'):
                submission=next(s for s in d['submissions'] if s['record']['market_date']==date);table([submission['record']]);table(submission['points'])
            if d['monitor']:
                with st.expander('剩余敞口监测，不重签、不自动交易'):table(d['monitor'])
        else:st.info('公网只展示本分支聚合头寸和研究结果。原实测功率、NWP、分时净量/申报输入保留在本地，不用合成数据冒充。')
        st.caption('合成主例不能偷偷附带九月私有接受代理反例。申报≠中标的原验证结论保留，私有反例明细未公开；不认证真实出清。')
    elif view==VIEWS[2]:
        st.subheader('市场电费、合约差价与机制差价，只各算一次')
        st.metric('本窗口已评价贡献 / 元',money(d['evaluated_contribution_yuan']))
        st.plotly_chart(bars([COMPONENTS.get(r['component'],r['component']) for r in d['coverage'] if r.get('evaluated_subtotal_yuan') is not None],
                           [r['evaluated_subtotal_yuan'] for r in d['coverage'] if r.get('evaluated_subtotal_yuan') is not None]),width='stretch');table(d['coverage'])
        st.warning('税、资本/经营成本、返还/补偿等仍有未知或未建模科目；局部已评价贡献不能称企业完整利润。')
        month_lines=[r for r in d['lines'] if len(r['period'])==7];st.write('月机制与环境权益按账期保留，不重复摊到每天');table(month_lines)
        st.subheader('风险：相对月前固定预算的短缺，不是现实亏损概率');table([d['risk']])
        chron=d['chronological_rows'];series=[]
        for segment in sorted({r['segment_id'] for r in chron}):
            rows=[r for r in chron if r['segment_id']==segment];series.append((f'连续段{segment}',[r['date'] for r in rows],[r['segment_cumulative_yuan'] for r in rows]))
        st.plotly_chart(line_chart(series,'相对无合约累计日差额 / 元'),width='stretch');table([d['chronological']])
        if d['details_available']:
            dates=sorted({r['period'][:10] for r in d['lines'] if len(r['period'])>7});date=st.selectbox('查看合成账务日',dates,key='b_ledger_date')
            with st.expander('合成日账务与公式口径'):table([r for r in d['lines'] if r['period'].startswith(date)])
        else:st.info('私有分时金融账本不公开，以免从量、价、金额组合还原原始输入；原逐行证据保留在本地。')
    else:
        st.subheader('降低模型内风险，为什么这条路径仍然少贡献？')
        st.metric('选定策略 − 无合约 / 已评价差额（元）',money(d['attribution'].get('difference_yuan')))
        st.caption('这是账务分解，不是唯一因果证明；不是完整利润差。');table(d['attribution_components'])
        case=st.selectbox('固定复盘案例',list(CASES),format_func=CASES.get,key='b_case');stress=next(s for s in payload['stress'] if s['case']==case)
        st.plotly_chart(bars([STRATEGIES[r['strategy']] for r in stress['rows']],[r['common_mask_contribution_yuan'] for r in stress['rows']]),width='stretch');table(stress['rows'])
        st.caption('原承诺与动作固定的事后压力，不是提前知道冲击后重新签约/申报。')
        if stress['lines']:
            with st.expander('合成压力账本'):
                table(next(s for s in stress['lines'] if s['strategy']==strategy)['rows'][-10:])
        with st.expander('有限候选事后参照（不可执行）'):table([payload['reference']]);table(payload['reference_choices'])
        with st.expander('未知科目会怎样改变结论？'):table([payload['unknown']])
        with st.expander('预测方法与受控因子归因'):
            table(d['controls']);st.caption('原冻结研究对照，预测指标是输入研究，不作为收益保证；不是唯一因果解释。')
    evidence(d['evidence'])
    with st.expander('Case B 公开结果导出'):show_downloads('B',strategy,payload,index)
