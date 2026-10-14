# 本机接手验证（2026-10-11）

负责人：Codex；本轮分支 `feat/local-acceptance`。远端 PR #1 已合并至 `main`，接手提交为 `cba7a12`，交接内容与 `codex/local-handoff` 的 `76c5d2c` 文件树一致。未在 main 或同事分支上开发。

## 保留本地模型

接手时发现工作区基准有未提交改动，SHA-256 为 `e43ead4f16b18d90a77f07da0381b7ece4fb9dcd5f1efb08b67b1d221245dac9`；提交中的基准为 `023d94cf9c7f2dd5b5bf1bd581b1f19ab8a38cf9304c3af25f239a2398707e1b`。

原文件未被覆盖、恢复或提交。已提交原件从本机 Git LFS 缓存只读复制到独立的 `outputs/local-acceptance/run-001/models/`，与五个异常模型一起核对 manifest；使用该目录作为 `--model-root`。没有修改清单哈希绕过保护。

## 离线测试与环境

- 本机环境为 Python 3.12.14、jsonschema 4.26.0、Tk 8.6；使用既有 `.venv-tests`，不把该环境提交仓库。
- 首次沙箱运行出现临时文件路径的 WinError 5；正常本机权限复现后仅剩一项来源字节指纹失败。
- 该项来自旧工作区 `baseline_verification.json` 的 CRLF 换行；按 `.gitattributes` 转成 LF 后，字节哈希与已提交证据的 `cd98b68f...` 一致，JSON 内容不变，也没有修改证据字段。原 274 项测试全部通过。
- 新增只读接手预检和专项测试；预检在当前工作区明确报告基准 `hash_mismatch`，在六模型独立副本上报告 `ready`，原修改仍然保留。
- 最终 285 项离线测试全部通过（原 274 项 + 11 项预检专项）；模拟故障及 1.500 秒求解输出属于离线测试，不是本轮真实求解记录。
- 默认 `.venv` 缺 jsonschema。另一环境测试成功不代表 `FlowPilot.cmd` 默认环境可用；本轮通过 `.venv-tests` 的解释器启动桌面入口，不替换或删除原环境。

## 真实 COMSOL 检查

本机 COMSOL 6.3.0.290 下，对六模型独立副本分别加载两次；批量状态 completed，6/6 完整检查，6/6 code 集合与工程标签一致。随后不调用 COMSOL 的离线复核得到相同结果。

本机原始证据：`outputs/local-acceptance/run-001/check-suite/` 和 `offline-evaluation/`。日志及模型副本不随 Git 共享。正式摘要仍保持 `acceptance_eligible: false`、`meets_recall_above_90_percent: null`；没有把开发回归集作为独立验收，也未求解异常模型。

随后使用同一已提交基准副本重新导出保存解云图、截面数据和带图组的 `baseline_with_review_plots.mph`；没有重新求解。11 项工程筛查全部通过，六个指标与历史记录一致；最大速度为 0.0144265456 m/s，质量相对误差为 8.29857166e-4。已查看导出 PNG，近壁低速、入口发展区及四条截面曲线可辨；这不代替 COMSOL GUI 或专业审核。

复核输出在 `outputs/local-acceptance/run-001/baseline-review/`。工作区修改版基准及已提交原件副本的前后哈希均未变化。小型可共享来源摘要见 [local_acceptance.json](../data/fixtures/local_acceptance.json)；原始日志和复核 MPH 仍留在忽略目录。

## 可见界面未完成

桌面启动后，窗口工具返回 `FlowPilot · 模型边界检查`。状态捕获却报 `window ... no longer belongs ...; current owner ...`；重新读取窗口归属并重试仍失败，已按 computer-use 恢复规则停止输入。

这不是可见界面、布局、新用户耗时或端到端验收通过的证据。未自动点击、取消、关闭窗口或丢弃用户模型状态。GUI 与专业复核继续保留待完成；不填造审核人或日期。

## 下一步

2026-10-12 后续已完成可见桌面工程核验及启动/布局修复，见 [DESKTOP_REVIEW.md](DESKTOP_REVIEW.md)。本页的窗口阻塞和 285 项测试为前一轮历史记录，不代表后续核验仍然受同一阻塞。

1. 使用可用 Python 环境打开桌面，按 `DESKTOP.md` 人工试用并记录操作耗时、布局和错误理解。
2. 明确本地基准改动的保留用途，原件与工作副本分开；不要未经确认覆盖。
3. 打开本机生成的带图组复核副本，按 `BASELINE_REVIEW.md` 和 `BOUNDARY_CASES.md` 完成真实 GUI 对照及专业标签审核。
4. 由未参与规则调试的团队成员建立真正独立的验收集；AI 参数推荐仍未开始。
