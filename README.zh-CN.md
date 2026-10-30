# ScopePay

**10月30日私有发布审阅：**最新英文成片138.666016秒，展示250美元模拟报价及另一次已完成的1美元官方Sandbox回执；命令行评委用例使用300美元。三种金额对应不同记录，不合并成同一笔交易。源码与视频URL待发布，材料审阅无需新交易。

**2026-10-28 / v1.2.1联调更新：**官方Sandbox OAuth、创建订单、测试买家同意、1美元虚拟capture、服务端核对回执全部完成。重复capture与刷新仍保留同一回执和一次派发。真实金额对象的可选breakdown字段暴露的整体相等判断缺陷已修复，金额/币种/商家/报价仍严格校验，30项相关回归通过，见[当前实证](docs/SANDBOX-20261028.md)。没有真实资金交易、公开发布或最终投稿。

当前入口：[评委运行说明](docs/JUDGE-SETUP.md)、[功能证据对照](docs/SCORING-AND-EVIDENCE.md)、[英文提交草案](docs/SUBMISSION-20261028.md)、[138.666秒现有成片说明](docs/DEMO-STORYBOARD.md)、[本轮实现与面试学习](docs/SPRINT-LEARNING.md)。真实本地模型提取与本次手工输入沙箱订单分别有证据，不冒充同一条AI支付记录。

v1.1架构加固：审批快照绑定支付、持久核对与有限重试、远程等待不占业务锁、同步线程实际容量、前端旧响应隔离。见[具体机制与学习点](docs/HARDENING.md)及[20类可靠性矩阵](docs/ROBUSTNESS-MATRIX.md)。交付仍限私有工作区与明确标识的模拟或官方Sandbox模式，尚非公开生产服务。

[English](README.md) · [产品范围](PRODUCT.md) · [部署](DEPLOYMENT.md) · [数据库](DATABASE.md) · [可靠性实证](docs/RELIABILITY.md) · [学习与面试](docs/LEARNING.md)

ScopePay 是私有采购审阅工作台：保存供应商报价，确定纳入范围、预算与批准有效期，按固定金额审批，再跟踪同一支付意图的买方同意、扣款、未知结果核对和唯一回执。修改范围必须建立修订稿并重新审批。

首页直接进入可搜索的采购列表。支持草稿保存/恢复、版本冲突提示、预算超限拦截、退回修改、撤销、过期和回执历史。界面切换中英文不会翻译或覆盖原始需求和用户输入。

## 启动

Python3.12 + FastAPI/Pydantic + PostgreSQL/Psycopg3；SQLite保留为本机后备；前端为离线可用的HTML/CSS/ES模块，无Node构建、无CDN。

```powershell
python -m venv .venv
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip install --no-clean -r requirements-lock.txt
Copy-Item .env.product.example .env
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

打开启动器输出的本机8215端口地址。停止用`scripts/stop.ps1`，会验证进程身份且不删除文件。现有配置不要直接覆盖；当前私有安装已使用真实PostgreSQL，旧SQLite完整保留。新安装默认模拟处理器与SQLite，可按DATABASE.md迁移。

## 使用路径

1. 新建采购或选取明确标注的示例。填写标题、供应商与原始需求。支持手工添加、按行整理，以及已配置本地模型的候选建议。
2. 勾选纳入的工作项，填写数量、正常货币单位的单价、预算和有效期；未完成可先保存草稿。
3. 提交后报价锁定。核对范围/币种/总额，记录本地审阅人并批准，或填写退回原因。预算不足不能提交。
4. 创建付款订单，获得买方同意，再捕获确定的金额。模拟模式可选择正常、响应丢失、处理器拒绝三条真实本地状态路径。
5. 扣款结果未知时，刷新后仍保持未知，只有核对入口，不能再次扣款或假装撤销成功。
6. 完成后读取唯一回执、查看处理历史、下载记录或打印。旧报价与新修订稿各有完整历史。

## 当前边界

本次已实现并实际验证本地采购闭环、真实PostgreSQL写入/迁移、两种数据库回归、跨进程单次捕获、备份恢复、中英浏览器操作和下载来源。源码交付包排除数据库、凭据、原始输入、私人报名资料与历史失败证据。

官方PayPal Sandbox已完成一笔1美元虚拟交易的真实API闭环，核对到一次完成capture；本笔为手工范围输入，真实本地AI提取另有记录。没有真钱交易或公网上线。适配器固定使用Sandbox，不支持任意供应商转账或买方委托钱包。本地审阅人姓名不是经过身份认证的客户电子签名；公众多用户托管还需要登录、租户隔离等能力。

AI只是可选范围建议，不能定价或触发支付。历史0.5B语义失败原样保留。本次实际调用共享qwen3.5-4b，首轮发现标题遗漏数量，修正后六个中英合成案例通过引用/数量检查及本线程语义复核；浏览器也实际完成一次模型建议。不是总体准确率或独立人工评审。见[模型记录](docs/MODEL.md)。人工流程可以独立完成。

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip check
```

真实PostgreSQL检查通过`--postgres-config <私人配置>`为每项测试建立独立保留schema。健康/就绪分别使用`/api/health`与`/api/ready`。部署、备份、故障实证与学习内容见上方文档，不进入产品操作页面。
