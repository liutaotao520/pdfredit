"""Verify that denser tiling reaches the PDF and survives editor round trips."""
from dataclasses import replace
import json
import os
from pathlib import Path
import uuid

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader
from PySide6.QtWidgets import QApplication, QFileDialog
import pytest

from pdfedit.engine import export_pdf, render_preview, stamp_positions
from pdfedit.imaging import inspect_image
from pdfedit.models import Layout, Watermark
from pdfedit.pdf_source import render_pdf
from pdfedit.window import MainWindow
from pdfedit.dialogs import Messages
from test_workflow import wait_until

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def samples():
    folder = Path(os.environ['PDFEDIT_TEST_DIR']) / uuid.uuid4().hex
    folder.mkdir(parents=True)
    photo, mark = folder / 'page.png', folder / 'mark.png'
    Image.new('RGB', (200, 300), 'white').save(photo)
    Image.new('RGBA', (100, 65), 'red').save(mark)
    return folder, photo, mark


def placements(path):
    reader = PdfReader(path)
    # The plain image page contains one image invocation plus its watermark copies.
    count = sum(operator == b'Do' for _, operator in reader.pages[0].get_contents().operations) - 1
    reader.close()
    return count


@pytest.mark.parametrize('angle,orientation', [(0, 'portrait'), (30, 'landscape'), (90, 'portrait')])
def test_density_changes_visible_coverage_and_exported_copy_count(samples, angle, orientation):
    folder, photo, mark = samples
    page = inspect_image(str(photo))[0][0]
    layout = Layout(paper='A3', orientation=orientation)
    counts, coverage = [], []
    for level in (1, 3, 10):
        wm = Watermark(kind='image', image_path=str(mark), scale=.05, angle=angle,
                       opacity=.6, tiled=True, density=level)
        path = folder / f'density-{level}.pdf'
        export_pdf([page], layout, wm, str(path))
        counts.append(placements(path))
        actual = render_pdf(path, max_side=1200).convert('RGB')
        preview = render_preview(page, layout, wm, 1, 1, 1200).resize(actual.size)
        difference = sum(ImageStat.Stat(ImageChops.difference(actual, preview)).mean) / 3
        # Qt/Pillow previews and PDFium round stamp edges differently. Permit
        # less than 1% mean channel error while checking copy counts/coverage.
        assert difference < 255 * .01, (level, angle, difference)
        red, green, _ = actual.split()
        coverage.append(ImageChops.subtract(red, green).point(lambda v: 255 if v > 50 else 0).histogram()[255])
    assert counts[0] < counts[1] < counts[2]
    assert coverage[0] < coverage[1] < coverage[2]
    assert coverage[2] > coverage[1] * 6


def test_density_does_not_resize_or_move_single_watermark(samples):
    _, photo, mark = samples
    page = inspect_image(str(photo))[0][0]
    wm = Watermark(kind='image', image_path=str(mark), scale=.05, tiled=False, density=1)
    first = render_preview(page, Layout(), wm, 1, 1)
    second = render_preview(page, Layout(), replace(wm, density=10), 1, 1)
    assert ImageChops.difference(first, second).getbbox() is None


@pytest.mark.parametrize('invalid', [0, 11, 1.5, float('nan')])
def test_invalid_density_cannot_enter_tiling_loop(invalid):
    with pytest.raises(ValueError, match='密度'):
        list(stamp_positions(Watermark(tiled=True, density=invalid), 600, 840, 30, 20))


def test_density_ui_save_restore_old_projects_and_validation(samples, monkeypatch):
    folder, photo, mark = samples
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ROOT)
    errors = []
    monkeypatch.setattr(Messages, 'warning', lambda *a, **k: errors.append(a[2]))
    monkeypatch.setattr(Messages, 'confirm', lambda *a, **k: True)
    try:
        window.add_paths([str(photo)])
        wait_until(app, lambda: not window.importing and not window.pending_paths)
        window.wm_kind.setCurrentIndex(window.wm_kind.findData('image'))
        assert window.wm_density_group.isHidden() and not window.wm_density.isEnabled()
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(mark), 'PNG'))
        window.choose_watermark()
        window.wm_scale.setValue(5)
        window.wm_tiled.setChecked(True)
        assert not window.wm_density_group.isHidden() and window.wm_density.isEnabled()
        window.wm_density.setValue(8)
        assert window.watermark.density == 8
        saved = folder / 'density.ipdf.json'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(saved), 'JSON'))
        window.save_project()
        data = json.loads(saved.read_text(encoding='utf-8'))
        assert data['watermark']['density'] == 8
        window.wm_density.setValue(2)
        window.wm_tiled.setChecked(False)
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(saved), 'JSON'))
        window.load_project()
        assert not errors
        assert window.wm_density.value() == 8 and window.wm_tiled.isChecked()
        assert window.watermark.density == 8 and window.watermark.scale == .05
        output = folder / 'restored-density.pdf'
        monkeypatch.setattr('pdfedit.window.choose_export', lambda *a, **k: (str(output), False))
        window.export()
        wait_until(app, lambda: not window.exporting)
        assert not errors and placements(output) > 80

        # Files saved before 1.3.2 have no density field and retain the old layout.
        data['watermark'].pop('density')
        saved.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        window.load_project()
        assert not errors and window.wm_density.value() == window.watermark.density == 3
        data['watermark']['density'] = 11
        saved.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        window.load_project()
        assert len(errors) == 1 and '密度' in errors[0]
        assert window.watermark.density == 3
    finally:
        wait_until(app, lambda: not window.preview_busy and not window.importing and not window.exporting)
        window.timer.stop()
        window.dirty = False
        window.close()
