# 直接交给 Codex 的安装与启用指令

先把完整 `open-source-radar.zip` 提供给Codex，或者在Codex中打开解压后的 `open-source-radar` 文件夹。只提供SKILL.md会缺少脚本、规则文档和模板。下面整段可直接复制；它是你执行时给予Codex的本地安装/调度授权，不代表本次对话已经替你安装。

```text
请安装并配置我刚提供的 open-source-radar skill 包，按包内文档执行，不重新凭空生成一个简化版本。

先读取README.zh-CN.md、SKILL.md、references/SCHEDULING.md和VERIFICATION.md，检查包的实际目录、脚本和现有安装。不要扫描任务无关目录或凭据。

将完整skill安装到用户级 $HOME/.agents/skills/open-source-radar，将长期状态放在独立持久目录 $HOME/OpenSourceRadar。Windows优先使用PowerShell兼容命令。不得覆盖同名已有skill或非空未知目录；发现冲突时只说明准确路径和差异，不删除或改写原文件。不要git init，不创建远端资源。

确认Python版本并运行随包离线测试。初始化工作区，然后手动执行一次真实联网 $open-source-radar。用当前真正可用的搜索、浏览器或只读GitHub连接器，不编造工具名；外网失败就按降级流程保存，不能宣称在线完整通过。

回读实际daily.md、data.json、audit.json和状态库记录，检查项目真实性、来源、许可、issue占用、贡献政策、未确认技能和覆盖缺口。不得运行或安装候选仓库，不得fork、评论、认领、提交代码或创建PR。

手动真实联网运行完成并经检查可用后，使用本客户端实际支持的Scheduled/计划任务入口，在上述持久目录创建每天宿主本地时间08:00执行的任务，名称“开源项目与贡献机会雷达”。这是我执行此安装指令时接受的默认时刻；创建结果必须显示实际时区和下次运行时间。任务正文完整使用templates/DAILY_PROMPT.md，显式调用 $open-source-radar。不要重复创建同名任务。

若没有可用的本地项目调度工具，不编造codex schedule命令、私有automation.toml格式或创建成功状态；提供在真实Scheduled界面的设置步骤。不在其他不能读取本地工作区的会话中悄悄建立替代任务。

最终分别报告：实际安装路径、工作区路径、测试结果、手动运行结果和文件路径、调度是否真实注册、是否启用、时区/下次运行时间，以及尚未验证项。首次定时任务没有实际触发日志前，只能写“已注册，尚未观察到首次定时执行”。
```

本地项目定时任务依赖机器与桌面应用运行；安装技能本身不是定时器。官方文档核验与平台变化见references/SOURCES.md。
