# 浙江电力市场交易策略研究原型

独立储能与新能源发电企业两个平行业务案例。此仓库是只读公网展示层，不是交易执行系统；仅包含字段白名单筛选后的冻结研究结果，不含原始购买数据和私有来源库。

[在线研究展示](https://zj-power-trading-research.streamlit.app/) · [GitHub源码](https://github.com/att984286-debug/zhejiang-power-trading-research) · [发布冻结](PUBLIC_DEPLOYMENT_FREEZE.json) · [验收摘要](docs/PUBLIC_DEPLOYMENT_ACCEPTANCE.md)

访客无需登录。选择上方Case，再依次浏览各自四个研究视图。切换场景后等页面刷新完成，再生成当前选择的公开结果导出。首次加载和图表模块加载可能需要等待；2026-10-05一次匿名测量首次渲染约13秒，不是长期时延保证。

## 运行

Python 3.12：

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

生产依赖仅由 `requirements.txt` 提供。Community Cloud的入口是仓库根 `app.py`；不要挂载本机研究文件夹或在启动时重新生成结果。

## 两个Case

- A：100MW/200MWh模拟独立储能。价格机会 → SOC/物理约束 → 充放电 → 剩余策略更新 → 已评价贡献与风险。四节点、200节点日、1600策略日，原8种策略和Oracle身份保留。
- B：新能源发电企业。预测不确定性 → 合约承诺 → 申报/接受 → 外生执行 → 现货敞口 → 机制/环境权益与风险。完整合成2026八月为主；九月25日、十月12日非同期研究为聚合详情。

研究纪律：`research`、`synthetic`、`non-synchronous`和严格历史资格阻断均明确显示。2025价格窗口在2026规则参考下属于反事实研究；普通策略不认证实盘可执行。局部已评价贡献不是完整企业利润，未知费用不默认为0。两Case不相加收益、不统一资产状态或账本。

## 公网省略范围

原始CSV/Excel/NWP、完整私有价格序列、卖家聊天、私人路径、源manifest目录与账号凭据不在仓库或运行环境。

A不公开可由分时电量和电费反推出行情的金融明细及原价复制型预测。B非同期分支不公开实测分时功率、净量代理和可还原明细；合成分支仍保留原96/48点链路、分项账务和时点信息。压力详情保留本地G6原视图最后10行，策略汇总完整，未把截取明细冒充全部压力账本。

压力入口沿用原G6的正常、低出力和交割基差三类，未扩展G5其他分支。监测仅公开明确的标量剩余敞口，不将已观测电量序列自动解释为汇总值。

没有公开某字段，不表示数值为0或原件不存在。本地完整研究版本保留原证据链。公网源hash只标识原版本，公开包hash验证筛选后内容，不能据此宣称访客已独立核验私有原始资料。

## 校验与更新

```sh
python -m pip install -r requirements-test.txt
python scripts/audit_public.py
python -m pytest tests -q
```

公开对象由 `config/public_profile.json` 与 `public_ui/schema.py` 固定允许字段；未知字段拒绝。运行时只读取 `public_results/` 中登记的工件，指纹或身份不匹配即停止，不fallback到其他版本。

更新结果需要在本地只读验证旧来源，另生成新版本公开包、核对金额/状态和已知反推风险，再更新manifest、外部锚点与发布冻结。此仓库不提供原资料重分发，也不提供训练/优化/结算脚本。不能在公开app里直接修改参数假装得到新研究收益。

发布验收和停止边界见 [公网验收说明](docs/PUBLIC_DEPLOYMENT_ACCEPTANCE.md)。

本次冻结为 `public-20261005-v1`。直接依赖与发布代码保持首个结果提交不变；最终文档提交只补网站入口、冻结记录和验收说明。Cloud实际使用Python 3.12.15，并由平台将pyarrow 25.0.1替换为24.0.0；该云端环境已通过实际网页和下载验收，不将洁净Linux与云端转移依赖误称完全相同。

面试前先打开网站检查交互；保留本地完整研究版作断网备用。尚未实测独立手机蜂窝网络，不承诺任意国内网络永久稳定可达。
