# 工程学习与面试说明 / Engineering notes

2026-10-24补充：本轮先复现再修复慢核对占锁、重复审批身份变化和浏览器旧错误污染新页面；新增持久核对租约、线程实际工作容量、Tenacity安全GET重试、进程退出恢复和真实HTTP测量。完整数据流、设计取舍和面试问题见[架构加固说明](HARDENING.md)。下文是前序实现说明，历史指标不当作本轮容量。

本次技术栈：Python 3.12、FastAPI、Pydantic 2、httpx、PostgreSQL 18.6、psycopg 3/有界连接池，以及无构建步骤的原生 ES modules、HTML/CSS。SQLite 作为有真实验证的本机后备路径保留。未为“现代化”增加无用途的前端框架或消息集群。

数据流：浏览器保存草稿 → Pydantic 校验 → 带版本号的草稿更新 → 事务内生成不可改写报价 → 人工核准精确范围/预算/有效期 → 持久创建请求 ID → 买方同意 → 提交 capture intent → 支付适配器 → 服务端核对 → 同一事务保存最终状态和唯一回执。模型只参与最前面的候选范围整理，不能跨越审批/支付边界。

1. **幂等不等于不允许重试。** 同一请求重发应返回同一个结果，参数变化则拒绝。草稿 ID 约束一次提交；订单 ID/请求 ID 保持稳定；回执有数据库唯一约束。问题：为什么只禁用按钮不能防重复扣款？因为重试可来自刷新、另一个进程或网络客户端，必须由后端与数据库控制。
2. **超时不等于失败。** capture 请求可能已被支付方接受，只是响应没有回来。先落盘 dispatch intent，即使进程退出，重启也能知道“可能已经扣过”。问题：为什么 GET 看到 APPROVED 仍不能清除意图？因为之前的 capture 可能仍在途，不能用一次旧观察证明没有副作用。
3. **锁与事务各管一段。** advisory lock 串行化同一报价跨进程操作；短数据库事务保证本地状态原子；网络调用不占用写事务。问题：为什么不拿着 SQL 写事务等待25秒外部HTTP？会占连接和锁，拖垮其他业务。为什么仅用 Python RLock 不够？两个进程没有共享该锁。
4. **金额用整数分。** 输入 65.00 EUR 转为6500分；数量乘单价后由服务器汇总。避免0.1+0.2这类二进制浮点误差。币种只支持USD/EUR/GBP两位小数，不假装覆盖所有货币。
5. **版本冲突保护协作。** 保存时提交 expected_version，服务端条件检查后递增。两个窗口都编辑第3版时，先保存者变第4版，后保存者得到409并保留本地输入。问题：为什么 last-write-wins 会丢工作？后到达的旧窗口会覆盖先到达的新内容。
6. **连接池不是无限并发。** 四个连接（包含业务锁）、八个排队请求、两秒等待；应用同时最多24个API请求。压力下503明确告诉客户端稍后重试。测量只说明这台机器、这批数据和这次时间窗口，不等于线上容量。
7. **索引不代表消灭扫描。** 列表用轻量投影和SQL分页，不把全部原文读进Python。初次计划需多次索引访问；补ANALYZE并先取50行投影后，最新1000行样本查询执行约0.542ms，仍有一次quotes元数据顺序扫描；包含匹配仍可能扫描元数据，不能宣称千万数据稳定。下一步有真实规模需求再评估全文索引/keyset分页。
8. **为什么没有 Redis？** 关键事实不能因缓存过期而恢复授权。当前本地查询足够快；没有缓存便没有人为引入的击穿、雪崩和错误失效。OAuth token缓存有互斥刷新，业务报价/付款状态不缓存。
9. **AI 引用存在不代表语义正确。** 严格JSON和原文定位只能证明输出结构与出处。还要检查标题是否得到引文支持、排除项是否被误纳入。六例实际推理脚本将技术连接与语义评审分开记录，旧失败不能换个名字当成功。
10. **可恢复备份必须真的恢复。** 这次首次JSON恢复因表顺序触发外键失败；事务回滚保留证据。改为明确依赖顺序后恢复至新的验证schema并逐行相同。仅生成一个备份文件不是恢复能力验证。

前端拆成工作流、翻译、响应契约三个ES模块；Pydantic/OpenAPI定义输入，浏览器对关键快照再次检查类型。新页面没有框架运行时和CDN；取舍是当前复杂度可控，但如果引入多角色实时协作/大量嵌套编辑器，应再考虑有类型组件框架与专用查询缓存，而不是无限增加全局状态。

English: Authorization is deterministic and quote-bound; inference only proposes reviewable work. Durable dispatch intent survives uncertain network outcomes, cross-process locks serialize one quote, and database uniqueness protects one receipt. Tests distinguish local simulation, provider mocks, real PostgreSQL and unverified live PayPal integration. Private local review is not authenticated multi-party approval.

补充学习点：HTTP请求收到响应头不代表结束。并发计数要包围ASGI receive/send的完整周期；慢上传、慢下载和取消都走finally释放。业务锁连接也算数据库预算，不能把池外连接遗漏。COMMIT断连要表达“结果未知”，回滚失败不能覆盖原始业务错误。
