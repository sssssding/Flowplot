# FlowPilot

FlowPilot 是一个面向 COMSOL 二维稳态层流模型的智能检查原型。第一版聚焦于读取 Inlet、Outlet 和 Wall 边界，发现边界缺失、冲突、方向异常及工况范围风险；在解析与规则检查闭环稳定后，再扩展求解参数推荐。

## 当前阶段

- 已冻结 MVP 范围。
- 基准模型已完成实际求解、三次重新加载验证与十次只读解析；GUI 设置已核对，专业复核待完成。
- 已加入模型生成/清单脚本、实测证据和 GitHub Actions fixture 测试。
- 五类未求解异常模型已生成并各重复读取五次；首版确定性诊断与 JSON Schema 已实现。
- 已提供指定 `.mph` 路径的只读检查入口，输出结构化证据和中文诊断报告，见 [使用说明](docs/MODEL_CHECK.md)。
- 已从基准保存解导出速度云图、截面曲线与可复现采样，见 [复核材料](docs/BASELINE_REVIEW.md)；专业审核待完成。
- 已完成基准连续五次自动重新求解，记录日志、耗时与结果一致性，见 [重复求解](docs/BASELINE_SOLVES.md)；GUI 日志对照待完成。
- 当前诊断只验证自建矩形通道模型族；专业标签审核与独立验收集待完成。
- 尚未进入 AI 求解参数推荐阶段。

## 仓库结构

```text
FlowPlot/
├─ docs/          协作规范、设计蓝图、注意事项和进度
├─ models/        COMSOL 模型说明；二进制模型需使用 Git LFS
├─ src/           源代码
├─ tests/         自动化测试与测试说明
├─ data/          小型、可公开的结构化测试数据
├─ scope.md       初始 MVP 范围记录
└─ README.md      项目入口
```

## 快速开始

1. 阅读 [项目范围](docs/PROJECT_SCOPE.md) 和 [技术蓝图](docs/BLUEPRINT.md)。
2. 按 [协作规范](docs/COLLABORATION.md) 创建 Issue 和功能分支。
3. 开发前查看 [注意事项](docs/NOTES.md) 与 [项目进度](docs/PROGRESS.md)。
4. 建立或验证 COMSOL 基准模型时，使用 [基准模型规范](docs/BASELINE_MODEL.md)。
5. 运行脚本和测试时，参照 [开发与验证](docs/DEVELOPMENT.md)。
6. 检查指定的模型文件时，使用 [只读文件检查入口](docs/MODEL_CHECK.md)。

## 一句话目标

> FlowPilot 第一版面向 COMSOL 二维稳态层流模型，自动读取 Inlet、Outlet 和 Wall 边界条件，并对边界缺失、冲突、方向异常和工况风险进行可解释检查。
