# 开发与验证

## 当前验证状态

2026-10-17 工程结果：555 项中 554 通过、1 项符号链接权限跳过；六个受控模型各只读加载两次，code 集合及离线重算均 6/6 匹配。12 次副本冷求解质量检查通过，但没有稳定收益证据。该记录不等于专业审核、独立模型、新用户或完整可见界面验收。详见 [日期摘要](validation/2026-10-17/README.md) 与 [完成审计](COMPLETION_AUDIT.md)。

## 环境与保护

使用 Git、Git LFS、Windows PowerShell、Python 3.12 64 位及 `requirements-dev.txt` 依赖。真实模型验证使用 COMSOL 6.3 构建 290。可见界面需要 Tk。不要将安装目录写入源码；下方 `<COMSOL_ROOT>` 指含 `bin/win64` 的 Multiphysics 目录。

先保存工作树中的用户修改。只读检查不求解或保存源模型。输出必须位于模型/报告输入树外的新目录；已存在的文件不覆盖。失败目录保留供复核。不要上传许可证、模型副本、原生日志、截图或本机绝对路径。

## 接手与快速回归

```powershell
git fetch origin
git switch -c codex/your-task origin/codex/second-pc-validation-20261017
git lfs pull
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -X utf8 src/flowpilot/preflight.py
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q
```

无 COMSOL 的单元测试不证明真实模型、许可证或桌面流程。真实可复现工程核验：

```powershell
$comsolRoot = '<COMSOL_ROOT>'
./.venv/Scripts/python.exe -X utf8 scripts/verify_delivery.py --model-root . --comsol-root $comsolRoot --output-dir ../FlowPlot-validation/check-001
```

该工具记录全量测试、六个模型各两次只读检查、离线复算及输入/源码稳定性。省略 COMSOL 参数只做离线核验；用户模型有修改时，使用经 manifest 核对的独立原件树，不恢复工作文件。

## 基准与诊断

```powershell
./scripts/build_baseline.ps1 -ComsolRoot '<COMSOL_ROOT>'
./scripts/inspect_baseline.ps1 -ComsolRoot '<COMSOL_ROOT>'
```

生成脚本在模型已存在时停止。枚举脚本连续加载基准十次；指定其他模型的读取入口见 [MODEL_CHECK.md](MODEL_CHECK.md)。规则与受支持边界见 [RULES.md](RULES.md)、[BOUNDARY_CASES.md](BOUNDARY_CASES.md)。

```powershell
./.venv/Scripts/python.exe -X utf8 src/flowpilot/diagnostics.py data/fixtures/cases/baseline.json --output outputs/diagnosis/baseline.json
./.venv/Scripts/python.exe -X utf8 src/flowpilot/diagnostics.py data/fixtures/cases/high_reynolds.json --output outputs/diagnosis/high_reynolds.json --reynolds-warning 2000
```

`checked` 不表示物理通过；需检查 findings。partial、unsupported、失败和取消都不能写成正常检查。

## 推荐实测与专篇

`calibrate_solver.py` 在独立副本上运行真实候选求解；`validate_recommendation.py` 只评估已有测量，不启动 COMSOL。按 [SECOND_PC_VALIDATION.md](SECOND_PC_VALIDATION.md) 的命令记录原始输入指纹、质量检查与比较结果。当前结论是没有稳定收益证据，不声称加速。

其它功能约束及专用命令由 [文档索引](README.md) 指向对应专篇：批量检查、正式验收、桌面、报告导出和历史核验各自保留契约。历史逐轮开发记录可从 Git 追溯，不在此重复。
