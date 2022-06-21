__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"

from common import logging, os, OS_SEP, valid_ip, Icons
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, QSortFilterProxyModel, QStringListModel, QRegExp
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QLineEdit, QFileDialog, QFrame,
    QTabBar, QStyle, QStylePainter, QStyleOptionTab,
    QTabWidget, QAction, QCompleter, QComboBox, QTableView,
)


cw_logger = logging.getLogger(__name__)
cw_logger.info(f">>> Initialized {__name__}")


# ---------------------- CUSTOM LINE -------------------------------------------------------


class Line(QFrame):
    def __init__(self, h=1):
        super().__init__()
        if h:
            # defaults to horizontal line
            self.setFrameShape(QFrame.HLine)
        else:
            self.setFrameShape(QFrame.VLine)
        self.setFrameShadow(QFrame.Sunken)

# ---------------------- END CUSTOM LINE -------------------------------------------------------


class LineEdit(QLineEdit):
    """ custom QLineEdit that shows error icon if it is empty on text() call """

    __slots__ = ("error_action", "usernames", "prev_text", "comp")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.error_action = QAction()
        self.error_action.setIcon(QIcon(Icons.error_icon))

        self.usernames = set()
        self.prev_text = ""

        self.comp = Completer(parent=self)
        self.comp.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(self.comp)

    def add_names(self, names):
        """ add unique user names """
        self.usernames.update(names)
        self.comp.setModel(self.usernames)
        cw_logger.info(f"Added usernames {self.usernames}")

    def focusInEvent(self, e):
        current_text = self.text()
        if current_text:
            self.prev_text = current_text
        # self.clear()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        current_text = self.text()
        if not current_text:
            self.setText(self.prev_text)
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        key = e.key()
        if (key == Qt.Key_Return) or (key == Qt.Key_Enter):
            # avoid setting an empty str
            self.comp.popup().hide()
            text = self.comp.currentCompletion()
            self.setText(text)
            e.accept()
        else:
            return super().keyPressEvent(e)

    def text(self):
        text = super().text()
        if text:
            self.remove_error()
        else:
            self.error_action.setToolTip("This field is required")
            self.raise_error()
        self.update()
        return text

    def setText(self, text: str):
        """ remove error icon if text """
        if text:
            self.remove_error()
        # else:
        #     self.raise_error()
        self.update()
        # set text
        super().setText(text)

    def remove_error(self):
        """ remove error icon """
        try:
            self.error_action.setToolTip("This field is required")
            self.removeAction(self.error_action)
        except Exception:
            pass

    def raise_error(self):
        """ add error icon """
        try:
            self.addAction(self.error_action, QLineEdit.LeadingPosition)
        except Exception:
            pass


