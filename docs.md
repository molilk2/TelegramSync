
# docs.md

## 项目职责概览

### main.py
兼容入口与主菜单。

职责：
- 默认打开主菜单
- 把 `main.py server ...` 转发给 `server_entry()`
- 把 `main.py cli ...` 转发给 `cli_entry()`
- 保留旧命令行兼容行为

### server_main.py
server 独立入口。

职责：
- 调用 `app.server.server_entry()`
- 适合打包成 `tg-server`

### cli_main.py
cli 独立入口。

职责：
- 调用 `app.cli.cli_entry()`
- 适合打包成 `tg-cli`

### app/server.py
server 侧核心。

主要职责：
- `interactive_server_setup()`：交互式写配置
- `ensure_server_login()`：仅在 server 侧执行登录
- `cache_account_dialogs()`：缓存账号里的最近会话/频道
- `interactive_server_menu()`：server 菜单
- `run_server_process()`：启动常驻服务
- `server_entry()`：server 入口，支持菜单和命令参数
- `TelegramDaemon`：长期运行的监听 / 补漏 / 下载 worker / IPC server

### app/cli.py
cli 侧核心。

主要职责：
- `interactive_root_menu()`：旧主菜单
- `interactive_cli_menu()`：cli 菜单
- `interactive_cli_channels()`：频道 / follow 管理菜单
- `rpc_call()`：通过本地 TCP 向 server 发命令
- `cmd_cli()`：命令式 CLI 子命令分发
- `cli_entry()`：cli 独立入口

### app/ipc.py
server 与 cli 的 TCP IPC。使用“4 字节长度头 + JSON 内容”的协议，避免长响应触发 `readline()` 长度限制。

### app/core/sync.py
负责：
- 列出 dialogs
- 解析 chat / peer_id / username
- 同步历史消息入库
- 把历史媒体补入下载队列

### app/core/downloader.py
下载队列消费者。

职责：
- 从 `download_jobs` 取任务
- 下载媒体
- 写回状态
- 与消息同步彻底解耦

### app/store/db.py
SQLite 连接与 schema 初始化。

### app/store/repo.py
数据库读写封装。

主要表：
- `messages`
- `chat_state`
- `follows`
- `download_jobs`
- `downloads`
- `dialogs_cache`
- `server_state`
- `runs`

### build/tg-server.spec
PyInstaller 构建说明，用于产出 `tg-server`。

### build/tg-cli.spec
PyInstaller 构建说明，用于产出 `tg-cli`。

### .github/workflows/build-binaries.yml
GitHub Actions 工作流。

职责：
- 在 Linux runner 构建 `tg-server` / `tg-cli`
- 在 Windows runner 构建 `tg-server.exe` / `tg-cli.exe`
- 产出 Termux aarch64 运行包
