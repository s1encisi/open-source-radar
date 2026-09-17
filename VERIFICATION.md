# 验证记录

## 1.1.0 第一阶段工程验收：2026-09-17

本地103项测试通过，技能frontmatter检查通过。新增来源绑定、保护机器字段、语义审阅、请求预算跨连接累计、配置实际生效和UTF-8 CLI输出的测试。真实运行完成10个候选、3个深读项目与2条issue，两个issue均有进行中的PR；重复发布与报告恢复已用这次真实运行验证。机器可读结果见 [stage1-checks.json](verification/stage1-checks.json)，范围与后续跨日验收见 [ACCEPTANCE.md](docs/ACCEPTANCE.md)。

本地测试不替代远端CI；实际矩阵状态见 GitHub Actions。跨日验收当前为1/3，未虚构后续日期或用户满意度。

## 批次 A 本地验收：2026-09-17

Windows / Python 3.11.14；引擎 1.0.1。82 项离线测试通过（原有 60 项，加 22 项回归与兼容测试），双次观测演示通过。完整输出见 [batch-a-unit-tests.txt](verification/batch-a-unit-tests.txt)，机器可读结果见 [batch-a-checks.json](verification/batch-a-checks.json)。

覆盖统一判定时钟、TTL 边界下正文/JSON/审计一致、过期负面状态、嵌套类型错误、CLI 错误输出、全 200 但不完整的采集、过期后重复发布、旧版记录无迁移导出及原有合同/夹具保护。另执行 1,384 个 JSON 字段类型替换案例，未出现未捕获异常；这不代表已穷尽所有非法输入。

本批次未修改真实运行工作区，也未执行新的联网日报、安装或定时任务。尚未提交或推送，因此远端 CI 记录仍对应 1.0.0；不能将此前的 8 组 CI 当成本次改动的验证结果。

## 当前本地验收：2026-09-16

环境：Windows，Python 3.11.14。机器可读记录见 [current-checks.json](verification/current-checks.json)。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 离线回归测试 | 60 项通过 | [完整日志](verification/windows-unit-tests.txt) |
| 双次观测演示 | 1 个项目、2 次观测，Star +4，贡献状态变更 | [演示结果](examples/sample-summary.json) |
| 重复发布与报告恢复 | 通过，重复发布未增加观测，恢复后字节一致 | `examples/demo.py` 中的运行时断言 |
| GitHub 公开仓库采集 | 5 次 GET 均返回 HTTP 200 | [采集摘要](verification/network-smoke-summary.json) |

联网冒烟读取 `psf/requests` 的仓库元数据、README、许可证、社区配置和近期发布，只验证采集传输，不构成项目推荐。公开摘要只保留请求 URL、状态、耗时和原始响应哈希；未将第三方完整正文加入仓库。

在本次 Windows 验证中修复了两处测试使用默认 GBK 读取 UTF-8 中文报告的错误。生产报告的写入编码原本就是 UTF-8。

CI 配置在 Windows/Linux 上分别运行 Python 3.10、3.11、3.12、3.13 的测试、演示和包清单校验。实际 CI 状态以 [GitHub Actions](https://github.com/s1encisi/open-source-radar/actions) 为准，不把已配置的矩阵视为已通过。

## 历史记录

原始包记录了 Linux/Python 3.13.5 的 60 项离线测试通过，以及一次 URLError 联网失败，分别保留于 `verification/unit-tests.txt`、`verification/package-checks.json` 和 `verification/network-smoke-failed.json`。历史失败不代表当前环境仍然失败，当前联网成功也不代表所有网络都可用。

## 尚未验证

- 未在真实用户技能目录执行安装器，也未注册每日任务。
- 未执行覆盖 40–80 个候选的完整真实日报或观察首次定时触发。
- 未测量线上推荐准确率、人工节省时间、贡献接受率或多进程性能。
- 双次观测演示是合成夹具，不能据此联系或认领真实项目。

结构校验、URL 检查和证据哈希验证不证明外部内容真实，语义引用仍需读源复核。
