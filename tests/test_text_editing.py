"""Text editing across native, raster, rotated and saved documents."""
from io import BytesIO
import json
import os
from pathlib import Path
import uuid

import pytest
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageStat
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QFileDialog

from pdfedit.engine import export_pdf, render_preview
from pdfedit.imaging import inspect_image
from pdfedit.models import Layout, Watermark, project_data
from pdfedit.pdf_source import render_pdf
from pdfedit.project_io import read_project
from pdfedit.text_editing import (recognize_page, new_block, edited_source_pdf,
    validate_text_state, has_text_output, render_edited)
from pdfedit.window import MainWindow
from pdfedit.style import apply_style
from test_pdf_input import source_pdf
from test_workflow import wait_until

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def app():
    application = QApplication.instance() or QApplication([])
    # The offscreen Qt platform does not enumerate Windows fallback fonts.
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyhbd.ttc')
    return application


@pytest.fixture
def folder():
    path = Path(os.environ['PDFEDIT_TEST_DIR']) / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


def recognize(path, index=0):
    page = inspect_image(str(path))[index][0]
    page.text_blocks, page.text_source_signature = recognize_page(page)
    page.text_recognized = True
    return page


def scanned(path, background='white'):
    image = Image.new('RGB', (1400, 800), background)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 62)
    draw.text((100, 120), '合页 PDF 文字编辑', font=font, fill='#202020')
    draw.text((100, 290), '合同编号 2026', font=font, fill='#202020')
    draw.text((100, 460), 'Total 1200', font=font, fill='#202020')
    image.save(path)
    return path


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('edit_rotation', [0, 90])
def test_native_text_replacement_crop_rotate_unit_and_preview(folder, rotation, edit_rotation):
    path = source_pdf(folder/'native.pdf', count=1, rotation=rotation, unit=2, cropped=True)
    page = recognize(path)
    assert len(page.text_blocks) == 1
    b = page.text_blocks[0]
    assert b['text'] == 'Native PDF page 1'
    assert b['font_size'] == pytest.approx(34, abs=.04)
    b.update(text='Edited Chinese 中文', font_family='Microsoft YaHei', font_size=26,
             color='#b02020', bold=True, italic=True, changed=True)
    page.rotation = edit_rotation
    page.zoom, page.offset_x, page.offset_y = .9, .03, -.05
    output = folder/'edited.pdf'
    layout = Layout(paper='A3')
    export_pdf([page], layout, Watermark(), str(output))
    with PdfReader(output) as reader:
        text = reader.pages[0].extract_text()
        assert 'Native PDF page' not in text and 'Edited Chinese 中文' in text
        assert b'110 145 re' in reader.pages[0].get_contents().get_data()
    actual = render_pdf(output, max_side=1100).convert('RGB')
    preview = render_preview(page, layout, Watermark(), 1, 1, 1100).convert('RGB').resize(actual.size)
    assert sum(ImageStat.Stat(ImageChops.difference(actual,preview)).mean)/3 < 2.5
    with PdfReader(path) as reader:
        assert 'Native PDF page 1' in reader.pages[0].extract_text()


def test_nested_form_removal_does_not_leave_old_glyphs(folder):
    path = folder/'nested.pdf'
    canvas = Canvas(str(path), pagesize=(400,300))
    canvas.setFont('Helvetica',18)
    canvas.drawString(20,260,'Keep this text')
    canvas.beginForm('nested',0,0,300,100)
    canvas.setFont('Helvetica',30)
    canvas.drawString(0,10,'REMOVE ME')
    canvas.endForm()
    canvas.saveState();canvas.translate(50,100);canvas.doForm('nested');canvas.restoreState()
    canvas.showPage();canvas.save()
    page = recognize(path)
    old = next(b for b in page.text_blocks if b['text']=='REMOVE ME')
    old['deleted'] = True
    data = edited_source_pdf(page)
    with PdfReader(BytesIO(data)) as reader:
        assert 'REMOVE ME' not in reader.pages[0].extract_text()
        assert 'Keep this text' in reader.pages[0].extract_text()
    rendered = render_edited(page,1200).convert('RGB')
    x,y,w,h = old['source_rect']
    crop = rendered.crop((int(x*1200),int(y*900),int((x+w)*1200),int((y+h)*900)))
    assert min(ImageStat.Stat(crop).mean)>250, 'Old nested text must actually disappear'


def test_reused_form_text_edits_one_visible_instance(folder):
    path = folder/'shared.pdf'
    c=Canvas(str(path),pagesize=(400,300))
    c.beginForm('shared',0,0,300,80)
    c.setFont('Helvetica',28);c.drawString(0,20,'Repeated label');c.endForm()
    for y in (70,190):
        c.saveState();c.translate(40,y);c.doForm('shared');c.restoreState()
    c.showPage();c.save()
    page=recognize(path)
    assert len(page.text_blocks)==2
    b=page.text_blocks[0]
    assert b['source'] in {'native','ocr'}
    b.update(text='Only first edited',font_family='Arial',changed=True)
    with PdfReader(BytesIO(edited_source_pdf(page))) as reader:
        text=reader.pages[0].extract_text()
        assert 'Only first edited' in text
        assert text.count('Repeated label')==1


