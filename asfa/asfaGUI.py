__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"


from typing import Iterable, Generator
import common
import os
from qss import disksTab
from serverSettings import ServerSettingsWindow
from customWidgets import (
    PathEdit, QTabWidget, TabWidget,
    QLineEdit, QFileDialog, LineEdit,
    PasswordEdit, SearchInput, DNEdit,
)
import asfaUtils
import asfaDownloads
from asfaModel import DiskFilesModel, SortFilterModel, ShareFilesModel
from PyQt5.QtCore import (
    QThreadPool, QTimer, Qt, pyqtSignal
)
from PyQt5.QtGui import (
    QIcon,
    QKeySequence
)
from PyQt5.QtWidgets import (
    QWidgetAction,
    QAbstractItemView,
    QHeaderView,
    QLabel, QWidget,
    QShortcut, QListWidget,
    QMenu, QPushButton,
    QComboBox,
    QGroupBox,
    QVBoxLayout, QGridLayout,
    QFormLayout, QHBoxLayout,
    QTableView, QRadioButton,
    QCheckBox, QProgressBar,
    QMessageBox
)


gui_logger = common.logging.getLogger(__name__)
gui_logger.info(f">>> Initialized {__name__}")


LAST_KNOWN_DIR = os.path.expanduser(f"~{common.OS_SEP}Documents")
DEFAULT_DOWNLOADS_FOLDER = os.path.expanduser(f"~{common.OS_SEP}Downloads")


def get_directory(parent, caption, last=LAST_KNOWN_DIR):
    """ get folder, return None on cancel """
    folder = os.path.normpath(QFileDialog.getExistingDirectory(
        parent, caption=f"{caption}",
        directory=last,
    ))
    if folder != ".":
        return folder


class TrayMenu(QMenu):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setObjectName("trayMenu")

        # header row
        self.to_transfer_win = QPushButton("Transfer folders")
        self.to_transfer_win.setObjectName("trayTransferBtn")
        header_row = QWidgetAction(self)
        header_row.setDefaultWidget(self.to_transfer_win)
        self.addAction(header_row)

        self.create_buttons()

    def create_buttons(self):
        # quit and more buttons
        self.addSeparator()
        self.abuttons_holder = QWidget(self)
        hlayout = QHBoxLayout(self)
        self.quit = QPushButton("Quit")
        self.quit.setObjectName("trayQuitBtn")
        self.more = QPushButton("More...")
        self.more.setObjectName("trayMoreBtn")
        hlayout.addWidget(self.more)
        hlayout.addWidget(self.quit)
        self.abuttons_holder.setLayout(hlayout)
        self.last_action = QWidgetAction(self)
        self.last_action.setDefaultWidget(self.abuttons_holder)
        self.addAction(self.last_action)


class DuplicatesWindow(QWidget):
    """
    window for displaying duplicate files
    inherits:
        QWidget
    """

    def __init__(self, files: Iterable[str], *args):

        super().__init__(*args)
        self.setObjectName("duplicatesWindow")
        self.setWindowTitle("Feedback - asfa")
        self.setFixedSize(600, 300)

        vlayout = QVBoxLayout()

        details_label = QLabel("These files already exist in the destination folder:")
        details_label.setObjectName("duplicatesTitle")
        list_widget = QListWidget()
        list_widget.setObjectName("duplicatesListWidget")
        list_widget.addItems(files)
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("duplicatesOkBtn")
        ok_btn.clicked.connect(self.deleteLater)

        vlayout.addWidget(details_label)
        vlayout.addWidget(list_widget)
        vlayout.addWidget(ok_btn, alignment=Qt.AlignRight)
        self.setLayout(vlayout)


