"""Verify A3 physical size and five-percent scaling across save/restore/export."""
import json
import os
from pathlib import Path
import uuid

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from PySide6.QtWidgets import QApplication, QFileDialog
import pytest

from pdfedit.engine import export_pdf, render_preview
from pdfedit.imaging import inspect_image
from pdfedit.models import Layout, Watermark
from pdfedit.pdf_source import render_pdf
from pdfedit.window import MainWindow
from pdfedit.dialogs import Messages
from test_workflow import wait_until

ROOT = Path(__file__).resolve().parents[1]


def folder():
    path = Path(os.environ['PDFEDIT_TEST_DIR']) / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.mark.parametrize('orientation,expected_mm', [('portrait', (297, 420)), ('landscape', (420, 297))])
def test_a3_export_physical_size_and_preview(orientation, expected_mm):
    base = folder()
    source = base / 'source.png'
    Image.new('RGB', (250, 100), '#3267ad').save(source)
    page = inspect_image(str(source))[0][0]
    layout = Layout(paper='A3', orientation=orientation)
    output = base / 'a3.pdf'
    export_pdf([page], layout, Watermark(), str(output))
    reader = PdfReader(output)
    box = reader.pages[0].mediabox
    assert (float(box.width) * 25.4 / 72, float(box.height) * 25.4 / 72) == pytest.approx(expected_mm, abs=.001)
    reader.close()
    actual = render_pdf(output, max_side=1000).convert('RGB')
    preview = render_preview(page, layout, Watermark(), 1, 1, 1000).resize(actual.size)
    assert sum(ImageStat.Stat(ImageChops.difference(preview, actual)).mean) / 3 < 2


def test_gui_a3_five_percent_watermark_and_content_roundtrip(monkeypatch):
    base = folder()
    photo, stamp, document = base / 'photo.png', base / 'stamp.png', base / 'source.pdf'
    Image.new('RGB', (240, 240), 'blue').save(photo)
    Image.new('RGBA', (100, 100), 'red').save(stamp)
    canvas = Canvas(str(document), pagesize=(300, 400))
    canvas.drawString(30, 350, 'A3 native content')
    canvas.showPage()
    canvas.save()
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT)
    errors = []
    monkeypatch.setattr(Messages, 'warning', lambda *a, **k: errors.append(a[2]))
    try:
        window.add_paths([str(photo), str(document)])
        wait_until(app, lambda: not window.pending_paths and not window.importing)
        assert window.page_list.count() == 2
        window.paper.setCurrentIndex(window.paper.findData('A3'))
        window.orientation.setCurrentIndex(window.orientation.findData('portrait'))
        window.page_list.setCurrentRow(0)
        window.zoom.setValue(5)
        window.wm_kind.setCurrentIndex(window.wm_kind.findData('image'))
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(stamp), 'PNG'))
        window.choose_watermark()
        window.wm_scale.setValue(5)
        window.wm_opacity.setValue(100)
        window.wm_angle.setValue(0)
        window.wm_position.setCurrentIndex(window.wm_position.findData('bottom-right'))
        project = base / 'a3-5pct.ipdf.json'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(project), 'JSON'))
        window.save_project()
        saved = json.loads(project.read_text(encoding='utf-8'))
        assert saved['layout']['paper'] == 'A3'
        assert saved['watermark']['scale'] == saved['pages'][0]['zoom'] == .05
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(project), 'JSON'))
        window.load_project()
        assert not errors
        assert window.paper.currentData() == 'A3'
        assert window.wm_scale.value() == window.zoom.value() == 5
        output = base / 'a3-5pct.pdf'
        monkeypatch.setattr('pdfedit.window.choose_export', lambda *a, **k: (str(output), False))
        window.export()
        wait_until(app, lambda: not window.exporting)
        assert not errors and output.is_file()
        reader = PdfReader(output)
        assert len(reader.pages) == 2
        assert float(reader.pages[0].mediabox.width) * 25.4 / 72 == pytest.approx(297, abs=.001)
        assert 'A3 native content' in reader.pages[1].extract_text()
        reader.close()
        # Measure the actual red watermark and blue content in the rendered PDF.
        rendered = render_pdf(output, max_side=1200).convert('RGB')
        red, green, blue = rendered.split()
        red_box = ImageChops.subtract(red, blue).point(lambda v: 255 if v > 150 else 0).getbbox()
        blue_box = ImageChops.subtract(blue, red).point(lambda v: 255 if v > 150 else 0).getbbox()
        assert red_box and blue_box
        assert red_box[2] - red_box[0] == pytest.approx(rendered.width * .05, abs=2)
        assert blue_box[2] - blue_box[0] == pytest.approx(rendered.width * ((297 - 24) / 297) * .05, abs=2)
    finally:
        wait_until(app, lambda: not window.preview_busy and not window.importing and not window.exporting)
        window.timer.stop()
        window.dirty = False
        window.close()
