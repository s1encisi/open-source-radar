# 来源、发现入口与核验记录

文档核验日：2026-09-15。下列链接是可复用入口，不是已认定为“今天热门”的固定项目清单。每次任务必须实际读取后才能计入覆盖。官网结构、访问要求、API规则和调度方式可能变化；至少每30天复核一次，变更提出维护建议，不自动修改技能安全边界。

## 方法与平台原始文档

| 编号 | 原始来源 | 用途 |
|---|---|---|
| S01 | https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md | 原skill当前入口，委托grilling和domain-modeling |
| S02 | https://www.aihero.dev/grill-with-docs | 方法说明：共享术语、重要决策、实际文件与依赖 |
| S03 | https://developers.openai.com/codex/skills | 官方skill格式、渐进加载、.agents/skills、openai.yaml；核验时跳转至learn.chatgpt.com/docs/build-skills |
| S04 | https://developers.openai.com/codex/app/automations | 官方调度说明；核验时跳转至learn.chatgpt.com/docs/automations?surface=app |
| S05 | https://docs.github.com/en/get-started/exploring-projects-on-github/finding-ways-to-contribute-to-open-source-on-github | 贡献入口与good first issue/help wanted标签 |
| S06 | https://docs.github.com/en/rest/issues/issues | issue接口与PR对象区分 |
| S07 | https://docs.github.com/en/rest/search/search | 搜索分页、最多1000结果、incomplete_results；示例API版本2026-03-10 |
| S08 | https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api | 速率限制、Retry-After、remaining/reset处理 |
| S09 | https://docs.github.com/en/rest/issues/timeline | issue时间线与交叉引用 |
| S10 | https://opensource.org/osd | 公开可读源码与符合开源定义的区别；项目具体许可另查 |
| S11 | https://docs.github.com/en/rest/repos/repos | 仓库不可变ID、归档、许可等元数据 |
| S12 | https://github.com/HackerNews/API | HN官方发现API说明；只作为项目线索入口 |

本包采集器的API版本在S07核验后固定为2026-03-10。版本固定是可复现选择，不意味着永远有效；未来版本变更须重读官方文档并测试。

## 多来源发现矩阵

| 来源家族 | 入口 | 发现价值与限制 |
|---|---|---|
| GitHub | https://github.com/trending ；https://github.com/topics | 热门、主题、活跃项目；必须回官方repo核实，不能只翻榜单 |
| GitLab | https://gitlab.com/explore/projects | 非GitHub托管项目；平台列表可能需要登录，不能绕过 |
| Gitee | https://gitee.com/explore | 中文与国内生态；注意镜像、上游和授权来源 |
| Codeberg | https://codeberg.org/explore/repos | 独立社区、自由软件；访问失败不得算覆盖成功 |
| Hugging Face | https://huggingface.co/spaces ；https://huggingface.co/models | AI应用、模型、数据线索；模型权重/代码/数据许可分别核验 |
| ModelScope | https://modelscope.cn/models | 国内模型与应用生态；前端动态内容需真实浏览能力 |
| Hacker News | https://news.ycombinator.com/show | Show HN中的新工具与创意；热议不等于开源或成熟 |
| 贡献聚合入口 | https://goodfirstissue.dev/ ；https://up-for-grabs.net/ | 发现真实issue入口；最终状态必须回原仓库核验 |
| 基金会与项目目录 | https://projects.apache.org/ ；https://www.cncf.io/projects/ | 稳定生态补充，避开纯流量榜；目录本身不证明存在适合的任务 |
| 中文讨论社区 | https://www.oschina.net/ ；https://www.v2ex.com/ | 中文项目线索与使用反馈；属于发现来源，不充当功能/许可最终证据 |

每日至少尝试5个来源家族，是策略目标；同一平台多个页面不重复计家族。HF模型、Space和关联GitHub同一项目不重复计数。第三方聚合站链接到GitHub，属于不同发现入口，但不算不同项目来源证据；两者要分别记录。

若某入口不可访问：记录具体URL、工具返回、失败类型、是否有官方替代入口。搜索引擎摘要可以补发现，但未经原文验证仍不能升级为已核验事实。不能把“无法读取”写成“没有项目”。

## 本次构建时的实际访问审计

以下仅用于验证设计会披露覆盖缺口，不是每日项目清单：

| 入口 | 本次工具实际结果 | 结论边界 |
|---|---|---|
| GitHub Trending | 浏览工具读取到页面 | 仅确认入口可读；未将页面里的项目逐一评为贡献候选 |
| GitLab trending入口 | 重定向到登录页面 | 未成功读取项目列表，不算成功覆盖 |
| Gitee explore | 浏览工具内部读取错误 | 不代表站点关闭；本次未核实列表 |
| Codeberg explore | 浏览工具内部读取错误 | 不代表站点关闭；本次未核实列表 |
| Hugging Face Spaces | 浏览工具读取到页面 | 仅确认入口可读，模型/项目需逐个核许可 |
| ModelScope models | 工具返回空的可解析正文 | 动态页面读取不足，不算完成项目核验 |
| Up For Grabs | 浏览工具读取到页面 | 聚合入口可用；不是issue当下可用保证 |
| GitHub API采集器联网冒烟 | 当前执行容器返回URLError | 在线传输未验证成功；测试文件保留真实失败，不填充虚构数据 |

## 引用规则

日报正文在事实旁给真实官方链接，证据索引给URL、真实观测时间和sha256。实际读取才能声明verified；文章发布日期、项目创建日期、最后修改日期、工具抓取时间和报告生成时间分别记录，不互相替代。长段资料只摘取必要短段，不批量复制README或评论全文进日报。
