# 第三方依赖与分发说明

核对日期：2026-10-21。本仓库的 MIT License 适用于项目自有源码、图标、示例和文档。第三方文件、库和工具保留各自许可证，MIT 不替代它们。

仓库只提供应用源码与构建脚本，未附带 Python / Qt / HEIF / PDFium 运行时二进制。下表对应锁定依赖，仅为索引，具体条件以各项目的完整许可文件为准。

| 组件 | 使用的版本 | 上游许可与来源 |
| --- | --- | --- |
| PySide6 Essentials / shiboken6 | 6.12.0 | 安装元数据列出 LGPL-3.0-only / GPL-2.0-only / GPL-3.0-only 选项；[Qt for Python 许可](https://doc.qt.io/qtforpython-6/licenses.html) |
| Pillow | 12.3.0 | MIT-CMU；另有内置编解码库，[上游许可](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| pillow-heif | 1.8.1 | Python 源码 BSD-3-Clause；预编译 wheel 的说明明确列出 GPLv2，[源码许可](https://github.com/bigcat88/pillow_heif/blob/master/LICENSE.txt)、[二进制依赖说明](https://github.com/bigcat88/pillow_heif/blob/master/LICENSES_bundled.txt) |
| ReportLab | 5.0.1 | BSD 风格许可；[上游](https://www.reportlab.com/)及安装包 LICENSE |
| pypdf | 6.21.0 | BSD-3-Clause；[上游许可](https://github.com/py-pdf/pypdf/blob/main/LICENSE) |
| pypdfium2 | 5.14.0 | BSD-3-Clause / Apache-2.0 及依赖许可；[上游](https://github.com/pypdfium2-team/pypdfium2) |
| PDFium | 156.0.8076.0（当前 Windows wheel） | BSD 风格及 Chromium 第三方组件；wheel 的 `licenses/data/windows_x64/BUILD_LICENSES` 提供通知 |
| RapidOCR | 3.10.0 | Apache-2.0；[上游](https://github.com/RapidAI/RapidOCR)，本地使用 wheel 附带的 PP-OCRv6 det / rec 与方向分类 ONNX 模型 |
| ONNX Runtime | 1.31.0 | MIT；[上游](https://github.com/microsoft/onnxruntime)，CPU 推理，关闭遥测 |
| fontTools | 4.67.0 | MIT；[上游](https://github.com/fonttools/fonttools)，读取字体元数据及嵌入限制 |
| OpenCV / NumPy / Shapely / pyclipper | 见 requirements-lock.txt | OCR 的图像与数值依赖；完整安装许可随本地构建复制到 licenses |
| charset-normalizer | 3.5.2 | MIT；[上游](https://github.com/jawah/charset_normalizer) |
| CPython | 3.12 | Python Software Foundation License；[完整许可](https://docs.python.org/3/license.html) |

## HEIF 预编译库

本次安装的 `pillow-heif 1.8.1` 的 `LICENSES_bundled.txt` 列出 libheif 1.23.6（LGPLv3）、libde265 1.1.3（LGPLv3）、x265 4.3（GPLv2）和 Windows MinGW 运行库。二进制 wheel 的许可与 Python 包源码的 BSD 许可不同。

因此，不能只保留本项目 MIT 文本就把包含这些库的整个 EXE 按 MIT 分发。发布者需要根据实际依赖组合履行对应的许可、源码提供等义务，或自行构建符合其分发方案的依赖。仅关闭应用中的 HEIF 编码功能，不会自动移除已经打包的 GPL 库。

## Qt 与 PDFium

Qt / PySide6 开源许可带有相应条件；Qt 自身也包含第三方组件。当前 wheel 的 dist-info 许可目录并不代表所有 Qt 组件的完整通知。请同时核对 [Qt 许可文档](https://doc.qt.io/qt-6/licensing.html)与实际模块。

PDFium 的许可证文件保存在多层子目录，有些文件名没有 `LICENSE` 字样；构建工具按整个 licenses 路径收集，避免漏掉这些通知。

## 构建工具与仓库内第三方文件

- PyInstaller：GPL-2.0-or-later，带允许打包非 GPL 应用的 bootloader 例外，见[官方许可说明](https://pyinstaller.org/en/stable/license.html)。
- pytest：MIT；仅开发时使用。
- Inno Setup：[上游许可证](https://github.com/jrsoftware/issrc/blob/main/license.txt)。`packaging/ChineseSimplified.isl` 来自官方仓库，保留原始翻译归属，来源与校验值记录在 `packaging/language-source.json`，完整许可保存在 `packaging/INNO-LICENSE.txt`。
- 依赖库、Windows 字体和安装工具不是本项目自有作品。没有将 Windows 字体文件纳入仓库。文字编辑时读取用户已安装或自行提供的字体，仅将需要的字形嵌入用户导出的 PDF。
- OCR 模型由锁定版本的 RapidOCR wheel 提供；源码仓库不提交模型二进制。构建时将模型与配置一并打包，不在用户首次使用时在线下载。

构建工具复制依赖包提供的许可文件，不等于完成全部二进制分发要求。当前公开交付范围为源码，预编译安装包不在本次 GitHub 发布范围内。
