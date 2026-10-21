from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QRect, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QWidget, QListWidget, QAbstractItemView, QStyledItemDelegate, QPushButton, QStyle, QApplication

from .icons import icon
from .style import COLORS, ui_font
from .inline_text import InlineTextEditor, TextMoveHandle


class PageDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(220, 82)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(0, 2, 0, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        painter.setPen(QPen(QColor(COLORS["text"]), 1) if focused else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["hover"] if selected else COLORS["surface"] if hover else COLORS["sidebar"]))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
        thumb_rect = QRect(rect.x() + 10, rect.y() + 11, 54, 54)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["white"]))
        painter.drawRoundedRect(thumb_rect, 3, 3)
        thumb = index.data(Qt.ItemDataRole.DecorationRole)
        if thumb:
            thumb.paint(painter, thumb_rect.adjusted(3, 3, -3, -3), Qt.AlignmentFlag.AlignCenter)
        font = ui_font(11)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["muted"]))
        text_rect = QRect(rect.x() + 76, rect.y() + 8, rect.width() - 91, 18)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, f"第 {index.row() + 1} 页")
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["text"]))
        text = painter.fontMetrics().elidedText(index.data() or "", Qt.TextElideMode.ElideMiddle, text_rect.width())
        painter.drawText(text_rect.translated(0, 20), Qt.AlignmentFlag.AlignVCenter, text)
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["muted"]))
        page = index.data(Qt.ItemDataRole.UserRole)
        if page:
            painter.drawText(text_rect.translated(0, 40), Qt.AlignmentFlag.AlignVCenter, (f"PDF · {page.width / 72 * 25.4:.0f} × {page.height / 72 * 25.4:.0f} mm" if page.is_pdf else f"{page.width:g} × {page.height:g} px"))
        painter.restore()


