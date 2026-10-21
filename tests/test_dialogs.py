"""Exercise real themed modal actions, export decisions and cancellation."""
import os
import threading
from pathlib import Path
import uuid

from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
import pytest

from pdfedit.dialogs import ExportDialog, ExportProgressDialog, MessageDialog, Messages
from pdfedit.engine import export_pdf
from pdfedit.imaging import inspect_image
from pdfedit.models import Layout, Watermark
from pdfedit.style import apply_style
from pdfedit.window import MainWindow
from test_workflow import wait_until


@pytest.fixture
def editor():
    folder = Path(os.environ['PDFEDIT_TEST_DIR']) / uuid.uuid4().hex
    folder.mkdir(parents=True)
    source = folder / 'source.png'
    Image.new('RGB', (120, 180), 'white').save(source)
    app = QApplication.instance() or QApplication([])
    apply_style(app)
    window = MainWindow(folder)
    window.show()
    window.add_paths([str(source)])
    wait_until(app, lambda: not window.importing and not window.pending_paths)
    try:
        yield app, window, folder, source
    finally:
        wait_until(app, lambda: not window.importing and not window.preview_busy and not window.exporting)
        window.timer.stop()
        window.dirty = False
        window.close()


def during_modal(trigger, action):
    errors = []
    def drive():
        dialog = QApplication.activeModalWidget()
        try:
            assert dialog is not None
            action(dialog)
        except BaseException as error:
            errors.append(error)
            if dialog:
                dialog.reject()
    QTimer.singleShot(0, drive)
    result = trigger()
    if errors:
        raise errors[0]
    return result


@pytest.mark.parametrize('action', ['escape', 'return', 'close', 'confirm'])
def test_exit_confirmation_keeps_edits_unless_explicitly_confirmed(editor, action):
    _, window, _, _ = editor
    assert window.dirty
    def interact(dialog):
        assert isinstance(dialog, MessageDialog)
        assert dialog.windowTitle() == '退出合页？'
        assert dialog.confirm_button.text() == '退出合页'
        if action == 'escape':
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        elif action == 'return':
            QTest.keyClick(dialog, Qt.Key.Key_Return)
        elif action == 'close':
            dialog.close_button.click()
        else:
            dialog.confirm_button.click()
    closed = during_modal(window.close, interact)
    assert bool(closed) == (action == 'confirm')
    assert window.isVisible() == (action != 'confirm')
    assert window.page_list.count() == 1


def test_export_escape_leaves_editor_and_files_intact(editor):
    _, window, folder, _ = editor
    def interact(dialog):
        assert isinstance(dialog, ExportDialog)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    during_modal(window.export, interact)
    assert not window.exporting and window.dirty and window.output_path is None
    assert not list(folder.rglob('*.pdf'))


def test_export_validation_and_overwrite_require_explicit_action(editor):
    app, window, folder, _ = editor
    target = folder / 'existing.pdf'
    target.write_bytes(b'original data')
    dialog = ExportDialog(window, folder, 1, Layout(), Watermark())
    dialog.show()
    dialog.name_edit.setText('../invalid.pdf')
    dialog.export_button.click()
    assert dialog.target is None and dialog.error_label.isVisible()
    dialog.name_edit.setText('existing.pdf')
    dialog.folder_edit.setText(str(folder / 'missing'))
    dialog.export_button.click()
    assert dialog.target is None and '文件夹' in dialog.error_label.text()
    dialog.folder_edit.setText(str(folder))
    during_modal(dialog.export_button.click, lambda prompt: prompt.cancel_button.click())
    assert dialog.isVisible() and dialog.target is None
    assert target.read_bytes() == b'original data'
    during_modal(dialog.export_button.click, lambda prompt: prompt.confirm_button.click())
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.target == str(target) and dialog.overwrite
    assert target.read_bytes() == b'original data'
    app.processEvents()


