"""Neutral desktop workspace: typography, spacing and grayscale hierarchy."""
from .icons import ASSETS
from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtGui import QColor, QFont, QPalette

COLORS = {
    "white": "#FFFFFF",
    "sidebar": "#F7F7F7",
    "surface": "#F0F0F0",
    "hover": "#EAEAEA",
    "border": "#E4E4E4",
    "text": "#242424",
    "muted": "#6B6B6B",
    "disabled": "#AAAAAA",
}


def ui_font(size=13):
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def apply_style(app):
    if not hasattr(app, "_pdfedit_translator"):
        translator = QTranslator(app)
        if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(translator)
        app._pdfedit_translator = translator
    app.setStyle("Fusion")
    app.setFont(ui_font())
    palette = QPalette()
    for role, token in [(QPalette.ColorRole.Window, "white"), (QPalette.ColorRole.Base, "white"),
        (QPalette.ColorRole.AlternateBase, "sidebar"), (QPalette.ColorRole.Button, "white"),
        (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "text"),
        (QPalette.ColorRole.HighlightedText, "white"), (QPalette.ColorRole.Link, "text"),
        (QPalette.ColorRole.PlaceholderText, "muted")]:
        palette.setColor(role, QColor(COLORS[token]))
    for role in [QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText]:
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(COLORS["disabled"]))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


