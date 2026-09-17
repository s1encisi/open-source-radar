# 数据合同与运行命令

## 目录

```text
<WORKSPACE>/
  mission.md                 固定合同
  profile.json               已确认背景与未知能力
  config.json                配额与预算默认值
  state/radar.sqlite3        唯一权威状态库
  runs/<run_id>/draft.json    当次可编辑记录
  runs/<run_id>/checkpoint-*.json
  evidence/<run_id>/*.json    工具抓取原始记录；不可信外部数据
  reports/<run_id>/daily.md
  reports/<run_id>/data.json
  reports/<run_id>/audit.json
  reports/latest.json        可重建指针
```

不要把runtime数据库写进安装目录，不要让每次新worktree创建一套互不相通的记忆。默认在独立的持久本地项目运行。

## draft根对象

由 `radar.py start` 创建。保留真实run_id/report_date/generated_at/report_timezone/utc_offset；长时间运行后将generated_at改成真实当前观测时刻，不用它替代各证据原先的时间。

`coverage`：每条含family、status、query、note、found、verified、evidence_ids。status为success/partial/blocked/failed/not_attempted。计数指该入口实际发现与完成核验的候选，跨入口会重复，因此不能把各入口found直接相加当唯一项目数。

`evidence`：每条含id、url、observed_at、role、primary、excerpt、sha256。id在整个工作区不可变；建议以run_id开头。role允许repository/readme/license/release/issue/comments/timeline/pull_requests/contributing/ai_policy/benchmark/discovery/code。API提供的字段可以按原值重排为JSON摘录；不能用助手撰写的总结冒充原文。

`projects`：参见 `templates/record-template.json`。模板不是示例事实；先填真实来源，再放进数组。license_status仅允许四种枚举。未知数值写null，不写0或臆造估计。

`claims`：kind/text/evidence_ids。fact与author_claim需原始来源，inference也要有支持的引用；recommendation明确是建议。一个证据对象可以支持多个相关字段，但必须真的支持，不能用整站首页替代特定功能证据。

`opportunities`：参见 `templates/opportunity-template.json`。assignees=null表示未查，[]表示已查且字段为空。claim_status为none_observed/claimed/unknown；linked_pr为none_observed/open/merged/unknown。checks是实际完成检查的布尔值，部分分页不能设true。scope为clear或unknown。ai_policy为allowed/conditional/disallowed/not_found_after_search/unknown。skill_match为verified/potential/unknown；verified需user_capability_evidence来源。

`metrics`：实测非负数或null；没有测到不能填0。token和费用不由本包脚本估算；不同工具调用耗时由宿主汇总。`limitations`为需要保留的字符串数组。

## 用真实API数据形成证据

只读采集器返回原始JSON与观察时间，不直接写“你适合贡献”的结论。例如：

```powershell
$Skill = Join-Path $HOME '.agents\skills\open-source-radar'
$Work = Join-Path $HOME 'OpenSourceRadar'
python -B "$Skill\scripts\github_readonly.py" --output "$Work\evidence\某次运行\repo.json" repo OWNER/REPO
python -B "$Skill\scripts\github_readonly.py" --output "$Work\evidence\某次运行\issue.json" issue OWNER/REPO ISSUE_NUMBER
```

实际使用时OWNER/REPO与ISSUE_NUMBER必须来自真实发现结果；`某次运行`替换为start返回的run_id，不照抄。output已存在会拒绝覆盖。

将采集文件中的API对象精确抽取为证据，可以运行：

```text
python -B <SKILL_ROOT>/scripts/evidence.py --file <CAPTURE_JSON> --json-pointer /result/repository/data --fields id,full_name,html_url,private,archived,stargazers_count,language --id <RUN_ID>-repo --url https://api.github.com/repos/OWNER/REPO --observed-at <CAPTURED_OBSERVED_AT> --role repository --primary
```

该命令只序列化选定的真实字段和计算哈希，不补编任何值。`--observed-at`用工具捕获时间，不是编写报告的时间。网页工具材料先保存短原始摘录，再使用 `--file <EXCERPT_TEXT>`，无需json-pointer；证据URL用真正读取的页面。

