__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"

import sys
from common import logging, pass_hash, MACHINE_IP, _join, Icons, SAFEGUARD_PASSWORD

from PyQt5.QtCore import Qt, QSortFilterProxyModel, pyqtSignal
from PyQt5.QtSql import QSqlDatabase, QSqlTableModel, QSqlQuery
from customWidgets import (
    PathEdit, SearchInput, QIcon,
    Line, PasswordEdit, LineEdit, IPInput,
)

from PyQt5.QtWidgets import (
    QApplication,
    QDataWidgetMapper,
    QFormLayout,
    QHBoxLayout,
    QTableView,
    QVBoxLayout,
    QWidget, QLabel,
    QSpinBox, QPushButton,
)


ss_logger = logging.getLogger(__name__)
ss_logger.info(f">>> Initialized {__name__}")


db = QSqlDatabase("QSQLITE")
db.setDatabaseName(_join("allowed.sqlite"))
is_open = db.open()

if is_open:
    ss_logger.debug("DB Open")

    class ServerSettingsWindow(QWidget):
        """ Server settings manager """

        new_user_signal = pyqtSignal(str, str, str)
        delete_user_signal = pyqtSignal(str)
        start_server_signal = pyqtSignal(str)
        stop_server_signal = pyqtSignal()

        def __init__(self):
            super().__init__()

            headers = {"id": "Index", "username": "Username", "access_folder": "Access Folder"}
            # start query and create table first, before creating self.model [recommended]
            self.query = QSqlQuery(db=db)

            if not ("User" in db.tables()):
                done = self.create_table()
                ss_logger.debug(f"Done creating Table: {done}")

            # prepare layouts
            main_hlayout = QHBoxLayout()
            server_controls_layout = QHBoxLayout()
            server_cred_form_layout = QFormLayout()
            left_side_layout = QVBoxLayout()
            left_side_layout.addLayout(server_cred_form_layout)
            right_side_layout = QVBoxLayout()
            form = QFormLayout()

            self.server_ip = IPInput()
            # drag/drop text
            self.server_ip.setDragEnabled(True)
            # disable editing by default
            self.server_ip.setReadOnly(True)
            self.server_ip.setToolTip("This machine's IP address is used by default")
            self.server_ip.setText(MACHINE_IP)

            self.start_server_btn = QPushButton("Start Server")
            self.start_server_btn.setObjectName("startServer")
            self.start_server_btn.setDisabled(True)
            self.start_server_btn.setIcon(QIcon(Icons.serve_icon))
            self.start_server_btn.setToolTip("Start server with the address set")
            self.start_server_btn.clicked.connect(self.start_clicked)

            self.stop_server_btn = QPushButton("Stop Server")
            self.stop_server_btn.setObjectName("stopServer")
            self.stop_server_btn.setIcon(QIcon(Icons.switch_icon))
            self.stop_server_btn.setToolTip("Stop running server\nThis will enable server address editing")
            self.stop_server_btn.clicked.connect(self.stop_clicked)

            server_controls_layout.addWidget(self.start_server_btn)
            server_controls_layout.addWidget(self.stop_server_btn)

            self.server_password = PasswordEdit()
            self.server_password.setToolTip("Set password the user will use\nGive this to your peer")
            self.server_password.setPlaceholderText("Access password")
            self.search_input = SearchInput()
            self.search_input.setPlaceholderText("Search username...")
            # table view
            self.table_view = QTableView()
            self.table_view.setEditTriggers(QTableView.NoEditTriggers)
            self.table_view.verticalHeader().setVisible(False)
            self.table_view.setShowGrid(0)
            self.table_view.setSelectionBehavior(QTableView.SelectRows)

            # database model
            self.model = QSqlTableModel(db=db)
            # get the Users table
            self.model.setTable("User")

            self.proxy_model = QSortFilterProxyModel()
            self.proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
            self.proxy_model.setSourceModel(self.model)
            # self.proxy_model.sort(1, Qt.AscendingOrder)
            # search usernames
            self.proxy_model.setFilterKeyColumn(1)
            self.table_view.setModel(self.proxy_model)
            # hide password column
            self.table_view.hideColumn(self.model.fieldIndex("password"))
            # change header titles
            for k, v in headers.items():
                idx = self.model.fieldIndex(k)
                self.model.setHeaderData(idx, Qt.Horizontal, v)
            # select
            self.model.select()

            server_cred_form_layout.addRow("Server Address", self.server_ip)
            server_cred_form_layout.addRow(server_controls_layout)
            # search input and table on left
            right_side_layout.addWidget(self.search_input)
            right_side_layout.addWidget(self.table_view)

            # add left and right layouts
            main_hlayout.addLayout(left_side_layout)
            # main_hlayout.addWidget(Line(h=0))
            main_hlayout.addLayout(right_side_layout)

            self.name = LineEdit()
            self.name.setPlaceholderText("Peer Username")
            self.id_label = QSpinBox()
            self.id_label.setRange(0, 2147483645)
            self.id_label.setDisabled(True)
            self.allowed_folder = PathEdit("Select folder the user will access")
            self.allowed_folder.setPlaceholderText("Access folder")

            form.addRow(QLabel("User details"))
            form.addRow(Line())
            form.addRow("Index", self.id_label)
            form.addRow("Username", self.name)
            form.addRow("Access Folder", self.allowed_folder)
            form.addRow("Access Password", self.server_password)

            # search when filter changes
            self.search_input.textChanged.connect(self.proxy_model.setFilterFixedString)

            self.mapper = QDataWidgetMapper()
            self.mapper.setSubmitPolicy(self.mapper.ManualSubmit)
            self.mapper.setModel(self.proxy_model)

            self.mapper.addMapping(self.id_label, 0)
            self.mapper.addMapping(self.name, 1)
            if not SAFEGUARD_PASSWORD:
                self.mapper.addMapping(self.server_password, 2)
            self.mapper.addMapping(self.allowed_folder, 3)

            # Change the mapper selection using the table.
            self.table_view.selectionModel().currentRowChanged.connect(self.mapper.setCurrentModelIndex)
            self.table_view.selectionModel().selectionChanged.connect(self.enable_remove_btn)

            self.mapper.toFirst()

            # buttons
            btn_layout = QHBoxLayout()

            add_record = QPushButton("Add User")
            add_record.setToolTip("Add new unique user\n(Only unique usernames will be added)")
            add_record.clicked.connect(self.add_user)

            self.remove_record = QPushButton("Remove User")
            self.remove_record.setToolTip("To remove user(s), select them on the table")
            self.remove_record.setDisabled(True)
            self.remove_record.clicked.connect(self.delete_user)

            prev_rec = QPushButton("<")
            prev_rec.clicked.connect(self.mapper.toPrevious)

            next_rec = QPushButton(">")
            next_rec.clicked.connect(self.mapper.toNext)

            save_rec = QPushButton("Save Changes")
            save_rec.setToolTip("Save changes\nRestart server for changes to reflect")
            save_rec.clicked.connect(self.submit_change)

            btn_layout.addWidget(prev_rec)
            btn_layout.addWidget(add_record)
            btn_layout.addWidget(self.remove_record)
            btn_layout.addWidget(save_rec)
            btn_layout.addWidget(next_rec)

            left_side_layout.addLayout(form)
            left_side_layout.addLayout(btn_layout)

            self.setLayout(main_hlayout)

        def create_table(self):
            """ create sqlite table if none exists """
            ss_logger.debug("Creating Table")
            isTableCreated = self.query.exec(
                """
                CREATE TABLE User (
                id INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE NOT NULL,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(16) NOT NULL,
                access_folder VARCHAR(256) NOT NULL
                )
                """)
            return isTableCreated

        def add_user(self):
            """ insert new user to db """

            username, password = self.name.text(), self.server_password.text()
            shared_dir = self.allowed_folder.text()

            if all((username, password, shared_dir)):
                # hash password
                pword = pass_hash(password)
                ss_logger.debug(f"""Adding user:
    Username: {username}
    Password: {pword}"""
                                )
                # creating a query using .prepare() for later execution
                self.query.prepare(
                    """
                    INSERT INTO User (
                        username,
                        password,
                        access_folder
                        )
                        VALUES (?, ?, ?)
                    """
                )
                self.query.addBindValue(username)
                self.query.addBindValue(pword)
                self.query.addBindValue(shared_dir)
                isSuccess = self.query.exec()
                if not isSuccess:
                    ss_logger.error(f"DB error adding user: {self.query.lastError().driverText()}")

                # emit for the server to pick up
                self.new_user_signal.emit(username, pword, shared_dir)
                # make the changes reflect
                self.model.select()
                self.clear_text()

        def submit_change(self):
            """ make sure all fields have data, save changes """
            username, password = self.name.text(), self.server_password.text()
            shared_dir = self.allowed_folder.text()
            if SAFEGUARD_PASSWORD and all((username, shared_dir)):
                pword = self.search_column(username)
                # emit signal for server to delete user
                self.delete_user_signal.emit(username)
                # add new changes
                self.new_user_signal.emit(username, pword, shared_dir)
                self.mapper.submit()
                # self.clear_text()
            elif all((username, password, shared_dir)):
                # emit signal for server to delete user
                self.delete_user_signal.emit(username)
                # add new changes
                self.new_user_signal.emit(username, password, shared_dir)
                self.mapper.submit()
                # self.clear_text()

        def delete_user(self):
            """ remove selected rows """
            indexes = self.table_view.selectionModel().selectedRows()
            for index in indexes:
                row = index.row()
                done = self.model.deleteRowFromTable(row)
                user = self.get_value_from_table(row)
                ss_logger.debug(f"Removing {user} {done}")
                # emit signal for server to pick up changes
                self.delete_user_signal.emit(user)
            self.remove_record.setDisabled(True)
            self.model.select()
            # clear lineEdit texts
            self.clear_text()

        def get_value_from_table(self, row: int, column: int = 1):
            """ get a value of row and column """
            index = self.model.index(row, column)
            return self.model.data(index)

        def search_column(self, text: str, column: int = 2):
            """ fetch the password of username """
            for i in range(self.model.rowCount()):
                # search the username column
                index = self.model.index(i, 1)
                username = self.model.data(index)
                if username == text:
                    return self.model.data(index, column)

        def enable_remove_btn(self):
            """ enable/disable user remove btn """
            if self.table_view.selectionModel().selectedRows():
                self.remove_record.setEnabled(True)
            else:
                self.remove_record.setDisabled(True)

        def fields_valid(self) -> bool:
            """ returns True if all fields are filled """
            username, shared_dir = self.name.text(), self.allowed_folder.text()
            if SAFEGUARD_PASSWORD:
                return all((username, shared_dir))
            else:
                password = self.server_password.text()
                return all((username, shared_dir, password))

        def clear_text(self):
            """ clear input text """
            self.name.clear()
            self.server_password.clear()
            self.allowed_folder.clear()

        def load_users(self):
            """" emit users as signals for the server to pick up """
            index = self.model.index
            cell = self.model.data

            # saved users
            ss_logger.info("Loading allowed users")
            for i in range(self.model.rowCount()):
                # emit saved users for the server to update
                self.new_user_signal.emit(cell(index(i, 1)), cell(index(i, 2)), cell(index(i, 3)))

        def start_clicked(self):
            """ emit signal """
            # disable start button, enable stop button
            self.start_server_btn.setDisabled(True)
            self.stop_server_btn.setEnabled(True)
            # disable editing
            self.server_ip.setReadOnly(True)
            # set input focus to this widget
            self.server_ip.setFocus()
            ip_address = self.server_ip.text()
            self.start_server_signal.emit(ip_address)

        def stop_clicked(self):
            """ stop server btn clicked """
            # disable stop button, enable start button
            self.start_server_btn.setEnabled(True)
            self.stop_server_btn.setDisabled(True)
            # enable editing
            self.server_ip.setReadOnly(False)
            # set input focus to this widget
            self.server_ip.setFocus()
            self.server_ip.selectAll()
            self.stop_server_signal.emit()


if __name__ == '__main__':

    app = QApplication(sys.argv)
    window = ServerSettingsWindow()
    window.show()
    app.exec_()
