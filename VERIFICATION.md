# 验证记录

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
