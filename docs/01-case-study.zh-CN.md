# 实操记录：架构、数据与 AI 记忆

[English](01-case-study.en.md) · [QQ 部署](02-astrbot-qq.zh-CN.md) · [AIRI 部署](03-airi.zh-CN.md)

原有方案在 Ubuntu 上运行 DDL、AstrBot 和 NapCat。本仓库从源码白名单导出并建立新 Git 历史，不包含原机器、运行数据或历史提交，也不修改原有部署。公开的账户、地址与截图均为示例。

QQ 私聊 → NapCat 的 OneBot 连接 → AstrBot DDL 插件 → DDL API → 当前账户的 SQLite，是已经搭建的链路。DDL 本身是独立网页应用与 HTTP 服务，只有 AstrBot 适配部分属于插件。NapCat 负责 QQ 消息传输，模型由 AstrBot 中选择的提供商执行。

插件先检查私聊 `/日程` 或 `/ddl` 指令、QQ 白名单与账户绑定，再读取该账户的日程，将规则、北京时间、完整日程、当前文字及最多三张直接或引用图片交给模型。模型返回结构化操作，插件与后端校验后事务写入，并通过 OneBot 返回结果。网页“AI 整理”也使用这个规划桥；没有配置桥时入口隐藏。公网由 HTTPS 反向代理提供服务，机器人令牌接口只留在内部网络。

## 数据与记忆

| 位置 | 存储内容 |
|---|---|
| `data/dashboard.sqlite3` | admin 账户的日程数据库 |
| `data/users/<username>/dashboard.sqlite3` | 每个附加账户的独立数据库 |
| `events` 表 | id、title、date、time、category、status、incomeCents、payment、notes、createdAt |
| `preferences` 表 | JSON 格式的主题、专注时长、每日目标 |
| `focus` 表 | 已完成专注会话的 ID、秒数、日期 |
| `bot_requests` 表 | 请求 ID、载荷摘要与原始结果，用于重试去重 |
| 浏览器本地存储 | 按账户区分的设置与未结束专注恢复状态 |
| AstrBot 自身存储 | 提供商、平台配置与普通聊天历史，不随本项目发布 |

附加账户密码使用 PBKDF2-SHA256 哈希，保存在私有配置；管理员密码来自 `DDL_PASSWORD`。网页登录按认证账户选择数据库。机器人访问还要验证内部令牌，并由可信 QQ 绑定确定账户；账户不是让模型从参数中自由选择的。

DDL 规划器的长期上下文主要来自已保存的日程：当前日程、北京时间、固定规则和本次输入。它没有另建一个保存聊天历史的“AI 记忆库”。AstrBot 普通对话历史由 AstrBot 独立管理；专注统计来自专注会话。新增 MCP 连接器也不额外保存对话，仅把日程、固定账户、时间与版本交给 AIRI；AIRI 自身的聊天记忆由 AIRI 管理。

两条路线可以绑定同一 DDL 账户共享日程，也可以使用不同账户隔离。AIRI 的模型在普通对话中选择工具，本地 stdio 连接器把调用转换为使用登录账号认证的 `/api/state`、`/api/events/batch` 请求，不需要 AstrBot 或机器人令牌。

## 验证范围

原部署已检查 Ubuntu 服务运行、账户隔离、网页日程编辑、专注同步以及 AstrBot 规划桥，实际调用过文字与图片模型。组件测试覆盖消息解析、授权与绑定、结构化操作和 HTTP 落库。本次准备开源时**没有主动发送新的真实 QQ 消息并观察完整收发**，不能把 OneBot 连接健康或解析测试等同于真实 QQ 端到端测试。

新增连接器使用临时数据库、虚构账户及官方 MCP 客户端测试。官方 AIRI 与 airi-HA 的桌面自然语言结果分别记录在 [VALIDATION.md](VALIDATION.md)，源码检查和 MCP 接口测试不冒充桌面验证。所有发布资产均未使用生产日程、绑定、凭据或对话导出。
