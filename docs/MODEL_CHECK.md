# 指定模型的只读检查

## 用途与支持范围

入口：`src/flowpilot/check_model.py`。在 Windows 上选择一个 `.mph` 文件，通过 COMSOL Java API 读取模型副本，运行现有规则，输出 JSON 和中文 Markdown 报告。

文件路径可自由指定，物理支持范围仍限已验证的二维、单域、米制、轴对齐矩形通道：稳态、牛顿层流、单材料，法向速度入口、压力出口与 No Slip 壁面。参数和几何限制见 [规则说明](RULES.md)。外部文件依赖、密码保护模型及更多物理配置尚未验证；解析失败时运行失败，不生成正常诊断结论。

## 环境与命令

- COMSOL Multiphysics 6.3，当前实测构建号 290，具备加载模型所需的许可。
- Python 3.12 或 3.13，以及 `requirements-dev.txt` 中的依赖。
- 已通过 Git LFS 下载实际模型，不能使用 LFS 指针文件。

在仓库根目录运行，`<COMSOL_ROOT>` 为包含 `bin/win64` 的 Multiphysics 安装目录：

```powershell
python src/flowpilot/check_model.py models/baseline_pipe_2d_laminar.mph --comsol-root '<COMSOL_ROOT>' --output-dir outputs/check/baseline-001 --loads 3
python src/flowpilot/check_model.py models/cases/high_reynolds.mph --comsol-root '<COMSOL_ROOT>' --output-dir outputs/check/high-reynolds-001 --reynolds-warning 2000
```

相对路径按调用时的工作目录解析；在其他目录调用时，可给脚本、输入模型和输出目录传入绝对路径。路径含空格时使用引号。每次指定新的输出目录，已存在的目录拒绝复用。

| 参数 | 含义 |
|---|---|
| `model` | 待检查的 `.mph` 文件路径 |
| `--comsol-root` | COMSOL Multiphysics 安装目录，必填 |
| `--output-dir` | 新运行目录，必填 |
| `--loads` | 加载 1–10 次，默认 1；大于 1 时验证 JSON 重复一致性 |
| `--timeout` | 编译、批处理各自的超时秒数，默认 300，必须为有限正数 |
| `--reynolds-warning` | 以高度 H 计算的名义 Re 筛查阈值，默认 2000，必须为有限正数 |

退出码 0 表示完成检查，结果仍可能为 `unsupported`、`partial` 或含 Critical 的 `checked`；必须读取报告。退出码 1 表示输入、编译、加载、证据校验或诊断失败。

## 输出与可复现性

每次运行生成独立目录：

```text
run/
├─ input.mph              输入模型的字节副本
├─ FileInventory.java     从共享枚举源码生成的独立入口
├─ FileInventory.class    本次编译产物
├─ compile.log            编译输出
├─ batch.log              COMSOL 批处理日志
├─ batch-console.log      包含 JSON 与完成标记的标准输出
├─ inventory.json         实际 API 清单，仅成功时生成
├─ diagnosis.json         现有 diagnosis-0.1 报告
├─ report.md              中文说明、节点/边界证据和建议
└─ run.json               check-run-0.1 运行状态与来源信息
```

运行记录包含源模型文件名及 SHA-256、Python/COMSOL 版本、规则阈值、加载次数和 UTC 时间。`run.json.status` 为 `completed` 才表示产物完整；`failed` 或 `cancelled` 不能当作检查完成。日志与模型副本留在本地 `outputs/` 中，不提交仓库。

## 模型保护与失败处理

Python 先复制输入文件，仅将副本交给 COMSOL。Java 入口只加载、枚举和释放模型，不调用求解或保存；批处理同时使用 `-nosave`。检查结束前再次比较源文件及副本的 SHA-256；发生变化时停止发布诊断。

不同运行使用各自的源码、编译产物及日志。Java 入口从 `ModelInventory.java` 机械生成，复用同一份 `inspectFile` / `inspect` 实现。入口参数只有固定副本名和已校验的加载次数，不把用户路径嵌入 Java 源码，也不通过 Java 普通文件 IO 读取额外配置，因此无需放宽 COMSOL 文件访问安全偏好。

编译必须实际产生新的非空 class；批处理必须输出唯一 JSON 和与请求次数匹配的完成标记。仅有退出码 0 不构成成功证据。超时或中断时终止本次启动的进程树，保留运行目录用于排查。COMSOL 编译或批处理受运行沙箱限制时，需要在允许启动本机 COMSOL 的环境中执行。

COMSOL 参数依据：[6.3 Windows 命令参考](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_ref_running.38.31.html)。

## 验证与未完成验收

离线测试覆盖输入保护、LFS 指针、中文/空格路径、输出拒绝覆盖、无编译产物、缺失/重复标记、异常 JSON、超时、模型哈希变化和报告状态。测试中模拟 COMSOL 进程，不作为真实模型加载证据。

本机真实验证结果记录在 [项目进度](PROGRESS.md)。GUI 速度云图、异常样本专业标签与独立验收集继续按原计划推进；增加文件入口不代表已达到独立 Recall 指标。
