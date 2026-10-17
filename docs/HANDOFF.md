# 当前接手说明

本次文档整理以 `d1f8a314a865f2c52f154075ad6a56c9419f3c9d` 为来源基线；该提交用于定位 2026-10-17 验证记录，不是后续开发分支入口。最新测试数字和实际结果只维护于 [PROGRESS.md](PROGRESS.md)，完整用户门槛与证据见 [COMPLETION_AUDIT.md](COMPLETION_AUDIT.md)。

## 继续开发

PR 合并后，从 `origin/main` 建立个人分支：

```powershell
git fetch origin
git switch -c codex/your-task origin/main
git lfs pull
python -X utf8 src/flowpilot/preflight.py
python -X utf8 -m unittest discover -s tests -q
```

分支名已存在时另选新名。先保存任何用户修改；不得强制重置或覆盖基准模型、配置和本地证据。模型检查输出放到输入根目录以外的新路径。完整环境与可运行验证命令见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 按需阅读

- [PROGRESS.md](PROGRESS.md)：当前实测结果及明确未完成项。
- [COMPLETION_AUDIT.md](COMPLETION_AUDIT.md)：原始产品目标、各自证据和验收缺口。
- [DELIVERY_PLAN.md](DELIVERY_PLAN.md)：下一步顺序及完成条件。
- [SECOND_PC_VALIDATION.md](SECOND_PC_VALIDATION.md)：可复测命令；10 月 17 日的实际结果链接至日期摘要。
- [PROJECT_SCOPE.md](PROJECT_SCOPE.md)、[DEVELOPMENT.md](DEVELOPMENT.md)：受支持范围、操作约束与开发命令。

历史逐轮过程可从 Git 提交追溯；模型副本、原生日志、截图、许可证和本机路径不随文档同步。