class PathEdit(LineEdit):
    """
    custom QLineEdit for path display, set to readOnly
    """
    __slots__ = ("caption", "last_known_dir", )

    def __init__(self, chooser_title, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.caption = chooser_title
        self.last_known_dir = os.path.expanduser(f"~{OS_SEP}Documents")

        self.textChanged.connect(self.validate)
        self.setToolTip("Click folder icon to browse")

        add_action = QAction(self)
        add_action.setObjectName("addPathAction")
        add_action.setIcon(QIcon(Icons.add_folder_icon))
        add_action.setToolTip("Browse")
        add_action.triggered.connect(self.get_dir)
        self.addAction(add_action, QLineEdit.TrailingPosition)
        # disable input
        self.setReadOnly(True)

    def get_dir(self):
        """ set abs folder str """
        folder = os.path.normpath(QFileDialog.getExistingDirectory(
            self, caption=f"{self.caption}",
            directory=self.last_known_dir,
        ))
        if folder and folder != ".":
            self.last_known_dir = folder
            self.setText(folder)

    def text(self):
        """ return a text str if it's a valid path """
        text = super().text()
        # raise errors if any
        self.validate(text)
        if not os.path.exists(text):
            text = ""
        return text

    def validate(self, text: str):
        """ set error icon if path does not exist """
        if text:
            if os.path.exists(text):
                self.remove_error()
            else:
                self.error_action.setToolTip("The path does not exist")
                self.raise_error()


class PasswordEdit(LineEdit):
    """
    custom QLineEdit for password display, with show/hide
    """
    __slots__ = ("show_action", )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # set masked input
        self.setEchoMode(QLineEdit.Password)
        self.show_action = QAction(self)
        self.show_action.setToolTip("Show password")
        self.show_action.setIcon(QIcon(Icons.show_icon))
        # since it defaults to hide, show on first click
        self.show_action.triggered.connect(self.show)
        self.addAction(self.show_action, QLineEdit.TrailingPosition)

    def show(self):
        """ show password """
        self.show_action.triggered.disconnect()
        self.show_action.setToolTip("Hide password")
        self.show_action.setIcon(QIcon(Icons.hide_icon))
        self.setEchoMode(QLineEdit.Normal)
        # when clicked again, hide
        self.show_action.triggered.connect(self.hide)

    def hide(self):
        """ hide password """
        self.show_action.triggered.disconnect()
        self.show_action.setToolTip("Show password")
        self.show_action.setIcon(QIcon(Icons.show_icon))
        self.setEchoMode(QLineEdit.Password)
        # when clicked again, show
        self.show_action.triggered.connect(self.show)


# ------------------------------------ CUSTOM TAB WIDGET ------------------------------------------
class TabBar(QTabBar):
    """
        create vertical tabs with horizontal texts
    """

    def tabSizeHint(self, index):
        s = QTabBar.tabSizeHint(self, index)
        s.transpose()
        return s

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOptionTab()

        for i in range(self.count()):
            self.initStyleOption(opt, i)
            painter.drawControl(QStyle.CE_TabBarTabShape, opt)
            painter.save()

            # s = opt.rect.size()
            s = QSize(200, 300)
            s.transpose()
            r = QRect(QPoint(), s)
            r.moveCenter(opt.rect.center())
            opt.rect = r

            c = self.tabRect(i).center()
            painter.translate(c)
            painter.rotate(90)
            painter.translate(-c)
            # set the font
            font = painter.font()
            font.setPointSize(14)
            painter.setFont(font)
            painter.drawControl(QStyle.CE_TabBarTabLabel, opt)
            painter.restore()


class TabWidget(QTabWidget):
    """
        create vertical tabs with horizontal icons and texts
    """

    def __init__(self, *args, **kwargs):
        QTabWidget.__init__(self, *args, **kwargs)
        self.setTabBar(TabBar(self))
        self.setTabPosition(QTabWidget.West)
# --------------------------------------------- END OF CUSTOM TAB WIDGET ---------------------------------


# custom search input
class SearchInput(QLineEdit):
    """
    custom QLineEdit for search
    """
    __slots__ = ("close_action", )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # introduce files searched model

        self.setObjectName("searchInput")
        self.close_action = QAction(self)
        self.close_action.setIcon(QIcon(Icons.cancel_icon))
        self.close_action.triggered.connect(self.close_search)

        self.addAction(QIcon(Icons.search_icon), QLineEdit.LeadingPosition)
        self.textChanged.connect(self.on_type)

    def close_search(self):
        """ clear search area and change icon """
        self.clear()
        self.removeAction(self.close_action)

    def on_type(self, txt):
        """ change icon, close on action triggered """
        if txt:
            self.addAction(self.close_action, QLineEdit.TrailingPosition)
        else:
            self.removeAction(self.close_action)


class IPInput(LineEdit):
    """ custom ip address line edit """

    __slots__ = ()

    def __init__(self):
        super().__init__()
        self.setObjectName("ipInput")
        self.textChanged.connect(self.validate)

    def validate(self, text: str):
        """ validate ip """
        if text:
            if valid_ip(text):
                self.remove_error()
            else:
                self.error_action.setToolTip("The address is not valid")
                self.raise_error()


class Completer(QCompleter):
    """ custom completer """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.local_prefix = ""
        self.source_model = None
        self.filter_model = QSortFilterProxyModel(self)
        self.using_original_model = False

    def setModel(self, model):
        if isinstance(model, (list, tuple, set)):
            model = QStringListModel(model)
        self.source_model = model
        self.filter_model = QSortFilterProxyModel(self)
        self.filter_model.setSourceModel(self.source_model)
        super().setModel(self.filter_model)
        self.using_original_model = True

    def updateModel(self):
        if not self.using_original_model:
            self.filter_model.setSourceModel(self.source_model)

        pattern = QRegExp(self.local_prefix,
                          Qt.CaseInsensitive, QRegExp.FixedString)
        self.filter_model.setFilterRegExp(pattern)

    def splitPath(self, path):
        self.local_prefix = path
        self.updateModel()
        if self.filter_model.rowCount() == 0:
            self.using_original_model = False
            self.filter_model.setSourceModel(QStringListModel([path]))
            return [path]
        return []


class DNEdit(QComboBox):
    """ custom server name line edit """

    __slots__ = ("comp", "prev_text", "u_users", "line_edit", "error_action")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setEditable(True)
        self.setInsertPolicy(self.NoInsert)
        self.editTextChanged.connect(self.validate)

        self.line_edit = self.lineEdit()
        self.u_users = set()
        self.prev_text = ""
        self.error_action = QAction()
        self.error_action.setIcon(QIcon(Icons.error_icon))

        self.comp = Completer(self)
        self.comp.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(self.comp)

    def drop_error(self):
        """ remove error QAction to the line edit """
        self.line_edit.removeAction(self.error_action)

    def validate(self, text):
        if not text:
            self.error_action.setToolTip("This field is required")
            self.line_edit.addAction(
                self.error_action, QLineEdit.LeadingPosition)
        elif text not in self.u_users:
            self.error_action.setToolTip("Server name not known")
            self.line_edit.addAction(
                self.error_action, QLineEdit.LeadingPosition)
        else:
            self.drop_error()

    def add_name(self, txt):
        """ add unique server names """
        if txt not in self.u_users:
            self.u_users.add(txt)
            self.addItem(txt)
            self.comp.setModel(self.model())
            cw_logger.info(f"Added new server name '{txt}'")

    def remove_name(self, name):
        """ drop name """
        if name in self.u_users:
            self.u_users.remove(name)
            index = self.findText(name)
            self.removeItem(index)
            cw_logger.info(f"Removed index '{index}'")

    def focusInEvent(self, e):
        current_text = self.currentText()
        if current_text:
            self.prev_text = current_text
        self.clearEditText()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        current_text = self.currentText()
        if not current_text:
            self.drop_error()
            self.setEditText(self.prev_text)
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        key = e.key()
        if (key == Qt.Key_Return) or (key == Qt.Key_Enter):
            # avoid setting an empty str
            self.comp.popup().hide()
            text = self.comp.currentCompletion()
            self.setEditText(text)
        return super().keyPressEvent(e)


# class TableView(QTableView):
#     """ custom QTableView class with drag n drop re-implemented """

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)

#         self.setAcceptDrops(True)
#         self.setDragEnabled(True)
#         self.setDropIndicatorShown(True)
#         self.setSelectionBehavior(QTableView.SelectRows)
#         self.setDragDropMode(QTableView.InternalMove)

#     def dragEnterEvent(self, event):
#         if event.mimeData().hasUrls():
#             event.accept()
#         else:
#             super().dragEnterEvent(event)

#     def dragMoveEvent(self, event):
#         if event.mimeData().hasUrls():
#             event.setDropAction(Qt.CopyAction)
#             event.accept()
#         else:
#             super().dragMoveEvent(event)

#     def dragEvent(self, event):
#         if event.mimeData().hasUrls():
#             event.setDropAction(Qt.CopyAction)
#             event.accept()
#             file_links = [url.toLocalFile()
#                           for url in event.mimeData().urls() if url.isLocalFile()]
#             print(file_links)
#         else:
#             super().dragEvent(event)
