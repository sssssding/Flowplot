# COMSOL 模型目录

本目录用于存放模型清单和经授权共享的 `.mph` 文件。

M3 三维直圆管与带固体管壁样例由 `scripts/verify_m3_api.py` 在新建的 `outputs/m3_api/<时间>/` 生成；每个模型均未求解，原目录模型不覆盖。小型可回放清单和摘要为 `data/fixtures/m3_inventories.json`、`m3_api_evidence.json`，支持与跳过范围见 [M3.md](../docs/M3.md)。

M1 的 13 个轴对称未求解开发样例由 `scripts/verify_m1_api.py` 在新的 `outputs/m1_api/<运行时间>/` 再生，不覆盖本目录的平面模型。可提交的真实清单与摘要在 `data/fixtures/m1_inventories.json`、`data/fixtures/m1_api_evidence.json`；支持范围和操作见 [M1.md](../docs/M1.md)。

- 基准模型建议命名为 `baseline_pipe_2d_laminar.mph`。
- `.mph` 为二进制大文件，提交前先配置 Git LFS：`git lfs track "*.mph"`。
- 不提交自动生成的恢复、锁定、缓存和求解结果文件。
- 每个共享模型必须在 `docs/BASELINE_MODEL.md` 或测试清单中记录 SHA-256、COMSOL 版本、用途和 Ground Truth。
- 若赛事或数据许可不允许公开，不要放入公开仓库。

M2 热与受限共轭样例生成在新的 `outputs/m2_api/<时间>/`，不覆盖这里的原六个模型。17个未求解样例的来源、正常/异常和支持边界见 [M2交付](../docs/M2.md)；复现入口为 `scripts/verify_m2_api.py`。
