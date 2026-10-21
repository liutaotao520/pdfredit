"""Capture the actual application with the repository's public demonstration files."""
from pathlib import Path
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from pdfedit.style import apply_style
from pdfedit.window import MainWindow


def main():
    output = ROOT / "docs" / "images"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    # The offscreen Qt plugin does not enumerate Windows fonts automatically.
    font_dir = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc"):
        if (font_dir / name).is_file():
            QFontDatabase.addApplicationFont(str(font_dir / name))
    apply_style(app)
    window = MainWindow(ROOT)
    window.resize(1440, 900)
    window.show()

    def settle():
        start = time.monotonic()
        while time.monotonic() - start < 20:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 40)
            if time.monotonic() - start > .5 and not (
                window.importing or window.preview_busy or window.pending_paths or window.timer.isActive()
            ):
                return
            time.sleep(.02)
        raise RuntimeError("Preview timed out")

    try:
        window.add_paths([str(ROOT / "examples" / name) for name in
                          ("01-sample.png", "02-sample.png", "sample.pdf")])
        settle()
        window.paper.setCurrentIndex(window.paper.findData("A3"))
        settle()
        assert window.grab().save(str(output / "workspace.png"))
        window.tabs.setCurrentIndex(1)
        window.wm_kind.setCurrentIndex(window.wm_kind.findData("image"))
        window.watermark.image_path = str(ROOT / "examples/watermark.png")
        window.wm_file_label.setText("watermark.png")
        window.wm_scale.setValue(5)
        window.wm_tiled.setChecked(True)
        window.wm_density.setValue(8)
        window.mark_changed()
        settle()
        window.tabs.widget(1).ensureWidgetVisible(window.wm_density)
        assert window.grab().save(str(output / "watermark.png"))
    finally:
        window.timer.stop()
        window.dirty = False
        window.close()
    print("Saved docs/images/workspace.png and watermark.png")


if __name__ == "__main__":
    main()
