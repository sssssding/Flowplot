# 多人接手前的只读预检

先确认当前 Python 环境、Git LFS 模型和 COMSOL 目录，再运行桌面或批量检查。入口只使用 Python 标准库，因此即使当前环境缺少 jsonschema，也能报告依赖问题。

```powershell
python -X utf8 src/flowpilot/preflight.py --comsol-root '<COMSOL_ROOT>'
# 只准备离线测试时可不指定 COMSOL：
python -X utf8 src/flowpilot/preflight.py
# 机器可读结果打印到标准输出，不自动写文件：
python -X utf8 src/flowpilot/preflight.py --json
```

与运行桌面的 Python 必须是同一个环境。若使用虚拟环境，将上述 `python` 替换为该环境的 `Scripts/python.exe`。`FlowPilot.cmd` 优先使用 `.venv`，而不是任意已通过测试的其他环境；不要因为另一个环境测试成功，就认定双击入口的依赖齐全。

## 结果含义

- `ready`：指定的六个模型与清单一致，Python 及依赖可导入，指定 COMSOL 目录有编译/批处理文件。
- `ready_with_warnings`：没有阻断项，但未指定 COMSOL，或 Python 不在当前已验证的 3.12/3.13 范围。
- `blocked`：模型缺失、仍是 LFS 指针、哈希不符、清单错误或必要依赖不可用。退出码为 1；其余结果为 0。

`ready` 只代表配置预检通过，不证明 COMSOL 的版本、许可证、模块、求解、可见窗口或物理正确性。预检不启动 COMSOL、不初始化 Tk 窗口，不执行下载、还原、重置、求解或保存。文件状态是读取时的快照，正式检查仍会执行自己的源文件保护。

## 模型问题如何处理

- `lfs_pointer`：确认仓库访问权限及 Git LFS，再手动执行 `git lfs pull`。
- `hash_mismatch`：先保存自己的修改、确认修改意图。不要覆盖模型或把 manifest 的哈希改成当前文件来绕过保护。
- `missing` / `read_error`：检查文件是否下载、是否被占用、目录权限是否正常。
- `outside_root`：模型链接或目录链接指向指定根目录之外，预检不读取该目标。

可通过 `--manifest`、`--model-root` 指定另一个清单及其模型根目录。清单使用 `case-manifest-0.1`，模型路径相对于根目录；拒绝越界路径、重复案例/路径/哈希、重复 JSON 字段和超过 64 KiB 的清单。这个入口不验证专业标签及独立性，不能代替批量评估。

若工作区有需保留的基准修改，可在独立目录准备已提交版本，再使用 `--model-root` 预检和批量检查。必须实际核对副本哈希，不复制改名后冒充已提交原件。

## 换行与来源指纹

仓库 `.gitattributes` 要求 JSON、Python、Java 使用 LF。旧工作区可能遗留 CRLF，Git 的文本归一化会使其内容 diff 看似相同，但文件字节哈希不同。遇到来源指纹失败，先确认工作区格式与提交中的 LF 一致；不要直接替换证据里的哈希。格式修正后重新运行测试及来源核验。

## 验证与回退

专项离线测试覆盖完整文件、本地修改保护、LFS 指针、缺失文件、路径越界、坏清单、缺依赖、COMSOL 文件存在性与 CLI 退出码。测试模型只是模拟字节，不是新的真实 COMSOL 实验。

本机接手验证见 [本轮记录](LOCAL_ACCEPTANCE.md)。撤回 `preflight.py`、专项测试和本说明即可；现有检查器、模型与诊断规则未改动。
