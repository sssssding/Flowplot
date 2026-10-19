# M0 起点与回退

2026-10-18 开始实施时，实际 HEAD 是 `1241c27a58fedcfded55ca119e19bfaa4fbde4c6`，分支为 `codex/diagnostic-coverage`。既有标签 `baseline/pre-m0-20261018` 指向该提交。未重新提交或覆盖用户的源模型。

规划提及的 5 个未提交文件已经由该提交保存；它们相对 `890af06` 的变化如下：

| 文件 | 保留的变化 |
|---|---|
| `schema/diagnostic-model.schema.json` | 增加平面边界模板及其几何、壁面模式约束 |
| `src/comsol/ModelInventory.java` | 记录 `isAxisymmetric()` 证据 |
| `src/flowpilot/diagnostics.py` | 矩形数值规则与平面边界规则分开，后者不把包围盒当作 Re 特征尺度 |
| `src/flowpilot/model_overview.py` | 展示平面几何和 Slip 模式 |
| `src/flowpilot/portable_recommend.py` | 推荐限定为原矩形模板 |

同一提交还包含 README、进度和规划文档。因此 `890af06` 是原功能提交，`1241c27` 是包含这 5 项既有扩展的保存点；不能将两个版本混称为同一套已实测源码。用户已确认现有功能人工验收通过；这不自动证明上述扩展的所有模式均已通过真实 API 验证。

本轮起始时仅 `PLAN.md` 尚未提交，内容是把实现派工模型从 GPT-6 Sol 改为 GPT-6.1 Sol，未改变功能范围。该修改随基线说明保留。

验证采用 `git archive 1241c27` 提取的独立源码快照，位于本机忽略目录 `outputs/m0/baseline-source/`。模型只复制已有文件，输入哈希另核对；快照测试不会受到 M0 实现期间并行编辑的影响。原工作目录在实现同时启动的一次探索测试存在并发编辑干扰，不能作为基线或最终验收结果。

该独立快照运行 519 项测试：513 通过、5 失败、1 项 Windows 符号链接权限跳过。四项失败为历史实测来源仍绑定旧源码，涉及批量、桌面、推荐和十四变体摘要；一项失败为旋转几何拒绝原因的旧文案断言。这些是 M0 修改前已经存在的差异。日志为 `outputs/m0/baseline-source/baseline-tests.log`。六模型的预期规则集合测试通过。M0 保留旧证据字节，分别核验历史来源与当前运行，不通过改写旧指纹消除失败。

回退时优先另建检出目录：`git worktree add --detach <新目录> baseline/pre-m0-20261018`。需要严格复现原功能提交时使用 `890af06`。不要通过 `reset --hard` 丢弃当前工作。
