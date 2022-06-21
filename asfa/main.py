__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"


from asfaGUI import (
    MainWindow,
    asfaUtils,
    LAST_KNOWN_DIR,
    DEFAULT_DOWNLOADS_FOLDER,
    TrayMenu,
    FolderTransferWin,
    WorkerManager,
    get_directory,
    asfaDownloads,
)

from PyQt5.QtCore import (
    Qt,
    QModelIndex
)

from asfaModel import (
    DiskFilesModel,
    SortFilterModel
)

from PyQt5.QtWidgets import (
    QSystemTrayIcon,
    QMenu,
    QMessageBox,
)

import os
import common
from typing import Iterable
from network import server, browser


main_logger = common.logging.getLogger(__name__)
main_logger.info(f">>> Initialized {__name__}")


class Controller(MainWindow):
    """
    the brain for controlling asfa GUI and its data models
    TODO: handle 200k files with ease - scalability
    """

    def __init__(self):
        super().__init__()

        # self.showMaximized()
        self.main_tab.currentChanged.connect(self.main_tab_changed)
        self.available_disks = set()
        self.current_disk_name = ""
        self.local_usernames = {}
        self.total_files_sent = 0
        self.total_incomplete_sent = 0
        # self.server_is_busy = 0
        self.client_is_busy = ""
        self.transfer_is_busy = ""
        self.last_known_dir = LAST_KNOWN_DIR
        # get values from the settings tab
        # if no value set, ask the user or use default
        self.username = self.settings_man.username_input.text() or common.USERNAME
        # self.password = self.settings_man.server_password_input.text()
        self.download_to_folder = self.settings_man.download_location_input.text() or DEFAULT_DOWNLOADS_FOLDER
        self.settings_man.download_location_input.setText(self.download_to_folder)
        # if username was empty, set the one from common
        self.settings_man.username_input.textChanged.connect(self.auto_fill_client)
        self.settings_man.username_input.setText(self.username)

        # system tray icon
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.app_icon)
        self.tray.setToolTip("asfa App\nShare files")
        self.tray.messageClicked.connect(self._show_folder_transfer_win)

        self.tray_menu = TrayMenu(self)
        self.tray_menu.more.clicked.connect(self.show_main_window)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()

        # Folder tansfer win
        self.folder_transfers_win = FolderTransferWin()
        self.folder_transfers_win.setWindowIcon(self.app_icon)
        self.folder_transfers_win.ok_button.clicked.connect(self.folder_transfer)
        self.tray_menu.to_transfer_win.clicked.connect(self._show_hide_transfers_win)

        self.server_browser = browser.ServerBrowser()
        # set server_browser signals
        self.server_browser.signals.success.connect(self.right_statusbar.setText)
        self.server_browser.signals.error.connect(self.center_statusbar.setText)
        self.server_browser.signals.refresh.connect(self.downloads_win.workers.cleanup)
        self.server_browser.signals.file_exists.connect(self.downloads_win.workers.add_row)
        # set download folder
        self.server_browser.dst_dir = self.download_to_folder

        # set KeyBoard shortcuts
        self.disk_man.copy_shortcut.activated.connect(self.copy)
        self.disk_man.cut_shortcut.activated.connect(self.cut)
        # set focus shortcut
        self.disk_man.on_search_shortcut.activated.connect(self.focus_search_input)

        # share/downloads
        self.share_man.back_folder.clicked.connect(self.back_to_folder)
        self.share_man.share_table.doubleClicked.connect(self.share_double_click)
        # on selection, get selected properties
        self.share_man.share_table.selectionModel().selectionChanged.connect(self.get_properties)
        self.share_man.refresh_shared_files.clicked.connect(self.update_shared_files)
        self.downloads_win.workers.worker_started.connect(self._on_download_started)
        self.downloads_win.workers.all_done.connect(self._on_download_ended)
        self.downloads_win.change_title(self.download_to_folder)

        self.worker_manager = WorkerManager()
        self.worker_manager.setWindowIcon(self.app_icon)
        self.worker_manager.all_done.connect(self._on_transfer_ended)

        # start the usb listener thread
        self.usb_thread = asfaUtils.DeviceListener()
        self.usb_thread.signals.on_change.connect(self.on_disk_changes)
        self.usb_thread.signals.error.connect(self.disk_man.create_banner)
        self.usb_thread.start()

        self.key_routes = {Qt.Key_Enter: self.open_file,
                           Qt.Key_Return: self.open_file,
                           Qt.Key_Delete: self.delete_files
                           }
        self.sharefiles_routes = {Qt.Key_Enter: self.share_open_file,
                                  Qt.Key_Return: self.share_open_file,
                                  Qt.Key_Backspace: self.back_to_folder
                                  }

        self.settings_man.apply_settings_btn.clicked.connect(self.change_settings)
        # server settings signal; add saved users to server authorizer
        self.settings_man.server_settings_win.new_user_signal.connect(self.authorize_user)
        self.settings_man.server_settings_win.delete_user_signal.connect(self.unauthorize_user)
        self.settings_man.server_settings_win.stop_server_signal.connect(self.stop_server)
        self.settings_man.server_settings_win.start_server_signal.connect(self.start_server_manual)

        # start server
        self.start_server_auto(addr=common.MACHINE_IP)

        # start monitoring IP address changes
        self.IP_monitor = asfaUtils.NetMonitor()
        self.IP_monitor.signals.changes.connect(self.on_new_ip)
        self.IP_monitor.start()

        # receive other machines' details
        self.user_discoverer = asfaUtils.ReceiveUser()
        self.user_discoverer.new_user.connect(self.update_resolver)
        self.user_discoverer.start()

        # for external storage
        # self.set_path(os.path.expanduser("~\\Music\\DAMN"))
        self.on_startup(self.usb_thread.disks)
        # put local machine on dropdown menu
        self.share_man.online_users_dropdown.currentTextChanged.connect(self.connect_to_user)
        # show window
        self.showMaximized()
        self.main_tab.setCurrentIndex(2)
        self.tab_changed()
        self.dn_lookup = {}
        self.current_server_name = "Home"

    def app_is_busy(self):
        """ if transfer and downloads are on-going """
        return self.client_is_busy or self.transfer_is_busy

    def start_server_auto(self, addr):
        """ create server instance, set its attr and start it """
        # server uses local machine's IP address
        # scan available ports and return one
        self.local_port = common.get_port()
        self.server = server.Server(self.username, (addr, self.local_port), parent=self)
        # set server signals
        self.server.signals.success.connect(self.right_statusbar.setText)
        self.server.signals.error.connect(self.center_statusbar.setText)
        # set event callbacks
        self.server.ftp_handler.on_file_sent = self.on_file_sent
        self.server.ftp_handler.on_incomplete_file_sent = self.on_incomplete_file_sent
        self.server.start()
        # saved users
        self.settings_man.server_settings_win.load_users()

    def on_new_ip(self, new_ip):
        """ make app changes on IP address change """
        common.MACHINE_IP = new_ip
        self.settings_man.server_settings_win.server_ip.setText(new_ip)
        self.user_discoverer.close_thread()

        try:
            self.stop_server()
            # restart it
            self.start_server_auto(addr=new_ip)
            self.inform("Your server address changed.\n- Server restarted successfully.")

        except Exception as e:
            self.center_statusbar_signal.emit("Error restarting after IP address change")
            server.server_logger.error(f"Error restarting after IP address change '{new_ip}':", e)

        # receive other machines' details
        self.user_discoverer = asfaUtils.ReceiveUser()
        self.user_discoverer.local_machine_ip = new_ip
        self.user_discoverer.new_user.connect(self.update_resolver)
        self.user_discoverer.start()

    def start_server_manual(self, ip_addr):
        """ start server manually """
        self.start_server_auto(addr=ip_addr)

    def stop_server(self):
        """ stop server """
        # stop server
        server.server_logger.info("Stopping server")
        self.server.stopServer()

    # ----------------------------- define server handler callbacks ------------------------------
    def on_dis_connect(self):
        message = f"{self.total_files_sent} sent, {self.total_incomplete_sent} incomplete sent"
        self.right_statusbar_signal.emit(message)

    def on_file_sent(self, file):
        self.total_files_sent += 1
        self.on_dis_connect()

    def on_incomplete_file_sent(self, file):
        self.total_incomplete_sent += 1
        message = f"{self.total_files_sent} sent, {self.total_incomplete_sent} incomplete sent"
        self.right_statusbar_signal.emit(message)
    # ----------------------------- end defining server handler callbacks ------------------------

    def main_tab_changed(self):
        """ called when main tabs are switched """
        self.get_properties()

    def tab_changed(self):
        """
        on drive tab change event
        get the current table, model and update the slots
        """
        self.disconnect_signals()
        if self.disk_man.on_banner:
            self.current_disk_name = ""

        else:
            self.table_view = self.disk_man.drives_tab.currentWidget()
            current_disk_index = self.disk_man.drives_tab.currentIndex()
            self.current_disk_name = self.disk_man.drives_tab.tabText(current_disk_index)
            # set focus on table
            self.table_view.setFocus()
            self.files_model = self.table_view.model()
            self.selection_model = self.table_view.selectionModel()
            self.selection_model.selectionChanged.connect(self.get_properties)
            # done once
            self.table_view.doubleClicked.connect(self.on_double_click)
            # on tab change
            self.update_stats()
            self.get_properties()
            # search on disk change
            self.on_search()

    def disconnect_signals(self):
        """ disconnect double-click, selection-changed signals """
        try:
            self.selection_model.selectionChanged.disconnect()
            self.table_view.doubleClicked.disconnect()
        except Exception:
            pass

    def get_server_ip(self) -> str:
        """ make decisions before returning server ip address """
        server_name = self.settings_man.server_name.currentText()
        server_ip = ""
        # if field is empty, raise 'field required' error
        if server_name:
            self.current_server_name = server_name
            # if valid ip entered, return it
            # if common.valid_ip(server_ip):
            #     return server_ip
            # else, do a name lookup, get an empty str if not found
            server_ip = self.dn_lookup.get(server_name, "")
        return server_ip

    def change_settings(self):
        """ apply client settings/local changes """
        username = self.settings_man.username_input.text()
        server_ip = self.get_server_ip()
        password = self.settings_man.server_password_input.text()
        download_to_folder = self.settings_man.download_location_input.text()
        if all((username, server_ip, password, download_to_folder)):
            # set check icon
            self.settings_man.apply_settings_btn.setIcon(self.check_icon)
            self.username, self.password, self.download_to_folder = username, password, download_to_folder
            self.remote_addr, self.remote_port = server_ip
            self.server_browser.dst_dir = self.download_to_folder
            self.downloads_win.change_title(self.download_to_folder)
            # save settings
            self.saved_settings.update_n_save(self.username, self.password, self.download_to_folder)
            self.update_new_user((self.username, self.password, self.remote_addr, self.remote_port))
            self.server.multicaster.username = self.username
            self.settings_man.username_input.add_names((self.username, ))
        else:
            # set error icon
            self.settings_man.apply_settings_btn.setIcon(self.share_man.error_icon)

    def auto_fill_client(self, name):
        """ get details for name and auto-fill """
        users: dict = self.settings_man.saved_settings.choices["users"]
        user: dict = users.get(name, {})

        self.settings_man.server_password_input.setText(user.get("password", ""))
        self.settings_man.download_location_input.setText(user.get("download_dir", DEFAULT_DOWNLOADS_FOLDER))

    def authorize_user(self, username, password, shared_dir):
        """ slot for signal from server settings """
        self.server.setUser(username, password, shared_dir)

    def unauthorize_user(self, username):
        """ unauthorize already set user """
        self.server.delete_user(username)

    @property
    def selected_rows(self) -> tuple:
        """
        get the currently selected rows
        """
        try:
            return tuple(self.selection_model.selectedRows())
        except Exception:
            return ()

    @property
    def isDiskTableFocused(self) -> bool:
        """
        check if table view is under mouse and focused
        """
        try:
            return (self.table_view.underMouse() and self.table_view.hasFocus())
        except Exception:
            return False

    @property
    def isShareTableFocused(self) -> bool:
        try:
            table = self.share_man.share_table
            return (table.underMouse() and table.hasFocus())
        except Exception:
            return False

    def refresh_files_list(self):
        """ on refresh """
        self.table_view.setModel(None)
        folders = asfaUtils.get_folders(f"{self.current_disk_name}{common.OS_SEP}")
        file_generators = [common.get_files(folder) for folder in folders]
        model = DiskFilesModel(file_generators, ("Name", "File Path", "Type", "Size"))
        model.data_thread.started.connect(self.disk_man.on_model_start)
        model.modelReset.connect(self.disk_man.on_model_done)

        filter_proxy_model = SortFilterModel()
        filter_proxy_model.setSourceModel(model)
        filter_proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        filter_proxy_model.setFilterKeyColumn(-1)
        self.table_view.setModel(filter_proxy_model)
        self.table_view.sortByColumn(1, Qt.AscendingOrder)
        self.tab_changed()
        self.update_stats()

    def get_properties(self, selected=None, deselected=None):
        """
        get the total size of all the selected files
        """
        if self.main_tab.currentIndex() == 0:
            self.get_disk_properties()

        elif self.main_tab.currentIndex() == 1:
            self.get_share_properties()
        else:
            self.left_statusbar.setText("")

    def get_disk_properties(self):
        """ get the number and size of the selected """
        readable = common.convert_bytes
        rows = self.selected_rows
        total_size = 0
        for index in rows:
            file = self.path_from_row(index)
            try:
                total_size += os.path.getsize(file)
            except FileNotFoundError:
                pass
        if rows and (not self.disk_man.on_banner):
            self.left_statusbar.setText(f"{len(rows):,} selected, {readable(total_size)}")
            self.table_view.update()
        else:
            self.left_statusbar.setText("")

    def get_share_properties(self):
        """ get the number and size of the selected """
        readable = common.convert_bytes
        rows = self.share_selected
        total_size = 0
        for index in rows:
            name, f_exists, file_type, size = self.share_from_row(index)
            total_size += size
        if rows:
            self.left_statusbar.setText(f"{len(rows):,} selected, {readable(total_size)}")
        else:
            self.left_statusbar.setText("")

    def update_stats(self):
        """
        update info about files on main window
        """

        self.disk_man.disk_stats_label.setText(f"Removable Disk ({self.current_disk_name})")

    def closeEvent(self, e):
        """
        minimize on close
        """

        # self.tray.show()

        self.hide()
        e.ignore()

    def show_main_window(self):
        """
        slot for 'more' button in tray
        """

        # self.tray.hide()
        if self.isVisible() and (not self.isMinimized()):
            self.hide()
        else:
            # show window
            self.showNormal()

    def _show_folder_transfer_win(self):
        """ show folder transfer win even when minimized """
        disk = f"{self.current_disk_name}{common.OS_SEP}"
        self.folder_transfers_win.populate_from_settings(disk)

    def _show_hide_transfers_win(self):
        """ slot for `transfer folders` button in tray """

        if self.folder_transfers_win.isVisible() and (not self.folder_transfers_win.isMinimized()):
            self.folder_transfers_win.hide()
        else:
            self._show_folder_transfer_win()

    def _show_downloads_tab(self):
        """ insert downloads tab """
        self.main_tab.insertTab(2, self.downloads_win, "Downloads")
        if self.client_is_busy:
            self.main_tab.setTabIcon(2, self.download_icon)
        else:
            self.main_tab.setTabIcon(2, self.done_icon)

    def _goto_downloads_tab(self):
        """ switch to downloads """
        self._show_downloads_tab()
        self.main_tab.setCurrentIndex(2)

    def _on_download_ended(self):
        """ make changes on all downloading activities done """
        # change `client busy` flag
        self.client_is_busy = ""
        # release sleep lock
        if not self.app_is_busy():
            common.release_sleep()
        self.main_tab.setTabIcon(2, self.done_icon)

    def _on_transfer_ended(self):
        """ make changes on all transfers done """
        self.transfer_is_busy = ""
        # release sleep lock
        if not self.app_is_busy():
            common.release_sleep()

    def _on_download_started(self):
        """ slot for download started signal """
        # prevent sleeping
        if not self.app_is_busy():
            common.prevent_sleep()
        self.client_is_busy = "downloading"
        self._show_downloads_tab()
        # self.right_statusbar_signal.emit(f"Downloading to: {self.download_to_folder}")

    def disk_context_menu(self, e):
        """
        external storage popup menu
        parameter e:
            contextMenu event
        assumes:
            self.tab_changed has been called
            self.table_view has been defined
        """
        context = QMenu(self)
        if self.isDiskTableFocused:

            # addAction(self, QIcon, str, PYQT_SLOT, shortcut: Union[QKeySequence, QKeySequence.StandardKey, str, int] = 0)
            context.addAction(self.open_icon, "Open", self.open_file)
            context.addSeparator()
            context.addAction(self.copy_icon, "Copy", self.copy, "Ctrl+C")
            context.addAction(self.cut_icon, "Cut", self.cut, "Ctrl+X")
            context.addSeparator()
            context.addAction(self.delete_icon, "Delete", self.delete_files)
            context.addSeparator()
        context.addAction("Transfer Folders", self._show_folder_transfer_win)
        context.exec_(e.globalPos())

    def share_context_menu(self, e):
        """
        share files popup menu
        parameter e:
            contextMenu event
        assumes:
            self.share_man.share_table has been defined
        """
        context = QMenu(self)
        if self.isShareTableFocused:

            # Name, Status, Type, Size
            # addAction(self, QIcon, str, PYQT_SLOT, shortcut: Union[QKeySequence, QKeySequence.StandardKey, str, int] = 0)

            context.addAction(self.download_icon, "Download", self.download_clicked)
            context.addSeparator()
            context.addAction(self.open_icon, "Open", self.share_menu_open)
            context.addSeparator()
            context.addAction(self.delete_icon, "Delete", self.handle_share_delete)
            context.addAction("I don't want to see this", self.handle_share_hide)
            context.addSeparator()
        context.addAction("Go to Downloads", self._goto_downloads_tab)
        context.exec_(e.globalPos())

    def contextMenuEvent(self, e):
        """
        window popup menu
        assumes:
            self.main_tab has been defined
        """
        if self.main_tab.currentIndex() == 0:
            self.disk_context_menu(e)

        elif self.main_tab.currentIndex() == 1:
            self.share_context_menu(e)

    def keyPressEvent(self, e):
        """
        route key presses to their respective slots
        """
        try:
            if self.main_tab.currentIndex() == 0:
                func = self.key_routes.get(e.key())
                if func:
                    print("Key pressed, executing", func.__name__)
                    func()
            elif self.main_tab.currentIndex() == 1:
                func = self.sharefiles_routes.get(e.key())
                if func:
                    print("Key pressed, executing", func.__name__)
                    func()

        except AttributeError:
            pass

    def on_startup(self, listdrives: Iterable[str]):
        """
        get disks and setup on startup
        """

        if listdrives:
            self.available_disks = set(listdrives)
            for disk in self.available_disks:
                self.set_path(disk)
            # simulate an insert
            self.set_events()
        else:
            self.center_statusbar_signal.emit("")
            self.disk_man.create_banner("Insert USB Drive")

    def set_events(self):
        """
        call on first disk insert
        """

        # call tab_changed whenever current tab changes
        self.disk_man.drives_tab.currentChanged.connect(self.tab_changed)
        # set signal callbacks; search on text change
        self.disk_man.search_input.textChanged.connect(self.search)
        # refresh btn update signals
        self.disk_man.refresh_files_btn.clicked.connect(self.refresh_files_list)

    def set_path(self, path: str):
        """
        update current folders and setup model/view
        """
        if self.disk_man.on_banner:
            self.disk_man.create_disk_win()
            self.set_events()

        folders = asfaUtils.get_folders(path)
        file_generators = [common.get_files(folder) for folder in folders]
        self.disk_man.create_files_list(file_generators, path)

    def on_disk_changes(self, listdrives: Iterable[str]):
        """
        respond to disk insert/eject
        """

        if listdrives:
            disks = set(listdrives)
            ejected = self.available_disks.difference(disks)
            inserted = disks.difference(self.available_disks)
            self.available_disks = disks
            if inserted:
                disk = inserted.pop()
                asfaUtils.utils_logger.info(f"USB inserted: '{disk}'")
                self.set_path(disk)
                # pop up folder transfer window
                self.folder_transfers_win.populate_from_settings(disk)
            elif ejected:
                disk = ejected.pop()
                asfaUtils.utils_logger.info(f"USB ejected: '{disk}'")
                index = self.index_from_tabText(disk[:2])
                self.disk_man.close_files_list(index)
                self.center_statusbar_signal.emit("")
        else:
            asfaUtils.utils_logger.info("No USB drives available")
            self.available_disks = set()
            self.disk_man.create_banner("Insert USB Drive")
            self.center_statusbar_signal.emit("")
            self.selection_model.clearSelection()
        # try:
        #     self.tab_changed()
        # except Exception as e:
        #     asfaUtils.utils_logger.error("Error on disk changes:", e)
        #     pass

    def on_search(self):
        """
        slot for search button
        """

        string = self.disk_man.search_input.text()
        self.search(string)

    def focus_search_input(self):
        """ focus search QLineEdit """
        try:
            index = self.main_tab.currentIndex()
            # if external storage tab is selected
            if index == 0:
                self.disk_man.search_input.setFocus()
                self.disk_man.search_input.selectAll()
        except Exception:
            pass

    def search(self, search_txt):
        """
        change the search button icon and set the filter txt
        callback for QLineEdit textChanged event
        """

        if self.main_tab.currentIndex() == 0:
            # search 2 characters and above
            if len(search_txt) > 1:
                self.files_model.setFilterFixedString(search_txt)
            elif not search_txt:
                self.close_search()

    def close_search(self):
        """
        close a search and update the search button icon
        """

        self.files_model.setFilterFixedString("")

    def on_double_click(self, s: QModelIndex):
        """
        open a file on double-click
        """

        self._open_file(s)

    def _open_file(self, index: QModelIndex):
        """ open file at index by default app """
        path = self.path_from_row(index)
        try:
            if self.main_tab.currentIndex() == 0:
                asfaUtils.start_file(path)
                asfaUtils.utils_logger.debug("File opened")

        except Exception as e:
            asfaUtils.utils_logger.error(f"Opening file: {str(e)}")
            self.center_statusbar_signal.emit(f"File not found: '{path}'")
            # remove row from model
            self.files_model.removeRows(set((path, )))

    def path_from_row(self, row: QModelIndex):
        """
        get data from the first and the second column of row
        join them and return full file path
        """

        row = row.row()
        dirname = self.files_model.data(self.files_model.index(row, 1))
        file = self.files_model.data(self.files_model.index(row, 0))
        return os.path.join(dirname, common._basename(file))

    def index_from_tabText(self, txt) -> int:
        """
        return the index of the tab with txt; suppose no duplicated tab name
        """

        for i in range(self.disk_man.drives_tab.count()):
            if txt == self.disk_man.drives_tab.tabText(i):
                return i

    def delete_files(self):
        """
        remove selected rows and delete assc'd files
        """

        selected = self.selected_rows
        if selected:
            confirmation = self.ask(f"Delete {len(selected)} selected file(s) permanently?\n\nNote: This cannot be undone!")
            # if confirmation is YES
            if confirmation == QMessageBox.Yes:
                to_delete = set()
                for index in selected:
                    path = self.path_from_row(index)
                    asfaUtils.utils_logger.debug(f"Deleting permanently: '{path}'")
                    asfaUtils.delete_file(path)
                    to_delete.add(path)
                # remove all rows from model before changing layout
                self.files_model.removeRows(to_delete)
                self.selection_model.clearSelection()
        # else:
        #     self.center_statusbar_signal.emit("No file selected!")

    def open_file(self):
        """
        open last-selected file
        """

        try:
            index = self.selected_rows[-1]
            self._open_file(index)
        except IndexError:
            self.center_statusbar_signal.emit("No file selected!")

    def register_worker(self, src, dst, task):
        """ create and enqueue transfer worker if valid """
        transfer_worker = asfaUtils.Transfer(
            src, dst,
            os.path.getsize(src),
            task=task
        )
        if self.worker_manager.is_valid(transfer_worker):
            self.worker_manager.enqueue(transfer_worker)
            # prevent system sleep
            if not self.app_is_busy():
                common.prevent_sleep()
            self.transfer_is_busy = "transferring"
        else:
            asfaUtils.utils_logger.info(f"Skipping '{src}'")
            # self.center_statusbar_signal.emit(f"'{common._basename(src)}' is in transfer queue")

    def _handle_transfer(self, dst, task="copy"):
        """ prepare transfer workers/objects and enqueue them to manager """
        selected = self.selected_rows[::-1]
        to_delete = set()
        for index in selected:
            src = self.path_from_row(index)
            try:
                self.register_worker(src, dst, task)
            except Exception:
                to_delete.add(src)
        self.files_model.removeRows(to_delete)

    def copy(self):
        """
        copy files
        """

        if (self.main_tab.currentIndex() == 0) and not self.disk_man.on_banner:
            try:
                # get the dst from dialog
                dst = get_directory(self, "Copy selected items to...", last=self.last_known_dir)
                # if dir selected
                if dst:
                    self.last_known_dir = dst
                    self.worker_manager.transfer_to.setText(f"Copying to '{common._basename(dst)}'")
                    self._handle_transfer(dst)

            except KeyError as e:
                print(">>>", e)
                self.center_statusbar_signal.emit("Insert USB Drive")

    def cut(self):
        """
        cut files
        """

        if (self.main_tab.currentIndex() == 0) and not self.disk_man.on_banner:
            try:
                # get the dst from dialog
                dst = get_directory(self, "Move selected items to...", last=self.last_known_dir)
                # if dir selected
                if dst:
                    self.last_known_dir = dst
                    self.worker_manager.transfer_to.setText(f"Moving to '{common._basename(dst)}'")

                    self._handle_transfer(dst, task="move")

            except KeyError:
                self.center_statusbar_signal.emit("Insert USB Drive")

    def folder_transfer(self):
        """ handles transfers initiated from quick transfer window """
        try:
            # source_folder, dest_folder, copy, recurse, save_selection, ignore_patterns
            choice = self.folder_transfers_win.get_selections()
            src, dst, copy, isRecursive, save_selection, ignore = choice[0], choice[1], choice[2], choice[3], choice[4], choice[5]
            if all((src, dst)):

                # hide folders window
                self.folder_transfers_win.hide()

                if save_selection:
                    disk = src[:3] if asfaUtils.isRemovable(src[:3]) else dst[:3]
                    self.saved_settings.remember_disk(disk, src, dst, copy, isRecursive, save_selection)

                if copy:
                    self.worker_manager.transfer_to.setText(f"Copying to '{dst}'")
                    self._move_folder(src, dst, recurse=isRecursive, ignore_patterns=ignore)
                else:  # move
                    self.worker_manager.transfer_to.setText(f"Moving to '{dst}'")
                    self._move_folder(src, dst, task="move", recurse=isRecursive, ignore_patterns=ignore)

        except Exception:
            self.inform("Folder Transfer Error")

    def _move_folder(self, src_folder, dst_folder, task="copy", recurse=True, ignore_patterns=None):
        """ copy folder recursively """
        try:
            dst_name = common._basename(src_folder) or f"Removable Disk ({src_folder[0]})"
            dst = os.path.join(dst_folder, dst_name)

            if not os.path.exists(dst):
                os.mkdir(dst)

            sorted_items = asfaUtils.get_files_folders(src_folder)

            for item in sorted_items:

                try:
                    # skip all links
                    if os.path.islink(item):
                        continue
                    # if it's a file, file is not a sys file
                    if os.path.isfile(item) and (not common.isSysFile(item)):

                        ext = os.path.splitext(item)[-1] or "without extensions"
                        if (ext.lower() in ignore_patterns):
                            # skip file with patttern
                            continue
                        # else, schedule to transfer
                        self.register_worker(item, dst, task)
                    elif os.path.isdir(item) and recurse:
                        # recurse
                        self._move_folder(item, dst, task=task, recurse=recurse, ignore_patterns=ignore_patterns)

                except Exception as e:
                    print(e)
                    self.center_statusbar_signal.emit("Error: skipping")
                    continue

        except PermissionError:
            self.inform("Permission to create and write folder denied!\n\nLet's try that again with a different destination folder")

    # ----------------------- Let's start sharing files ---------------------------------------

    def back_to_folder(self):
        """ go back a folder """
        try:
            if len(self.server_browser.browser_history) > 1:
                # keep home dir for refreshing
                self.server_browser.browser_history.pop()
                folder = self.server_browser.browser_history[-1]
                self.update_shared_files(path=folder, fore=0)
        except IndexError:
            pass

    def update_shared_files(self, path=None, fore=1):
        """
        FTPS: fetch files from the specified path
        if path is None, refresh the cwd
        """

        # for updating downloading icons
        self.server_browser.running = self.downloads_win.workers.active_workers

        self.server_browser.updateDir(path, forward=fore)
        generator = self.server_browser.getFilesList()
        self.share_man.add_files(generator)
        open_dir = f"{self.current_server_name}:/{'/'.join(self.server_browser.browser_history)}"
        self.share_man.show_current_folder.setText(open_dir)
        self.share_man.share_table.selectionModel().clearSelection()

    @property
    def share_selected(self) -> Iterable[QModelIndex]:
        """ get selected files in share window """
        selection_model = self.share_man.share_table.selectionModel()
        return selection_model.selectedRows()

    def share_from_row(self, row: QModelIndex):
        """ return a row as a tuple """

        model = self.share_man.share_model
        row_data = model.data(row, role=Qt.UserRole)
        return row_data

    def download_clicked(self):
        """
        1. get selected files
        2. loop passing each file to download worker
        """

        selected = self.share_selected
        cwdir = "/".join(self.server_browser.browser_history)
        if selected:
            # pass in all the details needed for a successful login
            r_host = (self.username, self.password, self.remote_addr, self.remote_port)

            from_index = self.share_from_row
            for index in selected:
                name, f_exists, file_type, size = from_index(index)
                filename = os.path.join(self.download_to_folder, common._basename(name))

                # skip folders or files that exist, are downloading, errored (codes 1, 2, 3)
                if (file_type == "Folder") or f_exists:
                    continue
                # else downloading will start
                # -> function to change file status hence its icon, 2 for loading
                self.share_man.share_model._change_icon(filename, 2)
                # worker instance `w`
                w = asfaDownloads.Worker(filename, cwdir, size, r_host)
                # -> 1 for success
                w.signals.finished.connect(self.on_download_success)
                # -> 3 for error
                w.signals.error.connect(self.on_download_error)
                # -> 0 for cancelled
                w.signals.cancelled.connect(lambda file: self.share_man.share_model._change_icon(file, 0))
                # enqueue to worker manager
                self.downloads_win.workers.enqueue(w)

    def on_download_success(self, file):
        """ slot for download success signal """
        self.share_man.share_model._change_icon(file, 1)
        self.center_statusbar_signal.emit("")

    def on_download_error(self, file, error):
        """ slot for download failure signal """
        self.share_man.share_model._change_icon(file, 3)
        self.center_statusbar_signal.emit(f"Couldn't download. {error}")
        self.right_statusbar_signal.emit("")

    def share_double_click(self, index: QModelIndex):
        """ respond to share table double-click """
        self.handle_share_open(index)

    def share_open_file(self):
        """
        open file if downloaded else download
        slot for `enter` button
        """
        try:
            index = self.share_selected[-1]
            self.handle_share_open(index)
        except IndexError:
            self.center_statusbar_signal.emit("No file selected!")

    def share_menu_open(self):
        """
        called by Menu Open
        """
        try:
            index = self.share_selected[-1]
            self.handle_share_open(index, exclusive=True)
        except IndexError:
            self.center_statusbar_signal.emit("No file selected!")

    def handle_share_delete(self):
        """ delete selected if downloaded """
        selected = self.share_selected[::-1]
        if selected:
            confirmation = self.ask(f"Delete only downloaded files?\n\nNote: These files are sent to trash.")
            # if confirmation is YES
            if confirmation == QMessageBox.Yes:
                for index in selected:
                    filename, f_exists, file_type, size = self.share_from_row(index)
                    path = os.path.join(self.download_to_folder, common._basename(filename))
                    if f_exists and (os.path.getsize(path) == size) and (file_type == "File"):
                        asfaUtils.delete_file(path, trash=True)
                        asfaUtils.utils_logger.debug(f"Downloaded deleted: {path}")
                        # not downloaded, 0
                        self.share_man.share_model._change_icon(filename, 0)

    def handle_share_hide(self):
        """ remove row from model until next refresh """
        selected = self.share_selected
        row = self.share_from_row
        try:
            self.share_man.share_model.removeRows({row(index)[0] for index in selected})
        except AttributeError:
            pass

    def handle_share_open(self, index, exclusive=False):
        """ goto folder or open downloaded file """
        filename, f_exists, file_type, size = self.share_from_row(index)
        if file_type == "Folder":
            self.update_shared_files(path=filename)
        else:
            # open files that exist
            path = os.path.join(self.download_to_folder, common._basename(filename))
            if os.path.exists(path) and (os.path.getsize(path) == size):
                asfaUtils.start_file(path)
            elif not exclusive:
                self.download_clicked()

    def update_new_user(self, user: tuple):
        """
        receive new users and add their details to share profile dropdown menu
        """

        username, password, address, port = user
        # the details of a client, overwrite if client exists in dict
        self.local_usernames[username] = user
        self.share_man.online_users_dropdown.clear()
        self.share_man.online_users_dropdown.addItems(self.local_usernames.keys())
        self.share_man.online_users_dropdown.setCurrentText(self.username)

    def connect_to_user(self, username):
        """
        slot for recent dropdown currentTextChanged signal
        `username` is the current profile
        """
        client_details = self.local_usernames.get(username)
        if client_details:
            self.username, self.password, self.remote_addr, self.remote_port = client_details
            # update server browser
            self.server_browser.updateUser(client_details)
            # for share files tab
            self.update_shared_files()

    def update_resolver(self, user: tuple):
        """ update the username-ip resolution dictionary """

        # user = (username, (ip, port)); received from MCAST
        self.dn_lookup[user[0]] = user[1]
        self.settings_man.server_name.add_name(user[0])
        # current_addr = self.dn_lookup.get(self.username)
        # try:
        #     if current_addr and (current_addr != (self.remote_addr, self.remote_port)):
        #         # update IP changes
        #         self.remote_addr, self.remote_port = current_addr
        # except Exception:
        #     pass
