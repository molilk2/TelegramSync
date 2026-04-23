# build/

该目录只放打包相关文件，不放运行时代码。

包含：
- `tg-server.spec`：PyInstaller server 构建入口
- `tg-cli.spec`：PyInstaller cli 构建入口
- `requirements-build.txt`：构建期额外依赖
- `build-local.sh`：Linux/macOS 本地打包脚本
- `build-local.ps1`：Windows PowerShell 本地打包脚本

## 本地打包

### Linux / macOS

```bash
python -m pip install -r requirements.txt -r build/requirements-build.txt
bash build/build-local.sh
```

### Windows PowerShell

```powershell
python -m pip install -r requirements.txt -r build/requirements-build.txt
powershell -ExecutionPolicy Bypass -File build/build-local.ps1
```

构建完成后，归档文件会出现在：
- `out/tg-linux-x86_64.tar.gz`
- `out/tg-windows-x64.zip`

源码发布包建议使用仓库根目录打包，不要把 `dist/`、`build-cache/`、`out/` 一起带上。
