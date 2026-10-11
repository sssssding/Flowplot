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
| Mesh | Physics-controlled, Normal |
| Expected Reynolds number | 约 500 |

## 必须补录的 COMSOL 内部标识

| 对象 | GUI 名称 | Tag | Boundary ID | 已核对 |
|---|---|---|---:|---|
| Component | 待填写 | 待填写 | — | ⬜ |
| Laminar Flow | 待填写 | 待填写 | — | ⬜ |
| Inlet | 待填写 | 待填写 | 待填写 | ⬜ |
| Outlet | 待填写 | 待填写 | 待填写 | ⬜ |
| Wall | 待填写 | 待填写 | 待填写 | ⬜ |

## 验收测试

- [ ] `Re ≈ 500`，数量级与单位正确。
- [ ] 壁面速度为 0，中心区域速度更高，无异常反向或尖峰。
- [ ] 入口与出口质量流量相对误差小于 `1e-3`。
- [ ] 关闭并重新打开后连续求解 3 次，均收敛。
- [ ] 三次最大速度、压降和质量流量无异常漂移。
- [ ] GUI 设置与本文件逐项一致。
- [ ] 模型文件 SHA-256 已记录。

## 实测记录

| 日期 | COMSOL 版本 | 模型 SHA-256 | 最大速度 | 压降 | 质量误差 | 求解时间 | 结论 |
|---|---|---|---:|---:|---:|---:|---|
| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待验证 |
