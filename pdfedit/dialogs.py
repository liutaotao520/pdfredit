"""Application dialogs sharing the main window's neutral design and controls."""
from pathlib import Path
import re

from PySide6.QtCore import Qt, QSize, Signal, QFileInfo
from PySide6.QtWidgets import (QDialog, QFileDialog, QFileIconProvider, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QToolButton, QVBoxLayout)

from .icons import icon


def text_label(text, name="dialogBody"):
    label = QLabel(text)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def action_button(text, callback, primary=False):
    button = QPushButton(text)
    button.setObjectName("primary" if primary else "dialogSecondary")
    button.setMinimumHeight(36)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAutoDefault(False)
    button.clicked.connect(callback)
    return button


class AppDialog(QDialog):
    def __init__(self, parent, title, width=480):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("dialogCard")
        outer.addWidget(self.card)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(20)
        header = QHBoxLayout()
        header.setSpacing(12)
        self.title_label = text_label(title, "dialogTitle")
        header.addWidget(self.title_label, 1)
        self.close_button = QPushButton()
        self.close_button.setObjectName("dialogClose")
        self.close_button.setIcon(icon("close"))
        self.close_button.setIconSize(QSize(18, 18))
        self.close_button.setFixedSize(28, 28)
        self.close_button.setAccessibleName("关闭弹窗")
        self.close_button.setToolTip("关闭")
        self.close_button.setAutoDefault(False)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.reject)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        layout.addLayout(self.body)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        self.actions.addStretch()
        layout.addLayout(self.actions)
        self._positioned = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._positioned:
            screen = self.screen().availableGeometry()
            area = self.parentWidget().frameGeometry() if self.parentWidget() else screen
            x, y = area.center().x() - self.width() // 2, area.center().y() - self.height() // 2
            self.move(max(screen.left(), min(x, screen.right() - self.width() + 1)),
                      max(screen.top(), min(y, screen.bottom() - self.height() + 1)))
            self._positioned = True


class MessageDialog(AppDialog):
    def __init__(self, parent, title, message, *, confirm_text=None, cancel_text="取消", details=""):
        super().__init__(parent, title, 500)
        if len(message) > 500:
            body = QPlainTextEdit(message)
            body.setObjectName("dialogDetails")
            body.setReadOnly(True)
            body.setFixedHeight(300)
        else:
            body = text_label(message)
        self.body.addWidget(body)
        if details:
            self.details = QPlainTextEdit(details)
            self.details.setObjectName("dialogDetails")
            self.details.setAccessibleName("详细信息")
            self.details.setReadOnly(True)
            self.details.setFixedHeight(160)
            self.details.hide()
            self.details_button = action_button("查看详情", self.toggle_details)
            self.details_button.setObjectName("subtle")
            self.body.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
            self.body.addWidget(self.details)
        if confirm_text:
            self.confirm_button = action_button(confirm_text, self.accept)
            self.cancel_button = action_button(cancel_text, self.reject, primary=True)
            self.actions.addWidget(self.confirm_button)
            self.actions.addWidget(self.cancel_button)
            self.cancel_button.setDefault(True)
            self.cancel_button.setFocus()
        else:
            self.confirm_button = action_button("知道了", self.accept, primary=True)
            self.actions.addWidget(self.confirm_button)
            self.confirm_button.setDefault(True)
            self.confirm_button.setFocus()

    def toggle_details(self):
        visible = self.details.isHidden()
        self.details.setVisible(visible)
        self.details_button.setText("收起详情" if visible else "查看详情")
        self.adjustSize()


class Messages:
    @staticmethod
    def information(parent, title, message, details=""):
        return MessageDialog(parent, title, message, details=details).exec()

    warning = information
    critical = information

    @staticmethod
    def confirm(parent, title, message, *, confirm_text="确认", cancel_text="取消"):
        dialog = MessageDialog(parent, title, message, confirm_text=confirm_text, cancel_text=cancel_text)
        return dialog.exec() == QDialog.DialogCode.Accepted


class MonochromeFileIcons(QFileIconProvider):
    def icon(self, value):
        return icon("page" if isinstance(value, QFileInfo) and value.isFile() else "folder")


def choose_directory(parent, path):
    dialog = QFileDialog(parent, "选择保存文件夹", str(path))
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setViewMode(QFileDialog.ViewMode.Detail)
    dialog.setObjectName("appFileDialog")
    dialog.file_icons = MonochromeFileIcons()
    dialog.setIconProvider(dialog.file_icons)
    for name, icon_name in [("backButton", "left"), ("forwardButton", "right"),
                            ("toParentButton", "up"), ("newFolderButton", "plus")]:
        control = dialog.findChild(QToolButton, name)
        if control:
            control.setIcon(icon(icon_name))
    for name in ("listModeButton", "detailModeButton"):
        control = dialog.findChild(QToolButton, name)
        if control:
            control.hide()
    for role, text in [(QFileDialog.DialogLabel.LookIn, "保存位置："),
                       (QFileDialog.DialogLabel.FileName, "文件夹："),
                       (QFileDialog.DialogLabel.FileType, "文件类型："),
                       (QFileDialog.DialogLabel.Accept, "选择文件夹"),
                       (QFileDialog.DialogLabel.Reject, "取消")]:
        dialog.setLabelText(role, text)
    dialog.resize(760, 480)
    return dialog.selectedFiles()[0] if dialog.exec() == QDialog.DialogCode.Accepted else ""


