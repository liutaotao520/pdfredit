"""Text styles and per-page history; content is edited on the document."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QDoubleSpinBox,
    QCheckBox, QColorDialog, QFileDialog, QScrollArea)

from .dialogs import Messages
from .text_editing import EDIT_FIELDS, MAX_BLOCKS, new_block, source_signature
from .text_fonts import FONT_CHOICES, font_for, validate_glyphs


class TextPanel(QScrollArea):
    changed = Signal()
    selected = Signal(str)
    recognizeRequested = Signal(str)
    flushRequested = Signal()
    editRequested = Signal(str, bool)

    def __init__(self, root):
        super().__init__()
        self.root = root
        self.page = None
        self.selected_id = ""
        self.syncing = False
        self.history = {}
        self.redo_history = {}
        self.batch_uid = None
        self.batch_timer = QTimer(self)
        self.batch_timer.setSingleShot(True)
        self.batch_timer.setInterval(700)
        self.batch_timer.timeout.connect(self.end_batch)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        def caption(text):
            widget = QLabel(text)
            widget.setWordWrap(True)
            widget.setObjectName("helper")
            return widget

        def btn(text, callback, primary=False):
            widget = QPushButton(text)
            widget.setObjectName("primary" if primary else "")
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
            widget.clicked.connect(callback)
            return widget

        self.recognize_current = btn("识别当前页", lambda: self.recognizeRequested.emit("current"), True)
        self.recognize_all = btn("识别全部", lambda: self.recognizeRequested.emit("all"))
        row = QHBoxLayout()
        row.addWidget(self.recognize_current, 1)
        row.addWidget(self.recognize_all, 1)
        layout.addLayout(row)
        self.supplement = btn("补充识别页面中的图片文字", lambda: self.recognizeRequested.emit("supplement"))
        self.supplement.setObjectName("subtle")
        layout.addWidget(self.supplement)
        self.summary = caption("添加 PDF 或图片后，识别页面文字。")
        layout.addWidget(self.summary)
        self.blocks = QListWidget()
        self.blocks.setObjectName("textBlocks")
        self.blocks.setMinimumHeight(108)
        self.blocks.setMaximumHeight(160)
        self.blocks.setAccessibleName("可编辑文字块")
        self.blocks.currentItemChanged.connect(self.choose_block)
        self.blocks.itemDoubleClicked.connect(lambda item: self.editRequested.emit(item.data(Qt.ItemDataRole.UserRole), False))
        layout.addWidget(self.blocks)
        row = QHBoxLayout()
        self.add_button = btn("添加文字", self.add_text)
        self.undo_button = btn("撤销", self.undo)
        self.redo_button = btn("重做", self.redo)
        for widget in (self.add_button, self.undo_button, self.redo_button):
            row.addWidget(widget)
        layout.addLayout(row)
        self.editor = QWidget()
        form = QVBoxLayout(self.editor)
        form.setContentsMargins(0, 4, 0, 0)
        form.setSpacing(9)
        form.addWidget(caption("在页面上点击文字修改内容，此处调整样式。"))
        form.addWidget(caption("字体"))
        row = QHBoxLayout()
        self.family = QComboBox()
        self.family.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.family.setMinimumContentsLength(4)
        for title, value in FONT_CHOICES:
            self.family.addItem(title, value)
        self.family.currentIndexChanged.connect(self.family_changed)
        row.addWidget(self.family, 1)
        self.font_button = btn("导入字体", self.choose_font)
        self.font_button.setToolTip("使用本机的 TTF / TTC 字体文件")
        row.addWidget(self.font_button)
        form.addLayout(row)
        self.font_hint = caption("")
        form.addWidget(self.font_hint)
        row = QHBoxLayout()
        self.size = QDoubleSpinBox()
        self.size.setRange(1, 600)
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        self.size.setAccessibleName("文字字号")
        self.size.setKeyboardTracking(False)
        self.size.setMaximumWidth(112)
        self.size.valueChanged.connect(self.update_edit)
        row.addWidget(self.size, 1)
        self.bold = QCheckBox("粗体")
        self.italic = QCheckBox("斜体")
        for widget in (self.bold, self.italic):
            widget.setStyleSheet("QCheckBox { spacing: 4px; }")
            widget.toggled.connect(self.update_edit)
            row.addWidget(widget)
        form.addLayout(row)
        row = QHBoxLayout()
        self.color_button = btn("文字颜色", lambda: self.choose_color("color"))
        self.background_button = btn("覆盖底色", lambda: self.choose_color("background"))
        self.background_button.setToolTip("扫描文字替换区域的底色，可匹配纸张颜色")
        row.addWidget(self.color_button)
        row.addWidget(self.background_button)
        form.addLayout(row)
        self.validation = caption("")
        form.addWidget(self.validation)
        row = QHBoxLayout()
        self.restore_button = btn("恢复原文", self.restore)
        self.delete_button = btn("删除文字", self.delete_text)
        row.addWidget(self.restore_button)
        row.addWidget(self.delete_button)
        form.addLayout(row)
        layout.addWidget(self.editor)
        layout.addWidget(caption("点击页面文字直接输入；拖动文字上方的移动柄调整位置。扫描识别请先校对；复杂背景上的替换可能留下覆盖痕迹。"))
        layout.addStretch()
        self.set_page(None)

    def end_batch(self):
        self.batch_uid = None

    def set_page(self, page):
        if page is not self.page:
            self.flushRequested.emit()
            self.end_batch()
            self.selected_id = ""
        self.page = page
        enabled = page is not None
        for widget in (self.recognize_current, self.recognize_all, self.supplement, self.add_button):
            widget.setEnabled(enabled)
        self.refresh()

    def current_block(self):
        return next((b for b in self.page.text_blocks if b['id'] == self.selected_id), None) if self.page else None

    def refresh(self):
        self.syncing = True
        self.blocks.clear()
        for b in self.page.text_blocks if self.page else []:
            prefix = "已删除 · " if b.get('deleted') else ""
            item = QListWidgetItem(prefix + b['text'].replace('\n', ' ')[:80])
            item.setData(Qt.ItemDataRole.UserRole, b['id'])
            item.setToolTip(b['text'])
            self.blocks.addItem(item)
            if b['id'] == self.selected_id:
                self.blocks.setCurrentItem(item)
        self.syncing = False
        count = len(self.page.text_blocks) if self.page else 0
        self.summary.setText(f"{count} 个文字块 · 点击文字开始编辑" if count else
                             "未找到文字，可手动添加或补充识别。" if self.page and self.page.text_recognized else
                             "本地识别中文 / 英文，支持扫描 PDF。")
        self.sync_fields()
        self.update_history_buttons()

    def choose_block(self, item, previous=None):
        if self.syncing:
            return
        self.flushRequested.emit()
        self.end_batch()
        self.selected_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        self.sync_fields()
        self.selected.emit(self.selected_id)

    def select(self, block_id):
        for i in range(self.blocks.count()):
            if self.blocks.item(i).data(Qt.ItemDataRole.UserRole) == block_id:
                self.blocks.setCurrentRow(i)
                return

    def sync_fields(self):
        block = self.current_block()
        self.editor.setEnabled(block is not None)
        if not block:
            return
        self.syncing = True
        index = self.family.findData(block['font_family'])
        self.family.setCurrentIndex(max(0, index))
        self.size.setValue(block['font_size'])
        self.bold.setChecked(block['bold'])
        self.italic.setChecked(block['italic'])
        self.delete_button.setEnabled(not block.get('deleted'))
        self.background_button.setVisible(block['source'] in {'ocr', 'native_scan'})
        for button, key, title in [(self.color_button, 'color', '文字'), (self.background_button, 'background', '底色')]:
            button.setText(f"{title} {block[key].upper()}")
        self.font_hint.setText("自定义：" + Path(block['font_file']).name if block['font_file'] else
                               "原字体：" + block.get('original_font', '扫描识别 / 新增文字') + " · 修改后使用所选字体")
        self.validation.setText("已删除，可点击「恢复原文」。" if block.get('deleted') else
                                f"识别置信度 {block['confidence']:.0%}，请核对文字。" if block['source'] == 'ocr' else "")
        self.syncing = False

    def record(self, batch=False):
        if not self.page:
            return
        uid = self.page.uid
        if not batch or self.batch_uid != uid:
            history = self.history.setdefault(uid, [])
            history.append(deepcopy(self.page.text_blocks))
            del history[:-30]
            self.redo_history[uid] = []
        self.batch_uid = uid if batch else None
        if batch:
            self.batch_timer.start()
        self.update_history_buttons()

    def update_history_buttons(self):
        uid = self.page.uid if self.page else ""
        self.undo_button.setEnabled(bool(self.history.get(uid)))
        self.redo_button.setEnabled(bool(self.redo_history.get(uid)))

    def update_edit(self, *args):
        if self.syncing:
            return
        self.flushRequested.emit()
        b = self.current_block()
        if self.syncing or not b or b.get('deleted'):
            return
        values = dict(font_size=self.size.value(),
                      font_family=self.family.currentData(), bold=self.bold.isChecked(), italic=self.italic.isChecked())
        if all(b[k] == v for k, v in values.items()):
            return
        self.record(batch=True)
        b.update(values)
        self.after_edit(b)

    def apply_text(self, page_uid, block_id, text):
        # A delayed focus event must never write a previous draft onto another page.
        if not self.page or self.page.uid != page_uid:
            return
        b = next((b for b in self.page.text_blocks if b['id'] == block_id), None)
        if not b or b.get('deleted') or text == b['text']:
            return
        if len(text) > 12000:
            raise ValueError("单个文字块最多 12000 个字符。")
        self.record()
        b['text'] = text
        self.after_edit(b)

    def after_edit(self, b):
        b['changed'] = b['source'] == 'added' or any(b[k] != b['original'][k] for k in EDIT_FIELDS)
        try:
            font, _, _ = font_for(b['font_family'], b['bold'], b['italic'], b['font_file'])
            validate_glyphs(font, b['text'])
            self.validation.setText("修改已应用 · 导出后生效")
        except Exception as exc:
            self.validation.setText(str(exc))
        for i in range(self.blocks.count()):
            item = self.blocks.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == b['id']:
                item.setText(b['text'].replace('\n', ' ')[:80])
                item.setToolTip(b['text'])
                break
        self.changed.emit()

    def family_changed(self):
        if not self.syncing:
            self.flushRequested.emit()
        if not self.syncing and (b := self.current_block()):
            self.record(batch=True)
            b['font_file'] = ''
            b['changed'] = True
            self.update_edit()
            self.font_hint.setText("修改后使用所选字体")
            self.changed.emit()

    def add_text(self):
        self.flushRequested.emit()
        if not self.page or len(self.page.text_blocks) >= MAX_BLOCKS:
            return
        try:
            if not self.page.text_source_signature:
                self.page.text_source_signature = source_signature(self.page.path)
        except Exception as exc:
            Messages.warning(self, "无法添加文字", str(exc))
            return
        self.record()
        b = new_block("新文字", (.15, .15, .35, .06), 20)
        self.page.text_blocks.append(b)
        self.selected_id = b['id']
        self.refresh()
        self.selected.emit(b['id'])
        self.changed.emit()
        self.editRequested.emit(b['id'], True)

    def choose_font(self):
        self.flushRequested.emit()
        b = self.current_block()
        if not b:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择编辑字体", str(self.root), "TrueType 字体 (*.ttf *.ttc)")
        if not path:
            return
        try:
            name, _, _ = font_for(b['font_family'], b['bold'], b['italic'], path)
            validate_glyphs(name, b['text'])
        except Exception as exc:
            Messages.warning(self, "无法使用字体", str(exc))
            return
        self.record()
        b['font_file'], b['changed'] = path, True
        self.sync_fields()
        self.changed.emit()

    def choose_color(self, key):
        self.flushRequested.emit()
        b = self.current_block()
        if not b:
            return
        color = QColorDialog.getColor(QColor(b[key]), self, "文字颜色" if key == 'color' else "扫描文字覆盖底色")
        if color.isValid() and color.name() != b[key]:
            self.record()
            b[key], b['changed'] = color.name(), True
            self.sync_fields()
            self.changed.emit()

    def move_text(self, dx, dy):
        self.flushRequested.emit()
        b = self.current_block()
        if b and not b.get('deleted') and (abs(dx) > .0001 or abs(dy) > .0001):
            self.record()
            dx = max(-2-b['anchor_x'], min(2-b['anchor_x'], dx))
            dy = max(-2-b['anchor_y'], min(2-b['anchor_y'], dy))
            for key, delta in [('x', dx), ('anchor_x', dx), ('y', dy), ('anchor_y', dy)]:
                b[key] += delta
            b['changed'] = True
            self.changed.emit()

    def delete_text(self):
        self.flushRequested.emit()
        if b := self.current_block():
            self.record()
            b['deleted'] = True
            self.refresh()
            self.changed.emit()

    def restore(self):
        self.flushRequested.emit()
        if b := self.current_block():
            self.record()
            if b['source'] == 'added':
                self.page.text_blocks.remove(b)
                self.selected_id = ''
            else:
                b.update(deepcopy(b['original']))
                b['changed'] = b['deleted'] = False
            self.refresh()
            self.changed.emit()

    def undo(self):
        self.travel(self.history, self.redo_history)

    def redo(self):
        self.travel(self.redo_history, self.history)

    def travel(self, source, target):
        self.flushRequested.emit()
        if self.page and source.get(self.page.uid):
            self.end_batch()
            target.setdefault(self.page.uid, []).append(deepcopy(self.page.text_blocks))
            self.page.text_blocks = source[self.page.uid].pop()
            self.refresh()
            self.changed.emit()
