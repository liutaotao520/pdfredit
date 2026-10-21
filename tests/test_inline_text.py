"""Direct page editing, including draft lifetime and real Qt input events."""
from copy import deepcopy
import json

import pytest
from pypdf import PdfReader
from PySide6.QtCore import Qt, QPoint, QMimeData, QRectF
from PySide6.QtGui import QInputMethodEvent, QTextCursor, QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QPlainTextEdit

from pdfedit.engine import export_pdf
from pdfedit.inline_text import MAX_TEXT_LENGTH
from pdfedit.style import apply_style
from pdfedit.text_editing import new_block
from pdfedit.window import MainWindow
from test_pdf_input import source_pdf
from test_text_editing import app, folder, ROOT, scanned
from test_workflow import wait_until


def ready(window, app):
    wait_until(app, lambda: not window.preview_busy and not window.timer.isActive()
               and not window.preview.pixmap.isNull())


@pytest.fixture
def window(folder, app, monkeypatch):
    errors = []
    monkeypatch.setattr('pdfedit.window.Messages.warning', lambda *a, **k: errors.append(a[1:]))
    apply_style(app)
    window = MainWindow(folder)
    window.show()
    window.add_paths([str(source_pdf(folder/'native.pdf', count=2))])
    wait_until(app, lambda: window.page_list.count() == 2 and not window.importing)
    window.tabs.setCurrentWidget(window.text_panel)
    window.recognize_text('all')
    wait_until(app, lambda: not window.recognizing)
    ready(window, app)
    yield window
    window.preview.finish_edit(False)
    window.dirty = False
    window.close()
    assert not errors


def click_block(window, index=0):
    # QTest delivers events directly; unlike a physical click, it does not
    # activate a top-level window after the modal recognition dialog closes.
    window.activateWindow()
    QApplication.processEvents()
    block_id, box = window.preview.text_boxes[index]
    QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton,
                     pos=window.preview.screen_box(box).center().toPoint())
    editor = window.preview.inline_editor
    assert editor.isVisible() and window.preview.inline_block_id == block_id
    assert editor.parent() is window.preview
    return editor


def type_text(editor, text):
    editor.selectAll()
    QTest.keyClicks(editor, text)


def test_click_commit_cancel_and_one_step_history(window, app):
    assert not window.text_panel.findChildren(QPlainTextEdit)
    page = window.current_page()
    original = deepcopy(page.text_blocks)
    editor = click_block(window)
    assert editor.hasFocus()
    type_text(editor, 'First change')
    assert page.text_blocks == original  # The on-page draft is not exported prematurely.
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert not editor.isVisible() and page.text_blocks == original
    assert not window.text_panel.history.get(page.uid)
    editor = click_block(window)
    type_text(editor, 'Final change')
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert not editor.isVisible() and page.text_blocks[0]['text'] == 'Final change'
    window.text_panel.undo()
    assert page.text_blocks == original
    window.text_panel.redo()
    assert page.text_blocks[0]['text'] == 'Final change'


def test_draft_survives_async_render_resize_and_text_selection(window, app):
    editor = click_block(window)
    type_text(editor, 'Keep my selection')
    cursor = editor.textCursor()
    cursor.setPosition(5)
    cursor.setPosition(7, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    anchor = window.current_page().text_blocks[0]['anchor_x']
    window.refresh_preview()
    wait_until(app, lambda: not window.preview_busy)
    window.resize(1440, 900)
    app.processEvents()
    assert editor.toPlainText() == 'Keep my selection'
    assert editor.textCursor().selectedText() == 'my'
    assert window.preview.rect().contains(editor.geometry())
    # Dragging inside the text editor selects text, not the PDF object.
    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    QTest.mouseMove(editor.viewport(), QPoint(70, 8))
    QTest.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(70, 8))
    assert window.current_page().text_blocks[0]['anchor_x'] == anchor
    assert editor.isVisible()


