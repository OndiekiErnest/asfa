disksTab = """
QTabBar::tab {
    padding-right: 3px;
    padding-left: 3px;
    color: black;
}
QTabBar::tab:selected {
    background-color: #ffffff;
}
QTabBar::tab:!selected {
    background-color: #5bc0eb;
}
QTabBar::tab:!selected:hover {
    border: 1px solid #f7fffe;
}
"""

# main styling
QSS = """
QWidget#mainWindow {
    background-color: #211a1e;
    color: #ffffff;
}
QWidget#duplicatesWindow QLabel {
    color: black;
}
QWidget#duplicatesWindow QListWidget {
    color: black;
    font: 12px;
}
QWidget#duplicatesWindow QScrollBar {
    background-color: #ffffff;
}
QWidget#duplicatesWindow QScrollBar::handle {
    background-color: gray;
}
QWidget#duplicatesWindow QScrollBar::handle:hover {
    background-color: #353535;
}
QWidget#duplicatesWindow QScrollBar::add-line:horizontal, QWidget#duplicatesWindow QScrollBar::add-line:vertical {
    background-color: #ffffff;
}
QWidget#duplicatesWindow QScrollBar::sub-line:horizontal, QWidget#duplicatesWindow QScrollBar::sub-line:vertical {
    background-color: #ffffff;
}
QWidget#transferWin QLabel {
    color: black;
    font: 12px;
}
QWidget#folderPopup QLabel {
    color: black;
}
QWidget#folderPopup QLineEdit {
    color: black;
    background-color: #ffffff;
    border: 1px solid #211a1e;
}
QWidget {
    font: 16px;
    color: #ffffff;
}
QGroupBox {
    border: 2px solid gray;
    border-radius: 5px;
    margin-top: 4ex;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top center;
    /*background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #ff0ece, stop: 1 #ffffff);*/
}
QGroupBox#extensionsGroup, QGroupBox#optionsGroup {
    color: black;
}
QGroupBox#extensionsGroup * {
    color: black;
    font: 12px;
}
QGroupBox#optionsGroup * {
    color: black;
}
.QPushButton {
    background-color: #5bc0eb;
    color: black;
}
.QPushButton:hover {
    border: 2px solid #f7fffe;
    border-radius: 5px;
}
.QPushButton:enabled {
    color: black;
}
.QPushButton:disabled {
    color: gray;
}
.QPushButton:pressed {
    background-color: #1f8eb0;
}
QPushButton#startServer {
    background-color: #1fa831;
}
QPushButton#stopServer {
    background-color: #fe9800;
}
QTabWidget::pane {
    border: 1px solid #211a1e;
    top: -1px;
    background-color: #211a1e;
}
QTabBar::tab {
    border: 1px solid #211a1e;
    padding: 0px 25px;
    color: black;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    border-top: 10px solid #ffffff;
    border-bottom: 10px solid #ffffff;
    margin-bottom: -1px;
}
QTabBar::tab:!selected {
    background-color: #5bc0eb;
}
QTabBar::tab:!selected:hover {
    border: 2px solid #f7fffe;
}
QLineEdit {
    background-color: #282828;
    color: #ffffff;
}
QLineEdit#searchInput {
    background-color: #353535;
}
QLineEdit:read-only, QLineEdit:focus:read-only {
    background-color: #211a1e;
    color: #ffffff;
    border: solid gray;
    /* top right bottom left */
    border-width: 0 0 1px 0;
}
QLineEdit:focus, QLineEdit#searchInput:focus, QComboBox:focus {
    border: 1px solid #5bc0eb;
}
QLineEdit#ipInput {
    padding-top: 2px;
    padding-bottom: 2px;
}
QSpinBox {
    background-color: #282828;
    color: #ffffff;
}
QComboBox {
    background-color: #282828;
    color: #ffffff;
}
QComboBox::drop-down {
    padding-left: 1px;
}
QComboBox QAbstractItemView, QCompleter QAbstractItemView, QListView {
    background-color: #ffffff;
    color: black;
}
QTableView {
    background-color: #282828;
    alternate-background-color: #353535;
    color: #ffffff;
}
QHeaderView {
    background-color: #5bc0eb;
    color: black;
}
QMenu#trayMenu {
    background-color: #211a1e;
    padding: 5px;
}
QMenu {
    background-color: #ffffff;
    color: black;
    padding: 5px;
}
QMenu::item {
    background-color: #ffffff;
    color: black;
}
QMenu::item:disabled {
    color: gray;
}
QMenu::item:selected {
    border: 2px solid black;
}
QScrollBar {
    background-color: #282828;
}
QScrollBar::handle {
    background-color: #353535;
}
QScrollBar::handle:hover {
    background-color: gray;
}
QScrollBar::add-line:vertical, QScrollBar::add-line:horizontal {
    background-color: #282828;
}
QScrollBar::sub-line:vertical, QScrollBar::sub-line:horizontal {
    background-color: #282828;
}
QMessageBox QLabel {
    color: black;
}
QWidget#downloadsWin QListView {
    background-color: #282828;
    color: #ffffff;
    padding-left: 5px;
    alternate-background-color: #353535;
    border: 1px solid gray;
    border-radius: 2px;
}
QLabel#leftStatusBar, QLabel#centerStatusBar, QLabel#rightStatusBar {
    font: 12px;
}
QLabel#fetchStatus, QLabel#noteLabel {
    background-color: #ffffff;
    color: black;
    border: 2px solid black;
    border-radius: 10px;
    min-width: 180px;
    padding-top: 1px;
    padding-bottom: 1px;
}
"""
