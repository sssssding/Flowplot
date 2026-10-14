# FlowPlot 命名与兼容约定

日期：2026-10-13。用户确认 **FlowPlot** 最初是一个笔误，但团队觉得有意思而保留，当前应用名称即为 FlowPlot。未来是否再次改名另行决定，不由开发代理提前替团队决定。

## 当前名称与入口

- 应用展示名：`FlowPlot`，用于窗口、启动提示、新生成的检查/对比/协作/验收报告。
- GitHub 仓库地址继续为 `sssssding/Flowplot`，不修改仓库或远端 URL。
- Windows 推荐入口：根目录 `FlowPlot.cmd`；旧 `FlowPilot.cmd` 保留，两个启动器内容相同，参数、退出码和解释器选择一致。
- 内部 Python 包/路径继续为 `flowpilot` / `src/flowpilot`；保留 `FLOWPILOT_PYTHON`、`FLOWPILOT_COMSOL_ROOT`、`FLOWPILOT_NO_PAUSE` 等已有环境变量，不要求队友迁移配置。

```powershell
./FlowPlot.cmd --check-env
./FlowPlot.cmd
# 旧命令仍兼容，不必修改既有快捷方式和脚本
./FlowPilot.cmd --check-env
```

本轮不重命名内部包、模型 feature tag、已有输出路径或 JSON schema，不重存任何 `.mph`。Java 生成器内的历史模型注释保留，以免仅为品牌变化修改解析/生成源码指纹和既有工程证据。

## 旧记录如何处理

旧报告和模型元数据中的 FlowPilot 保留原样，读取逻辑不根据标题判断有效性。新导出使用 FlowPlot；不能直接修改旧报告标题或清单指纹，因为这样会破坏报告包的字节完整性。

历史 `desktop_smoke.json` / `desktop_visible_review.json` 是改名前的实际记录，未覆盖、改标题或替换源码哈希。对应历史测试只对明确列出的六份源码逆向替换 `FlowPlot` → `FlowPilot`，再严格核对原字节指纹；其余文件不作转换，其他源码变化仍失败。该检查只证明源码差异限于本次文字改名，**不是新版本的人工可见核验**。额外反例测试确保追加无关代码不能通过。

新版本另行运行隐藏 Tk 测试，核对主窗口、检查历史、报告对比的标题及主标题文本，读取六份已有实测报告，并导出/重新读取新的协作包。该测试不加载模型、不调用 COMSOL、不执行求解，不代替专业审核、新用户计时或可见界面试用。记录位于本机 `outputs/acceptance-handoff/20261013/flowplot-naming-smoke-002/verification.json`；首个沙箱尝试未通过 Tcl 初始化，保留失败目录，未宣称该次成功。

## 正式验收版本注意事项

本次仅改变标题，但 `check_model.py` / `acceptance_result.py` 的字节确实变化，它们属于正式冻结源码指纹；打包器自身也发生变化。已有冻结集/正式结果/核验包不可手改哈希来适配新版本，应使用原匹配代码复核历史记录，或经团队确认后按当前版本重新冻结/运行。当前没有真实独立验收集，未生成或提升任何独立成绩。

诊断规则、Java 解析、原六模型均未改变，通用旧报告仍可按原规则来源核验。改名不意味着扩大支持范围，也不意味着完成专业、独立或 UI 验收。

## 验证与回退

新增命名专项检查可用以下命令运行；Windows 启动器测试在非 Windows 环境跳过，不伪称跨平台启动成功：

```powershell
python -X utf8 -m unittest discover -s tests -p test_naming.py -v
python -X utf8 scripts/smoke_naming.py --reports-root '<六模型报告目录>' --output-dir '<新的输出目录>'
```

新旧 `.cmd` 的环境检查和帮助命令均在另一个工作目录实际执行，使用同一解释器，不安装软件。初次测试的 cmd 引号错误已修正；沙箱对子进程/Tcl 的访问拒绝通过正常本机权限复核，没有修改系统权限或软件配置。

未来正式改名应另做决策和兼容测试，不直接全仓库替换字符串。回退本轮时还原用户可见标题及相关文档/测试，移除新启动入口即可；旧启动器、原模型、内部包、环境变量和历史记录保持不变。