class TransferWindow(QWidget):
    """
    window for displaying transfer progress
    inherits:
        QWidget
    """

    def __init__(self, *args):

        super().__init__(*args)
        self.setObjectName("transferWin")
        self.setWindowTitle("Transfering - asfa")
        self.setFixedSize(400, 150)

        main_layout = QVBoxLayout()
        btn_layout = QHBoxLayout()
        self.cancel_transfer = QPushButton("Cancel")
        self.cancel_transfer.setObjectName("transferCancelBtn")
        btn_layout.addWidget(self.cancel_transfer, alignment=Qt.AlignRight)
        self.transfer_to = QLabel("Transfering to:")
        self.transfer_to.setObjectName("transferTo")
        self.percentage_progress = QLabel("0%")
        self.percentage_progress.setObjectName("transferPercentage")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("transferProgressb")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(0)
        self.remaining_files = QLabel("0 Files Remaining", self)
        self.remaining_files.setObjectName("transferRem")

        main_layout.addWidget(self.transfer_to)
        main_layout.addWidget(self.percentage_progress)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.remaining_files)
        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)


class WorkerManager(TransferWindow):
    """
    Manager to handle our worker queues and state
    inherits:
        TransferWindow: transfer GUI
    assumes:
        all workers/runnables are the same
    """

    _workers_progress = {}
    _active_workers = {}
    _transferred = {}
    all_done = pyqtSignal()

    def __init__(self):
        super().__init__()
        # create a threadpool for workers
        self.files_threadpool = QThreadPool()
        self.files_threadpool.setMaxThreadCount(1)
        self.timer = QTimer()
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh_progress)
        self.timer.start()
        self.total_workers = 0
        self.total_size = 0
        self.duplicates = []
        asfaUtils.utils_logger.debug(f"Can transfer {self.files_threadpool.maxThreadCount()} files at a time")
        self.cancel_transfer.clicked.connect(self.cancel)

    def enqueue(self, worker: asfaUtils.Transfer):
        """ Enqueue a worker to run (at some point) by passing it to the QThreadPool """

        worker.signals.progress.connect(self.receive_progress)
        worker.signals.finished.connect(self.done)
        worker.signals.transferred.connect(self.receive_transferred)
        worker.signals.duplicate.connect(self.receive_dups)
        self._active_workers[worker.job_id] = worker
        self.total_workers += 1
        self.total_size += worker.size
        self.files_threadpool.start(worker)

        asfaUtils.utils_logger.debug(f"Total size {self.total_size} Bytes")
        self.show()

    def receive_progress(self, job_id, progress):
        self._workers_progress[job_id] = progress

    def receive_transferred(self, job_id, size):
        self._transferred[job_id] = size

    def receive_dups(self, file):
        self.duplicates.append(file)

    def calculate_progress(self):
        """ Calculate total progress """
        if not self._workers_progress or not self.total_workers:
            return 0
        return sum(v for v in self._workers_progress.values()) / self.total_workers

    def calculate_transferred(self):
        if not self._transferred:
            return 0
        return sum(v for v in self._transferred.values())

    def refresh_progress(self):
        """ get and update progress """
        progress = int(self.calculate_progress())
        transferred = self.calculate_transferred()
        rem_size = common.convert_bytes(self.total_size - transferred)
        rem_files = max(1, len(self._active_workers))

        self.progress_bar.setValue(progress)
        self.percentage_progress.setText(f"{progress}%")
        self.remaining_files.setText(f"{rem_files} remaining ({rem_size})")

    def done(self, job_id):
        """ Remove workers when all jobs are done 100% """
        # avoid KeyError
        if self._active_workers:
            del self._active_workers[job_id]
        if all(v == 100 for v in self._workers_progress.values()) and not (self._active_workers):
            self._workers_progress.clear()
            self._transferred.clear()
            self.total_workers = 0
            self.total_size = 0
            self.all_done.emit()
            self.handle_dups()
            self.hide()

    def cancel(self):
        """ cancel transfer """
        self.files_threadpool.clear()
        for w in self._active_workers.values():
            w.running = 0
        self._active_workers.clear()
        # self.hide()

    def handle_dups(self):
        if self.duplicates:
            self.w = DuplicatesWindow(self.duplicates)
            self.w.setWindowIcon(self.windowIcon())
            self.duplicates.clear()
            self.w.show()

    def is_valid(self, worker):
        """ if file is valid for transfer """
        remaining = {worker.src: (worker.task, worker.src, worker.dst) for worker in self._active_workers.values()}
        worker_src = worker.src
        if worker_src in remaining:
            task, src, dst = remaining[worker_src]
            if task == "move":
                asfaUtils.utils_logger.info("The same file is being moved, won't be available")
                return False
            if (src == worker_src) and (dst == worker.dst):
                asfaUtils.utils_logger.info("The same file is scheduled for the same destination folder")
                return False
        return True


