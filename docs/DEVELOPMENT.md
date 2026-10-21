# 开发与构建

## 环境与目录

支持 Windows x64、Python 3.12。运行环境为项目自己的 `.venv`，不依赖任何聊天客户端、内部 API 或会话缓存。先按根目录 README 克隆并建立虚拟环境。

| 路径 | 内容 |
| --- | --- |
| `main.py` | GUI / 命令行入口和本地运行目录 |
| `pdfedit/` | 图片解码、PDF 页面、导出、Qt 界面、水印和右键菜单 |
| `assets/` | 应用图标与界面 SVG 图标 |
| `examples/` | 可公开使用的测试图片与多页 PDF |
| `tests/` | 行为回归与真实 Qt 控件测试 |
| `tools/` | 测试、截图、构建和 EXE 验证工具 |
| `packaging/` | Inno Setup 安装脚本与中文语言文件 |
| `docs/` | 文档与界面截图 |

`requirements.txt` 固定运行直接依赖；`requirements-dev.txt` 增加开发工具；`requirements-lock.txt` 固定本次验证环境的所有版本。修改依赖后请重新验证解码、GUI 与打包后的程序。

## 安装开发依赖与测试

```powershell
$env:PIP_CACHE_DIR = "$PWD\.task_tmp\pip-cache"
New-Item -ItemType Directory -Force .task_tmp\install-temp | Out-Null
$env:TEMP = "$PWD\.task_tmp\install-temp"
$env:TMP = $env:TEMP
.\.venv\Scripts\python.exe -s -m pip install --only-binary=:all: -r requirements-lock.txt
.\.venv\Scripts\python.exe -B -s tools/run_tests.py --task development-tests
```

测试入口自动设置离屏 Qt 平台，将测试文件放入 `.task_tmp/development-tests`，JUnit 报告放入 `reports/tests.xml`。不要只运行语法编译来判断导出是否正确。

生成真实界面截图：

```powershell
.\.venv\Scripts\python.exe -B -s tools/capture_screenshots.py
```

## 构建 EXE

```powershell
.\.venv\Scripts\python.exe -B -s tools/build.py --task build-1.4.2 --name PDFedit-1.4.2
.\.venv\Scripts\python.exe -B -s tools/verify_release.py --task build-1.4.2 --name PDFedit-1.4.2
```

程序位于 `dist/PDFedit-1.4.2/PDFedit-1.4.2.exe`。必须保留整个目录，不能单独复制 EXE。构建拒绝覆盖已有同名目录；重复构建时使用新的 `--name`，并向验证和安装包工具传入同一个名称。

验证工具在去除 Python 环境变量、仅保留 Windows 系统 PATH 的进程中执行实际 EXE，检查多种图片、PDF 混排、原始文字、表单外观、A3、5% 水印和密度。报告写入 `reports/<构建名称>/release-verification.json`，包含构建 SHA-256。它不验证每台电脑的字体、显示缩放或所有文件编码。

构建时会收集已安装 Python 包提供的许可证目录和 notices，并保留原文件层次。**这不是完整的二进制许可审计**；特别是 HEIF 的 GPL 组件、Qt 与其第三方组件，还需按实际构建核对对应源码和分发要求。参见 [第三方说明](../THIRD_PARTY_NOTICES.md)。本仓库的自动化仅执行源码测试，不自动上传安装包。

## 构建中文安装包

安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)，然后执行：

```powershell
.\.venv\Scripts\python.exe -B -s tools/build_installer.py --task build-1.4.2 --name PDFedit-1.4.2 --compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

`--compiler` 可以指向其他安装位置。工具要求上一步验证成功且 EXE 哈希一致。输出为 `releases/合页-1.4.2-安装程序.exe`，校验文件为 `releases/SHA256SUMS.txt`。同名安装包不会被覆盖。

公开版安装脚本默认当前用户的 `AppData/Local/Programs/Heye`，可选择其他本地可写目录。没有管理员权限要求。更改版本需同步 `pdfedit/__init__.py`、构建默认名称、启动脚本、文档，以及安装脚本的后备版本。

## 启动、停止与清理

开发时运行 `.venv/Scripts/python.exe -B -s main.py`；打包后双击 EXE。关闭窗口结束程序，不部署服务。发布程序与数据独立保存，不需要开发终端保持打开。

不要提交 `.venv`、`.task_tmp`、`runtime`、`outputs`、`dist`、`releases`、本机报告或含私有路径的编辑方案。确认没有进程使用缓存后，可通过 Windows 资源管理器将对应任务目录移入回收站。源码、依赖清单、正式数据与发布目录分别备份。

## 文字编辑与 OCR 构建

运行依赖新增 RapidOCR、ONNX Runtime、fontTools；锁定版本见 requirements-lock.txt。构建脚本收集 RapidOCR 配置及三个本地 ONNX 模型，并复制推理和字体依赖的许可文件。模型约 31.75 MB（十进制），完整发布包还包含推理运行库。

`tools/verify_release.py` 会在仅含 Windows 的 PATH 下运行真实 EXE，检查扫描 OCR、中文嵌入和编辑方案导出；测试结果与模块来源审计保存在 reports。关闭 Codex 后的独立运行仍需实际手工验证，不能由环境隔离测试替代。

通过发布验证后运行 `.\.venv\Scripts\python.exe -B -s tools/package_portable.py --name PDFedit-1.4.2` 可生成便携 ZIP。工具排除 runtime / outputs 并逐个比对解压内容的 SHA-256，不覆盖已有包。
