"""Display formatting only. Shared appearance, not shared asset logic."""
from decimal import Decimal
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from .schema import canonical

COLORS=['#087f75','#db843b','#5b6f9e','#965875','#71836d','#b65e5e']
COMPONENTS={'day_ahead':'日前电费','real_time':'实时偏差','contract_energy':'合约差价',
            'deviation_recovery':'偏差回收','mechanism':'机制差价','environment':'环境权益',
            'recovery_refund':'回收返还','environment_compensation':'环境补偿','taxes':'税费',
            'operating_and_capital_costs':'经营/资本成本','other_fees':'其他费用','full_profit':'完整利润'}

def money(value):
    return '不可评价 / 未知' if value is None or value=='' else f'{Decimal(str(value)):,.2f}'

def table(rows,columns=None):
    if not rows:st.info('当前公开范围没有该明细；不是0，也不自动换场景。');return
    frame=pd.DataFrame(rows)
    if columns:frame=frame.reindex(columns=columns)
    for col in frame:
        if frame[col].dtype=='object':frame[col]=frame[col].map(lambda x:None if x is None else str(x))
    st.dataframe(frame,hide_index=True,width='stretch',height=min(380,55+35*len(frame)))

def evidence(rows,title='公开逻辑证据与指纹'):
    with st.expander(title):table(rows)

def line_chart(series,unit,height=270):
    fig=go.Figure()
    for i,(label,x,y) in enumerate(series):
        fig.add_trace(go.Scatter(x=x,y=[None if v is None else float(v) for v in y],name=label,
                                mode='lines',line={'color':COLORS[i%len(COLORS)],'width':2},connectgaps=False))
    fig.update_layout(height=height,margin={'l':8,'r':8,'t':10,'b':10},yaxis_title=unit,
                      paper_bgcolor='white',plot_bgcolor='white',hovermode='x unified',
                      font={'family':'Arial, PingFang SC, sans-serif','size':13},legend={'orientation':'h','y':1.2})
    fig.update_yaxes(gridcolor='#edf1f3');return fig

def bars(labels,values,unit='元'):
    fig=go.Figure(go.Bar(x=labels,y=[None if v is None else float(v) for v in values],
                       marker_color=[COLORS[0] if v is not None and float(v)>=0 else COLORS[1] for v in values]))
    fig.update_layout(height=280,margin={'l':8,'r':8,'t':10,'b':10},yaxis_title=unit,
                      paper_bgcolor='white',plot_bgcolor='white',xaxis_type='category')
    return fig

def show_downloads(case,selection,payload,index):
    from .export import export_bytes,export_metadata
    key=f'{case}:{selection}'
    if st.button(f'生成 Case {case} 公开结果导出',key=f'{case}_prepare_export'):
        raw,record=export_bytes(case,selection,payload,index)
        st.download_button(f'下载 Case {case} 公开结果工作簿',raw,f'Case_{case}_公开冻结结果.xlsx',
                           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key=key+':xlsx',on_click='ignore')
        st.download_button(f'下载 Case {case} 公开追溯元数据',canonical(record).encode(),f'Case_{case}_公开追溯.json',
                           'application/json',key=key+':json',on_click='ignore')
    st.caption('仅当前选择的白名单结果；不提供原始数据、原来源目录或整库下载。')