class FolderTransferWin(QWidget):
    """
    create a window to popup when a flash-disk is inserted
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setObjectName("folderPopup")
        # self.setMinimumSize(600, 300)
        self.setWindowTitle("Quick Transfer - asfa")

        # define layouts
        self.form_layout = QFormLayout()
        self.left_v_layout = QVBoxLayout()
        self.h_layout = QHBoxLayout()
        self.grid_layout = QGridLayout()
        # define groupboxes
        self.right_group = QGroupBox("Select file extensions to skip")
        self.right_group.setObjectName("extensionsGroup")
        self.bottom_left_group = QGroupBox("More options")
        self.bottom_left_group.setObjectName("optionsGroup")

        self.copy_flag = QRadioButton("Copy")
        self.copy_flag.setChecked(1)
        self.copy_flag.clicked.connect(self.vary_remember_disk_states)
        self.move_flag = QRadioButton("Cut")
        self.move_flag.clicked.connect(self.vary_remember_disk_states)
        self.recurse = QCheckBox("Transfer source sub-folders")
        self.recurse.setChecked(1)
        self.remember_disk_option = QCheckBox("Remember these choices (for this disk only)")
        self.remember_disk_option.setToolTip("""Fill these options automatically
the next time you insert this disk.""")
        self.remember_disk_option.setDisabled(True)
        self.ok_button = QPushButton("OK")

        # nest layouts and set the main one to the main window
        self.h_layout.addLayout(self.left_v_layout)
        self.h_layout.addWidget(self.right_group)
        self.right_group.setLayout(self.grid_layout)
        self.setLayout(self.h_layout)

        self.create_first_column()

    def create_first_column(self):
        left_title = QLabel("Choose folder to transfer:")
        self.transfer_from_folder_input = PathEdit("Choose a folder to transfer from")
        self.transfer_from_folder_size = QLabel()
        self.transfer_from_folder_input.setPlaceholderText("Source folder")
        self.transfer_from_folder_input.textChanged.connect(self.get_ext)

        self.transfer_to_folder_input = PathEdit("Choose a folder to transfer to")
        self.transfer_to_folder_input.setPlaceholderText("Destination folder")
        self.transfer_to_folder_input.textChanged.connect(self.vary_remember_disk_states)

        # dir chooser section
        first_row_layout = QHBoxLayout()
        first_row_layout.addWidget(self.transfer_from_folder_input)
        first_row_layout.addWidget(self.transfer_from_folder_size)
        self.form_layout.addRow("From", first_row_layout)
        self.form_layout.addRow("To", self.transfer_to_folder_input)

        # more settings group
        more_v_layout = QVBoxLayout()
        self.bottom_left_group.setLayout(more_v_layout)
        more_v_layout.addWidget(self.copy_flag)
        more_v_layout.addWidget(self.move_flag)
        more_v_layout.addWidget(self.recurse)
        more_v_layout.addWidget(self.remember_disk_option)

        self.left_v_layout.addWidget(left_title, alignment=Qt.AlignTop)
        self.left_v_layout.addLayout(self.form_layout)
        self.left_v_layout.addWidget(self.bottom_left_group)
        self.left_v_layout.addWidget(self.ok_button, alignment=Qt.AlignRight)

    def get_ext(self, folder):
        """ thread getting of exts """
        # remove the previous checkboxes
        asfaUtils.close_window(self.grid_layout)
        self.ext_thread = common.Thread(asfaUtils.get_ext_recursive, folder)
        self.ext_thread.results.connect(self.create_last_column)
        self.ext_thread.start()
        self.vary_remember_disk_states()

    def vary_remember_disk_states(self):
        """ enable remember widget if path is removable and copy is checked """
        from_path = self.transfer_from_folder_input.text()[:3]
        to_path = self.transfer_to_folder_input.text()[:3]
        if (asfaUtils.isRemovable(from_path) or asfaUtils.isRemovable(to_path)) and self.copy_flag.isChecked():
            self.remember_disk_option.setEnabled(True)
            self.remember_disk_option.setChecked(True)
        else:
            self.remember_disk_option.setChecked(False)
            self.remember_disk_option.setDisabled(True)

    def create_last_column(self, size_exts: Iterable):
        """ create checkboxes for file extensions available in dir """
        row, col = 0, 0
        folder_size, exts = size_exts
        data_len = len(exts)
        col_size = 5 if data_len > 25 else 3
        for r in range(data_len):
            try:
                self.grid_layout.addWidget(QCheckBox(exts[r]), row, col)
                col += 1
                if col == col_size:
                    row, col = row + 1, 0
            except IndexError:
                break
        self.transfer_from_folder_size.setText(f"({common.convert_bytes(folder_size)})")

    def get_selections(self):
        """ return: source_folder, dest_folder, copy, recurse, save_selection, ignore_patterns """
        source_folder = self.transfer_from_folder_input.text()
        dest_folder = self.transfer_to_folder_input.text()
        # move_flag and copy_flag are tied
        operation = self.copy_flag.isChecked()
        recurse = self.recurse.isChecked()
        save_selection = self.remember_disk_option.isChecked()

        item_at = self.grid_layout.itemAt
        total_widgets = self.grid_layout.count()
        ignore_patterns = {item_at(i).widget().text() for i in range(total_widgets) if item_at(i).widget().isChecked()}

        return source_folder, dest_folder, operation, recurse, save_selection, ignore_patterns

    def populate_from_settings(self, disk_name):

        settings = asfaUtils.get_settings()
        # this returns the disks dict {"D:\": {}}
        disks = settings.choices.get("disks")
        inserted_disk = disks.get(disk_name)
        if inserted_disk:
            self.transfer_from_folder_input.setText(inserted_disk.get("source_folder", ""))
            self.transfer_to_folder_input.setText(inserted_disk.get("dest_folder", ""))
            # move_flag and copy_flag are tied
            copy = inserted_disk.get("copy", False)
            self.copy_flag.setChecked(copy)
            self.move_flag.setChecked(not copy)
            self.recurse.setChecked(inserted_disk.get("recurse", True))
            self.remember_disk_option.setChecked(inserted_disk.get("save", True))
        else:
            # raise errors if path does not exist
            self.transfer_from_folder_input.text()
            self.transfer_to_folder_input.text()

        # make sure the states are correct
        self.vary_remember_disk_states()
        # minimize then show to take focus
        self.showMinimized()
        # show window
        self.showNormal()

    def closeEvent(self, e):
        """ on window close """
        self.hide()
        e.ignore()


class DiskManager(QWidget):
    """
        disk window widget
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setObjectName("diskManager")
        # window icons
        self.main_layout = QVBoxLayout()
        self.search_icon = QIcon(common.Icons.search_icon)
        self.refresh_icon = QIcon(common.Icons.refresh_icon)
        self.on_banner = 0
        # self.main_layout = None
        self.on_search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        self.cut_shortcut = QShortcut(QKeySequence("Ctrl+X"), self)

    def create_disk_win(self):
        """
            create the window to hold widgets
            that will go in the disk management tab
        """

        asfaUtils.close_window(self.main_layout)
        hlayout = QHBoxLayout()
        # use v layout for this widget
        self.setLayout(self.main_layout)
        self.disk_stats_label = QLabel()
        self.refresh_files_btn = QPushButton()
        self.refresh_files_btn.setObjectName("refreshBtn")
        self.refresh_files_btn.setIcon(self.refresh_icon)
        self.refresh_files_btn.setToolTip("Refresh")
        # create search area
        self.search_input = SearchInput()
        self.search_input.setPlaceholderText("Search files here")
        hlayout.addWidget(self.disk_stats_label)
        hlayout.addStretch()
        hlayout.addWidget(self.search_input)
        hlayout.addWidget(self.refresh_files_btn)
        # nest an inner layout
        self.main_layout.addLayout(hlayout)
        # create the inner vertical tab widget
        self.drives_tab = TabWidget()
        self.drives_tab.setStyleSheet(disksTab)
        self.drives_tab.setMovable(1)
        self.drives_tab.setDocumentMode(1)
        self.main_layout.addWidget(self.drives_tab)
        self.on_banner = 0

        self.note_label = QLabel("Updating files...")
        self.note_label.setAlignment(Qt.AlignCenter)
        self.note_label.setObjectName("noteLabel")
        self.main_layout.addWidget(self.note_label, alignment=Qt.AlignCenter)
        self.note_label.hide()

    def create_files_list(self, generators: Iterable[Generator], root_folder):
        """
            create a table to show files in different folders
        """

        model = DiskFilesModel(generators, ("Name", "File Path", "Type", "Size"))
        model.data_thread.started.connect(self.on_model_start)
        model.modelReset.connect(self.on_model_done)

        filter_proxy_model = SortFilterModel()
        filter_proxy_model.setSourceModel(model)
        filter_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        filter_proxy_model.setFilterKeyColumn(-1)

        self.table = QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        self.table.setModel(filter_proxy_model)
        self.table.setShowGrid(0)
        self.table.setAlternatingRowColors(1)
        self.table.setEditTriggers(self.table.NoEditTriggers)
        self.drives_tab.addTab(self.table, root_folder[:2])
        # self.drives_tab.adjustSize()

    def close_files_list(self, index: int):
        """
            remove the specified tab index
        """

        self.drives_tab.removeTab(index)

    def create_banner(self, msg: str):
        """
            create a banner to communicate to the user
        """

        asfaUtils.close_window(self.main_layout)
        self.msg_label = QLabel()
        self.msg_label.setText(msg)
        self.msg_label.setAlignment(Qt.AlignCenter)

        self.main_layout.addWidget(self.msg_label)
        self.setLayout(self.main_layout)
        # banner flag
        self.on_banner = 1

    def on_model_start(self):
        """ popup 'updating' notification """
        self.note_label.show()

    def on_model_done(self):
        """ hide popup notification """
        self.note_label.hide()
        self.table.sortByColumn(1, Qt.AscendingOrder)


