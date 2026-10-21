"""Exercise the asynchronous GUI workflow without relying on desktop capture."""
from pathlib import Path
import json
import time
import uuid
import os

from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import QEventLoop, Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from pdfedit.window import MainWindow


def wait_until(app, predicate, timeout=12):
    deadline=time.monotonic()+timeout
    while not predicate():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents,50)
        if time.monotonic()>=deadline:
            raise AssertionError("Timed out waiting for the GUI job")
        time.sleep(.01)
    app.processEvents()


def test_import_edit_watermark_export_save_restore(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    base=Path(os.environ.get("PDFEDIT_TEST_DIR", root/'.task_tmp/20261016-image-pdf/tests'))/uuid.uuid4().hex
    base.mkdir(parents=True)
    files=[]
    for index,color in enumerate(['red','green','blue']):
        file=base/f'图片 {index+1}.png'
        Image.new('RGB',(240,360),color).save(file)
        files.append(str(file))
    app=QApplication.instance() or QApplication([])
    window=MainWindow(root)
    window.add_paths(files)
    wait_until(app,lambda:window.page_list.count()==3 and not window.importing)
    # Deduplicate repeated shell invocations.
    window.add_paths(files)
    wait_until(app,lambda:not window.pending_paths and not window.importing)
    assert window.page_list.count()==3
    window.page_list.setCurrentRow(2)
    window.move_pages(-1)
    assert [Path(p.path).name for p in window.pages()]==['图片 1.png','图片 3.png','图片 2.png']
    window.zoom.setValue(70)
    window.drag_image(.1,-.05)
    window.wm_kind.setCurrentIndex(window.wm_kind.findData('text'))
    window.wm_text.setText('合同副本 · GUI验收')
    window.wm_pages.setText('1,3')
    output=base/'界面导出.pdf'
    monkeypatch.setattr('pdfedit.window.choose_export', lambda *a, **k: (str(output), False))
    window.export()
    wait_until(app,lambda:not window.exporting)
    assert output.is_file(),window.status.text()
    assert len(PdfReader(output).pages)==3
    assert not window.dirty
    project=base/'方案.ipdf.json'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(project),'JSON'))
    window.save_project()
    saved=json.loads(project.read_text(encoding='utf-8'))
    assert saved['watermark']['text']=='合同副本 · GUI验收'
    assert saved['pages'][1]['zoom']==.7
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(project),'JSON'))
    window.load_project()
    assert window.page_list.count()==3
    assert window.watermark.pages=='1,3'
    assert window.pages()[1].offset_x==.1
    wait_until(app,lambda:not window.preview_busy)
    window.timer.stop()
    window.dirty=False
    window.close()
