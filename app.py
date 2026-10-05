"""Public, read-only dual Case navigation. All data comes from filtered snapshots."""
import streamlit as st
from public_ui.package import get_package
from public_ui.schema import PublicDataError

st.set_page_config(page_title='浙江电力市场交易策略研究原型',page_icon='⚡',layout='wide')
st.markdown('''<style>
.block-container{max-width:1240px;padding-top:3.5rem;padding-bottom:2rem}
h1{font-size:2rem!important;letter-spacing:-.02em}h2{font-size:1.4rem!important}
[data-testid="stMetricValue"]{font-size:1.6rem!important}
[data-testid="stCaptionContainer"]{color:#526570}
</style>''',unsafe_allow_html=True)
NAV=['项目总览','Case A 独立储能','Case B 新能源发电企业']
def reset_case():
    for key in list(st.session_state):
        if key.startswith(('a_','b_')):del st.session_state[key]

nav=st.radio('研究案例',NAV,horizontal=True,key='case_nav',on_change=reset_case,label_visibility='collapsed')
try:
    p=get_package()
    if nav==NAV[0]:
        st.caption('公开版 · 冻结研究结果 · 只读展示')
        st.title('浙江电力市场交易策略研究原型')
        st.subheader('面对价格与预测不确定性，两类资产分别能决定什么？')
        a,b=st.columns(2,gap='large')
        with a.container(border=True):
            st.markdown('### Case A｜独立储能');st.markdown('**有限电池，什么时候充、放、等？**')
            st.write('价格机会 → SOC与物理约束 → 充放电 → 滚动更新 → 贡献与风险')
            st.write('管理库存选择权：容量、功率、循环预算和期末SOC约束下，保留电量与未来机会。')
            st.caption('100MW / 200MWh模拟资产；四节点；2025反事实与2026八月框架样本。')
        with b.container(border=True):
            st.markdown('### Case B｜新能源发电企业');st.markdown('**发电不确定，这个月应该承诺多少？**')
            st.write('预测不确定性 → 合约头寸 → 申报/接受 → 现货敞口 → 权益与结算')
            st.write('管理承诺与风险：外生出力不能移时，机制权益不是独立物理电量桶。')
            st.caption('完整合成交易月为主；非同期实测功率研究作为聚合详情。')
        st.info('共同纪律：当时信息 · 日期化规则/假设 · 原承诺 · 分项账务 · 逻辑证据指纹')
        st.write('两个平行案例，不相加收益，不统一资产状态或账本。普通研究策略不等于真实实盘可执行认证。')
        st.caption('research / synthetic / non-synchronous标签保留；strict未认证。局部已评价贡献≠完整企业利润；未知费用不填0。')
        with st.expander('公网省略范围与证据边界'):
            st.write('未公开：购买原始CSV/Excel/NWP、私有行情完整序列、聊天、私人路径、源manifest目录及凭据。')
            st.write('储能不发布可反推私有价格的分时金融账本；非同期发电分支不发布实测分时功率/净量。')
            st.write('完整合成主例保留完整链路。金额和策略没有因发布重算；原逐行来源在本地核对。公开包hash证明公开版本完整性，不冒充原件公开认证。')
        st.caption('Release '+p.anchor['release_id']+' · 无训练、求解、结算或自动交易按钮。')
    elif nav==NAV[1]:
        from public_ui.storage import render
        render()
    else:
        from public_ui.generation import render
        render()
except PublicDataError:
    st.error('公开冻结结果校验未通过，已停止展示；不自动回退到其他数据版本。');st.stop()
except (ValueError,KeyError,TypeError,OSError,IndexError):
    st.error('公开工件结构或选择不匹配，已停止展示；不显示源路径或载荷。');st.stop()
