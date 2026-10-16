# 第二台电脑检验（Windows 10 / COMSOL 6.3）

2026-10-16：用户确认可提供此环境并执行步骤。以下是操作方案，不是第二台电脑已经通过的记录。先完成 A，再按需要执行 B；每次使用新的输出位置，不删除或覆盖上次结果。

两阶段尽量保持同一代码提交，不在检查或求解期间更新工作文件。推荐说明更新后会显示覆盖、当前参数、网格限制及默认保留原因；旧版本输出仍须按其实际来源记录，不手改结果适配新版。

## A. 功能与真实模型复现

准备：Git/Git LFS、带 Tk 的 Python 3.12/3.13、可使用的 COMSOL 6.3 许可证，及至少两个逻辑 CPU。已有自己的代码或模型改动先保存，勿强制重置。拉取当前开发分支后创建自己的检验分支；分支名已存在时另选。

```powershell
git fetch origin
git switch -c codex/second-pc-validation origin/codex/post-handoff-finish
git lfs install
git lfs pull
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
# 改为这台电脑的实际 Multiphysics 安装目录，不要照抄交出方路径
$flowplotComsol = 'D:\COMSOL63\Multiphysics'
./.venv/Scripts/python.exe -X utf8 scripts/verify_delivery.py --model-root . --comsol-root $flowplotComsol --output-dir ../FlowPlot-validation/pc2-001
```

检验输出放在仓库旁边，避免写进输入根目录。脚本会记录解释器/依赖版本、真实退出码、测试数量、源码指纹及前后模型哈希。六个开发模型各读取两次，随后离线重算；不求解或保存源模型。失败时保留整个目录，先查看 verification.json 和对应阶段日志，不挑成功的子项宣称全套通过。

全量测试退出成功、六模型完整且 6/6 code 集合匹配、离线重算一致、前后文件不变，才能说这一台电脑的自动工程复现通过。仍不是专业审核或独立模型验收。

打开可见界面：

```powershell
./.venv/Scripts/python.exe -X utf8 src/flowpilot/recommend_ui.py --report ../FlowPlot-validation/pc2-001/checks/baseline --comsol-root $flowplotComsol
```

人工实际操作并记录：正常模型、缺少入口、入口重叠、Re 风险、检查失败/超出范围、运行后取消与重试、历史/对比/报告包往返，以及推荐刷新和拒绝推荐。已有报告从检查目录的具体模型子目录读取。不要为了触发失败改坏原模型；可用不存在的模型路径验证失败，范围外/部分模型需要对应真实样本，缺少样本就明确留待验证。

至少记录实际系统/COMSOL 版本、各步骤结果、错误提示和截图。没有未参与开发的真实参与者及计时，不能填写“新用户五分钟通过”。本机助手窗口工具的归属错误不是 Win10 端的已知软件故障，需以这台电脑实际体验判断。

## B. 推荐的本机实际耗时与质量

这一部分明确运行求解器：在仓库基准的独立副本上比较四个容差/线程候选，各三次冷求解。不会编辑源模型，也不会求解异常模型；运行期间避免同时执行其他大型计算，以减少噪声。

```powershell
./.venv/Scripts/python.exe -X utf8 src/flowpilot/calibrate_solver.py --model models/baseline_pipe_2d_laminar.mph --comsol-root $flowplotComsol --output-dir ../FlowPlot-validation/pc2-calibration-001
./.venv/Scripts/python.exe -X utf8 src/flowpilot/validate_recommendation.py --report ../FlowPlot-validation/pc2-001/checks/baseline --calibration ../FlowPlot-validation/pc2-calibration-001/dataset.json --output ../FlowPlot-validation/pc2-ai-evaluation-001.json
```

评估在实际测量的同一电脑运行，核对原模型、当前报告、校准环境和工程质量，再比较被选候选与严格双线程默认配置的中位数、范围和离散性。质量失败优先于速度；若未满足超过 5% 且测量范围不重叠，明确写“没有稳定收益证据”，不把速度排序当加速证明。所选配置就是默认时也不声称加速。

评估不启动 COMSOL，结果记录输入指纹但不是作者签名。输入报告和测量文件不能放到其他电脑后冒充当地实际耗时。这个开发基准参与过训练，即使换电脑也仍不是独立模型测试；正式 T13 还需未见模型及默认/经验/随机参照设计。

## 回传哪些材料

- verification.json、本机界面操作记录，以及 B 的 pc2-ai-evaluation-001.json。
- 若需复查耗时/质量，可在人工审阅后单独提供 dataset.json；它不是许可证文件，但仍应检查项目参数和来源。
- 不直接上传整个验证目录：其中含 MPH 副本、原生日志及本机路径。不要共享许可证、账户、环境目录或原模型修改。
- 可以只回报失败阶段和提示先排查；不要把尚未执行的步骤填为通过。

当前代码及命令实际发布状态以 Git 为准；找不到新脚本时先核对是否拉到了包含本页的提交，而不是从旧 main 开始。
