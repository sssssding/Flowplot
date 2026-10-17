# FlowPlot MVP 范围

## 项目定义

FlowPlot 是面向 COMSOL 二维、单流体域、稳态层流模型的边界检查原型。输入受支持的 `.mph` 模型，输出结构化边界信息、确定性诊断及可解释建议。当前名称和历史兼容约定见 [NAMING.md](NAMING.md)。

## 支持范围与首版检查项

支持 Single-Phase Flow / Laminar Flow、Stationary 研究、二维单流体域、Inlet/Outlet/Wall 边界；Wall 的 No Slip 为基线，Slip 仅作为候选扩展。

1. 缺少入口或出口。
2. 同一边界存在明显冲突设置。
3. 入口速度方向异常。
4. 参数超出预设工况范围时提示风险，不武断判错。

## 暂不支持

- 3D、湍流、多相流、非牛顿流或瞬态研究。
- Heat Transfer、流固耦合、Moving Mesh 等其他物理场。
- 通用物理正确性判定或跨物理场 AI 求解参数推荐。
- 对任意几何、物理场和网格做精度/性能保证。

## 当前推荐边界

保留特征迁移的求解容差/线程候选，但仍限当前受支持的矩形层流族和登记训练覆盖。推荐提供相对排序；必须在独立副本本机验证，不自动修改或求解模型。没有稳定收益证据时保留严格默认，不声称加速。细则见 [AI_RECOMMENDATION.md](AI_RECOMMENDATION.md)、[AI_PORTABILITY.md](AI_PORTABILITY.md) 和 [MESH_TRANSFER.md](MESH_TRANSFER.md)。

## 诊断数据流

```text
.mph → COMSOL Java API → 版本化 JSON → 确定性规则检查 → 带证据的诊断报告
```

## 原始 MVP 验收条件

- 基准 `.mph` 连续 10 次稳定加载。
- 对自建测试模型，物理场和边界识别与 COMSOL GUI 100% 一致。
- 同一模型连续解析 5 次得到一致 JSON。
- 第一批确定性问题在独立异常案例上的 Recall 高于 90%。
- 未参与开发的用户可在 5 分钟内完成“选择模型—检查—理解问题”。

这些是范围内的退出条件，不因后来增加推荐功能或工程回归而放宽。完整目标及正式独立验收要求见 [COMPLETION_AUDIT.md](COMPLETION_AUDIT.md)。
