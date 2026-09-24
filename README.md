# Open Source Radar

基于 Python 标准库和 SQLite 的开源项目发现与贡献机会核验工具。支持来源绑定、证据校验、增量观测、可恢复报告，以及 Skill 工作流入口。

## 离线运行

需要 Python 3.10+：

```bash
python -B -m unittest discover -s tests -v
python -B examples/demo.py
```

演示使用明确标记的合成夹具，不访问网络。实际采集入口为 `scripts/workflow.py`，状态引擎为 `scripts/radar.py`。Skill 的执行规则在 `SKILL.md`、`references/` 与 `templates/`。

Windows 可显式运行 `Install.ps1` 安装；安装不会自动启用定时任务或执行外部投稿。

许可证：[MIT](LICENSE)。
