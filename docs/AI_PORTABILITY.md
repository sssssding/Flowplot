# 跨环境与模型特征推荐

2026-10-14；本轮将默认推荐升级为 `solver-ranker-0.2`。没有删掉旧模型或篡改旧数据：`solver_ranker.json` 仍按 0.1 的固定文件/机器规则工作，新默认文件为 `data/ai/portable_ranker.json`。

## 通用到哪里

- 推理不再要求 MPH 哈希与某个训练文件相同，也不匹配机器指纹。已核验报告可以在另一电脑离线读取，不需要原模型、COMSOL 或云端密钥。
- 根据 SI 尺寸、Re、长宽比匹配相近样本，适用的是现有 `rectangular-channel-v1`：二维单域稳态牛顿层流矩形、单入口/出口及 NoSlip。并非任意 COMSOL 模型；三维/湍流/耦合仍不支持。
- 只输出候选相对耗时与待验证建议，不把训练电脑的秒数搬到其他机器。预测归一化到每个模型、每个测量环境中的严格双线程配置，kNN 按模型特征距离加权。
- 所有结果都带 `requires_local_validation=true`、`confidence=experimental-transfer`、`independent_validation=false`。换机器/网格/模型必须在副本检验，不能承诺加速、精度或物理正确性。
- CPU 数不足会过滤线程候选；CPU 数未知、COMSOL 主/次版本不匹配、超出训练特征范围或距离过大时拒绝推荐。小收益仍优先严格容差配置。
- 已知严格参考求解失败的具体文件拒绝推荐，不能用相似模型的结果覆盖已有失败证据；修复后重新保存、实际核验并记录新证据。

## 数据与模型边界

当前数据为同源的三个开发几何点：1×0.05、0.5×0.02、2×0.1 m；入口 0.01 m/s、密度 1000 kg/m³、黏度 0.001 Pa·s。训练数据不是独立测试集。两个新变体细化了网格到 hmax=H/40、hmin=H/200，原基准保持不变。没有网格自由度/质量特征，模型相似度不能充分描述网格差异，所以迁移只作为实验候选。

首次窄模型原网格的质量守恒误差 0.00123880648 超过固定 0.001 门槛，未纳入训练；只停止本工具的进程树并保留失败目录，随后在新目录细化副本网格重测。没有放宽阈值、复写旧观测或修改用户原模型。全部生成哈希含失败样本登记到 `ai_development_registry.json`，不能重标为独立验收输入。

正式冻结程序现在额外绑定 AI 开发登记，源码/登记指纹发生变化；旧正式冻结/结果可能不再匹配当前版本。不要改旧指纹复用成绩，需重新核验/冻结。该变更不改变确定性诊断规则和历史报告字节。

## 使用

推荐现在绑定当前展示的运行/诊断两个字节指纹，初次展示与手动刷新都核对；同一模型的报告或配置变化时不混用旧诊断与新建议，须重新读取。测量输出必须为输入报告树之外的新目录，普通报告与轻量协作包同样保护；路径别名解析后也不能绕过，拒绝时不写输入目录。

接手收尾额外在候选计算完成、拒绝结果返回和导出写入前重新读取报告，发现运行/诊断快照或目录变化时不发布旧结果。CLI 推荐命令的 `--output` 必须位于输入报告树之外且不存在，避免新增文件使完整协作包失效；不自动创建嵌套输出目录或覆盖结果。这是发布时点的核验，不是文件锁，也不是长期有效性/作者身份保证。

`FlowPlotAI.cmd` 默认读取便携模型；正常报告显示候选，异常/partial/unsupported 报告仍先处理问题。`--report '<已有报告目录>'` 可离线直接预览。

```powershell
python src/flowpilot/recommend.py recommend --report '<已核验的单模型报告目录>'
python src/flowpilot/recommend.py recommend --report '<已核验的单模型报告目录>' --output outputs/ai-recommendation/my-candidate.json
python src/flowpilot/benchmark_portable.py --baseline '<相同已提交基准副本.mph>' --baseline-report '<基准报告目录>' --comsol-root '<Multiphysics 目录>' --output-dir outputs/ai-recommendation/my-new-portable-benchmark
python src/flowpilot/portable_recommend.py --dataset '<实测 dataset.json>' --output outputs/ai-recommendation/my-portable-model.json
```

推理和训练都不启动 COMSOL；只有 `benchmark_portable.py` 明确求解。当前真实测量入口仍使用 COMSOL Windows 命令，在独立副本上运行、串行比较四个候选各三次；Linux/macOS 的实际 COMSOL 驱动适配尚未验证，不能把跨平台推理单测当作跨硬件实测。

扩展训练数据需提供实际求解的完整三次观测、该模型第一次 strict-2 的参考指标、结构化 SI 模型、模型/产物哈希和测量环境记录。逐记录重新计算工程检查，不信任手填通过标记；至少三种不同特征点，版本相容，不混用其他模型的参考值。数据和哈希不是认证/签名，必须审阅来源。

重新生成会改变 MPH 元数据/哈希；提交新的训练数据时同步把新增开发哈希加入 `ai_development_registry.json`，不覆盖既有登记。这份登记只能识别已知字节，不能自动认证来源独立性。

## 测试与回退

第二台 Win10 / COMSOL 6.3 实测步骤见 [SECOND_PC_VALIDATION.md](SECOND_PC_VALIDATION.md)。使用原校准入口在独立副本取得 12 条实际冷求解，再由 `validate_recommendation.py` 核对同机/同模型来源并比较默认与所选配置的中位数、范围和离散性；质量失败优先于速度。评估本身不求解。当前开发基准参与过训练，换电脑仍不能把它称为独立测试集，默认/经验/随机和未见模型的正式门槛保留。

验证分为真实副本测量、明确合成的跨平台/新哈希/新特征/资源反例和隐藏 Tk 功能核对；结果见 `PROGRESS.md`。未取得第二台机器实际性能实验，未达到 T13 的独立性能标准。以前两份 GUI 功能记录保留原字节，新实测独立保存。

验收修复后新实测为 `ai_review_safety_smoke.json`，19 项隐藏 Tk 检查含四项临时合成快照反例；之前三份 AI 功能摘要均保持原字节。正常流程使用本机真实只读报告，没有重新求解或重采训练数据，隐藏检查不代替可见/新用户或性能验收。

继续接手后的最新功能证据为 `ai_publication_smoke.json`，23 项隐藏 Tk 检查包含计算中变更的临时合成反例和报告包导出/重读，前四份摘要原字节保留。源码绑定以该新记录为准，不修改旧摘要来适配新源码。学习文件、诊断规则、模型与正式冻结集合不因本次推荐发布保护而改变。

回退推荐时在窗口选择旧 `solver_ranker.json`，或使用 CLI 的 `--learned-model` 指定旧文件。旧版仍只能对原基准/本机推荐。不要移除新开发登记来绕过正式验收门槛，也不要上传本机原始模型与运行日志。
