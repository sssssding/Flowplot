# 确定性规则第一版

当前实现：`src/flowpilot/diagnostics.py`；规则结果包含稳定 code、严重等级、解释、feature tag、边界 ID 和数值证据。

## 输入与限制

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
| REYNOLDS_RISK | Warning | rho × abs(Uin) × H / mu > 可配置阈值，默认 2000 |
| INVALID_MATERIAL_PARAMETER | Critical | 当前牛顿流体模板的密度或动力黏度非正 |
| EVALUATION_UNAVAILABLE | Warning | 常数求值或单位转换失败；不填 0，不给干净结论 |

默认 Re 阈值是团队初始筛查参数，不是二维通道普适转捩值。这里使用高度 H，而不是水力直径；不能混用名义入口速度、实际积分流量或不同特征长度下的 Reynolds 数。

`Critical` 仅说明当前模板需要先处理的问题，不代表所有 COMSOL 模型都不合法。`checked` 表示已执行当前可用规则，即便包含 Critical；`findings=[]` 也不证明求解收敛或物理正确。`partial` / `unsupported` 不得在 UI 中显示成“通过”。

## JSON 契约

- `inventory-0.2`：实际 API 清单，保留原始表达式、输入/有效选择和单位求值。
- `diagnostic-0.1`：自动归一化诊断输入，对应 `schema/diagnostic-model.schema.json`，通过 Draft 2020-12 校验。
- `diagnosis-0.1`：诊断报告，包含状态与规则证据。
- 原 `0.1.0` Schema 与人工 baseline fixture 保留为旧参考接口，不是新版自动输出。

六个真实模型的清单用于回归；其他不支持结构、无效 Schema、未求值数据等测试为 Python 构造的反例，不能称作 COMSOL 实测。
