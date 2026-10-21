from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QRect, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QFont
from PySide6.QtWidgets import QWidget, QListWidget, QAbstractItemView, QStyledItemDelegate, QPushButton, QStyle

from .icons import icon
from .style import COLORS, ui_font


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

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 300)
        self.pixmap = QPixmap()
        self.paper_rect = QRectF()
        self.drag_start = None
        self.setAccessibleName("PDF 页面预览，可拖动内容位置")
        self.add_button = QPushButton("选择文件", self)
        self.add_button.setObjectName("primary")
        self.add_button.setIcon(icon("plus-light"))
        self.add_button.setIconSize(QSize(16, 16))
        self.add_button.setFixedSize(138, 38)
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self.addRequested.emit)

    def resizeEvent(self, event):
        self.add_button.move((self.width() - 138) // 2, self.height() // 2 + 52)
        super().resizeEvent(event)

    def set_image(self, data: bytes):
        self.pixmap.loadFromData(data)
        self.add_button.setVisible(self.pixmap.isNull())
        self.update()

    def clear(self):
        self.pixmap = QPixmap()
        self.add_button.show()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(COLORS["white"]))
        if self.pixmap.isNull():
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
            available = self.size() - QSize(72, 64)
            size = self.pixmap.size().scaled(available, Qt.AspectRatioMode.KeepAspectRatio)
            rect = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2, size.width(), size.height())
            self.paper_rect = rect
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 9))
            p.drawRect(rect.adjusted(0, 2, 0, 2))
            p.setPen(QPen(QColor(COLORS["border"]), 1))
            p.setBrush(QColor(COLORS["white"]))
            p.drawRect(rect.adjusted(-.5, -.5, .5, .5))
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(rect.toRect(), self.pixmap)
        p.end()

    def mouseMoveEvent(self, event):
        if self.drag_start is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif not self.pixmap.isNull() and self.paper_rect.contains(event.position()):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.pixmap.isNull() and self.paper_rect.contains(event.position()):
            self.drag_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        if self.drag_start is not None:
            delta = event.position() - self.drag_start
            self.drag_start = None
            self.unsetCursor()
            if self.paper_rect.width() and self.paper_rect.height():
                self.imageMoved.emit(delta.x() / self.paper_rect.width(), delta.y() / self.paper_rect.height())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.filesDropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()