class ExportDialog(AppDialog):
    def __init__(self, parent, folder, count, layout, watermark):
        super().__init__(parent, "导出 PDF", 580)
        self.target = None
        self.overwrite = False
        self.body.addWidget(text_label("将当前页面按列表顺序合并为一个 PDF。"))
        summary = QFrame()
        summary.setObjectName("dialogSummary")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(6)
        paper = "跟随原始尺寸" if layout.paper == "original" else layout.paper
        summary_layout.addWidget(text_label(f"共 {count} 页  ·  {paper}", "sectionTitle"))
        kind = {"none": "不添加水印", "text": "文字水印", "image": "图片水印"}[watermark.kind]
        if watermark.kind != "none" and watermark.tiled:
            kind += f" · 平铺密度 {watermark.density} 级"
        summary_layout.addWidget(text_label(kind, "helper"))
        self.body.addWidget(summary)
        self.name_edit = QLineEdit("合并文档.pdf")
        self.name_edit.setAccessibleName("PDF 文件名")
        name_label = text_label("文件名", "fieldLabel")
        name_label.setBuddy(self.name_edit)
        self.body.addWidget(name_label)
        self.body.addWidget(self.name_edit)
        folder_label = text_label("保存位置", "fieldLabel")
        self.folder_edit = QLineEdit(str(folder))
        self.folder_edit.setAccessibleName("保存位置")
        folder_label.setBuddy(self.folder_edit)
        self.body.addWidget(folder_label)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.folder_edit, 1)
        self.browse_button = action_button("选择文件夹", self.browse)
        self.browse_button.setIcon(icon("folder"))
        row.addWidget(self.browse_button)
        self.body.addLayout(row)
        self.error_label = text_label("", "dialogValidation")
        self.error_label.setAccessibleName("保存位置提示")
        self.error_label.hide()
        self.body.addWidget(self.error_label)
        self.cancel_button = action_button("取消", self.reject)
        self.export_button = action_button("导出 PDF", self.accept, primary=True)
        self.actions.addWidget(self.cancel_button)
        self.actions.addWidget(self.export_button)
        self.export_button.setDefault(True)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def browse(self):
        folder = choose_directory(self, self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def accept(self):
        name = self.name_edit.text().strip()
        invalid = not name or not name.strip('.') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        reserved = re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', name.split('.')[0], re.I)
        if invalid or reserved or name.endswith('.'):
            self.show_error("请输入有效的文件名，不要包含路径或特殊字符。", self.name_edit)
            return
        if not name.lower().endswith('.pdf'):
            name += '.pdf'
        folder = Path(self.folder_edit.text().strip()).expanduser()
        if not folder.is_absolute() or not folder.is_dir():
            self.show_error("请选择存在的保存文件夹，或填写完整文件夹路径。", self.folder_edit)
            return
        target = folder / name
        if target.is_dir():
            self.show_error("同名文件夹已存在，请更换文件名。", self.name_edit)
            return
        exists = target.exists()
        if exists and not Messages.confirm(self, "替换已有 PDF？", f"“{name}”已存在。\n替换后将覆盖这个文件的内容。",
                confirm_text="替换文件", cancel_text="返回修改"):
            return
        self.target, self.overwrite = str(target), exists
        super().accept()

    def show_error(self, message, control):
        self.error_label.setText(message)
        self.error_label.show()
        control.setFocus()
        self.adjustSize()


def choose_export(parent, folder, count, layout, watermark):
    dialog = ExportDialog(parent, folder, count, layout, watermark)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.target, dialog.overwrite
    return None


class ExportProgressDialog(AppDialog):
    canceled = Signal()

    def __init__(self, parent, count, recognizing=False):
        self.recognizing = recognizing
        super().__init__(parent, "正在识别文字" if recognizing else "正在导出 PDF", 480)
        self.count = count
        self.cancel_requested = False
        self.completed = False
        self.description = text_label(f"正在本机识别 {count} 页，首次识别扫描件需加载模型。" if recognizing else f"正在排版并合并 {count} 页，请稍候。")
        self.body.addWidget(self.description)
        self.progress = QProgressBar()
        self.progress.setObjectName("dialogProgress")
        self.progress.setRange(0, count)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("文字识别进度" if recognizing else "PDF 导出进度")
        self.body.addWidget(self.progress)
        self.counter = text_label(f"已处理 0 / {count} 页", "helper")
        self.body.addWidget(self.counter)
        self.cancel_button = action_button("取消识别" if recognizing else "取消导出", self.reject)
        self.actions.addWidget(self.cancel_button)
        self.cancel_button.setFocus()

    def setValue(self, value):
        self.progress.setValue(value)
        if not self.cancel_requested:
            self.counter.setText(f"已处理 {value} / {self.count} 页")
            if value == self.count:
                self.description.setText("正在整理识别结果，请稍候。" if self.recognizing else "正在完成保存，请稍候。")

    def reject(self):
        if self.completed or self.cancel_requested:
            return
        self.cancel_requested = True
        self.description.setText("正在取消识别…" if self.recognizing else "正在取消导出…")
        self.counter.setText("当前页处理结束后停止，保留已完成页面。" if self.recognizing else "正在结束当前操作，请稍候。")
        self.cancel_button.setText("正在取消…")
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.canceled.emit()

    def closeEvent(self, event):
        if self.completed:
            event.accept()
        else:
            self.reject()
            event.ignore()

    def finish(self):
        self.completed = True
        super().accept()
