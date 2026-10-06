# 浙江电力市场交易策略研究原型

独立储能与新能源发电企业两个平行业务案例。新版把**只读研究回放**和**交互式决策沙盒**永久分开：研究回放读取旧冻结结果；沙盒只根据访客明确提交的条件重新计算。不是实盘、自动申报或企业完整利润系统。

[在线研究与测算](https://zj-power-trading-research.streamlit.app/) · [GitHub源码](https://github.com/att984286-debug/zhejiang-power-trading-research) · [历史首版冻结](PUBLIC_DEPLOYMENT_FREEZE.json) · [历史首版验收](docs/PUBLIC_DEPLOYMENT_ACCEPTANCE.md)

访客无需登录。选择一个案例，再选择“研究回放”或“决策沙盒／头寸沙盒”。沙盒默认“快速测算”，高级入口控制更多假设，不代表数据更真实。默认内容使用中文业务语言，内部字段、版本与指纹在“查看技术证据”中。输入修改后需要主动重新计算，旧答案和旧下载暂停展示。

## 运行

Python 3.12：

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

生产依赖由 `requirements.txt` 引用 `requirements-runtime.txt` 固定。Community Cloud入口是根目录 `app.py`，无需相邻项目、私人目录或知识库。储能仅使用PuLP与HiGHS；不支持静默切换求解器。不要挂载研究文件夹或在启动时重新生成旧结果。

## 两个Case

- A：100MW/200MWh模拟独立储能。价格机会 → SOC/物理约束 → 充放电 → 剩余策略更新 → 已评价贡献与风险。四节点、200节点日、1600策略日，原8种策略和Oracle身份保留。
- B：新能源发电企业。预测不确定性 → 合约承诺 → 申报/接受 → 外生执行 → 现货敞口 → 机制/环境权益与风险。完整合成2026八月为主；九月25日、十月12日非同期研究为聚合详情。

研究纪律：`research`、`synthetic`、`non-synchronous`和严格历史资格阻断均明确显示。2025价格窗口在2026规则参考下属于反事实研究；普通策略不认证实盘可执行。局部已评价贡献不是完整企业利润，未知费用不默认为0。两Case不相加收益、不统一资产状态或账本。

## 公网省略范围

原始CSV/Excel/NWP、完整私有价格序列、卖家聊天、私人路径、源manifest目录与账号凭据不在仓库或运行环境。

A不公开可由分时电量和电费反推出行情的金融明细及原价复制型预测。B非同期分支不公开实测分时功率、净量代理和可还原明细；合成分支仍保留原96/48点链路、分项账务和时点信息。压力详情保留本地G6原视图最后10行，策略汇总完整，未把截取明细冒充全部压力账本。

压力入口沿用原G6的正常、低出力和交割基差三类，未扩展G5其他分支。监测仅公开明确的标量剩余敞口，不将已观测电量序列自动解释为汇总值。

没有公开某字段，不表示数值为0或原件不存在。本地完整研究版本保留原证据链。公网源hash只标识原版本，公开包hash验证筛选后内容，不能据此宣称访客已独立核验私有原始资料。访客手填的价格和电量来自本次用户情景，不是开放原始购买资料；只有本会话能下载本次结果，不建立访客参数库。

## 两个现场测算工具

- 储能：当前电量比例、剩余充放额度、未来价格 → 现在充／放／等、后续计划、电量轨迹、现在满放与等待方案的比较。高级可调整容量、功率、效率、期末电量、损耗与时间间隔。最多96区间，单线程求解5秒、整次计算20秒、同一服务进程最多2项储能任务；繁忙／失败不当成零收益。
- 发电：预计月上网量、少发范围、已有合同、合同价及现货价判断 → 0／25／50／75／100%新增覆盖候选、有限联合情景及正常／稳健取舍。高级可控制机制量和额度、不同参考价、履约条件等。快速模式采用明示的合同锁价研究假设，不认证真实机制资格。

工具只计算声明范围内的收支。储能期初期末电量不同会显示库存变化；发电机制是差价权益，不从市场移除物理电量。未知成本、环境价值和完整利润不自动补零。压力范围不是现实概率，模型输出不是交易指令。

用法、解释路线与资源边界见 [沙盒使用说明](docs/SANDBOX_USAGE_AND_LIMITS.md)；旧版本回退见 [回退说明](docs/SANDBOX_ROLLBACK.md)。

## 校验与更新

```sh
python -m pip install -r requirements-test.txt
python scripts/audit_public.py
python scripts/audit_sandbox_release.py
python -m pytest tests -q
python scripts/check_sandbox_runtime.py
```

公开对象由 `config/public_profile.json` 与 `public_ui/schema.py` 固定允许字段；未知字段拒绝。运行时只读取 `public_results/` 中登记的工件，指纹或身份不匹配即停止，不fallback到其他版本。

`decision_core/`、`sandbox_compute/`、`sandbox_display/`、`sandbox_ui/`来自唯一维护源码的单向白名单发布副本，见 `SANDBOX_SOURCE_MAP.json`；不要在两处分别维护。新增核心不调用历史研究运行时，不重新训练或结算。回放的205份工件、原schema、原机器导出和外部锚点保持首版不变；沙盒采用独立输入指纹、版本和导出契约，明确标记“本次情景测算，不属于历史冻结研究结果”。

发布验收和停止边界见 [公网验收说明](docs/PUBLIC_DEPLOYMENT_ACCEPTANCE.md)。

研究包仍为 `public-20261005-v1`，其 `PUBLIC_DEPLOYMENT_FREEZE.json` 是不可改写的首版历史记录。新版沙盒发布单独记录为 `sandbox-public-20261006-v2`；部署与匿名访问结果以新的 `SANDBOX_RELEASE_FREEZE.json` 为准，不继承旧验收数字。Cloud可能进行平台依赖替换，实际运行环境与洁净Linux的差别需在新冻结中如实登记。

面试前先打开网站检查交互；保留本地完整研究版作断网备用。尚未实测独立手机蜂窝网络，不承诺任意国内网络永久稳定可达。