class ShareManager(QWidget):
    """
        share window manager
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setObjectName("shareManager")

        tick_icon = QIcon(common.Icons.tick_icon)
        arrow_icon = QIcon(common.Icons.arrow_icon)
        loading_icon = QIcon(common.Icons.loading_icon)
        self.error_icon = QIcon(common.Icons.error_icon)
        back_icon = QIcon(common.Icons.back_icon)
        refresh_icon = QIcon(common.Icons.refresh_icon)

        self.icons = {0: arrow_icon, 1: tick_icon, 2: loading_icon, 3: self.error_icon}

        self.main_layout = QVBoxLayout()
        # use v layout for this widget
        self.setLayout(self.main_layout)
        self.back_folder = QPushButton()
        self.back_folder.setIcon(back_icon)
        self.show_current_folder = QLineEdit()
        self.show_current_folder.setObjectName("folderNav")
        self.show_current_folder.setReadOnly(1)
        self.refresh_shared_files = QPushButton()
        self.refresh_shared_files.setObjectName("refreshBtn")
        self.refresh_shared_files.setIcon(refresh_icon)

        self.online_users_dropdown = QComboBox()
        self.online_users_dropdown.setEditable(True)
        self.online_users_dropdown.setPlaceholderText("Select")
        self.online_users_dropdown.setToolTip("Select a username")
        self.on_banner = 0

    def create_share_win(self):
        """
        create the window for share files tab
        """

        asfaUtils.close_window(self.main_layout)
        hlayout = QHBoxLayout()
        hlayout.addWidget(QLabel("Username:"))
        hlayout.addWidget(self.online_users_dropdown)
        hlayout.addWidget(self.back_folder)
        hlayout.addWidget(self.show_current_folder)
        hlayout.addWidget(self.refresh_shared_files)
        # nest the inner hlayout
        self.main_layout.addLayout(hlayout)

        self.fetch_status = QLabel("Fetching items...")
        self.fetch_status.setObjectName("fetchStatus")
        self.fetch_status.setAlignment(Qt.AlignCenter)

        self.share_model = ShareFilesModel(("Name", "Status", "Type", "Size"), self.icons)
        # create table for files display
        self.share_table = QTableView()
        self.share_table.verticalHeader().setVisible(0)
        # set a model before hand to avoid errors if self.add_files is not called right away
        self.share_table.setModel(self.share_model)
        self.share_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.share_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.share_table.setSortingEnabled(1)
        self.share_table.setShowGrid(0)
        self.share_table.setEditTriggers(QTableView.NoEditTriggers)

        self.main_layout.addWidget(self.share_table)
        self.main_layout.addWidget(self.fetch_status, alignment=Qt.AlignCenter)
        self.fetch_status.hide()
        self.on_banner = 0

    def add_files(self, generator: Generator):
        """
        create a table to show shared generator
        """
        self.share_model.setup_model(generator)
        self.share_model.data_thread.started.connect(self.on_model_start)
        self.share_model.modelReset.connect(self.on_model_done)

    def on_model_done(self):
        """ when model thread done; hide popup note, enable tableview, set model """
        self.fetch_status.hide()
        self.share_table.setModel(self.share_model)
        self.share_table.sortByColumn(2, Qt.DescendingOrder)
        self.share_table.setEnabled(True)

    def on_model_start(self):
        """ model thread started; popup note, disable tableview """
        self.fetch_status.show()
        self.share_table.setDisabled(True)


class SettingsWindow(QWidget):
    """
    Settings window
    inherits:
        QWidget
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setObjectName("settingsWindow")

        # argument
        self.saved_settings = asfaUtils.get_settings()
        self.server_settings_win = ServerSettingsWindow()

        # main layouts
        self.outer_layout = QVBoxLayout()

        self.client_settings_group = QGroupBox("Client settings")
        self.client_settings_group.setObjectName("clientGroup")
        self.server_settings_group = QGroupBox("Server settings")
        self.server_settings_group.setObjectName("serverGroup")

        self.server_settings_layout = QVBoxLayout()
        self.server_settings_layout.addWidget(self.server_settings_win)
        # bind the server_settings_layout to groupbox
        self.server_settings_group.setLayout(self.server_settings_layout)

        # add the groups to the outer-most layout
        self.outer_layout.addWidget(self.client_settings_group)
        self.outer_layout.addWidget(self.server_settings_group)
        # bind the outer layout to the main window
        self.setLayout(self.outer_layout)

    def create_settings_widgets(self):
        """
        create the widgets for settings tab
        """

        username: str = self.saved_settings.choices["username"]
        users: dict = self.saved_settings.choices["users"]
        user: dict = users.get(username, {})
        # form layout for client settings
        form_layout = QFormLayout()
        # create fields
        self.username_input = LineEdit()
        self.username_input.setPlaceholderText("Your Username")
        self.username_input.setText(username)
        self.username_input.add_names(users.keys())

        self.server_password_input = PasswordEdit()
        self.server_password_input.setPlaceholderText("Server password (Get this from your peer)")
        self.server_password_input.setText(user.get("password", ""))

        self.download_location_input = PathEdit("Choose a folder to download to")
        self.download_location_input.setPlaceholderText("Select downloads folder")
        self.download_location_input.setText(user.get("download_dir", ""))

        self.server_name = DNEdit()
        self.server_name.line_edit.setPlaceholderText("Server Name (this is your peer's username)")

        self.apply_settings_btn = QPushButton("Apply changes")
        self.apply_settings_btn.setFixedSize(160, 35)
        self.apply_settings_btn.setObjectName("applyBtn")
        # set widgets to layout
        form_layout.addRow("Username", self.username_input)
        form_layout.addRow("Password", self.server_password_input)
        form_layout.addRow("Server Name", self.server_name)
        form_layout.addRow("Download location", self.download_location_input)
        form_layout.addRow(self.apply_settings_btn)
        # set client group's layout
        self.client_settings_group.setLayout(form_layout)


