"""Public v2 entry: frozen research readers plus isolated user-supplied sandbox."""
import streamlit as st
from public_ui.schema import PublicDataError

st.set_page_config(page_title="浙江电力市场交易策略研究原型",layout="wide")
st.markdown("""<style>
.block-container{max-width:1240px;padding-top:3.3rem;padding-bottom:2rem}
h1{font-size:2rem!important}h2{font-size:1.4rem!important}
[data-testid="stMetricValue"]{font-size:1.45rem!important}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p,[data-testid="stCaption"],.stCaption{color:#526570!important}
</style>""",unsafe_allow_html=True)
nav=st.radio("选择案例",["项目总览","案例 A · 独立储能","案例 B · 新能源发电企业"],
    horizontal=True,key="sandbox_nav")
try:
    if nav=="项目总览":
        st.title("浙江电力市场交易策略研究原型")
        st.subheader("看原来的研究，也能给新条件现场测算")
        a,b=st.columns(2)
        with a.container(border=True):
            st.markdown("### 案例 A｜独立储能")
            st.write("有限电池，什么时候充、放、等？")
            st.caption("价格机会 → 电量状态与物理约束 → 充放计划 → 更新剩余安排 → 收支与风险")
            st.write("研究回放：看原来的安排和结果。决策沙盒：输入当前电量、剩余额度及预测价格，重新计算。")
        with b.container(border=True):
            st.markdown("### 案例 B｜新能源发电企业")
            st.write("发电不确定，这个月应该再签多少电？")
            st.caption("预计发电 → 已有与新增合同 → 市场敞口 → 机制差价 → 情景与取舍")
            st.write("研究回放：看申报、接受、执行和分项账务。头寸沙盒：比较不同新增合同量在少发与涨跌时的结果。")
        st.info("两个平行案例，不合并状态和账本，不相加收益。研究回放是只读；沙盒每次根据已提交条件新算。")
        st.caption("兆瓦表示功率或充放速度；兆瓦时表示电量。高级模式只是控制条件更多，不保证更真实、更精确。")
        st.warning("研究与测算均不认证真实成交、正式结算或企业完整利润；原始购买数据不通过页面公开。")
    else:
        storage=nav.startswith("案例 A")
        st.title("有限电池，什么时候充、放、等？" if storage else "发电不确定，这个月应该再签多少电？")
        entry=st.radio("选择使用方式",["研究回放","决策沙盒" if storage else "头寸沙盒"],horizontal=True,
            key="a_entry_s4" if storage else "b_entry_s4")
        if entry=="研究回放":
            from sandbox_ui import replay
            (replay.storage if storage else replay.generation)()
        else:
            from sandbox_ui import storage as a, generation as b
            (a if storage else b).render()
except PublicDataError:
    st.error("冻结结果校验未通过，已停止展示，不回退或暴露源路径。")
except (ValueError,KeyError,TypeError,ArithmeticError,IndexError,OSError):
    st.error("显示或输入结构未通过检查，暂不提供结果；没有使用旧答案或把失败写成零收益。")
