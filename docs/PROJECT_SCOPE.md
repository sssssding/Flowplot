# FlowPlot MVP 范围

## 项目定义

FlowPlot 第一版是“面向二维稳态层流模型的 COMSOL 边界条件智能检查原型”。输入为受支持的 `.mph` 模型，输出为结构化边界信息、规则诊断和可解释建议。当前名称及历史兼容约定见 [NAMING.md](NAMING.md)。

## 支持范围

- COMSOL 二维模型
- Single-Phase Flow / Laminar Flow
- 单流体域
- Stationary 稳态研究
- Inlet、Outlet、Wall 边界
- Wall 的 No Slip；Slip 作为候选扩展

## 第一版检查项

1. 入口缺失
2. 出口缺失
3. 同一边界存在明显冲突设置
4. 入口速度方向异常
5. 参数超出预设工况范围（标记为风险，不武断判错）

## 暂不支持

- 3D 几何
- 湍流、多相流、非牛顿流
- Time Dependent 瞬态研究
- Heat Transfer、流固耦合、Moving Mesh
- 通用物理正确性判定
- 第一阶段的 AI 求解参数推荐

## MVP 输出

```text
.mph 文件
  → COMSOL Java API 解析
  → 统一 JSON 表示
  → 确定性规则检查
  → Critical / Warning / Suggestion
  → 可解释诊断报告
```

## MVP 验收

- 可连续 10 次稳定加载基准 `.mph`。
- 对自建测试模型的物理场与边界识别结果与 GUI 100% 一致。
- 同一模型连续解析 5 次得到一致 JSON。
- 第一批确定性问题在独立异常案例上的 Recall 高于 90%。
- 未参与开发的用户可在 5 分钟内完成“选择模型—检查—理解问题”。
