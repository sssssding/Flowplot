# COMSOL 模型目录

本目录用于存放模型清单和经授权共享的 `.mph` 文件。

- 基准模型建议命名为 `baseline_pipe_2d_laminar.mph`。
- `.mph` 为二进制大文件，提交前先配置 Git LFS：`git lfs track "*.mph"`。
- 不提交自动生成的恢复、锁定、缓存和求解结果文件。
- 每个共享模型必须在 `docs/BASELINE_MODEL.md` 或测试清单中记录 SHA-256、COMSOL 版本、用途和 Ground Truth。
- 若赛事或数据许可不允许公开，不要放入公开仓库。
