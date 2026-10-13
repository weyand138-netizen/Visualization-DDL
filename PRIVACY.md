# Privacy and release contents / 隐私与发布内容

Only source code, generic deployment templates, tests using fictional fixtures, documentation and synthetic screenshots belong in this repository.

Do not submit databases (including SQLite WAL/SHM), credentials or password hashes from a real deployment, actual QQ identifiers or bindings, user schedules, real conversation histories, logs, backups, SSH material, private operational scripts, production screenshots or unreviewed archives. Replace personal hosts, QQ identifiers and local paths in **tests and documentation**, too.

Fictional test prompts, synthetic schedules and placeholder identifiers are permitted when clearly presented as examples. Numeric QQ identifiers in tests are synthetic fixtures and do not represent this project's users or their bindings. A “fixed account” is selected from each operator's private local configuration; no personal account is embedded in the public connector.

Use placeholders in `.env.example` and MCP examples. Actual `.env` and `mcp.json` files stay on the operator's machine. Use a GitHub noreply commit email. Check `git ls-files`, `python tools/privacy_check.py --history`, the generated release archive and the Docker build context before publishing. The scanner is a release guard, not proof that arbitrary data is anonymous; review all textual fixtures and images.

Both the author and committer identities are checked throughout Git history. Personal GitHub noreply addresses (`@users.noreply.github.com`) and GitHub's platform address (`noreply@github.com`) are allowed; a GitHub committer does not exempt an author's personal email. Before editing files on GitHub, enable "Keep my email addresses private" in your GitHub email settings so web edits use your noreply author address. A clean new commit does not remove a personal email from an older commit.

发布仅包含源码、通用部署模板、虚构测试、文档和演示截图。数据库、已有日程、真实密码哈希、真实 QQ 号及绑定、真实对话记录、日志、备份、SSH 文件和生产截图不得提交。文档及测试也需替换个人信息。真实配置仅保存在部署机器；提交使用 GitHub noreply 邮箱。工具扫描之外，还需人工核对全部发布文件及图片。

隐私检查会核对 Git 历史中每次提交的作者和提交者邮箱，允许个人 GitHub noreply 地址（`@users.noreply.github.com`）及 GitHub 平台地址（`noreply@github.com`）；提交者是 GitHub 并不会豁免作者的普通邮箱。在 GitHub 网页编辑文件前，请在 GitHub 邮箱设置中启用「Keep my email addresses private」，让网页编辑使用 noreply 作者地址。新增一个干净提交不能移除旧提交里的普通邮箱。

允许明确标注用途的虚构测试对话、演示日程和占位标识。测试中的数字 QQ 标识仅为测试占位，不对应本项目用户的实际身份或绑定。“固定账户”由各部署者的本地私有配置决定，公开连接器不预置私人账户。
