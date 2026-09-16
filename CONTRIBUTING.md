# 参与开发

本项目运行于 Python 3.10+，不需要第三方运行依赖。提交改动前执行：

```powershell
python -B -m unittest discover -s tests -v
python -B examples/demo.py
python -B scripts/package_manifest.py
python -B scripts/package_manifest.py --check
```

请说明要解决的问题、变化后的行为和实际验证结果。状态、证据、发布流程的修改应提供覆盖失败场景的测试；文档修改不要求添加镜像式测试。

测试只使用明确标记的合成资料。不要提交个人画像、真实工作区、令牌、候选项目的私有内容或未经核实的性能数字。生产 CLI 默认拒绝合成项目，演示只在隔离目录显式放行。

AI 辅助修改需要由提交者审阅和验证；引用外部实现或材料时注明来源。仓库的贡献指南不代表候选项目也采用同样政策。