# ------------------------------------- MAIN WINDOW -----------------------------------------
class MainWindow(QWidget):
    """
    main app window
    """

    center_statusbar_signal = pyqtSignal(str)
    right_statusbar_signal = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setObjectName("mainWindow")
        self.setWindowTitle("asfa")

        self.app_icon = QIcon(common.Icons.app_icon)
        self.setWindowIcon(self.app_icon)
        # window icons
        self.download_icon = QIcon(common.Icons.download_icon)
        self.done_icon = QIcon(common.Icons.done_icon)
        self.cancel_icon = QIcon(common.Icons.cancel_icon)
        self.copy_icon = QIcon(common.Icons.copy_icon)
        self.cut_icon = QIcon(common.Icons.cut_icon)
        self.delete_icon = QIcon(common.Icons.delete_icon)
        self.open_icon = QIcon(common.Icons.open_icon)
        self.check_icon = QIcon(common.Icons.check_icon)
        self.hide_icon = QIcon(common.Icons.hide_icon)
        # saved settings
        self.saved_settings = asfaUtils.get_settings()

        self.vlayout = QVBoxLayout()
        self.hlayout = QHBoxLayout()
        # set the main window layout
        self.setLayout(self.vlayout)
        # add widgets to the layout
        self.main_tab = QTabWidget()
        self.main_tab.setObjectName("mainTab")
        self.main_tab.setDocumentMode(1)

        # create the window to hold widgets that will go in the first tab
        self.disk_man = DiskManager(self)
        self.main_tab.insertTab(0, self.disk_man, "External Storage")
        # create the first tab
        self.disk_man.create_disk_win()
        # for the second tab
        self.share_man = ShareManager(self)
        self.share_man.create_share_win()
        self.main_tab.addTab(self.share_man, "Share Files")

        # create settings window
        self.settings_man = SettingsWindow(self)
        self.settings_man.create_settings_widgets()
        self.main_tab.addTab(self.settings_man, "Settings")

        # prepare downloads window
        self.downloads_win = asfaDownloads.DownloadsWindow()

        # create the status bars
        self.left_statusbar = QLabel()
        self.left_statusbar.setObjectName("leftStatusBar")
        self.center_statusbar = QLabel()
        self.center_statusbar.setObjectName("centerStatusBar")
        self.right_statusbar = QLabel()
        self.right_statusbar.setObjectName("rightStatusBar")
        # add to horizontal layout
        self.hlayout.addWidget(self.left_statusbar)
        self.hlayout.addWidget(self.center_statusbar)
        self.hlayout.addWidget(self.right_statusbar)
        self.hlayout.setSpacing(5)

        # bind status signals
        self.center_statusbar_signal.connect(self.center_statusbar.setText)
        self.right_statusbar_signal.connect(self.right_statusbar.setText)

        # add the tab widget to the layout
        self.vlayout.addWidget(self.main_tab)
        # nest the status bar layout in the vertical main layout
        self.vlayout.addLayout(self.hlayout)

    def ask(self, qtn):
        """
            ask confirm questions
        """

        return QMessageBox.question(self, "Confirmation - asfa", qtn, defaultButton=QMessageBox.Yes)

    def inform(self, info):
        """ send information to the user """
        return QMessageBox.information(self, "Information - asfa", info)
# -------------------------------------- END OF MAIN WINDOW ----------------------------------------
