# GitHub 采集、审阅与发布

Python 3.10+，标准库。所有远端调用仅为公开 GitHub HTTPS GET。个人画像与原始捕获保存在源码以外的工作区。

## 生命周期

```powershell
python -B scripts/radar.py --workspace ../radar-workspace init
python -B scripts/radar.py --workspace ../radar-workspace start
```

保存 start 返回的真实运行编号。旧工作区首次使用采集功能时执行 `python -B scripts/workflow.py --workspace ../radar-workspace setup`，会备份数据库后增加三张表；重复 setup 不重复迁移。

候选文件是用户或 Agent 已实际发现的仓库和 issue，例如：

```json
[{"repository": "psf/requests", "issues": []}]
```

```powershell
python -B scripts/workflow.py --workspace ../radar-workspace collect RUN_ID --candidates candidates.json
python -B scripts/workflow.py --workspace ../radar-workspace status RUN_ID
python -B scripts/workflow.py --workspace ../radar-workspace prepare RUN_ID
```

将 RUN_ID 替换为实际编号。collect 默认跳过已有捕获；`--refresh` 追加新捕获，不覆盖旧文件。每次真实请求前通过 SQLite 事务预留额度，多次命令和多个连接共享同一个运行预算。进程中断后的未知尝试保守计入预算，不冒充未调用。此次调用预算不代表 GitHub 账号配额，平台限流仍优先。

prepare 创建新的初稿和 `.annotations.json` 审阅模板，保留原文件。只需填写分类、主张与引用、许可审阅、相关性、限制和评分。机会的认领、PR语义关系、任务范围与能力判断由审阅者提供；仓库和issue的确定性字段不能覆盖。

```powershell
python -B scripts/workflow.py --workspace ../radar-workspace review PREPARED_DRAFT --annotations ANNOTATIONS_JSON
python -B scripts/radar.py --workspace ../radar-workspace validate REVIEWED_DRAFT
python -B scripts/radar.py --workspace ../radar-workspace publish REVIEWED_DRAFT
```

使用各命令实际返回的路径。annotations 的项目必填键为 `project_id/category/license_status/claims/relevance/caveats/scores`。可选 `opportunities` 数组按 number 对应已有 issue；允许补充 `claim_status/linked_pr/related_pr_numbers/scope/ai_policy/skill_match/task/first_step/acceptance/skills_needed/skill_gaps/user_capability_evidence`。`policy_checks` 只允许 `contributing` 与 `ai_policy_search` 布尔值。

`linked_pr=open/merged` 必须列出 captured PR 中状态相符的 `related_pr_numbers`；说明“相关”是否意味着正在解决目标子项仍需读原文。合并不自动证明整个需求已经完成。`comments/timeline/pr_search` 完整性不能由审阅者升级。

## 来源绑定

每份原始捕获以不可变文件加 SQLite 登记哈希保存。证据包含 subject、capture_id、原始字段定位、精确摘录和哈希。PR 证据采用固定的 `pr_evidence_v1` 字段投影，同时保留搜索范围和相关 PR 详情。发布时回读捕获、验证哈希、重新提取并比较证据，同时核对机器字段和检查完整性。

旧版已发布报告继续原样导出。旧版尚未发布的 GitHub 手工草稿需通过本流程重新采集和审阅；不能通过改 provider 绕过绑定。绑定证明引用对象与保存的采集结果一致，不保证远端内容真实、语义判断无误，也不抵御具有本地写权限的人同时改写数据库与捕获。

## 实际执行的配置

| 配置 | 执行位置 |
| --- | --- |
| budgets.github_requests_max | 单个 run 的持久请求台账，范围 1–120 |
| verification.dynamic_ttl_hours | 判定和校验，范围 0.1–168 小时 |
| budgets.initial_context_chars_target | context 序列化上限，范围 2048–64000 字符 |

start 冻结运行配置与配置哈希；audit 的 evaluation 记录生效值。其余领域轮换、探索比例与兴趣评分仍是 Agent 策略，不能视为代码硬约束。已有工作区的固定配置不得静默改写；完整配置迁移工具仍待后续阶段。

## 真实验收边界

三次不同日期的运行必须真实发生。单日重复运行只检验软件增量行为，不替代跨日验收。用户相关性反馈必须来自用户；模型判断应单独标记。未观测 token、费用或人工时间时保留未知。

持久请求预算只约束经本采集器发出的请求；宿主搜索、浏览或连接器调用须另行统计，不能宣称跨工具预算已经由 Python 强制执行。
