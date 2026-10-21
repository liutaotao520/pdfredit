from __future__ import annotations

import ctypes
import argparse
import json
import logging
import os
from pathlib import Path
import sys


def runtime_root():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def configure_environment(root):
    root = Path(root).absolute()
    for parent in (root, *root.parents):
        if parent.lstat().st_file_attributes & 0x400:
            raise RuntimeError("软件目录不能使用符号链接或 junction。")
    runtime = root / "runtime"
    for folder in [runtime, runtime / "temp"]:
        if folder.exists() and folder.lstat().st_file_attributes & 0x400:
            raise RuntimeError("运行数据目录不能指向其他位置。")
        folder.mkdir(exist_ok=True)
    for name in ["TEMP", "TMP", "TMPDIR"]:
        os.environ[name] = str(runtime / "temp")
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    logging.basicConfig(filename=runtime / "app.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    return runtime


def main():
    root = runtime_root()
    configure_environment(root)
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from pdfedit.style import apply_style
    from pdfedit.dialogs import Messages
    app = QApplication(sys.argv[:1])
    app.setApplicationName("合页")
    app.setOrganizationName("PDFedit")
    apply_style(app)
    assets = Path(__file__).resolve().parent / "assets"
    app.setWindowIcon(QIcon(str(assets / "app.ico")))
    def error_handler(kind, value, tb):
        logging.error("Unhandled error", exc_info=(kind, value, tb))
        Messages.critical(None, "合页遇到问题", str(value) + "\n详细记录见 runtime/app.log。")
    sys.excepthook = error_handler
    if "--install-menu" in sys.argv:
        from pdfedit.shell import install_menu
        result = install_menu(root)
        (root / "runtime" / "shell-status.txt").write_text(result, encoding="utf-8")
        return 0
    if "--uninstall-menu" in sys.argv:
        from pdfedit.shell import uninstall_menu
        result = uninstall_menu()
        (root / "runtime" / "shell-status.txt").write_text(result, encoding="utf-8")
        return 0
    if "--export" in sys.argv:
        from pdfedit.engine import PAPERS, export_pdf
        parser = argparse.ArgumentParser(description="合页离线批量导出")
        parser.add_argument("--export", required=True)
        parser.add_argument("--watermark-text", default="")
        parser.add_argument("--watermark-image", default="")
        parser.add_argument("--paper", choices=[*PAPERS, "original"], default="A4")
        parser.add_argument("--watermark-scale", type=int, default=28, help="图片水印占页面宽度的百分比，5–90")
        parser.add_argument("--watermark-tiled", action="store_true", help="平铺水印，覆盖整页")
        parser.add_argument("--watermark-density", type=int, choices=range(1, 11), default=3, help="平铺密度 1–10，默认 3")
        parser.add_argument("--project", help="读取 .ipdf.json 编辑方案，保留文字修改与排版")
        parser.add_argument("--ocr", action="store_true", help="在本机识别输入文件，加入可搜索文字层")
        parser.add_argument("images", nargs="*")
        args = parser.parse_args()
        if bool(args.project) == bool(args.images):
            parser.error("请选择输入文件或 --project 编辑方案，两者不能同时使用。")
        if not 5 <= args.watermark_scale <= 90:
            parser.error("图片水印缩放必须在 5% 至 90% 之间。")
        from pdfedit.imaging import inspect_image
        from pdfedit.models import Layout, Watermark
        pages = [page for path in args.images for page, _ in inspect_image(path)]
        watermark = Watermark()
        if args.watermark_text:
            watermark = Watermark(kind="text", text=args.watermark_text)
        if args.watermark_image:
            watermark = Watermark(kind="image", image_path=args.watermark_image, scale=args.watermark_scale / 100)
        watermark.tiled, watermark.density = args.watermark_tiled, args.watermark_density
        layout = Layout(paper=args.paper)
        if args.project:
            from pdfedit.project_io import read_project
            pages, layout, watermark = read_project(args.project)
        if args.ocr:
            from pdfedit.text_editing import recognize_page
            for page in pages:
                page.text_blocks, page.text_source_signature = recognize_page(page)
                page.text_recognized = True
        result = export_pdf(pages, layout, watermark, args.export)
        result["executable"] = sys.executable
        result["packaged"] = bool(getattr(sys, "frozen", False))
        result["application_modules"] = sorted({str(module.__file__) for name, module in sys.modules.items()
            if name.startswith(("PySide6", "PIL", "pillow_heif", "reportlab", "pdfedit", "pypdf", "pypdfium2", "rapidocr", "onnxruntime", "cv2", "numpy", "fontTools")) and getattr(module, "__file__", None)})
        (root / "runtime" / "last-export.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    paths = [str(Path(value).absolute()) for value in sys.argv[1:] if not value.startswith("--")]
    from pdfedit.instance import Instance
    instance = Instance(root)
    if not instance.primary:
        success = instance.forward(paths)
        instance.close()
        if not success:
            Messages.warning(None, "无法连接合页窗口", "合页正在启动或未响应，请稍后重试。")
        return 0 if success else 1
    from pdfedit.window import MainWindow
    window = MainWindow(root)
    def receive(new_paths):
        window.add_paths(new_paths)
        window.showNormal()
        window.raise_()
        window.activateWindow()
    instance.pathsReceived.connect(receive)
    window.show()
    if paths:
        QTimer.singleShot(0, lambda: window.add_paths(paths))
    logging.info("Started pid=%s executable=%s", os.getpid(), sys.executable)
    code = app.exec()
    instance.close()
    logging.info("Stopped pid=%s", os.getpid())
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.exception("Startup failed")
        ctypes.windll.user32.MessageBoxW(None, str(error), "合页启动失败", 0x10)
        raise SystemExit(1)
