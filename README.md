# tg-daemon-cli

一个以 **server + cli** 方式运行的 Telegram 采集 / 下载工具。

## 推荐入口

- `python server_main.py` 或打包后的 `tg-server`
- `python cli_main.py` 或打包后的 `tg-cli`

兼容入口仍然保留：

- `python main.py server ...`
- `python main.py cli ...`

`main.py` 现在只做兼容转发，不再承担默认交互菜单，避免模糊 server / cli 边界。

## 常用流程

1. `python server_main.py setup`
2. `python server_main.py login`
3. `python server_main.py run`
4. 另开终端执行 `python cli_main.py status`

## 运行模式

- 消息：持续入库
- 媒体：进入 `download_jobs` 队列
- 下载：由 server 后台 worker 异步逐步消费
- 数据库：底层仍是 SQLite，但 daemon 侧通过异步 facade 调用 Repo，减少事件循环被同步提交阻塞的概率

## 菜单说明

### tg-server

不带参数时进入 server 菜单。

功能：
1. 启动服务
2. 更改配置
3. 登录并刷新会话缓存
4. 退出登录
5. 优化数据库

### tg-cli

不带参数时进入 cli 菜单。

功能：
1. Ping server
2. 查看账号
3. 查看状态
4. 查看缓存会话
5. 频道 / Follow 管理
6. 手动同步某个 chat
7. 停止 server

## 打包

### PyInstaller

项目提供了两个 spec：

- `build/tg-server.spec`
- `build/tg-cli.spec`

可以分别构建 `tg-server` 和 `tg-cli`。

### GitHub Actions

项目附带 `.github/workflows/build-binaries.yml`，当前用于构建 Linux 和 Windows 分发物。

构建相关文件统一放在 `build/`：
- `build/tg-server.spec`
- `build/tg-cli.spec`
- `build/requirements-build.txt`
- `build/build-local.sh`
- `build/build-local.ps1`

补充说明：
- Linux / Windows：当前仓库已覆盖源码运行与自动构建
- Termux / Android：当前按**源码运行**为主，暂未纳入 GitHub Actions 自动打包产物
- 发布包建议只上传归档文件，不再额外上传松散的 dist 目录内容