def test_recognition_cancel_preserves_completed_pages(folder, app, monkeypatch):
    import threading
    release=threading.Event()
    entered=threading.Event()
    path=source_pdf(folder/'cancel.pdf',count=2)
    window=MainWindow(ROOT)
    window.add_paths([str(path)])
    wait_until(app,lambda:window.page_list.count()==2 and not window.importing)
    actual=recognize_page
    def slow(page,**kwargs):
        if page.frame==1:
            entered.set()
            release.wait(5)
        return actual(page,**kwargs)
    monkeypatch.setattr('pdfedit.window.recognize_page',slow)
    window.recognize_text('all')
    wait_until(app,entered.is_set)
    window.recognition_progress.reject()
    release.set()
    wait_until(app,lambda:not window.recognizing)
    assert window.pages()[0].text_recognized
    assert not window.pages()[1].text_recognized
    assert '已停止' in window.status.text()
    assert window.splitter.isEnabled()
    window.dirty=False;window.close()


@pytest.mark.parametrize('pdf', [False, True])
def test_offline_ocr_search_and_replace_scans(folder, monkeypatch, pdf):
    import pdfedit.ocr as ocr
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request', lambda *a,**k: pytest.fail('OCR accessed the network'))
    ocr._engine = None
    path = scanned(folder/'scan.png', '#faf5e7')
    if pdf:
        output = folder/'merged-scan.pdf'
        export_pdf([inspect_image(str(path))[0][0]], Layout(paper='original'), Watermark(), str(output))
        path = output
    page = recognize(path)
    assert len(page.text_blocks) >= 3
    assert all(b['source']=='ocr' for b in page.text_blocks)
    assert any('合页' in b['text'] for b in page.text_blocks)
    original = edited_source_pdf(page)
    with PdfReader(BytesIO(original)) as reader:
        assert '2026' in reader.pages[0].extract_text()
    b = next(b for b in page.text_blocks if '1200' in b['text'])
    assert b['background'].lower() == '#faf5e7'
    b.update(text='Total 9999',font_family='Arial',font_size=25,changed=True)
    b['anchor_y'] += .1
    result = edited_source_pdf(page)
    with PdfReader(BytesIO(result)) as reader:
        text = reader.pages[0].extract_text()
        assert '9999' in text and '1200' not in text and '2026' in text
    image = render_edited(page,1400).convert('RGB')
    x,y,w,h = b['source_rect']
    crop = image.crop((round(x*image.width),round(y*image.height),round((x+w)*image.width),round((y+h)*image.height)))
    assert min(ImageStat.Stat(crop).mean)>225


def test_native_multi_page_merged_pdf_and_added_text(folder):
    source = source_pdf(folder/'source.pdf',count=2)
    first, second = (p for p,_ in inspect_image(str(source)))
    merged = folder/'merged.pdf'
    export_pdf([second,first], Layout(paper='original'), Watermark(), str(merged))
    pages = [recognize(merged,index) for index in (0,1)]
    pages[0].text_blocks[0].update(text='Changed second',font_family='Arial',changed=True)
    pages[1].text_blocks.append(new_block('新添加说明',(.1,.8,.5,.1),20))
    output = folder/'result.pdf'
    export_pdf(pages,Layout(paper='original'),Watermark(),str(output))
    with PdfReader(output) as reader:
        assert len(reader.pages)==2
        assert 'Changed second' in reader.pages[0].extract_text()
        assert 'Native PDF page 2' not in reader.pages[0].extract_text()
        assert 'Native PDF page 1' in reader.pages[1].extract_text()
        assert '新添加说明' in reader.pages[1].extract_text()


def test_searchable_scan_reimport_uses_visible_ink_bounds(folder):
    path=scanned(folder/'paper.png','#faf5e7')
    first=recognize(path)
    original=next(b for b in first.text_blocks if '1200' in b['text'])
    searchable=folder/'searchable.pdf'
    searchable.write_bytes(edited_source_pdf(first))
    page=recognize(searchable)
    block=next(b for b in page.text_blocks if '1200' in b['text'])
    assert block['source']=='ocr'
    assert block['background']=='#faf5e7'
    with PdfReader(BytesIO(edited_source_pdf(page))) as reader:
        assert reader.pages[0].extract_text().count('1200')==1, 'Do not duplicate the old OCR layer'
    block.update(text='Total 9999',changed=True)
    block['anchor_y']+=.14
    data=edited_source_pdf(page)
    with PdfReader(BytesIO(data)) as reader:
        text=reader.pages[0].extract_text()
        assert '9999' in text and '1200' not in text
    image=render_edited(page,1400).convert('RGB')
    x,y,w,h=original['source_rect']
    crop=image.crop((round(x*image.width),round(y*image.height),round((x+w)*image.width),round((y+h)*image.height)))
    assert max(ImageStat.Stat(crop).stddev)<2, 'No old glyph edges may remain'


