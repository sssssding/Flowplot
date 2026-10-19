# 本机接手验证：早期记录

本页记录 2026-10-11 的一次本机复现，不再作为当前状态入口。小型来源摘要仍保留在 [local_acceptance.json](../data/fixtures/local_acceptance.json)；后续界面记录和当前状态见 [DESKTOP_REVIEW.md](DESKTOP_REVIEW.md)、[2026-10-17 摘要](validation/2026-10-17/README.md) 与 [完成审计](COMPLETION_AUDIT.md)。

当时一个旧报告因 CRLF 与提交证据中的 LF 不同而出现字节哈希不匹配；将工作副本按仓库属性转换后，JSON 内容未变且原证据哈希匹配。遇到类似情况应核对 `.gitattributes` 和原始字节，不应手改报告哈希或覆盖用户模型。旧环境、测试计数和窗口状态可从 Git 历史追溯。