def test_multiline_paste_local_undo_and_chinese_input_method(window, app):
    editor = click_block(window)
    type_text(editor, 'Line one')
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(editor, 'Line two')
    assert editor.toPlainText() == 'Line one\nLine two'
    assert editor.isVisible()
    QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert 'Line two' not in editor.toPlainText()
    QTest.keyClick(editor, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert 'Line two' in editor.toPlainText()
    editor.selectAll()
    mime = QMimeData()
    mime.setText('中文校对\n第二行')
    mime.setHtml('<b>not the pasted text</b>')
    editor.insertFromMimeData(mime)
    assert editor.toPlainText() == '中文校对\n第二行'
    before = editor.toPlainText()
    preedit = QInputMethodEvent('输入', [])
    QApplication.sendEvent(editor, preedit)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.isVisible() and editor.toPlainText() == before
    commit = QInputMethodEvent()
    commit.setCommitString('完成')
    QApplication.sendEvent(editor, commit)
    assert editor.toPlainText().endswith('完成')
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert window.current_page().text_blocks[0]['text'].endswith('完成')


def test_blank_click_styles_and_move_handle_apply_pending_text(window, app):
    editor = click_block(window)
    type_text(editor, 'Click away')
    QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert not editor.isVisible()
    assert window.current_page().text_blocks[0]['text'] == 'Click away'
    editor = click_block(window)
    type_text(editor, 'Set font next')
    window.text_panel.size.setValue(29)
    b = window.current_page().text_blocks[0]
    assert b['text'] == 'Set font next' and b['font_size'] == 29
    assert not editor.isVisible()
    ready(window, app)
    editor = click_block(window)
    type_text(editor, 'Move this draft')
    anchor = (b['anchor_x'], b['anchor_y'])
    handle = window.preview.move_handle
    assert handle.isVisible()
    center = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=center+QPoint(25, 15))
    assert b['text'] == 'Move this draft'
    assert (b['anchor_x'], b['anchor_y']) != anchor


def test_flip_page_tab_and_other_block_never_lose_or_misroute_draft(window, app):
    first, second = window.pages()
    editor = click_block(window)
    type_text(editor, 'Only first page')
    window.navigate_page(1)  # Programmatic navigation has no focus-out event to rely on.
    assert first.text_blocks[0]['text'] == 'Only first page'
    assert second.text_blocks[0]['text'] == 'Native PDF page 2'
    assert not editor.isVisible()
    assert window.preview.pixmap.isNull()  # Never edit new hit targets on the old page image.
    ready(window, app)
    editor = click_block(window)
    type_text(editor, 'Only second page')
    window.tabs.setCurrentIndex(0)
    assert second.text_blocks[0]['text'] == 'Only second page'
    assert not editor.isVisible()
    window.tabs.setCurrentWidget(window.text_panel)
    second.text_blocks.append(new_block('Another block', (.2,.6,.3,.07), 18))
    window.text_panel.refresh()
    window.mark_changed()
    ready(window, app)
    editor = click_block(window, 0)
    type_text(editor, 'Separate first block')
    editor2 = click_block(window, 1)
    assert second.text_blocks[0]['text'] == 'Separate first block'
    assert editor2.toPlainText() == 'Another block'