def test_new_export_does_not_overwrite_a_file_created_after_confirmation(editor):
    _, window, folder, source = editor
    dialog = ExportDialog(window, folder, 1, Layout(), Watermark())
    dialog.name_edit.setText('new-export')
    dialog.accept()
    assert dialog.target.endswith('new-export.pdf') and not dialog.overwrite
    target = Path(dialog.target)
    target.write_bytes(b'competing writer')
    page = inspect_image(str(source))[0][0]
    with pytest.raises(FileExistsError):
        export_pdf([page], Layout(), Watermark(), dialog.target, overwrite=dialog.overwrite)
    assert target.read_bytes() == b'competing writer'


def test_real_export_dialog_starts_worker_and_writes_pdf(editor):
    app, window, folder, _ = editor
    def interact(dialog):
        assert isinstance(dialog, ExportDialog)
        dialog.folder_edit.setText(str(folder))
        dialog.name_edit.setText('真实弹窗导出')
        dialog.export_button.click()
    during_modal(window.export, interact)
    wait_until(app, lambda: not window.exporting)
    target = folder / '真实弹窗导出.pdf'
    reader = PdfReader(target)
    assert len(reader.pages) == 1
    reader.close()
    assert window.output_path == str(target)
    assert window.splitter.isEnabled() and window.export_button.isEnabled()


@pytest.mark.parametrize('cancel', [False, True])
def test_progress_only_cancels_on_user_action(editor, cancel):
    app, window, _, _ = editor
    dialog = ExportProgressDialog(window, 3)
    requests = []
    dialog.canceled.connect(lambda: requests.append(True))
    dialog.show()
    app.processEvents()
    dialog.setValue(2)
    assert '2 / 3' in dialog.counter.text()
    if cancel:
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.isVisible() and dialog.cancel_requested
        assert not dialog.cancel_button.isEnabled()
        dialog.reject()
    dialog.finish()
    assert not dialog.isVisible()
    assert len(requests) == int(cancel)


def test_export_worker_error_is_reported_and_controls_recover(editor, monkeypatch):
    app, window, folder, _ = editor
    errors = []
    monkeypatch.setattr('pdfedit.window.choose_export', lambda *a, **k: (str(folder / 'failed.pdf'), False))
    def fail_export(*a, **k):
        raise ValueError('测试导出失败')
    monkeypatch.setattr('pdfedit.window.export_pdf', fail_export)
    monkeypatch.setattr(Messages, 'warning', lambda *a, **k: errors.append(a[2]))
    window.export()
    wait_until(app, lambda: not window.exporting)
    assert len(errors) == 1 and '测试导出失败' in errors[0]
    assert window.splitter.isEnabled() and window.export_button.isEnabled()
    assert not (folder / 'failed.pdf').exists()


def test_cancel_export_reaches_worker_and_preserves_existing_file(editor, monkeypatch):
    app, window, folder, _ = editor
    target = folder / 'existing.pdf'
    target.write_bytes(b'keep existing PDF')
    started, proceed = threading.Event(), threading.Event()
    errors = []
    monkeypatch.setattr('pdfedit.window.choose_export', lambda *a, **k: (str(target), True))
    def controlled_export(*args, **kwargs):
        started.set()
        assert proceed.wait(3), 'Test worker was not released'
        return export_pdf(*args, **kwargs)
    monkeypatch.setattr('pdfedit.window.export_pdf', controlled_export)
    monkeypatch.setattr(Messages, 'warning', lambda *a, **k: errors.append(a[2]))
    try:
        window.export()
        wait_until(app, started.is_set)
        progress = next(d for d in window.findChildren(ExportProgressDialog) if d.isVisible())
        progress.cancel_button.click()
    finally:
        proceed.set()
    wait_until(app, lambda: not window.exporting)
    assert not errors and '取消' in window.status.text()
    assert target.read_bytes() == b'keep existing PDF'
    assert window.splitter.isEnabled() and window.dirty
