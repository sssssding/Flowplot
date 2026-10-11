# 开发与验证

## 环境

- COMSOL Multiphysics 6.3，已验证构建号 290。
- PowerShell 7（Windows）。
- Python 3.12 64 位（当前验证环境），以及 `requirements-dev.txt` 中的 JSON Schema 验证依赖。
- Git 与 Git LFS。

不在源码中写死 COMSOL 安装目录。以下 `<COMSOL_ROOT>` 指包含 `bin/win64` 的 Multiphysics 安装目录。

## 生成基准模型

在仓库根目录运行：

```powershell
./scripts/build_baseline.ps1 -ComsolRoot '<COMSOL_ROOT>'
```

脚本会编译 `src/comsol/BaselinePipe2D.java`、求解基准模型、保存 `.mph`、重新加载求解三次，并检查质量守恒、速度、壁面内部速度和结果漂移。

- 模型：`models/baseline_pipe_2d_laminar.mph`
- 本机日志与中间模型：`outputs/baseline/<运行时间>/`
- 本机验证报告：`outputs/baseline/verification.json`

为保护已经存在的基准模型，生成脚本在目标 `.mph` 已存在时停止。重新生成前，将旧模型移动到单独的存档目录。失败后 COMSOL 自动保存的中间模型不能作为已验收的基准文件。

COMSOL 的编译器或批处理有时在内部失败时仍返回退出码 0。脚本同时检查编译产物时间、验证标记与 JSON 报告，避免把退出码误当作成功证明。

## 验证加载与枚举

```powershell
./scripts/inspect_baseline.ps1 -ComsolRoot '<COMSOL_ROOT>'
```

工具通过 Java API 十次加载本地基准模型，枚举实际组件、几何、研究、物理场、feature 类型、启用状态、选择结果及一组常用边界表达式。十次 JSON 必须完全相同。

这是基准模型上的只读技术验证。它尚未提供任意输入路径的 CLI，也未覆盖所有物理场、所有边界模式、嵌套 feature 和空间表达式求值。`u0` 等字段可能在当前边界模式下不生效，后续规则引擎必须先判断 `BoundaryCondition`，不能把所有存储属性同时视为有效设置。

`ModelInventory` 现输出 `inventory-0.2`，增加几何/材料证据、声明与有效选择、入口速度模式及 COMSOL 带单位求值。新诊断归一化输出为 `diagnostic-0.1`，对应 `schema/diagnostic-model.schema.json`。旧 `inventory-0.1` 与人工 `0.1.0` fixture 保留作历史参考，不应误认成新工具的自动输出。

## 异常模型与只读诊断

样本生成或复核见 [异常模型](BOUNDARY_CASES.md)，规则约束见 [规则说明](RULES.md)。异常模型不运行求解器，并清除继承的解。

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe src/flowpilot/diagnostics.py data/fixtures/cases/baseline.json --output outputs/diagnosis/baseline.json
./.venv/Scripts/python.exe src/flowpilot/diagnostics.py data/fixtures/cases/high_reynolds.json --output outputs/diagnosis/high_reynolds.json --reynolds-warning 2000
```

输出包含归一化模型和诊断证据。已存在的报告拒绝覆盖，重复运行请换输出路径。`checked` 不是“物理通过”；需读取 findings，`partial` / `unsupported` 也不能当作正常模型。

本机系统 Python 3.14 的依赖解析曾因没有匹配的 rpds wheel 失败，已选用 64 位 Python 3.12 测试环境；虚拟环境不提交仓库。不要为安装依赖关闭证书校验。

## 无 COMSOL 的快速测试

```powershell
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

测试核对版本化 fixture 与实际 API 清单的边界一致性，重新计算质量守恒误差及重复性指标，并检查六个真实模型清单的规则输出、Schema、不支持范围、未求值表达式、默认壁面覆盖与 CLI 不覆盖行为。GitHub Actions 安装依赖后执行这些测试，不执行需要 COMSOL 许可的真实求解；fixture 测试不能代替本机集成验证。

## 更新实验记录

重新生成模型后，将本机 JSON 报告中经审核的证据更新到 `data/fixtures/`，同步更新 `docs/BASELINE_MODEL.md` 中的指标、SHA-256 和验证范围。保留原始日志用于本机排查，但不上传含计算机信息的运行日志。

## API 参考

- [COMSOL 6.3 Named selections](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_api_general.47.56.html)
- 本机 COMSOL 帮助：Java API、Stationary solver 与 COMSOL Commands on Windows。