class PageList(QListWidget):
    filesDropped = Signal(list)
    orderChanged = Signal()

    def __init__(self):
        super().__init__()
        self.setItemDelegate(PageDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setObjectName("pageList")
        self.setAccessibleName("页面顺序列表，可拖动排序")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.count():
            p = QPainter(self.viewport())
            y = min(self.viewport().height() // 2, 180)
            p.setPen(QColor(COLORS["muted"]))
            font = ui_font()
            font.setPixelSize(12)
            p.setFont(font)
            p.drawText(QRect(0, y, self.viewport().width(), 26), Qt.AlignmentFlag.AlignCenter, "暂无页面")
            p.end()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.filesDropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
            self.orderChanged.emit()


class Preview(QWidget):
    filesDropped = Signal(list)
    imageMoved = Signal(float, float)
    addRequested = Signal()
    textSelected = Signal(str)
    textMoved = Signal(float, float)
    textEditRequested = Signal(str)
    textCommitted = Signal(str, str, str)
    inputLimitReached = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 300)
        self.pixmap = QPixmap()
        self.paper_rect = QRectF()
        self.drag_start = None
        self.editing_text = False
        self.text_boxes = []
        self.selected_text_id = ""
        self.page_uid = ""
        self.inline_block_id = ""
        self.inline_page_uid = ""
        self.inline_style = None
        self._finishing = False
        self._font_files = {}
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAccessibleName("PDF 页面，识别后可点击文字直接修改")
        self.inline_editor = InlineTextEditor(self)
        self.inline_editor.accepted.connect(self.finish_edit)
        self.inline_editor.canceled.connect(lambda: self.finish_edit(False))
        self.inline_editor.limitReached.connect(self.inputLimitReached.emit)
        self.inline_editor.textChanged.connect(self.position_editor)
        self.move_handle = TextMoveHandle(self)
        self.move_handle.pressed.connect(self.finish_edit)
        self.move_handle.moved.connect(self.move_text_pixels)
        self.add_button = QPushButton("选择文件", self)
        self.add_button.setObjectName("primary")
        self.add_button.setIcon(icon("plus-light"))
        self.add_button.setIconSize(QSize(16, 16))
        self.add_button.setFixedSize(138, 38)
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.addRequested.emit)

    def resizeEvent(self, event):
        self.add_button.move((self.width() - 138) // 2, self.height() // 2 + 52)
        self.update_paper_rect()
        self.position_editor()
        super().resizeEvent(event)

    def set_image(self, data: bytes):
        self.pixmap.loadFromData(data)
        self.add_button.setVisible(self.pixmap.isNull())
        self.update_paper_rect()
        self.position_editor()
        self.update()

    def set_page(self, uid):
        if uid != self.page_uid:
            self.finish_edit()
            self.page_uid = uid
            self.clear()

    def clear(self):
        self.finish_edit()
        self.pixmap = QPixmap()
        self.paper_rect = QRectF()
        self.text_boxes = []
        self.move_handle.hide()
        self.add_button.setVisible(not self.page_uid)
        self.update()

    def update_paper_rect(self):
        if self.pixmap.isNull():
            self.paper_rect = QRectF()
        else:
            available = self.size() - QSize(72, 64)
            size = self.pixmap.size().scaled(available, Qt.AspectRatioMode.KeepAspectRatio)
            self.paper_rect = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2,
                                    size.width(), size.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(COLORS["white"]))
        if self.pixmap.isNull():
            if self.page_uid:
                p.setFont(ui_font(12))
                p.setPen(QColor(COLORS["muted"]))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "正在加载页面…")
                p.end()
                return
            cx, cy = self.width() / 2, self.height() / 2
            icon("image").paint(p, QRect(int(cx - 19), int(cy - 99), 38, 38))
            font = ui_font(21)
            font.setWeight(QFont.Weight.Medium)
            p.setFont(font)
            p.setPen(QColor(COLORS["text"]))
            p.drawText(QRectF(10, cy - 42, self.width() - 20, 36), Qt.AlignmentFlag.AlignCenter, "添加文件，开始整理")
            p.setFont(ui_font(12))
            p.setPen(QColor(COLORS["muted"]))
            p.drawText(QRectF(10, cy + 2, self.width() - 20, 24), Qt.AlignmentFlag.AlignCenter,
                       "拖入图片或 PDF · 自由整理每一页")
            self.paper_rect = QRectF()
        else:
            rect = self.paper_rect
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 9))
            p.drawRect(rect.adjusted(0, 2, 0, 2))
            p.setPen(QPen(QColor(COLORS["border"]), 1))
            p.setBrush(QColor(COLORS["white"]))
            p.drawRect(rect.adjusted(-.5, -.5, .5, .5))
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(rect.toRect(), self.pixmap)
            if self.editing_text:
                p.save()
                p.setClipRect(rect)
                for block_id, box in self.text_boxes:
                    selected = block_id == self.selected_text_id
                    p.setPen(QPen(QColor('#242424' if selected else '#999999'), 1.8 if selected else .8,
                                  Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine))
                    p.setBrush(QColor(0, 0, 0, 12) if selected else Qt.BrushStyle.NoBrush)
                    p.drawRect(self.screen_box(box).adjusted(-2, -2, 2, 2))
                p.restore()
        p.end()

    def screen_box(self, box):
        x, y, w, h = box
        rect = self.paper_rect
        return QRectF(rect.x()+x*rect.width(), rect.y()+y*rect.height(), w*rect.width(), h*rect.height())

    def hit_text(self, position):
        matches = [(w*h, block_id) for block_id, (x, y, w, h) in self.text_boxes
                   if self.screen_box((x, y, w, h)).adjusted(-4, -4, 4, 4).contains(position)]
        return min(matches)[1] if matches else ""

    def set_text_boxes(self, boxes, selected, enabled):
        self.text_boxes, self.selected_text_id, self.editing_text = boxes, selected, enabled
        self.position_editor()
        self.update()

    def begin_edit(self, page_uid, block, font_scale, select_all=False):
        if self.pixmap.isNull() or not self.editing_text or page_uid != self.page_uid:
            return
        self.finish_edit()
        self.inline_block_id, self.inline_page_uid = block['id'], page_uid
        self.inline_style = dict(block, font_scale=font_scale)
        editor = self.inline_editor
        editor.preediting = False
        editor.setPlainText(block['text'])
        self.position_editor()
        editor.show()
        editor.raise_()
        self.move_handle.raise_()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)
        if select_all:
            editor.selectAll()
        else:
            # Place the caret where the page was clicked, as in a normal editor.
            position = None
            if getattr(self, 'edit_click', None) is not None:
                position = editor.viewport().mapFrom(self, self.edit_click.toPoint())
            if position is not None:
                editor.setTextCursor(editor.cursorForPosition(position))
        self.edit_click = None

    def finish_edit(self, accept=True):
        if not self.inline_block_id or self._finishing:
            return
        self._finishing = True
        try:
            if accept:
                QGuiApplication.inputMethod().commit()
            else:
                QGuiApplication.inputMethod().reset()
            uid, block_id = self.inline_page_uid, self.inline_block_id
            text = self.inline_editor.toPlainText()
            self.inline_block_id = self.inline_page_uid = ""
            self.inline_editor.hide()
            self.inline_editor.preediting = False
            if accept:
                self.textCommitted.emit(uid, block_id, text)
        finally:
            self._finishing = False
        self.position_editor()

    def position_editor(self):
        box = next((box for block_id, box in self.text_boxes if block_id == self.selected_text_id), None)
        if not self.editing_text or box is None or self.paper_rect.isEmpty():
            self.move_handle.hide()
            return
        rect = self.screen_box(box)
        if self.inline_block_id:
            editor, style = self.inline_editor, self.inline_style
            family = style['font_family']
            if style['font_file']:
                if style['font_file'] not in self._font_files:
                    font_id = QFontDatabase.addApplicationFont(style['font_file'])
                    self._font_files[style['font_file']] = QFontDatabase.applicationFontFamilies(font_id)
                family = next(iter(self._font_files[style['font_file']]), family)
            # Keep small page text readable while typing; the saved pt size is unchanged.
            pixels = max(12, min(96, style['font_scale'] * self.paper_rect.width()))
            family = family.replace('\\', '\\\\').replace('"', '\\"')
            css = (f'QPlainTextEdit#inlineTextEditor {{ font-family: "{family}"; font-size: {pixels:.1f}px; '
                   f'font-weight: {700 if style["bold"] else 400}; font-style: {"italic" if style["italic"] else "normal"}; '
                   f'color: {style["color"]}; background: {style["background"]}; '
                   'border: 1px solid #242424; border-radius: 2px; padding: 0; '
                   'selection-background-color: #242424; selection-color: #ffffff; }')
            if editor.styleSheet() != css:
                editor.setStyleSheet(css)
            metrics = editor.fontMetrics()
            lines = editor.toPlainText().split('\n')
            natural_width = max((metrics.horizontalAdvance(line) for line in lines), default=0) + 14
            width = min(self.width()-24, max(120, rect.width()+8, natural_width))
            height = min(max(40, self.height()-48), 240,
                         max(rect.height()+8 if rect.height()<120 else 0,
                             metrics.lineSpacing()*len(lines)+10) + (16 if natural_width>width else 0))
            left = max(8, min(rect.left()-4, self.width()-width-8))
            top = max(26, min(rect.top()-4, self.height()-height-8))
            editor.setGeometry(round(left), round(top), round(width), round(height))
            rect = QRectF(editor.geometry())
        if rect.intersects(QRectF(self.rect())):
            self.move_handle.move(round(max(4, min(rect.left(), self.width()-26))),
                                  round(max(2, min(rect.top()-24, self.height()-26))))
            self.move_handle.show()
            self.move_handle.raise_()
        else:
            self.move_handle.hide()

    def move_text_pixels(self, dx, dy):
        self.finish_edit()
        if self.paper_rect.width() and self.paper_rect.height():
            self.textMoved.emit(dx/self.paper_rect.width(), dy/self.paper_rect.height())

    def mouseMoveEvent(self, event):
        if self.drag_start is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif not self.pixmap.isNull() and self.paper_rect.contains(event.position()) and (not self.editing_text or self.hit_text(event.position())):
            self.setCursor(Qt.CursorShape.IBeamCursor if self.editing_text else Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.finish_edit()
        if event.button() == Qt.MouseButton.LeftButton and not self.pixmap.isNull() and self.paper_rect.contains(event.position()):
            if self.editing_text:
                block_id = self.hit_text(event.position())
                if not block_id:
                    return
                self.selected_text_id = block_id
                self.textSelected.emit(block_id)
            self.drag_start = event.position()
            self.setCursor(Qt.CursorShape.IBeamCursor if self.editing_text else Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        if self.drag_start is not None:
            delta = event.position() - self.drag_start
            self.drag_start = None
            self.unsetCursor()
            if self.paper_rect.width() and self.paper_rect.height():
                if self.editing_text and delta.manhattanLength() < QApplication.startDragDistance():
                    self.edit_click = event.position()
                    self.textEditRequested.emit(self.selected_text_id)
                    return
                signal = self.textMoved if self.editing_text else self.imageMoved
                signal.emit(delta.x() / self.paper_rect.width(), delta.y() / self.paper_rect.height())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.filesDropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()