def test_saved_project_roundtrip_legacy_and_source_change(folder):
    path = source_pdf(folder/'source.pdf',count=1)
    page = recognize(path)
    page.text_blocks[0].update(text='Saved change',changed=True)
    data = project_data([page],Layout(paper='original'),Watermark())
    project = folder/'test.ipdf.json'
    project.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    loaded,layout,wm = read_project(project)
    assert loaded[0].text_blocks == page.text_blocks
    data['version']=1
    for key in ['text_blocks','text_recognized','text_source_signature']:
        data['pages'][0].pop(key)
    legacy = folder/'legacy.ipdf.json'
    legacy.write_text(json.dumps(data),encoding='utf-8')
    assert not read_project(legacy)[0][0].text_blocks
    source_pdf(path,count=2)
    with pytest.raises(ValueError,match='原文件'):
        read_project(project)


def test_invalid_text_and_font_fails_before_overwriting(folder):
    path = source_pdf(folder/'source.pdf',count=1)
    page = recognize(path)
    page.text_blocks[0].update(text='中文',font_family='Arial',changed=True)
    target = folder/'output.pdf'
    target.write_bytes(b'existing output')
    with pytest.raises(ValueError,match='不包含'):
        export_pdf([page],Layout(),Watermark(),str(target),overwrite=True)
    assert target.read_bytes()==b'existing output'
    page.text_blocks[0]['font_size']=float('nan')
    with pytest.raises(ValueError):
        validate_text_state(page)


def test_gui_recognize_edit_undo_drag_export_and_restore(folder, app, monkeypatch):
    apply_style(app)
    errors=[]
    monkeypatch.setattr('pdfedit.window.Messages.warning',lambda *a,**k:errors.append(a[1:]))
    path = source_pdf(folder/'native.pdf',count=2)
    window = MainWindow(ROOT)
    window.show()
    window.add_paths([str(path)])
    wait_until(app,lambda:window.page_list.count()==2 and not window.importing)
    window.tabs.setCurrentWidget(window.text_panel)
    window.recognize_text('all')
    wait_until(app,lambda:not window.recognizing)
    assert not errors
    assert all(p.text_recognized for p in window.pages())
    panel=window.text_panel
    wait_until(app,lambda:not window.preview_busy and not window.preview.pixmap.isNull())
    block_id,box = window.preview.text_boxes[0]
    QTest.mouseClick(window.preview,Qt.MouseButton.LeftButton,pos=window.preview.screen_box(box).center().toPoint())
    editor = window.preview.inline_editor
    assert editor.isVisible() and editor.toPlainText()=='Native PDF page 1'
    editor.selectAll()
    QTest.keyClicks(editor,'New title')
    QTest.keyClick(editor,Qt.Key.Key_Return)
    assert window.current_page().text_blocks[0]['text']=='New title'
    panel.undo()
    assert window.current_page().text_blocks[0]['text']=='Native PDF page 1'
    panel.redo()
    assert window.current_page().text_blocks[0]['text']=='New title'
    panel.size.setValue(24)
    panel.bold.setChecked(True)
    wait_until(app,lambda:not window.preview_busy)
    window.refresh_preview()
    wait_until(app,lambda:not window.preview_busy)
    app.processEvents()
    assert window.preview.editing_text and window.preview.text_boxes
    block_id,box = window.preview.text_boxes[0]
    center=window.preview.screen_box(box).center().toPoint()
    before=window.current_page().text_blocks[0]['anchor_x']
    QTest.mousePress(window.preview,Qt.MouseButton.LeftButton,pos=center)
    QTest.mouseRelease(window.preview,Qt.MouseButton.LeftButton,pos=center+QPoint(20,10))
    assert window.current_page().text_blocks[0]['anchor_x']>before
    project=folder/'saved.ipdf.json'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(project),''))
    window.save_project()
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(project),''))
    window.load_project()
    assert window.current_page().text_blocks[0]['text']=='New title'
    output=folder/'gui-output.pdf'
    monkeypatch.setattr('pdfedit.window.choose_export',lambda *a,**k:(str(output),False))
    window.export()
    wait_until(app,lambda:not window.exporting)
    assert not errors
    with PdfReader(output) as reader:
        assert 'New title' in reader.pages[0].extract_text()
        assert 'Native PDF page 1' not in reader.pages[0].extract_text()
    panel.blocks.setCurrentRow(0)
    panel.restore()
    assert not has_text_output(window.current_page())
    panel.delete_text()
    assert has_text_output(window.current_page())
    panel.undo()
    assert not has_text_output(window.current_page())
    panel.blocks.setCurrentRow(0)
    wait_until(app,lambda:not window.preview_busy)
    window.refresh_preview()
    wait_until(app,lambda:not window.preview_busy)
    app.processEvents()
    assert panel.horizontalScrollBar().maximum()==0
    window.grab().save(str(ROOT/'reports'/'text-editing-ui.png'))
    window.dirty=False
    window.close()
