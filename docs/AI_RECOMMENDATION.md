# 本地 AI 求解参数推荐原型

2026-10-14；开发分支 `codex/resume-acceptance`。按用户要求提前实现推荐功能，快速检查后收尾本轮功能交付，不撤销原有专业/独立验收门槛。

## 能做什么

双击 `FlowPlotAI.cmd` 启动带“AI 参数推荐”页签的检查窗口。原 `FlowPlot.cmd`、原诊断和报告格式不变。选择 MPH 完成检查，或“读取已有报告…”，随后查看推荐；也可在页签读取自己的学习模型 JSON。

启动入口优先使用显式 `FLOWPILOT_PYTHON`，否则依次尝试现有 `.venv-tests`、`.venv`、系统 Python；启动前检查依赖，不自动安装。缺少依赖时选择已准备环境或按 `DEVELOPMENT.md` 安装项目依赖。

快速离线试用：`./FlowPlotAI.cmd --report '<已有单模型报告目录>'`。启动后直接展示已核验报告和 AI 页签，不需要 COMSOL 或模型原件，不自动开始检查。报告无效时在创建窗口前拒绝；异常报告仍展示拒绝推荐的原因。报告包目录也适用。

首版是本地 k 近邻对数耗时回归，不调用云端大模型，不需 API key，不把二进制 MPH 发送出去。训练数据来自实际冷启动求解。候选为：

| ID | 稳态相对容差 stol | 计算线程数 |
|---|---:|---:|
| strict-1 | 1e-6 | 1 |
| strict-2（原基准） | 1e-6 | 2 |
| balanced-2 | 1e-5 | 2 |
| loose-2 | 1e-4 | 2 |

每配置测量三次，轮换顺序；特征为 `log10(stol)`、`log2(threads)`，k=3。预测为最近三条有效观测的几何平均求解时间；部署仅允许这些已实际测量的配置，不进行未观测候选插值。所有重复必须通过守恒、速度、壁面/反向速度、压降、历史指标漂移检查且无求解器警告，才能进入推荐。相对原基准收益不足 5% 或实测区间重叠时，保留原配置。不保证测量区间是置信区间，也不保证下一次耗时。

只改变副本的稳态求解器 `sol1/s1` 用户控制相对容差及批处理 `-np`，不改物理参数、边界、几何、网格或原模型。相对容差不是网格误差控制或物理正确性的保证。

## 本机重新校准与训练

校准会真实调用 COMSOL，需要许可；仅接受 manifest 中已提交基准的相同 SHA-256，可指定其独立副本，不接受本机有修改的原文件。输出必须为新目录，异常或中断不发布学习模型，已有副本/日志保留本地排查。

```powershell
python src/flowpilot/calibrate_solver.py --model '<与 manifest 一致的基准副本.mph>' --comsol-root '<Multiphysics 目录>' --output-dir outputs/ai-recommendation/my-calibration-001
python src/flowpilot/recommend.py train --dataset outputs/ai-recommendation/my-calibration-001/dataset.json --output outputs/ai-recommendation/my-model.json
python src/flowpilot/recommend.py recommend --report '<基准单模型检查目录>' --learned-model outputs/ai-recommendation/my-model.json
```

`train` 是读取测量样本构建惰性学习器，不再次求解；`recommend` 只读，退出码 0 为有建议、2 为明确不能推荐、1 为读取或验证失败。输出 JSON 用 `--output` 另存新文件，不能覆盖。

默认学习文件为 `data/ai/solver_ranker.json`。它只适用于同一基准哈希和校准运行环境；机器指纹由平台/CPU描述/逻辑CPU数生成，不包含主机名、账号、路径或许可证，但也不是完整硬件/负载认证。换电脑先在本机校准，再通过窗口选择新模型；不要修改旧数据指纹绕过限制。

## 拒绝推荐的情况

- 诊断存在任何问题，或状态为 partial/unsupported：先处理模型，推荐不能覆盖规则证据。
- 模型未参与校准或文件哈希不同：当前基准数据不能外推到另一模型。
- 运行环境不匹配、数据缺失/重复/损坏、驱动或参考指标变化。
- 原基准候选未通过全部质量门槛。

校准 JSON/学习模型不是签名或认证；只使用自己生成或经审阅的文件。读取模型/报告有容量限制，重复字段、非有限数值和不一致质量记录拒绝。界面清空报告或读取失败时不保留旧推荐。推荐界面没有“自动应用”操作，用户在副本中自行核对建议。

## 验证边界与回退

本轮实际校准、离线故障测试及隐藏 Tk 功能检查的结果见 `PROGRESS.md`；原始模型副本/日志在忽略的 outputs 中，不直接共享。历史证据原样保留。

这是同一开发基准的配置学习，不是多个独立模型，也没有模型级训练/测试划分。因此不宣称优于 COMSOL 默认、经验或随机配置基线；T13 的正式性能验收仍待完成。后续需独立模型、专业审核及真实新用户测试；快速功能检查不能替代这些步骤。

回退只需停止使用 `FlowPlotAI.cmd` 并撤回本轮新增推荐/校准/窗口模块和学习文件；原检查入口及六个模型保持不变。

API 依据：[COMSOL 6.3 Stationary solver 编程参考](https://cdn.comsol.com/doc/6.3.0.290/COMSOL_ProgrammingReferenceManual.pdf)（`control=user`、`stol`）；[COMSOL 并行批处理说明](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_ref_running.38.32.html)（`-np`）。具体 Windows 命令已通过本机真实校准核对。
