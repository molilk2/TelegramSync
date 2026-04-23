
# tg-daemon-cli

一个以 **server + cli** 方式运行的 Telegram 采集 / 下载工具。

## 入口

推荐入口已经拆成两个：

- `python server_main.py` 或打包后的 `tg-server`
- `python cli_main.py` 或打包后的 `tg-cli`

兼容入口仍然保留：

- `python main.py`：默认打开主菜单
- `python main.py server ...`：转发到 server 入口
- `python main.py cli ...`：转发到 cli 入口

## 常用流程

1. `python server_main.py setup`
2. `python server_main.py login`
3. `python server_main.py run`
4. 另开终端执行 `python cli_main.py` 或 `python cli_main.py status`

## 运行模式

- 消息：持续入库
- 媒体：进入 `download_jobs` 队列
- 下载：由 server 后台 worker 异步逐步消费

## 菜单说明

### tg-server

不带参数时进入 server 菜单。菜单会在必要时引导初始化和登录。

功能：
1. 启动服务
2. 更改配置
3. 退出登录
4. 优化数据库
5. 刷新会话缓存

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

可以分别构建 `tg-server` 和 `tg-cli`。PyInstaller 的 spec 文件是官方支持的构建描述方式，适合多入口程序。citeturn136241search1turn136241search17

### GitHub Actions

项目附带 `.github/workflows/build-binaries.yml`，会为 Linux、Windows 和 Termux 产出分发物。工作流使用矩阵和 artifact 上传方式，均是 GitHub Actions 官方支持的能力。citeturn136241search0turn136241search2turn136241search5
