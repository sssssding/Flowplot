# 受控矩形通道变体

该入口从已提交基准的独立副本生成 14 个 **未求解** 的 COMSOL 模型，再使用正式文件检查和批量评估入口核验。目标是扩充实际 API 回归覆盖，发现只用原来六个模型看不到的问题；不是独立验收集或 AI 训练/推荐结果。

## 覆盖内容

| 样本 | 改动 | 预先指定的预期 code |
|---|---|---|
| units_equivalent | 速度、密度、黏度分别改用 mm/s、g/cm³、mPa·s | 无 |
| re_below / re_at / re_above | 入口速度 0.03998 / 0.04 / 0.04002 m/s，名义 Re 1999 / 2000 / 2001 | 无 / 无 / REYNOLDS_RISK |
| zero_velocity | 零入口速度 | INLET_DIRECTION |
| reversed_fast | 负速度且高 Re | INLET_DIRECTION、REYNOLDS_RISK |
| empty_inlet / empty_outlet | 节点保留，声明与生效选择均为空 | MISSING_INLET / MISSING_OUTLET |
| both_missing | 同时删除入口和出口节点 | MISSING_INLET、MISSING_OUTLET |
| overlap_reversed | 负速度入口被新增出口覆盖 | BC_SELECTION_OVERLAP、MISSING_INLET |
| zero_viscosity / low_viscosity | 动力黏度 0 / 1e-4 Pa·s | INVALID_MATERIAL_PARAMETER / REYNOLDS_RISK |
| short_narrow / long_wide | 尺寸 0.5×0.02 / 2×0.1 m | 无 |

新增出口覆盖入口后，该入口没有生效边界，因此不对其负速度和 Re 另行报警；空选择则保留节点标签及 `all_effective_selections_empty` 证据，不冒充删除节点。

尺寸变化时重新构建几何并更新坐标选择，核对入口、出口及上下壁各选择一条边，不硬编码重建后的边界编号。三个尺寸组仍属于同一种轴对齐单矩形模型族，不代表扩展到三维、组合几何或其他物理场。

## 使用

需安装项目 Python 依赖，具有 COMSOL 6.3 和适用许可证。从项目根目录执行：

```powershell
python -X utf8 src/flowpilot/regression_family.py --comsol-root '你的 COMSOL Multiphysics 安装目录' --output-dir outputs/regression-families/my-new-run --loads 2
```

输出目录必须不存在。保存的原始基准 SHA-256 不匹配时，在创建输出目录和启动 COMSOL 前拒绝。入口不改变 COMSOL 安全偏好，不读取外部脚本或允许任意 Java 注入。版本文字以 ASCII 转义 JSON 标记传递，避免 Windows 控制台编码损坏中文来源信息。

新目录中包含：

- `input.mph`：受保护的基准副本；原文件及副本前后核对哈希。
- `models/`：14 个新模型；生成时清除保存解并检查求解器为空，不执行求解。
- `manifest.json`：真实模型 SHA-256 与事先确定的预期标签；明确声明开发用途及专业审核未完成。
- `checks/`：正式只读检查结果及批量汇总，每个模型默认独立加载两次。
- `summary.json`：code 集合、实际 SI 数值、尺寸、特定节点证据和源码指纹的验证结果。
- `run.json`：完成、标签/证据不匹配、失败或取消状态；日志和生成驱动仅保留本地。

退出码 0 表示本次受控验证通过，1 表示运行失败，2 表示标签或生成证据不匹配。异常不会删除已有文件、重用旧目录或把部分运行说成成功；修复后用新目录重跑。

生成副本用于配置检查，不是可直接开展物理实验的已审核模型：不验证新网格质量、求解收敛或流场。尤其零黏度等故障样本不得作为物性建议。

## 真实测试发现的阈值问题

首次本机运行中，14 个模型均成功读取，但只有 13 个匹配预期：名义 Re=2000 的模型，其 API 高度是 `0.05000000000000001 m`，计算得到 `2000.0000000000005`，触发严格大于比较。该失败目录保留，不改标签或旧报告。

规则现为 `Re > threshold` 且 `Re - threshold > 4 × ulp(threshold)` 才报风险。默认阈值处保护宽度约 `9.09e-13`，只处理极少数浮点末位间距，不使用宽泛相对误差，不修改原始数值。报告记录 `numeric_policy.reynolds_threshold_guard_ulps=4`；实际风险条目带 `numerical_comparison_margin`。这不是测量误差、物理容差或“阈值附近安全”的判断。详见 [数值边界](NUMERIC_SAFETY.md)。

## 证据、限制与下一步

小型真实摘要保存在 `data/fixtures/regression_family.json`。自动化测试核对当前生成/规则源码指纹及预期结果；模拟编译失败、输出残缺、重复哈希、中断和证据错误的测试明确为离线合成，不代替 COMSOL 实测。

新模型、日志和运行目录默认不提交；队友可用相同入口重新生成，重新保存的二进制哈希可能因 COMSOL 元数据不同而变化，应以各次 manifest 为准。需要交换模型时另行审阅，再使用 Git LFS，不自动上传。

这些样本由规则开发者生成并用于开发，专业标签待审核，独立验收资格始终为 false。T12 仅开始收集当前模型族的配置差异；尚无推荐实验的求解参数—性能数据、独立模型族划分或足够的物理覆盖，不能宣称完成 T12/T13 或十个未见模型验收。

回退生成入口可独立删除新模块、Java 模板及对应文档/测试，不影响原模型与桌面入口。阈值规则回退须恢复配套测试并重新生成匹配版本的证据，不改旧报告哈希来复用历史成绩。
