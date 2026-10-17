# Win10 / COMSOL 6.3 验证复测

实际操作结果和原始证据统一见 [2026-10-17 摘要](validation/2026-10-17/README.md)、[工程 JSON](validation/2026-10-17/engineering-summary.json)、[推荐评估](validation/2026-10-17/recommendation-evaluation.json) 与 [可见操作记录](validation/2026-10-17/visible-ui-record.md)。本页只说明复测步骤；当前状态以 [PROGRESS.md](PROGRESS.md) 为准。

## A. 工程检查与可见操作

准备 Git/LFS、Python 3.12 或 3.13（带 Tk）、COMSOL 6.3 许可证和至少两个逻辑 CPU。先保存已有代码/模型修改。PR 合并后从 `origin/main` 建立新分支；使用新的输出目录，不覆盖工作文件。

```powershell
git fetch origin
git switch -c codex/pc2-recheck origin/main
git lfs install
git lfs pull
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
$comsolRoot = '<本机 Multiphysics 安装目录>'
./.venv/Scripts/python.exe -X utf8 scripts/verify_delivery.py --model-root . --comsol-root $comsolRoot --output-dir ../FlowPlot-validation/pc2-recheck-001
```

若分支或输出目录已存在，换新名称。检查输出必须在仓库和模型输入树之外。失败时保留目录并检查 JSON 与阶段日志；不要只选成功的子项汇报。工程复现需要全量测试成功、六模型完整且 code 集合 6/6 匹配、离线复算一致、源码和输入哈希不变。该结果只覆盖本机工程复现。

可见 UI 使用新生成的基准报告：

```powershell
./.venv/Scripts/python.exe -X utf8 src/flowpilot/recommend_ui.py --report ../FlowPlot-validation/pc2-recheck-001/checks/baseline --comsol-root $comsolRoot
```

记录系统/COMSOL 版本、实际提示和结果。覆盖正常模型、缺少入口、入口重叠、Re 风险、失败/范围外、取消重试、历史、对比、报告包往返、查看完整报告及推荐刷新/拒绝。不要修改模型来制造失败；缺少真实范围外样本就标记“未验证”。

## B. 同机候选质量与耗时

此阶段会运行 COMSOL。仅在基准独立副本上比较四个容差/线程候选，各三次冷求解；不要求解异常模型，并避免同时运行大型计算。使用新输出路径：

```powershell
./.venv/Scripts/python.exe -X utf8 src/flowpilot/calibrate_solver.py --model models/baseline_pipe_2d_laminar.mph --comsol-root $comsolRoot --output-dir ../FlowPlot-validation/pc2-calibration-001
./.venv/Scripts/python.exe -X utf8 src/flowpilot/validate_recommendation.py --report ../FlowPlot-validation/pc2-recheck-001/checks/baseline --calibration ../FlowPlot-validation/pc2-calibration-001/dataset.json --output ../FlowPlot-validation/pc2-ai-evaluation-001.json
```

质量优先于速度。收益需超过 5% 且测量区间不重叠；否则结论为“没有稳定收益证据”。若所选配置与默认相同，不声称加速。评估器不启动 COMSOL，输入测量必须来自同一台电脑。

## 尚未完成的门槛

真实范围外/部分模型界面、新用户五分钟计时、专业复核、至少 10 个独立来源未见模型，以及推荐优于经验/随机参照的证据仍缺。开发基准参与过训练；本流程不能证明独立模型或跨硬件性能。只回传工程 JSON、人工结果和推荐评估 JSON；不要上传模型副本、原生日志、许可证、账户信息或本机路径。
