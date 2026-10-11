# 设计蓝图

## 总体思路

项目遵循“先可靠解析，再规则判断，最后数据驱动推荐”的顺序。AI 不直接读取二进制 `.mph`，而是消费经过验证的结构化数据。

```text
COMSOL .mph
    │
    ▼
Parser（COMSOL Java API）
    │  physics / study / geometry / boundaries / parameters
    ▼
Canonical JSON + Schema Validation
    │
    ├──► Rule Engine ──► 诊断与风险等级
    │
    └──► Feature Builder ──► 求解参数推荐（后续阶段）
                                  │
                                  ▼
                         COMSOL 批量验证与指标对比
```

## 模块划分

| 模块 | 职责 | 主要输出 |
|---|---|---|
| `model-loader` | 加载模型并定位组件、物理场、研究 | 模型元数据 |
| `boundary-parser` | 枚举边界 feature、ID、启用状态和表达式 | 原始边界记录 |
| `schema` | 统一字段、单位与版本 | 可验证 JSON |
| `rule-engine` | 执行缺失、冲突、方向和范围规则 | 诊断列表 |
| `reporter` | 生成人可读说明 | Markdown/JSON 报告 |
| `runner` | 批量修改配置、求解、采集日志 | 实验记录 |
| `recommender` | 对候选求解器配置排序 | 推荐配置与置信信息 |
| `ui` | 展示检查、证据和建议 | 可交互原型 |

## 数据契约草案

```json
{
  "schema_version": "0.1.0",
  "model": {
    "dimension": 2,
    "physics": "laminar_flow",
    "study": "stationary"
  },
  "boundaries": [
    {
      "feature_tag": "inl1",
      "type": "inlet",
      "boundary_ids": [1],
      "enabled": true,
      "parameters": {"velocity": "0.01[m/s]"}
    }
  ]
}
```

## 阶段与退出条件

1. **范围冻结**：团队对支持/不支持项回答一致。
2. **基准模型**：稳态层流管道稳定收敛，Ground Truth 完整。
3. **解析闭环**：物理场、边界、参数与 GUI 100% 对齐。
4. **规则检查**：异常测试集可复现，Recall > 90%。
5. **自动求解**：基准模型连续 5 次自动运行并采集关键字段。
6. **数据集**：模型级划分，无泄漏，配置效果存在可学习差异。
7. **推荐模型**：优于 COMSOL 默认、人工经验和随机配置基线。
8. **系统展示**：10 个未见模型完成端到端验证。

## 技术原则

- 解析层与规则层解耦，后续 AI 不依赖 COMSOL 内部对象。
- 确定性结论来自规则；生成式模型只组织解释，不创造事实。
- 每条诊断必须包含证据、风险等级、适用范围和建议动作。
- 所有指标按模型级划分评估，禁止同一模型的不同配置跨训练/测试集。
- 记录 COMSOL 版本、模型哈希、规则版本和 Schema 版本，保证可复现。
