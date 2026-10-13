# Privacy and release contents / 隐私与发布内容

Only source code, generic deployment templates, tests using fictional fixtures, documentation and synthetic screenshots belong in this repository.

Do not submit databases (including SQLite WAL/SHM), credentials or password hashes from a real deployment, QQ bindings, user schedules, conversation histories, logs, backups, SSH material, private operational scripts, production screenshots or unreviewed archives. Replace personal hosts, QQ identifiers and local paths in **tests and documentation**, too.

Use placeholders in `.env.example` and MCP examples. Actual `.env` and `mcp.json` files stay on the operator's machine. Use a GitHub noreply commit email. Check `git ls-files`, `python tools/privacy_check.py --history`, the generated release archive and the Docker build context before publishing. The scanner is a release guard, not proof that arbitrary data is anonymous; review all textual fixtures and images.

发布仅包含源码、通用部署模板、虚构测试、文档和演示截图。数据库、已有日程、真实密码哈希、QQ 绑定、对话、日志、备份、SSH 文件和生产截图不得提交。文档及测试也需替换个人信息。真实配置仅保存在部署机器；提交使用 GitHub noreply 邮箱。工具扫描之外，还需人工核对全部发布文件及图片。
