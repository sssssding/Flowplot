# 确定性规则第一版

当前调度：`src/flowpilot/diagnostics.py`，流动实现：`src/flowpilot/diagnostic_modules/flow.py`；规则结果包含稳定 code、严重等级、解释、feature tag、边界 ID 和数值证据。

M1 增加受控二维轴对称圆管，支持范围、`AXIS_SELECTION_INCONSISTENT` / `EMPTY_BOUNDARY_SELECTION`、默认轴线选择语义及实测见 [M1.md](M1.md)。新模型使用 `diagnostic-0.2`，外层报告继续为 `diagnosis-0.2`。轴对称 Re 使用经边界坐标及拓扑核验的圆管直径 D，公式为 rho × abs(Uin) × D / mu；滑移或轴线配置不满足前提时跳过。下文的高度 H、旧模板限制及 `diagnosis-0.1` 描述保留为原平面规则说明，不适用于新轴对称模型。

M2 另以 `heat` 与 `thermal_coupling` 模块接入 `diagnosis-0.3`，支持受控流体传热及流热引用/选择检查。规则清单、常量材料和递归子节点证据、合法替代配置与受限共轭范围见 [M2.md](M2.md)。以下原平面规则的单域/单物理场限制不代表新版总调度范围；各模块的实际覆盖独立记录。

## 输入与限制

M3 三维规则与支持矩阵见 [M3.md](M3.md)。新报告为 `diagnosis-0.4 / static-3d-v1`，流动子模型为 `diagnostic-0.3 / pipe-3d-v1`。`FLOW_FACE_SELECTION_INCONSISTENT` 根据实际流体域的已核验端面/侧面检查流动角色；不跨流动和传热接口判定边界冲突。三维 Re 仍使用流体圆管直径 D，要求几何、法向速度、材料和完整无滑移壁面证据；缺证据按规则跳过。原平面规则说明保留如下。

当前只验证自建、米制、轴对齐矩形通道模型族：一个二维组件、单域、一个启用的 LaminarFlow、单一定常步骤、一个覆盖全域的材料、牛顿流体属性来自材料。入口限法向速度模式，出口限压力/无黏性应力，壁面限 No Slip。

不支持的几何、研究、耦合、物理场、启用节点、嵌套节点、边界模式和材料来源显式返回 `unsupported`。[文件检查入口](MODEL_CHECK.md) 可以读取用户指定路径的模型副本，但仍使用当前物理配置；更多几何和空间速度字段需另外扩展验证，不能直接套用此配置。无法枚举的模型会令运行失败，不返回正常结论。

新版 `inventory-0.2` 清单增加可选的 `rectangle_rotation_expression`，仅接受显式 `0`、`0[deg]` 或 `0[rad]`（忽略空白）。其他角度或待求值表达式返回 `unsupported`，避免把旋转矩形的包围盒高度误作通道高度。旧历史 fixture 无该字段时保留原有行为；新 COMSOL 解析会提供此证据。

COMSOL 自己将表达式转换到指定单位；Python 不执行表达式。无法得到常数标量时保留 `unresolved`，相关检查跳过并报告 `partial`。JSON Schema 校验不等于物理有效性证明。

## 规则

| code | 等级 | 判定依据 |
|---|---|---|
| MISSING_INLET / MISSING_OUTLET | Critical | 模板内无该角色的非空有效边界；忽略未启用节点 |
| BC_SELECTION_OVERLAP | Warning | 不同显式角色的声明边界重叠，结合有效选择提示优先级覆盖；不包括未命名的全边界 fallback wall |
| INLET_DIRECTION | Warning | 当前法向流入速度 <= 0；不适用于速度分量模式 |
| REYNOLDS_RISK | Warning | rho × abs(Uin) × H / mu 超过可配置阈值（默认 2000），且超出量大于阈值处 4 ULP 浮点保护 |
| INVALID_MATERIAL_PARAMETER | Critical | 当前牛顿流体模板的密度或动力黏度非正 |
| EVALUATION_UNAVAILABLE | Warning | 常数求值/单位转换失败，或派生 Re 超出非零有限表示范围；不填 0，不给干净结论 |

默认 Re 阈值是团队初始筛查参数，不是二维通道普适转捩值。这里使用高度 H，而不是水力直径；不能混用名义入口速度、实际积分流量或不同特征长度下的 Reynolds 数。

Re 合并计算已记录数值的十进制精确比值，最后才转换为报告数值，避免中间乘积溢出/下溢改变结论；最终值无法表示时返回带计算量、原因和操作数的 `EVALUATION_UNAVAILABLE`，整体 `partial`。真正零速度和非正材料仍按原规则处理。有限坐标产生无穷大尺寸时不使用该几何；超大整数或非有限输入不成为有效证据。数值选项不接受布尔值。详见 [数值稳定性](NUMERIC_SAFETY.md)。

`Critical` 仅说明当前模板需要先处理的问题，不代表所有 COMSOL 模型都不合法。`checked` 表示已执行当前可用规则，即便包含 Critical；`findings=[]` 也不证明求解收敛或物理正确。`partial` / `unsupported` 不得在 UI 中显示成“通过”。

缺少入口/出口现在补充启用角色节点数、空的有效边界和所有启用边界节点的声明/实际生效证据，区分没有启用角色节点与有效选择全空；节点仍存在时保留相关标识，不猜测缺失边界位置。此处不区分已删除和未启用节点。判定条件不变，但规则源码哈希已变，跨版本报告需重新检查后再比较或评分；详见 [模型概览与证据](MODEL_OVERVIEW.md)。

## JSON 契约

- `inventory-0.2`：实际 API 清单，保留原始表达式、输入/有效选择和单位求值。
- `diagnostic-0.1`：自动归一化诊断输入，对应 `schema/diagnostic-model.schema.json`，通过 Draft 2020-12 校验。
- `diagnosis-0.1`：诊断报告，包含状态与规则证据。
- 原 `0.1.0` Schema 与人工 baseline fixture 保留为旧参考接口，不是新版自动输出。

原六个真实模型的清单及 [14 个受控变体](REGRESSION_FAMILY.md) 用于开发回归；不支持结构、无效 Schema、极端未求值数据等 Python 构造反例不能称作 COMSOL 实测，也不能用这些开发样本替代专业标签审核或独立验收。
