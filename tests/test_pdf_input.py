"""PDF input: native fidelity, mixed ordering, real GUI flow and failure safety."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import uuid

from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, FloatObject, RectangleObject
from reportlab.pdfgen.canvas import Canvas
from PySide6.QtWidgets import QApplication, QFileDialog
import pytest

from pdfedit.engine import export_pdf, render_preview, geometry, ExportCancelled
from pdfedit.imaging import EXTENSIONS, FILE_FILTER, IMAGE_FILTER, inspect_image, load_image
from pdfedit.models import Layout, Watermark
from pdfedit.pdf_source import render_pdf
from pdfedit.window import MainWindow
from pdfedit.dialogs import Messages
from test_workflow import wait_until

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def folder():
    target = Path(os.environ['PDFEDIT_TEST_DIR']) / uuid.uuid4().hex
    target.mkdir(parents=True)
    return target


@pytest.fixture(scope='module', autouse=True)
def application():
    return QApplication.instance() or QApplication([])


def source_pdf(path, count=2, rotation=0, unit=1, cropped=False, forms=False):
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400, 300))
    for number in range(count):
        canvas.setFillColorRGB(.92, .94, .96)
        canvas.rect(0, 0, 400, 300, fill=1, stroke=0)
        canvas.setFillColorRGB(.2, .4, .8)
        canvas.rect(70, 65, 110, 145, fill=1, stroke=0)
        canvas.setFillColorRGB(.8, .2, .15)
        canvas.rect(240, 180, 80, 45, fill=1, stroke=0)
        canvas.setFillColorRGB(0, 0, 0)
        canvas.setFont('Helvetica', 17)
        canvas.drawString(80, 240, f'Native PDF page {number + 1}')
        if forms:
            canvas.acroForm.textfield(name=f'name{number}', value='Visible field value',
                                      x=190, y=100, width=130, height=24, fontSize=12)
            canvas.acroForm.checkbox(name=f'check{number}', x=200, y=150, checked=True)
        canvas.showPage()
    canvas.save()
    stream.seek(0)
    reader = PdfReader(stream)
    writer = PdfWriter()
    # Append preserves the form field tree used by the input preview.
    writer.append(reader)
    for page in writer.pages:
        page[NameObject('/Rotate')] = NumberObject(rotation)
        page[NameObject('/UserUnit')] = FloatObject(unit)
        if cropped:
            page.cropbox = RectangleObject((50, 40, 350, 260))
    writer.write(path)
    writer.close()
    reader.close()
    return path


def test_pdf_filters_and_multipage_import(folder):
    path = source_pdf(folder / '中文 合同.PDF', count=3)
    imported = inspect_image(str(path))
    assert '.pdf' in EXTENSIONS and '*.pdf' in FILE_FILTER and '*.pdf' not in IMAGE_FILTER
    assert [page.frame for page, _ in imported] == [0, 1, 2]
    assert imported[0][0].label == '中文 合同.PDF · 第 1 页'
    assert all(page.is_pdf and (page.width, page.height) == (400, 300) for page, _ in imported)
    assert all(thumb.startswith(b'\x89PNG') for _, thumb in imported)


@pytest.mark.parametrize('source_rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('edit_rotation', [0, 90, 180, 270])
def test_pdf_crop_rotation_placement_preview_native_export(folder, source_rotation, edit_rotation):
    path = source_pdf(folder / 'cropped.pdf', count=1, cropped=True, rotation=source_rotation, unit=2)
    page = inspect_image(str(path))[0][0]
    expected = (440, 600) if source_rotation % 180 else (600, 440)
    assert (page.width, page.height) == expected
    assert geometry(page, Layout(paper='original'))[:2] == expected
    page.rotation, page.zoom, page.offset_x, page.offset_y = edit_rotation, .8, .13, -.08
    layout = Layout('A4', 'portrait', 14, 'compact')
    watermark = Watermark(kind='text', text='测试水印', opacity=.35, angle=25)
    output = folder / 'output.pdf'
    export_pdf([page], layout, watermark, str(output))
    reader = PdfReader(output)
    assert reader.pdf_header >= '%PDF-1.7'
    assert 'Native PDF page 1' in reader.pages[0].extract_text()
    rendered = render_pdf(output, max_side=1000).convert('RGB')
    preview = render_preview(page, layout, watermark, 1, 1, 1000).resize(rendered.size)
    error = sum(ImageStat.Stat(ImageChops.difference(preview, rendered)).mean) / 3
    assert error < 3, error
    # The blue rectangle remains native vector drawing, even in compact mode.
    assert b'110 145 re' in reader.pages[0].get_contents().get_data()
    reader.close()


def test_mixed_pages_order_and_image_watermark(folder):
    first = source_pdf(folder / 'first.pdf')
    second = source_pdf(folder / 'second.pdf', count=1)
    png = folder / 'photo.png'
    Image.new('RGB', (300, 200), 'white').save(png)
    mark = folder / 'mark.png'
    Image.new('RGBA', (50, 50), 'red').save(mark)
    pages = [p for p, _ in inspect_image(str(first))]
    pages = [pages[1], inspect_image(str(png))[0][0], inspect_image(str(second))[0][0], pages[0]]
    watermark = Watermark(kind='image', image_path=str(mark), opacity=1, angle=0, pages='2,4')
    output = folder / 'mixed.pdf'
    export_pdf(pages, Layout(paper='original'), watermark, str(output))
    reader = PdfReader(output)
    assert len(reader.pages) == 4
    assert ['Native PDF page 2' in reader.pages[0].extract_text(),
            not reader.pages[1].extract_text(),
            'Native PDF page 1' in reader.pages[2].extract_text(),
            'Native PDF page 1' in reader.pages[3].extract_text()] == [True] * 4
    for index in (1, 3):
        image = render_pdf(output, index, 600)
        pixel = image.getpixel((image.width // 2, image.height // 2))
        assert pixel[0] > 250 and pixel[1] < 5
    reader.close()


@pytest.mark.parametrize('rotation', [0, 90])
def test_visible_forms_flatten_without_losing_native_text(folder, rotation):
    path = source_pdf(folder / 'form.pdf', count=1, forms=True, rotation=rotation, cropped=True)
    page = inspect_image(str(path))[0][0]
    assert '固定内容' in page.note
    page.rotation, page.zoom = 90, .8
    output = folder / 'form-merged.pdf'
    layout = Layout(paper='original')
    export_pdf([page], layout, Watermark(), str(output))
    reader = PdfReader(output)
    text = reader.pages[0].extract_text()
    assert 'Native PDF page 1' in text and 'Visible field value' in text
    assert not reader.pages[0].get('/Annots')
    rendered = render_pdf(output, max_side=1000).convert('RGB')
    preview = render_preview(page, layout, Watermark(), 1, 1, 1000).resize(rendered.size)
    error = sum(ImageStat.Stat(ImageChops.difference(preview, rendered)).mean) / 3
    assert error < 3, error
    reader.close()


def test_encrypted_broken_and_empty_pdf_errors(folder):
    source = source_pdf(folder / 'plain.pdf', count=1)
    reader = PdfReader(source)
    for name, password in [('locked', 'secret'), ('empty-password', '')]:
        writer = PdfWriter()
        writer.append(reader)
        writer.encrypt(password, owner_password='owner')
        writer.write(folder / f'{name}.pdf')
        writer.close()
    with pytest.raises(ValueError, match='密码'):
        inspect_image(str(folder / 'locked.pdf'))
    assert len(inspect_image(str(folder / 'empty-password.pdf'))) == 1
    broken = folder / 'broken.pdf'
    broken.write_bytes(b'not a pdf')
    with pytest.raises(ValueError, match='损坏'):
        inspect_image(str(broken))
    empty = folder / 'empty.pdf'
    writer = PdfWriter()
    writer.write(empty)
    writer.close()
    with pytest.raises(ValueError, match='没有'):
        inspect_image(str(empty))
    reader.close()


def test_pdf_cancel_source_protection_and_stale_page(folder):
    source = source_pdf(folder / 'source.pdf')
    original = source.read_bytes()
    pages = [p for p, _ in inspect_image(str(source))]
    with pytest.raises(ValueError, match='不能覆盖'):
        export_pdf(pages, Layout(), Watermark(), str(source), overwrite=True)
    output = folder / 'previous.pdf'
    output.write_bytes(original)
    with pytest.raises(ExportCancelled):
        export_pdf(pages, Layout(), Watermark(), str(output), cancelled=lambda: True, overwrite=True)
    pages[0].frame = 7
    with pytest.raises(ValueError, match='页数已改变'):
        export_pdf(pages, Layout(), Watermark(), str(output), overwrite=True)
    assert source.read_bytes() == output.read_bytes() == original


def test_pdf_render_serialized_across_workers(folder):
    source = source_pdf(folder / 'parallel.pdf')
    with ThreadPoolExecutor(max_workers=4) as pool:
        images = list(pool.map(lambda i: load_image(str(source), i % 2, 200), range(12)))
    assert all(image.size == (200, 150) for image in images)


def test_gui_pdf_folder_import_reorder_save_restore_export(folder, application, monkeypatch):
    source_pdf(folder / '01-contract.pdf', count=2)
    Image.new('RGB', (160, 240), 'white').save(folder / '02-photo.png')
    window = MainWindow(ROOT)
    failures = []
    monkeypatch.setattr(Messages, 'warning', lambda *a, **kw: failures.append(a[2]))
    try:
        window.add_paths([str(folder)])
        wait_until(application, lambda: not window.pending_paths and not window.importing)
        assert window.page_list.count() == 3
        # Re-add only the removed second page, without duplicating existing pages.
        window.page_list.setCurrentRow(1)
        window.remove_pages()
        window.add_paths([str(folder / '01-contract.pdf')])
        wait_until(application, lambda: not window.pending_paths and not window.importing)
        assert [p.frame if p.is_pdf else -1 for p in window.pages()] == [0, -1, 1]
        window.page_list.setCurrentRow(2)
        window.move_pages(-1)
        window.rotate(90)
        window.zoom.setValue(75)
        window.drag_image(.08, -.04)
        window.wm_kind.setCurrentIndex(window.wm_kind.findData('text'))
        window.wm_text.setText('PDF 混合合并')
        project = folder / '编辑方案.ipdf.json'
        monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **kw: (str(project), 'JSON'))
        window.save_project()
        monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **kw: (str(project), 'JSON'))
        window.load_project()
        assert window.pages()[1].is_pdf and window.pages()[1].rotation == 90
        assert window.pages()[1].zoom == .75
        output = folder / 'GUI-mixed.pdf'
        monkeypatch.setattr('pdfedit.window.choose_export', lambda *a, **k: (str(output), False))
        window.export()
        wait_until(application, lambda: not window.exporting)
        assert not failures
        reader = PdfReader(output)
        assert len(reader.pages) == 3
        assert 'Native PDF page 2' in reader.pages[1].extract_text()
        reader.close()
    finally:
        wait_until(application, lambda: not window.importing and not window.preview_busy and not window.exporting)
        window.timer.stop()
        window.dirty = False
        window.close()