不要把404自动当“没有贡献指南”：可能有权限、路径、网络等问题。collector记录失败并返回非零退出码，有些可选端点不存在不代表仓库无效，必须人工判读。

## 生命周期命令

```text
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> init
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> context
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> start
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> query github:NUMERIC_ID
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> checkpoint RUN_ID --phase verify --note "已完成与待恢复的ID和证据路径"
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> validate <DRAFT_PATH>
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> publish <DRAFT_PATH>
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> export RUN_ID
```

validate退出码0表示结构和规则检查没有errors，仍可能有warnings，并不表示真实性已经自动认证。publish退出码0且status=published/already_published才可报告成功。读取实际输出并确认中文内容和计数一致。

显式用户反馈：

```text
python -B <SKILL_ROOT>/scripts/radar.py --workspace <WORKSPACE> feedback --project-id github:NUMERIC_ID --event watch --note "用户明确要求关注" --user-quote "用户本次实际指令原文"
```

feedback不自动改profile。长期画像变更需要专门的、用户明确授权的维护任务，而不是日报自动学习并改写。

## 本包实现范围

GitHub提供标准库只读采集器；GitLab、Gitee、Codeberg、Hugging Face、ModelScope及发现社区通过Codex实际具备的浏览/连接器能力读取，统一填入合同。本包不伪称为每个平台实现了未经测试的API适配器。没有浏览能力时，跨社区覆盖会降级，必须报告。


## 1.0.1：统一决策快照与退出码

首次发布在取得数据库写事务后固定一次 `evaluated_at`，校验和所有机会分类共用该时刻。`audit.json` 与 `data.json` 新增相同的只读 `evaluation` 对象，其中包含 `evaluated_at`、`rules_version` 和 `decisions`。每项决策保存 `project_id`、`number`、`status`、`reason_codes`、`reasons` 与 `evidence_ids`；正文和候选计数直接使用这份快照，不在渲染时重新判断。

`data.json` 中的 `evaluation` 是派生输出，不是填写草稿的输入。重复发布使用原始 `runs/<run_id>/draft.json`：内容与已提交记录相同即可返回 `already_published`，即使已超过 TTL，也不会刷新历史判断。不同内容仍被拒绝。首次发布仍强制检查时效；合成数据与固定合同保护继续生效。

旧的 schema 1 数据库无需迁移。没有决策快照的旧记录仍导出已存储的原始报告、payload 和审计；不会补写新决策或升级历史结论。规则版本与数据表版本、工作区配置版本分别管理。

类型或嵌套结构错误在业务规则之前返回，例如 `$.projects[0].canonical_url: expected str`。有效类型不等于事实已核实。证据主体绑定仍属于后续工作。

采集器在文件和终端结果中共同返回 `transport_complete`、`partial`、`incomplete_reasons` 与 `non_200`。全部 HTTP 200 也可能因为分页、搜索结果或正文截断而 `partial=true`；原因附带采集结果路径。远端正文中的同名字段不会被解释为采集器标志。

采集退出码：`0` 表示本次请求范围内没有已知传输或完整性缺口；`1` 表示已保存不完整结果（包括 HTTP 失败、预算耗尽和截断）；`2` 表示参数或执行错误。调用方不能因退出码 1 丢弃全部结果，也不能把某个可选端点缺失扩展成所有检查都失败。完整性自动约束草稿检查项的转换程序尚未实现。


## 1.1.0：捕获绑定和运行配置

当前 GitHub 正式发布使用 [PIPELINE.md](PIPELINE.md) 中的注册采集流程。证据新增 `subject`（project_id/可选 issue_number）和 `source`（capture_id/pointer/length/可选 projection）。发布前验证 SQLite 登记哈希和原始捕获中的字段，不能只给任意摘录补上正确主体标签。

`evaluation.effective_policy` 保存本次生效的 TTL、累计请求预算、上下文上限与配置哈希。每次 start 冻结一份策略。数据表基础 schema 1 保持不变，工作流扩展有独立版本；历史已发布记录仍按原记录导出，新的非夹具 GitHub 草稿必须有注册来源与完成的语义审阅。

第一阶段只为 GitHub 实现确定性字段转换。其他平台仍依赖宿主只读能力，不得声称它们经过同样的捕获绑定验收。
