# Repository guidance

- Start with `README.md`; use `docs/README.md` to choose one task-specific guide.
- Read `docs/HANDOFF.md` for the current branch and next actions. Read `docs/PROGRESS.md` for current status; older session logs are recoverable from Git history.
- Treat dated validation records and their JSON hashes as evidence. Never rewrite an old result to make it match current code.
- Keep model files, training data, reviewed fixtures, schemas, tests, and source code unchanged during documentation-only work.
- Preserve user-modified models, local configuration, licenses, logs, and private outputs. Never add them to Git.
- Retain runnable commands and safety limits in `docs/DEVELOPMENT.md`; keep detailed feature contracts in their dedicated guides.
- Update the relevant index and current-state docs when behavior or verified status changes.
- Run only the verification needed for the change; report exact failures and skipped checks. Do not install dependencies without an explicit need.
- Use UTF-8 Markdown and repository-relative links. Keep instructions concise and avoid duplicating chronological work logs.
