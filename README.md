# FlowPlot

FlowPlot 是面向 COMSOL 二维、单域、稳态层流矩形模型的检查原型。它读取 Inlet、Outlet、Wall 边界，给出缺失、冲突、方向异常和工况风险的结构化证据。当前应用名、旧入口和内部兼容约定见 [NAMING.md](docs/NAMING.md)。

## 当前状态

截至 2026-10-17，第二台电脑记录了全量 555 项测试（554 通过、1 项符号链接权限跳过）、六个模型各两次只读检查及离线重算匹配；12 次副本冷求解完成。推荐仍保留严格双线程默认值，没有稳定收益证据。可见操作记录 13 项中 12 项通过、范围外/部分模型 1 项未验证。完整目标仍未完成：专业审核、独立未见模型、完整可见验收和新用户计时尚缺。

权威当前状态见 [接手说明](docs/HANDOFF.md)、[进度](docs/PROGRESS.md) 与 [完成审计](docs/COMPLETION_AUDIT.md)。第二台电脑原始摘要、可见记录和 JSON 指纹保存在 [validation/2026-10-17](docs/validation/2026-10-17/README.md)。

## 快速开始

需要 Git、Git LFS、Python 3.12 64 位、COMSOL 6.3（需要真实模型检查时）以及 `requirements-dev.txt` 依赖。

```powershell
git clone https://github.com/sssssding/Flowplot.git
cd Flowplot
git lfs install
git lfs pull
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q
```

Windows 桌面入口为 `FlowPlot.cmd`；推荐页签入口为 `FlowPlotAI.cmd`。已有工作树先保存本地修改，再创建个人分支；不要强制重置模型或配置。详细环境、真实模型验证和各阶段命令见 [开发与验证](docs/DEVELOPMENT.md)。

## 文档与仓库

- [文档索引](docs/README.md)：按任务找到唯一入口。
- [项目范围](docs/PROJECT_SCOPE.md)、[技术蓝图](docs/BLUEPRINT.md)：支持边界与架构。
- [开发与验证](docs/DEVELOPMENT.md)：可运行命令、环境和保护条件。
- [只读检查](docs/MODEL_CHECK.md)、[桌面界面](docs/DESKTOP.md)：用户操作。
- [AI 推荐](docs/AI_PORTABILITY.md)：推荐覆盖与限制。
- `src/` 源代码，`tests/` 自动化测试，`data/` 小型受审 fixture，`models/` 模型说明和 LFS 文件。

FlowPilot 是历史名称；内部 `flowpilot` 包、旧入口与旧报告格式保留兼容。