# Open Source Radar｜中文使用指南

项目概览、快速演示和架构图见 [README.md](README.md)。本工具将开源项目发现、证据核验、贡献机会评估和增量报告串成可复用工作流，运行脚本只依赖 Python 3.10+ 标准库。

## 从演示开始

```powershell
python -B -m unittest discover -s tests -v
python -B examples/demo.py
```

演示采用明确标记的合成数据，不联网、不需要令牌；默认在临时目录运行。保留结果可使用 `--output .demo-output`，且目录必须不存在或为空。

## 安装与配置

Windows 可执行 `./Install.ps1`。安装器先运行离线测试和包清单校验，再只复制清单内文件，避免将 Git 元数据或本地运行数据带入技能目录。默认安装到 `$HOME/.agents/skills/open-source-radar`，工作区为 `$HOME/OpenSourceRadar`；同名技能已存在时拒绝覆盖。

完整安装指令与定时配置见 [INSTALL_IN_CODEX.md](INSTALL_IN_CODEX.md)。安装不自动开启每日任务，宿主调度要单独配置。当前验证范围见 [VERIFICATION.md](VERIFICATION.md)。

`templates/profile.json` 是空的通用画像。可以在初始化前填入自愿提供的兴趣、公开作品和能力证据；未知项保留为空。个人画像不能提交到公共仓库，也不要发给第三方搜索服务。初始化后的固定合同受哈希保护，修改需要显式审阅与迁移。

## 产出与边界

每次运行输出 `daily.md`、`data.json`、`audit.json`，SQLite 保存项目身份、观测、证据、变化和反馈。后续会话通过有界摘要恢复上下文；历史事实须重新核验后才能当作当前事实。

默认候选与深读数量是工作量目标，未达成时明确记录缺口。跨社区发现依赖宿主浏览/搜索能力；本包只提供 GitHub 的独立采集器。不会自动安装或执行候选项目、认领 issue、评论或创建 PR。

数据结构见 [DATA_CONTRACT.md](references/DATA_CONTRACT.md)，机会判断规则见 [CONTRIBUTION.md](references/CONTRIBUTION.md)，参与本项目开发见根目录 [CONTRIBUTING.md](CONTRIBUTING.md)。