STYLE = """
QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: @text@; }
QMainWindow, #root { background: @white@; }
QFrame#dialogCard { background: @white@; border: 1px solid @border@; border-radius: 10px; }
#dialogTitle { color: @text@; font-size: 18px; font-weight: 600; }
#dialogBody { color: @muted@; font-size: 13px; }
#dialogSummary { background: @sidebar@; border: 1px solid @border@; border-radius: 6px; }
#dialogValidation { color: @text@; font-size: 12px; }
QPlainTextEdit#dialogDetails { background: @sidebar@; color: @text@; border: 1px solid @border@; border-radius: 5px; padding: 10px; }
QPushButton#dialogClose { background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 4px; }
QPushButton#dialogClose:hover { background: @surface@; }
QPushButton#dialogClose:focus { border-color: @text@; }
QProgressBar#dialogProgress { min-height: 5px; max-height: 5px; }
QFileDialog#appFileDialog { background: @white@; }
QFileDialog QTreeView, QFileDialog QListView { background: @white@; border: 1px solid @border@; border-radius: 5px; outline: none; }
QFileDialog QTreeView::item, QFileDialog QListView::item { min-height: 27px; padding: 2px; }
QFileDialog QTreeView::item:selected, QFileDialog QListView::item:selected { background: @surface@; color: @text@; }
QFileDialog QHeaderView::section { background: @sidebar@; color: @muted@; border: none; border-bottom: 1px solid @border@; padding: 7px; }
QFileDialog QToolButton { background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 5px; }
QFileDialog QToolButton:hover { background: @surface@; }
QFileDialog QToolButton:focus { border-color: @text@; }
QLabel { background: transparent; }
#header { background: @white@; border-bottom: 1px solid @border@; }
#footer { background: @white@; border-top: 1px solid @border@; }
#brand { color: @text@; font-size: 17px; font-weight: 600; }
#headerTag { color: @muted@; font-size: 12px; }
#panelTitle { font-size: 13px; font-weight: 600; color: @text@; }
#sectionTitle { font-size: 12px; font-weight: 600; color: @text@; }
#fieldLabel { color: @muted@; font-size: 12px; }
#muted, #previewInfo { color: @muted@; font-size: 12px; }
#pageCount { color: @muted@; background: transparent; font-size: 11px; padding: 0; }
#leftPanel { background: @sidebar@; }
#centerPanel, #previewHead { background: @white@; }
#sidePanel { background: @white@; }
#separator { background: @border@; max-height: 1px; }
#helper { color: @muted@; font-size: 11px; }
#hintBox { background: @sidebar@; border: none; border-radius: 6px; }
#hintTitle { font-size: 12px; font-weight: 400; }
QPushButton { background: @white@; border: 1px solid @border@; border-radius: 6px; padding: 7px 10px; font-weight: 400; }
QPushButton:hover { background: @surface@; border-color: @border@; }
QPushButton:pressed { background: @hover@; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid @text@; }
QPushButton:disabled { color: @disabled@; background: @sidebar@; border-color: @border@; }
QPushButton#primary { color: @white@; background: @text@; border-color: @text@; font-weight: 500; padding: 8px 16px; }
QPushButton#primary:hover { background: @muted@; border-color: @muted@; }
QPushButton#primary:pressed { background: @text@; }
QPushButton#primary:focus { border: 2px solid @muted@; padding: 7px 15px; }
QPushButton#primary:disabled { background: @surface@; border-color: @surface@; color: @disabled@; }
QPushButton#addImages { background: @white@; color: @text@; border-color: @border@; padding: 7px 10px; }
QPushButton#addImages:hover { background: @hover@; }
QPushButton#addImages:focus { border-color: @text@; }
QPushButton#subtle { background: transparent; border: 1px solid transparent; color: @muted@; padding: 7px 9px; }
QPushButton#subtle:hover { background: @surface@; color: @text@; }
QPushButton#subtle:focus { border-color: @text@; }
QPushButton#subtle:disabled { color: @disabled@; background: transparent; border-color: transparent; }
QPushButton#iconButton { padding: 7px; background: transparent; border-color: transparent; }
QPushButton#iconButton:hover { background: @hover@; }
QPushButton#iconButton:focus { border-color: @text@; }
QPushButton#navButton { padding: 6px; border-color: transparent; background: transparent; }
QPushButton#navButton:hover { background: @surface@; }
QPushButton#navButton:focus { border-color: @text@; }
QPushButton#resetButton { color: @muted@; padding: 7px 10px; background: transparent; border-color: transparent; }
QPushButton#resetButton:hover { background: @surface@; }
QPushButton#resetButton:focus { border-color: @text@; }
QPushButton#resetButton:disabled { color: @disabled@; background: transparent; border-color: transparent; }
QListWidget#pageList { background: transparent; border: none; outline: none; }
QListWidget::item { border: none; }
QListWidget#textBlocks { background: @sidebar@; border: 1px solid @border@; border-radius: 5px; outline: none; }
QListWidget#textBlocks::item { padding: 7px 5px; color: @text@; }
QListWidget#textBlocks::item:selected { background: @hover@; color: @text@; }
QSplitter::handle { background: @border@; }
QSplitter::handle:hover { background: @disabled@; }
QScrollArea { border: none; background: @white@; }
QScrollArea > QWidget > QWidget { background: @white@; }
QTabWidget::pane { border: none; background: @white@; }
QTabWidget::tab-bar { left: 0; }
QTabBar { background: @white@; }
QTabBar::tab { background: @white@; border: none; border-bottom: 1px solid @border@; color: @muted@; padding: 15px 14px 14px 14px; }
QTabBar::tab:hover { color: @text@; background: @sidebar@; }
QTabBar::tab:selected { color: @text@; border-bottom: 2px solid @text@; padding-bottom: 13px; font-weight: 600; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QFontComboBox { background: @sidebar@; border: 1px solid @border@; border-radius: 5px; padding: 6px 9px; min-height: 20px; selection-background-color: @text@; selection-color: @white@; }
QComboBox:hover, QLineEdit:hover, QSpinBox:hover { border-color: @disabled@; }
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled { background: @sidebar@; color: @disabled@; border-color: @border@; }
QComboBox { padding-right: 27px; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url(__ICONS__/down.svg); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: @white@; border: 1px solid @border@; selection-background-color: @surface@; selection-color: @text@; outline: none; padding: 4px; }
QComboBox QAbstractItemView::item { min-height: 28px; }
QSpinBox { padding-right: 28px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 25px; border: none; border-top-right-radius: 5px; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 25px; border: none; border-bottom-right-radius: 5px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: @hover@; }
QSpinBox::up-arrow { image: url(__ICONS__/up.svg); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url(__ICONS__/down.svg); width: 12px; height: 12px; }
QCheckBox { spacing: 8px; color: @text@; font-size: 12px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid @disabled@; background: @white@; border-radius: 3px; }
QCheckBox::indicator:checked { background: @text@; border-color: @text@; image: url(__ICONS__/check-light.svg); }
QCheckBox::indicator:focus { border: 1px solid @text@; }
QProgressBar { border: none; background: @surface@; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: @text@; border-radius: 2px; }
QMenu { background: @white@; border: 1px solid @border@; padding: 5px; }
QMenu::item { padding: 8px 20px; border-radius: 4px; }
QMenu::item:selected { background: @surface@; }
QMenu::separator { height: 1px; background: @border@; margin: 5px 10px; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: @border@; min-height: 30px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: @disabled@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: @text@; color: @white@; border: none; padding: 7px 10px; }
""".replace("__ICONS__", (ASSETS / "icons").as_posix())
for _token, _color in COLORS.items():
    STYLE = STYLE.replace("@" + _token + "@", _color)
