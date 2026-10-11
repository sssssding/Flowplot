# 基准 COMSOL 模型规范

建议文件名：`baseline_pipe_2d_laminar.mph`

基准模型的团队验证环境为 COMSOL 6.3。实测记录中请补充具体补丁/构建版本及 Java API 版本。

## 人工 Ground Truth

| 项目 | 预期值 |
|---|---|
| Physics | Laminar Flow |
| Dimension | 2D |
| Study | Stationary |
| Geometry | 矩形管道，x: 0–1 m，y: 0–0.05 m |
| Fluid | Water |
| Density | 1000 kg/m³ |
| Dynamic viscosity | 0.001 Pa·s |
| Inlet | 左边界，0.01 m/s，v = 0 |
| Outlet | 右边界，0 Pa 相对压力 |
| Wall | 上下边界，No Slip |
| Mesh | FreeTri，hmax = H/20，hmin = H/100，无边界层 |
| Expected Reynolds number | 约 500 |
| Stationary tolerance | `sol1/s1/stol = 1e-6` |

## 必须补录的 COMSOL 内部标识

| 对象 | GUI 名称 | Tag | Boundary ID | 已核对 |
|---|---|---|---:|---|
| Component | 2D Pipe Component | comp1 | — | API 与 GUI 已核对 |
| Laminar Flow | Laminar Flow | spf | — | API 与 GUI 已核对 |
| Inlet | Velocity Inlet | inl1 | 1（左） | API tag；GUI 名称、选择和模式已核对 |
| Outlet | Pressure Outlet | out1 | 4（右） | API tag；GUI 名称、选择和模式已核对 |
| Wall | No-Slip Walls | wallbc1 | 2、3（上下壁面） | API tag；GUI 默认覆盖与无滑移已核对 |

编号来自 COMSOL 坐标选择的实际结果，不应推广到其他几何。默认 Wall 的实际类型为 `WallBC`，本模型中 API 返回的有效边界是 `[2, 3]`；不能把所有默认节点重叠都直接判为边界冲突。

## 验收测试

- [x] `Re ≈ 500`，数量级与单位正确（以 H 和设定入口速度计算）。
- [x] 壁面内部速度为 0，最大速度高于设定入口速度，全域无负向 u；GUI 云图待人工复核。
- [x] 入口与出口质量流量相对误差小于 `1e-3`。
- [x] 从保存的 `.mph` 重新加载并连续求解 3 次，均收敛（API 验证）。
- [x] 三次最大速度、压降和质量流量相对漂移小于 `1e-5`。
- [x] GUI 几何、参数、材料、边界、网格、稳态与求解容差和本文件一致（Codex 工程核对，不代替专业签字）。
- [ ] GUI / 专业人员速度云图复核；已从保存解导出云图、截面曲线及带图组的独立复核副本，见 [复核材料](BASELINE_REVIEW.md)。
- [x] 模型文件 SHA-256 已记录。

均匀入口与 No Slip 在交角处存在不连续约束。壁面检查使用 `H < x < L-H` 范围，排除交角；报告不把交角插值速度误认作整个壁面不满足 No Slip。网格与容差经过实测调整，不采用未验证的 Normal 默认网格。

二维质量流量为单位出平面厚度的 `kg/(m·s)`。实际入口积分为 `0.4875 kg/(m·s)`，低于连续均匀入口的理想值 `0.5`，主要与交角约束的离散处理有关；不要把设定速度对应的 Re=500 写成实际积分流量对应的 Reynolds 数。当前模型已满足初始守恒阈值，尚未开展网格无关性验证。

## 实测记录

| 日期 | COMSOL 版本 | 模型 SHA-256 | 最大速度 | 压降 | 质量误差 | 求解时间 | 结论 |
|---|---|---|---:|---:|---:|---:|---|
| 2026-10-11 | 6.3.0.290 | 见下方 | 0.0144265456 m/s | 0.0775840421 Pa | 8.29857166e-4 | 单次求解约 2 s | API 验证及 GUI 设置核对通过；云图、专业复核待完成 |

SHA-256：`023D94CF9C7F2DD5B5BF1BD581B1F19AB8A38CF9304C3AF25F239A2398707E1B`

网格：20,034 个域单元；31,314 个求解自由度（另有 1 个内部自由度）。

版本化证据：[求解记录](../data/fixtures/baseline_verification.json)、[实际 API 清单](../data/fixtures/baseline_inventory.json)。

界面核对详情、旧入口/出口特征的弃用提示和待办见 [GUI 核对记录](GUI_REVIEW.md)。本轮未保存模型，磁盘哈希保持一致。

后续 API 保存解复核材料见 [速度场复核](BASELINE_REVIEW.md)。定量指标与原记录一致；原始基准仍未新增图组，新增图组只存在于本地复核副本中。

运行方法见 [开发与验证](DEVELOPMENT.md)。
