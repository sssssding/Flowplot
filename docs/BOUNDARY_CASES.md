# 异常模型与人工复核

日期：2026-10-11；COMSOL 6.3.0.290。

五个模型均从已验收基准加载后单点修改、清除继承的求解数据并另存。未调用求解器，不能用基准的速度云图或收敛结果代替异常模型的结果。每个保存后的文件加载五次，增强版 API JSON 一致。

| 样本 | 修改 | 首版预期诊断 |
|---|---|---|
| missing_inlet | 删除入口节点 | MISSING_INLET，Critical（通道模板约束） |
| missing_outlet | 删除出口节点 | MISSING_OUTLET，Critical（通道模板约束） |
| selection_overlap | 新出口选择入口所在边界 | BC_SELECTION_OVERLAP，Warning；MISSING_INLET，Critical |
| reversed_inlet | Uin = -0.01 m/s | INLET_DIRECTION，Warning |
| high_reynolds | Uin = 0.1 m/s，名义 Re_H = 5000 | REYNOLDS_RISK，Warning |

重叠样本中，COMSOL 把原入口有效选择变为 `[]`，新增出口有效选择为 `[1]`，但二者声明选择仍为 `[1]`。这是覆盖优先级导致的意图疑点，不是同时有效的两个约束。默认壁面的声明选择为所有边界 `[1,2,3,4]`，有效选择则排除入口、出口，不能直接按声明集合相交误报。

模型路径、SHA-256、重复加载次数及工程预期标签见 [manifest](../data/fixtures/cases/manifest.json)。原始 API 证据见同目录 JSON。

## 复现

```powershell
./scripts/build_cases.ps1 -ComsolRoot '<COMSOL_ROOT>'
# 已存在模型时只读验证，不覆盖模型：
./scripts/build_cases.ps1 -ComsolRoot '<COMSOL_ROOT>' -InspectOnly
```

首个命令会拒绝覆盖已有样本。失败时可能留下尚未验收的模型，需先存档后再生成。`-PrepareOnly` 仅在本机 outputs 中准备自包含 Java 入口，不执行 COMSOL。

批处理环境未能解析相邻 Java helper 类，因此入口由 `ModelInventory.java` 机械生成；共享枚举逻辑只有一份源码。不会通过修改 COMSOL 安全偏好解决类加载问题。

## 待专业人员完成

2026-10-13 已在本机 GUI 核对缺少入口/出口、重叠及反向入口的角色节点、模式/单位和壁面有效选择。反向入口 Uin=-0.01 m/s；GUI 有符号 Re=-500，诊断按绝对速度计算 Re=500。高 Re 样本与专业标签仍待完成。详见 [GUI_REVIEW.md](GUI_REVIEW.md)，团队验收执行计划见 [ACCEPTANCE_PLAN.md](ACCEPTANCE_PLAN.md)。工程对照不会修改 manifest 的专业审核状态。

- [ ] GUI 核对所有选择、边界模式、速度符号与单位。
- [ ] 审核工程预期标签及严重等级，填写审核人和日期。
- [ ] 制作不参与规则开发的独立模型集，计算 Recall 和误报率。

这些是受控合成回归样本，不是独立验收集。即使全部命中，也不能声称已经达到 Recall > 90% 的项目验收指标。