def test_save_export_and_close_commit_even_with_editor_focused(window, app, folder, monkeypatch):
    editor = click_block(window)
    type_text(editor, 'Saved from page')
    project = folder/'draft.ipdf.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(project), ''))
    QTest.keyClick(editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert json.loads(project.read_text(encoding='utf-8'))['pages'][0]['text_blocks'][0]['text'] == 'Saved from page'
    ready(window, app)
    editor = click_block(window)
    type_text(editor, 'Exported from page')
    output = folder/'draft-output.pdf'
    monkeypatch.setattr('pdfedit.window.choose_export', lambda *a, **k: (str(output), False))
    window.export()
    wait_until(app, lambda: not window.exporting)
    with PdfReader(output) as reader:
        assert 'Exported from page' in reader.pages[0].extract_text()
        assert 'Native PDF page 1' not in reader.pages[0].extract_text()
    ready(window, app)
    editor = click_block(window)
    type_text(editor, 'Keep when canceling exit')
    calls = []
    monkeypatch.setattr('pdfedit.window.Messages.confirm', lambda *a, **k: calls.append(a) or False)
    window.close()
    assert calls and window.isVisible() and window.dirty
    assert window.current_page().text_blocks[0]['text'] == 'Keep when canceling exit'


def test_add_delete_restore_and_undo_with_active_editor(window, app):
    panel = window.text_panel
    panel.add_text()
    editor = window.preview.inline_editor
    assert editor.isVisible() and editor.textCursor().selectedText() == '新文字'
    QTest.keyClicks(editor, 'Added on page')
    panel.undo()  # Flush the draft then undo that single content edit.
    assert not editor.isVisible()
    assert panel.current_block()['text'] == '新文字'
    panel.redo()
    assert panel.current_block()['text'] == 'Added on page'
    ready(window, app)
    window.edit_text_inline(panel.selected_id)
    type_text(editor, 'Deleted draft')
    panel.delete_text()
    assert panel.current_block()['deleted'] and not editor.isVisible()
    panel.undo()
    assert panel.current_block()['text'] == 'Deleted draft'
    assert not panel.current_block()['deleted']
    panel.restore()
    assert len(window.current_page().text_blocks) == 1


@pytest.mark.parametrize('angle', [0, 90, 180, 270])
def test_rotated_and_scaled_page_inline_placement_and_export(window, app, folder, angle):
    page = window.current_page()
    page.rotation, page.zoom, page.offset_x, page.offset_y = angle, .8, .06, -.03
    window.mark_changed()
    ready(window, app)
    editor = click_block(window)
    assert QRectF(editor.geometry()).intersects(window.preview.screen_box(window.preview.text_boxes[0][1]))
    assert window.preview.rect().contains(editor.geometry())
    type_text(editor, 'Rotated edit')
    QTest.keyClick(editor, Qt.Key.Key_Return)
    output = folder/f'rotate-{angle}.pdf'
    export_pdf([page], window.layout_options, window.watermark, str(output))
    with PdfReader(output) as reader:
        assert 'Rotated edit' in reader.pages[0].extract_text()
        assert 'Native PDF page 1' not in reader.pages[0].extract_text()


def test_popup_menu_and_input_length_do_not_close_or_truncate_draft(window, app):
    editor = click_block(window)
    before = editor.toPlainText()
    QApplication.sendEvent(editor, QFocusEvent(QFocusEvent.Type.FocusOut, Qt.FocusReason.PopupFocusReason))
    assert editor.isVisible()
    rejected = []
    editor.limitReached.connect(lambda: rejected.append(True))
    mime = QMimeData()
    mime.setText('x'*(MAX_TEXT_LENGTH+1))
    editor.insertFromMimeData(mime)
    assert rejected and editor.toPlainText() == before
    # Long unbroken text remains scrollable rather than reflowing into new PDF lines.
    editor.selectAll()
    mime.setText('A'*2000)
    editor.insertFromMimeData(mime)
    app.processEvents()
    assert window.preview.rect().contains(editor.geometry())
    assert editor.horizontalScrollBar().maximum() > 0
    assert '\n' not in editor.toPlainText()
    editor.selectAll()
    mime.setText('A'*MAX_TEXT_LENGTH)
    editor.insertFromMimeData(mime)
    QTest.keyClicks(editor, 'B')
    assert len(editor.toPlainText()) == MAX_TEXT_LENGTH
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert len(editor.toPlainText()) == MAX_TEXT_LENGTH-1
    QTest.keyClicks(editor, 'B')
    assert editor.toPlainText().endswith('B')


def test_scanned_pdf_chinese_on_page_roundtrip(app, folder, monkeypatch):
    from pdfedit.imaging import inspect_image
    from pdfedit.models import Layout, Watermark
    image = scanned(folder/'scan.png')
    source = folder/'scan.pdf'
    export_pdf([inspect_image(str(image))[0][0]], Layout(paper='original'), Watermark(), str(source))
    window = MainWindow(folder)
    window.show()
    window.add_paths([str(source)])
    wait_until(app, lambda: window.page_list.count() == 1 and not window.importing)
    window.open_text_editor()
    wait_until(app, lambda: not window.recognizing, timeout=60)
    ready(window, app)
    editor = click_block(window)
    editor.selectAll()
    mime = QMimeData()
    mime.setText('合页 · 页面内直接修改')
    editor.insertFromMimeData(mime)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    ready(window, app)
    output = folder/'scan-edited.pdf'
    export_pdf(window.pages(), window.layout_options, window.watermark, str(output))
    with PdfReader(output) as reader:
        assert '页面内直接修改' in reader.pages[0].extract_text()
    # Capture the actual editor with a Chinese draft for visual inspection.
    editor = click_block(window)
    window.grab().save(str(ROOT/'reports'/'inline-text-editing-ui.png'))
    window.preview.finish_edit(False)
    window.dirty = False
    window.close()
