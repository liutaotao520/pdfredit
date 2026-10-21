"""Page-local text input. Drafts become one undoable edit on acceptance."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QPlainTextEdit, QWidget


MAX_TEXT_LENGTH = 12000


class InlineTextEditor(QPlainTextEdit):
    accepted = Signal()
    canceled = Signal()
    limitReached = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.preediting = False
        self.setObjectName("inlineTextEditor")
        self.setAccessibleName("在当前页面修改文字")
        self.setToolTip("Enter 完成 · Shift+Enter 换行 · Esc 取消")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(3)
        self.hide()

    def can_insert(self, text, replacing=None):
        removed = len(self.textCursor().selectedText()) if replacing is None else replacing
        if len(self.toPlainText()) - removed + len(text) > MAX_TEXT_LENGTH:
            self.limitReached.emit()
            return False
        return True

    def insertFromMimeData(self, source):
        # Only plain text is meaningful in a PDF text block.
        if source.hasText() and self.can_insert(source.text()):
            self.insertPlainText(source.text())

    def inputMethodEvent(self, event):
        if event.commitString() and not self.can_insert(
            event.commitString(), max(event.replacementLength(), len(self.textCursor().selectedText()))
        ):
            event.accept()
            return
        self.preediting = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if self.preediting and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            # The platform sends the chosen candidate in an input-method event.
            # Do not interpret its confirmation key as a newline or a PDF commit.
            event.accept()
            return
        if not self.preediting:
            if event.key() == Qt.Key.Key_Escape:
                self.canceled.emit()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.accepted.emit()
                event.accept()
                return
        # An IME owns Enter / Escape while choosing a candidate.
        inserting = event.text() and (event.text().isprintable() or event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter))
        if inserting and not self.preediting and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            if not self.can_insert(event.text()):
                event.accept()
                return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Opening the editor's copy/paste menu must not close the draft.
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.accepted.emit()


class TextMoveHandle(QWidget):
    pressed = Signal()
    moved = Signal(float, float)

    def __init__(self, parent):
        super().__init__(parent)
        self.start = None
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("拖动这里移动文字")
        self.setAccessibleName("移动所选文字")
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#d4d4d4'), 1))
        p.setBrush(QColor('#ffffff'))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 3, 3)
        p.setPen(QPen(QColor('#555555'), 1.2))
        p.drawLine(5, 11, 17, 11)
        p.drawLine(11, 5, 11, 17)
        for x1, y1, x2, y2 in [(5,11,8,8),(5,11,8,14),(17,11,14,8),(17,11,14,14),
                               (11,5,8,8),(11,5,14,8),(11,17,8,14),(11,17,14,14)]:
            p.drawLine(x1, y1, x2, y2)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = event.globalPosition()
            self.pressed.emit()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            delta = event.globalPosition() - self.start
            self.start = None
            self.moved.emit(delta.x(), delta.y())
            event.accept()
