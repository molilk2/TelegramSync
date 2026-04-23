# docs.md

## 项目职责概览

### main.py
兼容入口。

职责：
- 把 `main.py server ...` 转发给 `server_entry()`
- 把 `main.py cli ...` 转发给 `cli_entry()`
- 不再承担默认交互菜单，避免弱化 server / cli 边界

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
server 薄入口与命令分发。

主要职责：
- 参数解析
- server 菜单
- 登录 / 启动流程编排
- 构建异步 Repo facade

### app/server_auth.py
server 登录与初始化相关逻辑。

主要职责：
- `interactive_server_setup()`
- `ensure_server_login()`
- `cache_account_dialogs()`
- `server_logout()`

### app/server_daemon.py
常驻 daemon 核心。

主要职责：
- IPC server
- 新消息入库
- 周期补漏
- 下载 worker
- stop / status / follow 等命令处理

### app/server_lock.py
单实例锁。

主要职责：
- 管理 `server.lock`
- 防止同时运行多个 server
- 处理陈旧锁文件

### app/server_helpers.py
server 侧通用辅助函数。

主要职责：
- row 安全读取
- dialog 名称与用户名提取

### app/cli.py
cli 侧核心。

主要职责：
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
同步数据库读写封装。

### app/store/async_repo.py
异步数据库 facade。

职责：
- 用 `asyncio.to_thread()` 包装 Repo 调用
- 减少 daemon 线程中的 SQLite 阻塞对事件循环的影响

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

### build/README.md
打包目录说明与本地构建说明。

### build/requirements-build.txt
构建期额外依赖，当前主要用于固定 PyInstaller。

### build/build-local.sh
Linux / macOS 本地一键打包脚本。

### build/build-local.ps1
Windows 本地一键打包脚本。

### .github/workflows/build-binaries.yml
GitHub Actions 工作流。

职责：
- 用 matrix 统一管理 Linux / Windows 构建
- 清理 `__pycache__`、`dist/`、`out/`、`build-cache/` 等临时目录
- 只上传打包后的归档产物到 Actions artifact / GitHub Release


## 平台兼容性说明

- Linux：当前默认优先支持的平台，源码运行与 GitHub Actions 自动构建均已覆盖。
- Windows：源码运行与 GitHub Actions 自动构建已覆盖；已补充 Windows 保留文件名过滤与更稳妥的路径组件长度限制。
- Termux / Android：当前以源码运行支持为主，尚未纳入 GitHub Actions 自动打包产物范围。

## 发布包整理

- 发布包不再携带 `__pycache__`。
- PyInstaller spec 不再把整个 `app/` 目录重复作为 data 打包，只保留文档资源。
