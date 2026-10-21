from __future__ import annotations

import copy
import json
from pathlib import Path
import threading

from PySide6.QtCore import Qt, QTimer, QThreadPool, QUrl, QSize
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
    QDoubleSpinBox, QFileDialog, QFontComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidgetItem, QMainWindow, QMenu, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .engine import PAPERS, export_pdf, geometry, render_preview
from .imaging import EXTENSIONS, FILE_FILTER, IMAGE_FILTER, inspect_image, png_bytes
from .models import Layout, Page, Watermark, natural_key, page_selection, project_data
from .widgets import PageList, Preview
from .workers import Job
from .icons import ASSETS, icon
from .dialogs import Messages, ExportProgressDialog, choose_export


def label(text, name=""):
    result = QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(True)
    return result


def button(text, callback, name="", icon_name=""):
    result = QPushButton(text)
    result.setObjectName(name)
    if icon_name:
        result.setIcon(icon(icon_name))
        result.setIconSize(QSize(16, 16))
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.clicked.connect(callback)
    return result


def combo(items):
    result = QComboBox()
    result.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    result.setMinimumContentsLength(4)
    for title, value in items:
        result.addItem(title, value)
    return result


class MainWindow(QMainWindow):
    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.layout_options = Layout()
        self.watermark = Watermark()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.jobs = set()
        self.importing = False
        self.exporting = False
        self.pending_paths = []
        self.preview_serial = 0
        self.preview_busy = False
        self.preview_again = False
        self.dirty = False
        self.output_path = None
        self._syncing = False
        self.setWindowTitle("合页 · 图片与 PDF 合并")
        self.resize(1280, 820)
        self.setMinimumSize(1060, 720)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(140)
        self.timer.timeout.connect(self.refresh_preview)
        self.import_timer = QTimer(self)
        self.import_timer.setSingleShot(True)
        self.import_timer.setInterval(260)
        self.import_timer.timeout.connect(self.start_import)
        self.build_ui()
        self.bind_shortcuts()

    def build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        header = QFrame()
        header.setObjectName("header")
        head = QHBoxLayout(header)
        head.setContentsMargins(18, 10, 18, 10)
        head.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(QIcon(str(ASSETS / "mark.svg")).pixmap(QSize(26, 26), self.devicePixelRatioF()))
        mark.setFixedSize(28, 28)
        head.addWidget(mark)
        head.addWidget(label("合页", "brand"))
        head.addSpacing(8)
        tagline = label("图片与 PDF 合并", "headerTag")
        tagline.setWordWrap(False)
        head.addWidget(tagline)
        head.addStretch()
        self.tools_button = button("更多", self.tools_menu, "subtle", "more")
        head.addWidget(self.tools_button)
        self.export_button = button("导出 PDF", self.export, "primary", "download-light")
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("PDF 按页展开，与图片按左侧顺序导出  Ctrl+E")
        self.export_button.setMinimumWidth(116)
        head.addWidget(self.export_button)
        main.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        self.splitter = splitter
        left = QFrame()
        left.setObjectName("leftPanel")
        left.setMinimumWidth(240)
        left.setMaximumWidth(360)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 20, 14, 14)
        ll.setSpacing(12)
        line = QHBoxLayout()
        line.addWidget(label("页面列表", "panelTitle"))
        line.addStretch()
        self.page_count = label("0 页", "pageCount")
        line.addWidget(self.page_count)
        ll.addLayout(line)
        ll.addWidget(label("拖动调整顺序 · Ctrl 多选", "muted"))
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.add_button = button("添加文件", self.choose_images, "addImages", "plus")
        self.add_button.setToolTip("添加文件  Ctrl+O")
        self.folder_button = button("", self.choose_folder, "iconButton", "folder")
        self.folder_button.setFixedSize(34, 34)
        self.folder_button.setAccessibleName("添加文件夹")
        self.folder_button.setToolTip("添加文件夹中的图片和 PDF")
        add_row.addWidget(self.add_button, 1)
        add_row.addWidget(self.folder_button)
        ll.addLayout(add_row)
        self.page_list = PageList()
        self.page_list.filesDropped.connect(self.add_paths)
        self.page_list.orderChanged.connect(self.mark_changed)
        self.page_list.currentRowChanged.connect(self.select_page)
        self.page_list.itemSelectionChanged.connect(self.update_selection_controls)
        self.page_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.page_list.customContextMenuRequested.connect(self.list_menu)
        ll.addWidget(self.page_list, 1)
        controls = QHBoxLayout()
        controls.setSpacing(5)
        self.move_up = button("上移", lambda: self.move_pages(-1), "subtle", "up")
        self.move_down = button("下移", lambda: self.move_pages(1), "subtle", "down")
        self.remove_button = button("移除", self.remove_pages, "subtle", "trash")
        for control in [self.move_up, self.move_down, self.remove_button]:
            control.setStyleSheet("padding: 7px 6px; font-size: 12px;")
            controls.addWidget(control, 1)
        ll.addLayout(controls)
        ll.addWidget(label("从列表移除，不会删除源文件", "helper"))
        splitter.addWidget(left)

        center = QFrame()
        center.setObjectName("centerPanel")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        preview_head = QFrame()
        preview_head.setObjectName("previewHead")
        ph = QHBoxLayout(preview_head)
        ph.setContentsMargins(24, 12, 20, 6)
        ph.setSpacing(8)
        self.preview_title = label("页面预览", "panelTitle")
        ph.addWidget(self.preview_title)
        ph.addStretch()
        self.previous_page = button("", lambda: self.navigate_page(-1), "navButton", "left")
        self.next_page = button("", lambda: self.navigate_page(1), "navButton", "right")
        for control, title in [(self.previous_page, "上一页"), (self.next_page, "下一页")]:
            control.setFixedSize(30, 30)
            control.setToolTip(title)
            control.setAccessibleName(title)
            ph.addWidget(control)
        center_layout.addWidget(preview_head)
        self.preview = Preview()
        self.preview.filesDropped.connect(self.add_paths)
        self.preview.addRequested.connect(self.choose_images)
        self.preview.imageMoved.connect(self.drag_image)
        center_layout.addWidget(self.preview, 1)
        self.preview_info = label("PDF / JPG / PNG / HEIC / WebP / TIFF 等", "previewInfo")
        self.preview_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_info.setContentsMargins(20, 0, 20, 0)
        self.preview_info.setMinimumHeight(30)
        center_layout.addWidget(self.preview_info)
        tip = label("拖动纸张内的内容调整位置 · 右侧修改后实时预览", "helper")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setContentsMargins(12, 0, 12, 16)
        center_layout.addWidget(tip)
        splitter.addWidget(center)

        self.right = QFrame()
        self.right.setObjectName("sidePanel")
        self.right.setMinimumWidth(292)
        self.right.setMaximumWidth(340)
        rl = QVBoxLayout(self.right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.setIconSize(QSize(16, 16))
        self.tabs.addTab(self.layout_tab(), "页面排版")
        self.tabs.addTab(self.watermark_tab(), "添加水印")
        rl.addWidget(self.tabs)
        splitter.addWidget(self.right)
        splitter.setSizes([260, 716, 304])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        main.addWidget(splitter, 1)

        footer = QFrame()
        footer.setObjectName("footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 6, 18, 6)
        fl.setSpacing(8)
        self.status = label("准备就绪 · 文件仅在本机处理", "helper")
        fl.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(130)
        self.progress.setTextVisible(False)
        self.progress.hide()
        fl.addWidget(self.progress)
        self.open_output = button("打开 PDF", self.open_pdf, "subtle")
        self.open_output.hide()
        fl.addWidget(self.open_output)
        main.addWidget(footer)
        self.update_selection_controls()

    def navigate_page(self, direction):
        target = self.page_list.currentRow() + direction
        if 0 <= target < self.page_list.count():
            self.page_list.setCurrentRow(target)

    def update_selection_controls(self):
        if not hasattr(self, "current_group"):
            return
        count, row = self.page_list.count(), self.page_list.currentRow()
        selected = [self.page_list.row(item) for item in self.page_list.selectedItems()]
        self.current_group.setEnabled(row >= 0)
        self.move_up.setEnabled(bool(selected) and min(selected) > 0)
        self.move_down.setEnabled(bool(selected) and max(selected) < count - 1)
        self.remove_button.setEnabled(bool(selected))
        self.previous_page.setEnabled(row > 0)
        self.next_page.setEnabled(0 <= row < count - 1)

    def form(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(14)
        scroll.setWidget(body)
        return scroll, layout

    def field(self, form, title, widget):
        container = QWidget()
        container.setMinimumWidth(0)
        container.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        caption = label(title, "fieldLabel")
        caption.setBuddy(widget)
        widget.setAccessibleName(title)
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(caption)
        layout.addWidget(widget)
        if isinstance(form, QHBoxLayout):
            form.addWidget(container, 1)
        else:
            form.addWidget(container)
        return container

    def section_heading(self, form, title, note=""):
        row = QHBoxLayout()
        row.addWidget(label(title, "sectionTitle"))
        row.addStretch()
        if note:
            row.addWidget(label(note, "helper"))
        form.addLayout(row)

    def separator(self, form):
        line = QFrame()
        line.setObjectName("separator")
        line.setFixedHeight(1)
        form.addWidget(line)

    def layout_tab(self):
        scroll, form = self.form()
        self.section_heading(form, "文档设置", "应用到所有页面")
        self.paper = combo([("A4 · 常用打印", "A4"), ("A3 · 297 × 420 mm", "A3"), ("A5 · 小册子", "A5"), ("Letter · 信纸", "Letter"), ("跟随原始尺寸 · 无白边", "original")])
        self.field(form, "纸张大小", self.paper)
        self.orientation = combo([("自动适应内容横竖", "auto"), ("纵向", "portrait"), ("横向", "landscape")])
        self.field(form, "页面方向", self.orientation)
        self.margin = QSpinBox()
        self.margin.setRange(0, 50)
        self.margin.setValue(12)
        self.margin.setSuffix(" mm")
        self.field(form, "页面留白", self.margin)
        self.quality = combo([("原始清晰度 · 无损", "original"), ("高清 · 适合打印", "high"), ("轻巧 · 适合分享", "compact")])
        self.quality.setToolTip("原始清晰度：保留像素，文件较大\n高清：适合打印\n轻巧：适合发送和分享")
        self.field(form, "输出质量", self.quality)
        self.separator(form)
        self.current_group = QWidget()
        current = QVBoxLayout(self.current_group)
        current.setContentsMargins(0, 0, 0, 0)
        current.setSpacing(12)
        self.section_heading(current, "当前页面", "只调整选中页")
        rotate = QHBoxLayout()
        rotate.setSpacing(8)
        rotate.addWidget(button("向左旋转", lambda: self.rotate(-90), "", "rotate-left"))
        rotate.addWidget(button("向右旋转", lambda: self.rotate(90), "", "rotate-right"))
        current.addLayout(rotate)
        self.zoom = QSpinBox()
        self.zoom.setRange(5, 250)
        self.zoom.setValue(100)
        self.zoom.setSuffix(" %")
        self.field(current, "内容缩放", self.zoom)
        offsets = QHBoxLayout()
        offsets.setSpacing(8)
        self.offset_x = QSpinBox()
        self.offset_y = QSpinBox()
        for control, title in [(self.offset_x, "水平位置"), (self.offset_y, "垂直位置")]:
            control.setRange(-100, 100)
            control.setSuffix(" %")
            self.field(offsets, title, control)
        current.addLayout(offsets)
        current.addWidget(label("也可拖动预览移动内容，超出纸张的部分会被裁切。", "helper"))
        current.addWidget(button("恢复原始位置与大小", self.reset_page, "resetButton", "reset"))
        form.addWidget(self.current_group)
        form.addStretch()
        for control in [self.paper, self.orientation, self.quality]:
            control.currentIndexChanged.connect(self.global_change)
        self.margin.valueChanged.connect(self.global_change)
        for control in [self.zoom, self.offset_x, self.offset_y]:
            control.valueChanged.connect(self.page_change)
        return scroll

    def watermark_tab(self):
        scroll, form = self.form()
        self.section_heading(form, "水印设置", "实时预览")
        self.wm_kind = combo([("不添加水印", "none"), ("文字水印", "text"), ("图片水印", "image")])
        self.field(form, "水印类型", self.wm_kind)
        self.wm_empty = QFrame()
        self.wm_empty.setObjectName("hintBox")
        empty = QVBoxLayout(self.wm_empty)
        empty.setContentsMargins(16, 24, 16, 24)
        empty.setSpacing(12)
        stamp = QLabel()
        stamp.setPixmap(icon("stamp").pixmap(24, 24))
        stamp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(stamp)
        heading = label("选择一种水印", "hintTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(heading)
        detail = label("支持文字或图片，设置后实时预览。", "muted")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(detail)
        form.addWidget(self.wm_empty)

        self.wm_text_group = QWidget()
        text = QVBoxLayout(self.wm_text_group)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(12)
        self.wm_text = QLineEdit("仅供参考")
        self.wm_text.setMaxLength(200)
        self.wm_text.setPlaceholderText("输入水印文字")
        self.field(text, "水印内容", self.wm_text)
        self.wm_font = QFontComboBox()
        self.wm_font.setCurrentFont(QFont("Microsoft YaHei"))
        self.field(text, "字体", self.wm_font)
        self.wm_size = QSpinBox()
        self.wm_size.setRange(8, 160)
        self.wm_size.setValue(36)
        self.wm_size.setSuffix(" pt")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.field(row, "字号", self.wm_size)
        self.wm_color = button("选择颜色", self.choose_color)
        self.field(row, "颜色", self.wm_color)
        text.addLayout(row)
        form.addWidget(self.wm_text_group)

        self.wm_image_group = QWidget()
        image = QVBoxLayout(self.wm_image_group)
        image.setContentsMargins(0, 0, 0, 0)
        image.setSpacing(10)
        self.wm_file = button("选择水印图片", self.choose_watermark, "", "image")
        self.wm_file.setToolTip("透明 PNG 可保留透明背景")
        image.addWidget(self.wm_file)
        self.wm_file_label = label("建议使用透明 PNG", "helper")
        image.addWidget(self.wm_file_label)
        self.wm_scale = QSpinBox()
        self.wm_scale.setRange(5, 90)
        self.wm_scale.setValue(28)
        self.wm_scale.setSuffix(" %")
        self.field(image, "图片水印缩放", self.wm_scale)
        image.addWidget(label("相对于页面宽度，支持 5%–90%。", "helper"))
        form.addWidget(self.wm_image_group)

        self.wm_common_group = QWidget()
        common = QVBoxLayout(self.wm_common_group)
        common.setContentsMargins(0, 0, 0, 0)
        common.setSpacing(14)
        self.separator(common)
        self.section_heading(common, "显示效果")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.wm_opacity = QSpinBox()
        self.wm_opacity.setRange(1, 100)
        self.wm_opacity.setValue(25)
        self.wm_opacity.setSuffix(" %")
        self.field(row, "不透明度", self.wm_opacity)
        self.wm_angle = QSpinBox()
        self.wm_angle.setRange(-180, 180)
        self.wm_angle.setValue(30)
        self.wm_angle.setSuffix(" °")
        self.field(row, "倾斜角度", self.wm_angle)
        common.addLayout(row)
        self.wm_position = combo([("居中", "center"), ("左上角", "top-left"), ("右上角", "top-right"), ("左下角", "bottom-left"), ("右下角", "bottom-right")])
        self.field(common, "水印位置", self.wm_position)
        self.wm_tiled = QCheckBox("平铺水印，覆盖整页")
        common.addWidget(self.wm_tiled)
        self.wm_density_group = QWidget()
        density = QVBoxLayout(self.wm_density_group)
        density.setContentsMargins(0, 0, 0, 0)
        density.setSpacing(6)
        self.wm_density = QSpinBox()
        self.wm_density.setRange(1, 10)
        self.wm_density.setValue(3)
        self.wm_density.setSuffix(" 级")
        self.field(density, "平铺密度", self.wm_density)
        density.addWidget(label("1 最稀疏，10 最密集；不改变水印大小。", "helper"))
        common.addWidget(self.wm_density_group)
        self.wm_pages = QLineEdit()
        self.wm_pages.setPlaceholderText("留空应用全部页")
        self.field(common, "应用页码", self.wm_pages)
        common.addWidget(label("指定页码可填写：1,3-5", "helper"))
        form.addWidget(self.wm_common_group)
        form.addStretch()
        for control in [self.wm_kind, self.wm_position]:
            control.currentIndexChanged.connect(self.watermark_change)
        for control in [self.wm_text, self.wm_pages]:
            control.textChanged.connect(self.watermark_change)
        for control in [self.wm_size, self.wm_scale, self.wm_opacity, self.wm_angle, self.wm_density]:
            control.valueChanged.connect(self.watermark_change)
        self.wm_font.currentFontChanged.connect(self.watermark_change)
        self.wm_tiled.toggled.connect(self.watermark_change)
        self.update_watermark_controls()
        self.update_color_button()
        return scroll

    def update_color_button(self):
        swatch = QPixmap(14, 14)
        swatch.fill(QColor(self.watermark.color))
        self.wm_color.setIcon(QIcon(swatch))
        self.wm_color.setToolTip(self.watermark.color)

    def bind_shortcuts(self):
        for key, handler in [("Ctrl+O", self.choose_images), ("Ctrl+E", self.export),
            ("Ctrl+S", self.save_project), ("Alt+Up", lambda: self.move_pages(-1)),
            ("Alt+Down", lambda: self.move_pages(1))]:
            QShortcut(QKeySequence(key), self, activated=handler)
        delete = QShortcut(QKeySequence("Delete"), self.page_list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.remove_pages)

    def pages(self):
        return [self.page_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.page_list.count())]

    def current_page(self):
        item = self.page_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def mark_changed(self, *args):
        self.dirty = True
        self.update_selection_controls()
        self.preview_serial += 1
        self.page_count.setText(f"{self.page_list.count()} 页")
        self.export_button.setEnabled(self.page_list.count() > 0 and not self.importing and not self.exporting)
        self.timer.start()

    def select_page(self, *args):
        self.update_selection_controls()
        page = self.current_page()
        if page:
            self._syncing = True
            self.zoom.setValue(round(page.zoom * 100))
            self.offset_x.setValue(round(page.offset_x * 100))
            self.offset_y.setValue(round(page.offset_y * 100))
            self._syncing = False
        self.preview_serial += 1
        self.timer.start()

    def global_change(self, *args):
        if self._syncing:
            return
        self.layout_options = Layout(self.paper.currentData(), self.orientation.currentData(), self.margin.value(), self.quality.currentData())
        original = self.layout_options.paper == "original"
        self.orientation.setEnabled(not original)
        self.margin.setEnabled(not original)
        self.mark_changed()

    def page_change(self, *args):
        if self._syncing:
            return
        page = self.current_page()
        if page:
            page.zoom, page.offset_x, page.offset_y = self.zoom.value() / 100, self.offset_x.value() / 100, self.offset_y.value() / 100
            self.mark_changed()

    def update_watermark_controls(self):
        kind = self.wm_kind.currentData()
        self.wm_empty.setVisible(kind == "none")
        self.wm_text_group.setVisible(kind == "text")
        self.wm_image_group.setVisible(kind == "image")
        self.wm_common_group.setVisible(kind != "none")
        for widget in [self.wm_text, self.wm_font, self.wm_size, self.wm_color]:
            widget.setEnabled(kind == "text")
        for widget in [self.wm_file, self.wm_scale]:
            widget.setEnabled(kind == "image")
        for widget in [self.wm_opacity, self.wm_angle, self.wm_tiled, self.wm_pages]:
            widget.setEnabled(kind != "none")
        self.wm_position.setEnabled(kind != "none" and not self.wm_tiled.isChecked())
        self.wm_density_group.setVisible(kind != "none" and self.wm_tiled.isChecked())
        self.wm_density.setEnabled(kind != "none" and self.wm_tiled.isChecked())

    def watermark_change(self, *args):
        if self._syncing:
            return
        wm = self.watermark
        wm.kind, wm.text, wm.font_family = self.wm_kind.currentData(), self.wm_text.text(), self.wm_font.currentFont().family()
        wm.font_size, wm.scale, wm.opacity = self.wm_size.value(), self.wm_scale.value() / 100, self.wm_opacity.value() / 100
        wm.angle, wm.position = self.wm_angle.value(), self.wm_position.currentData()
        wm.tiled, wm.pages = self.wm_tiled.isChecked(), self.wm_pages.text()
        wm.density = self.wm_density.value()
        self.update_watermark_controls()
        self.mark_changed()

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.watermark.color), self, "选择文字颜色")
        if color.isValid():
            self.watermark.color = color.name()
            self.update_color_button()
            self.mark_changed()

    def choose_watermark(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择水印图片", str(self.root), IMAGE_FILTER)
        if path:
            self.watermark.image_path = path
            self.wm_file_label.setText(Path(path).name)
            self.mark_changed()

    def drag_image(self, dx, dy):
        page = self.current_page()
        if page and not self.exporting:
            page.offset_x = max(-1.0, min(1.0, page.offset_x + dx))
            page.offset_y = max(-1.0, min(1.0, page.offset_y + dy))
            self.select_page()
            self.mark_changed()

    def rotate(self, angle):
        if self.exporting:
            return
        for item in self.page_list.selectedItems():
            page = item.data(Qt.ItemDataRole.UserRole)
            page.rotation = (page.rotation + angle) % 360
        self.mark_changed()

    def reset_page(self):
        if page := self.current_page():
            page.rotation, page.zoom, page.offset_x, page.offset_y = 0, 1, 0, 0
            self.select_page()
            self.mark_changed()

    def run_job(self, job, done, failed):
        self.jobs.add(job)
        def success(result):
            self.jobs.discard(job)
            done(result)
        def failure(error):
            self.jobs.discard(job)
            failed(error)
        job.signals.done.connect(success)
        job.signals.failed.connect(failure)
        self.pool.start(job)

    def refresh_preview(self):
        if self.preview_busy:
            self.preview_again = True
            return
        page = self.current_page()
        if not page:
            self.preview.clear()
            self.preview_title.setText("页面预览")
            self.preview_info.setText("PDF / JPG / PNG / HEIC / WebP / TIFF 等")
            return
        number, count = self.page_list.currentRow() + 1, self.page_list.count()
        page, layout, watermark = copy.deepcopy(page), copy.copy(self.layout_options), copy.copy(self.watermark)
        serial = self.preview_serial
        self.preview_busy = True
        job = Job(lambda _: png_bytes(render_preview(page, layout, watermark, number, count)))
        def finish(data=None, error=None):
            self.preview_busy = False
            if serial == self.preview_serial:
                if error:
                    self.status.setText("预览提示：" + error)
                else:
                    self.preview.set_image(data)
                    self.preview_title.setText(f"第 {number} 页 / 共 {count} 页")
                    pw, ph, _ = geometry(page, layout)
                    self.preview_info.setText(f"{page.label}  ·  {pw / 72 * 25.4:.0f} × {ph / 72 * 25.4:.0f} mm" + (f"  ·  {page.note}" if page.note else ""))
            if self.preview_again or serial != self.preview_serial:
                self.preview_again = False
                self.timer.start()
        self.run_job(job, lambda data: finish(data=data), lambda error: finish(error=error))

    def choose_images(self):
        if self.exporting:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "添加文件", str(self.root), FILE_FILTER)
        self.add_paths(paths)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "添加文件夹中的图片和 PDF（不含子文件夹）", str(self.root))
        if path:
            self.add_paths([path])

    def add_paths(self, paths):
        if not paths:
            return
        self.pending_paths.extend(paths)
        self.import_timer.start()

    def start_import(self):
        if self.importing or self.exporting:
            return
        if not self.pending_paths:
            return
        paths, self.pending_paths = self.pending_paths, []
        self.importing = True
        self.export_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText("正在读取文件…")
        existing = {(p.path, p.frame) for p in self.pages()}
        def task(signals):
            candidates, errors = [], []
            for value in paths:
                try:
                    path = Path(value).resolve(strict=True)
                    if path.is_dir():
                        candidates.extend(sorted((x for x in path.iterdir() if x.is_file() and x.suffix.lower() in EXTENSIONS), key=lambda x: natural_key(x.name)))
                    elif path.is_file():
                        candidates.append(path)
                except Exception as exc:
                    errors.append(f"{value}：{exc}")
            candidates = list(dict.fromkeys(candidates))
            results = []
            for i, path in enumerate(candidates, 1):
                try:
                    # Reimport can restore individual PDF/TIFF pages removed from the list.
                    results.extend((page, thumb) for page, thumb in inspect_image(str(path)) if (page.path, page.frame) not in existing)
                except Exception as exc:
                    errors.append(f"{path.name}：{exc}")
                signals.progress.emit(i, len(candidates))
            return results, errors
        job = Job(task)
        job.signals.progress.connect(self.import_progress)
        def done(result):
            results, errors = result
            for page, thumb in results:
                pix = QPixmap()
                pix.loadFromData(thumb)
                item = QListWidgetItem(QIcon(pix), page.label)
                item.setData(Qt.ItemDataRole.UserRole, page)
                item.setToolTip(page.path + ("\n" + page.note if page.note else ""))
                self.page_list.addItem(item)
            self.importing = False
            self.progress.hide()
            if self.page_list.currentRow() < 0 and self.page_list.count():
                self.page_list.setCurrentRow(0)
            self.status.setText(f"已添加 {len(results)} 页 · 共 {self.page_list.count()} 页" + (f" · {len(errors)} 个文件未导入" if errors else ""))
            self.mark_changed()
            if errors:
                Messages.warning(self, "部分文件未导入", f"成功添加 {len(results)} 页，{len(errors)} 个文件无法读取。\n支持图片和 PDF。可查看详情了解各文件原因。", details="\n".join(errors))
            if self.pending_paths:
                self.import_timer.start()
        def fail(error):
            self.importing = False
            self.progress.hide()
            self.status.setText(error)
            self.mark_changed()
            if self.pending_paths:
                self.import_timer.start()
        self.run_job(job, done, fail)

    def import_progress(self, current, total):
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.status.setText(f"正在读取文件 {current} / {total}")

    def remove_pages(self):
        if self.exporting:
            return
        for item in self.page_list.selectedItems():
            self.page_list.takeItem(self.page_list.row(item))
        self.mark_changed()

    def move_pages(self, direction):
        if self.exporting:
            return
        selected = self.page_list.selectedItems()
        rows = sorted((self.page_list.row(item) for item in selected), reverse=direction > 0)
        if not rows or min(rows) + direction < 0 or max(rows) + direction >= self.page_list.count():
            return
        current = self.page_list.currentItem()
        for row in rows:
            item = self.page_list.takeItem(row)
            self.page_list.insertItem(row + direction, item)
        self.page_list.setCurrentItem(current)
        for item in selected:
            item.setSelected(True)
        self.mark_changed()

    def sort_pages(self):
        items = [self.page_list.takeItem(0) for _ in range(self.page_list.count())]
        items.sort(key=lambda item: (natural_key(item.data(Qt.ItemDataRole.UserRole).path), item.data(Qt.ItemDataRole.UserRole).frame))
        for item in items:
            self.page_list.addItem(item)
        if items:
            self.page_list.setCurrentRow(0)
        self.mark_changed()

    def list_menu(self, position):
        menu = QMenu(self)
        menu.addAction("合并为 PDF…", self.export)
        menu.addSeparator()
        menu.addAction("上移", lambda: self.move_pages(-1))
        menu.addAction("下移", lambda: self.move_pages(1))
        menu.addAction("按文件名排序", self.sort_pages)
        menu.addAction("顺时针旋转", lambda: self.rotate(90))
        menu.addSeparator()
        menu.addAction("从列表移除", self.remove_pages)
        menu.exec(self.page_list.mapToGlobal(position))

    def tools_menu(self):
        menu = QMenu(self)
        menu.addAction("保存编辑方案…  Ctrl+S", self.save_project)
        menu.addAction("打开编辑方案…", self.load_project)
        menu.addSeparator()
        menu.addAction("安装右键「合并为 PDF」", lambda: self.shell_change(True))
        menu.addAction("卸载右键菜单", lambda: self.shell_change(False))
        menu.addSeparator()
        menu.addAction("支持格式与使用说明", self.help)
        menu.exec(self.tools_button.mapToGlobal(self.tools_button.rect().bottomLeft()))

    def shell_change(self, install):
        from .shell import install_menu, uninstall_menu
        try:
            result = install_menu(self.root) if install else uninstall_menu()
            Messages.information(self, "右键菜单", result)
        except Exception as exc:
            Messages.warning(self, "右键菜单未完成", str(exc))

    def help(self):
        Messages.information(self, "合页 · 使用说明",
            "1. 添加或拖入图片 / PDF / 文件夹。\n2. 拖动左侧卡片调整页序，右侧设置排版和水印。\n3. 点击「导出 PDF」，选择保存位置。\n\n"
            "支持 PDF / JPG / PNG / BMP / WebP / TIFF / GIF / HEIC / HEIF / AVIF / SVG / ICO / JPEG 2000 等。\n"
            "PDF / TIFF 多页自动展开；动态图片仅取首帧；PSD 仅读取兼容合成预览，不编辑图层；SVG 栅格化。\n"
            "PDF 保留文字与矢量，批注与表单按外观转为固定内容，不保留签名效力、交互表单、附件与书签。需要打开密码的 PDF 请先解密另存。\n不支持相机 RAW、AI / EPS 或损坏的文件。单张图片上限 8000 万像素。\n\n"
            "右键入口：更多 → 安装右键菜单。Windows 11 通常位于「显示更多选项」，传统入口最多选择 100 个文件。更多文件请拖入窗口或添加文件夹。\n\n"
            "编辑方案保存源文件路径和设置，不打包图片与 PDF。移动或备份时需同时保留源文件。所有处理均在本机完成。")

    def save_project(self):
        if self.importing or self.exporting:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存编辑方案", str(self.root / "合页方案.ipdf.json"), "合页方案 (*.ipdf.json)")
        if path:
            try:
                Path(path).write_text(json.dumps(project_data(self.pages(), self.layout_options, self.watermark), ensure_ascii=False, indent=2), encoding="utf-8")
                self.dirty = False
                self.status.setText("编辑方案已保存 · 请同时保留原始图片和 PDF")
            except Exception as exc:
                Messages.warning(self, "保存失败", str(exc))

    def load_project(self):
        if self.importing or self.exporting or not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开编辑方案", str(self.root), "合页方案 (*.ipdf.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if data.get("version") != 1:
                raise ValueError("不支持的方案版本。")
            pages = [Page(**x) for x in data["pages"]]
            layout, watermark = Layout(**data["layout"]), Watermark(**data["watermark"])
            if layout.paper not in {*PAPERS, "original"} or layout.orientation not in {"auto", "portrait", "landscape"} or layout.quality not in {"original", "high", "compact"}:
                raise ValueError("方案包含无效的页面设置。")
            if watermark.kind not in {"none", "text", "image"} or not 0 < watermark.opacity <= 1 or not 8 <= watermark.font_size <= 160 or not .05 <= watermark.scale <= .9:
                raise ValueError("方案包含无效的水印设置。")
            if type(watermark.density) is not int or not 1 <= watermark.density <= 10:
                raise ValueError("方案中的平铺密度应为 1 至 10 的整数。")
            if any(not Path(p.path).is_file() for p in pages):
                raise ValueError("方案中的部分源文件已移动或不存在，请先恢复源文件路径。")
            if any(not .05 <= p.zoom <= 2.5 or abs(p.offset_x) > 1 or abs(p.offset_y) > 1 or p.rotation not in {0,90,180,270} for p in pages):
                raise ValueError("方案包含无效的内容位置。")
            from .imaging import load_image
            thumbs = []
            for page in pages:
                image = load_image(page.path, page.frame, 190)
                thumbs.append(png_bytes(image))
            self.page_list.clear()
            for page, thumb in zip(pages, thumbs):
                pix = QPixmap()
                pix.loadFromData(thumb)
                item = QListWidgetItem(QIcon(pix), page.label)
                item.setData(Qt.ItemDataRole.UserRole, page)
                self.page_list.addItem(item)
            self.layout_options, self.watermark = layout, watermark
            self.sync_controls()
            if pages:
                self.page_list.setCurrentRow(0)
            self.mark_changed()
            self.dirty = False
        except Exception as exc:
            Messages.warning(self, "无法打开方案", str(exc))

    def sync_controls(self):
        self._syncing = True
        l, w = self.layout_options, self.watermark
        for control, value in [(self.paper,l.paper), (self.orientation,l.orientation), (self.quality,l.quality), (self.wm_kind,w.kind), (self.wm_position,w.position)]:
            control.setCurrentIndex(control.findData(value))
        for control, value in [(self.margin,l.margin_mm), (self.wm_size,w.font_size), (self.wm_scale,w.scale*100), (self.wm_opacity,w.opacity*100), (self.wm_angle,w.angle), (self.wm_density,w.density)]:
            control.setValue(round(value))
        self.wm_text.setText(w.text)
        self.wm_pages.setText(w.pages)
        self.wm_font.setCurrentFont(QFont(w.font_family))
        self.wm_tiled.setChecked(w.tiled)
        self.wm_file_label.setText(Path(w.image_path).name if w.image_path else "建议使用透明 PNG")
        self.update_color_button()
        self.orientation.setEnabled(l.paper != "original")
        self.margin.setEnabled(l.paper != "original")
        self.update_watermark_controls()
        self._syncing = False

    def export(self):
        if self.exporting or self.importing or not self.page_list.count():
            return
        try:
            if self.watermark.kind != "none":
                page_selection(self.watermark.pages, self.page_list.count())
                if self.watermark.kind == "text" and not self.watermark.text.strip():
                    raise ValueError("请填写水印文字。")
                if self.watermark.kind == "image" and not Path(self.watermark.image_path).is_file():
                    raise ValueError("请先选择有效的水印图片。")
        except ValueError as exc:
            Messages.warning(self, "请检查水印", str(exc))
            return
        output_folder = self.root / "outputs"
        output_folder.mkdir(exist_ok=True)
        selection = choose_export(self, output_folder, self.page_list.count(), self.layout_options, self.watermark)
        if selection is None:
            return
        path, overwrite = selection
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.exporting = True
        self.splitter.setEnabled(False)
        self.export_button.setEnabled(False)
        self.tools_button.setEnabled(False)
        cancel = threading.Event()
        progress = ExportProgressDialog(self, self.page_list.count())
        progress.canceled.connect(cancel.set)
        progress.show()
        pages, layout, wm = copy.deepcopy(self.pages()), copy.copy(self.layout_options), copy.copy(self.watermark)
        job = Job(lambda signals: export_pdf(pages, layout, wm, path, cancel.is_set, signals.progress.emit, overwrite))
        job.signals.progress.connect(lambda current, total: progress.setValue(current))
        def finish(result=None, error=None):
            progress.finish()
            progress.deleteLater()
            self.exporting = False
            self.splitter.setEnabled(True)
            self.export_button.setEnabled(True)
            self.tools_button.setEnabled(True)
            if error:
                self.status.setText(error)
                if not cancel.is_set():
                    Messages.warning(self, "导出未完成", error)
            else:
                self.output_path = result["path"]
                self.dirty = False
                self.open_output.show()
                self.status.setText(f"已导出 {result['pages']} 页 · {result['bytes'] / 1_000_000:.2f} MB · {result['path']}")
            if self.pending_paths:
                self.import_timer.start()
        self.run_job(job, lambda result: finish(result=result), lambda error: finish(error=error))

    def open_pdf(self):
        if self.output_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_path))

    def confirm_discard(self, closing=False):
        if self.dirty and self.page_list.count():
            return Messages.confirm(self, "退出合页？" if closing else "打开其他编辑方案？",
                "当前编辑尚未保存。离开后，本次页序、排版和水印设置将丢失。\n可继续编辑，并通过「更多 → 保存编辑方案」保留。",
                confirm_text="退出合页" if closing else "放弃并打开", cancel_text="继续编辑")
        return True

    def closeEvent(self, event):
        if self.importing or self.exporting:
            Messages.information(self, "正在处理", "请等待文件导入完成，或取消 PDF 导出后再关闭。")
            event.ignore()
            return
        if not self.confirm_discard(closing=True):
            event.ignore()
            return
        self.timer.stop()
        self.pool.waitForDone()
        event.accept()
