__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"

import uuid
import time
import socket
import struct
import os
from psutil import disk_partitions
from send2trash import TrashPermissionError, send2trash
from filestat import copystat, _samefile
from PyQt5.QtCore import QRunnable, QThread, pyqtSlot
import common
from config import Settings

utils_logger = common.logging.getLogger(__name__)
utils_logger.info(f">>> Initialized {__name__}")


def isRemovable(path: str):
    """ returns True if path (e.g. G:\\) is removable """
    try:
        return (path in {i.mountpoint for i in disk_partitions() if "removable" in i.opts})
    except Exception:
        return False


def get_settings() -> Settings:
    """ get the settings class instance """
    settings = Settings()
    settings.load()
    return settings


class NetMonitorSignals(common.QObject):
    """
    signals to emit on IP address changes
    supported signals:
        changes
        `str` IP address of machine
    """
    __slots__ = ()

    changes = common.pyqtSignal(str)


class NetMonitor(QThread):
    """ monitor IP address changes and emit signals accordingly """

    __slots__ = ("signals", "alive", "machine_ip")

    def __init__(self):
        super().__init__()
        self.setTerminationEnabled(True)

        utils_logger.info("Starting IP address monitor")
        self.signals = NetMonitorSignals()
        self.alive = 1
        self.machine_ip = common.MACHINE_IP

    @pyqtSlot()
    def run(self):
        while self.alive:
            new_ip = common.get_machine_ip()
            if new_ip != self.machine_ip:
                utils_logger.info(
                    f"Reporting IP address change: '{self.machine_ip}' -> '{new_ip}'")
                self.machine_ip = new_ip
                self.signals.changes.emit(new_ip)
            time.sleep(3)

    def kill(self):
        """ kill the while loop """
        self.alive = 0
        self.quit()
        self.wait()
        utils_logger.info("Stopped IP address monitor")

    def __del__(self):
        self.kill()
        del self


class DeviceSignals(common.QObject):
    """
    Defines the signals available from a running worker thread.
    Supported signals are:
    error
    `str` Exception string
    on_change
    `list` data returned from processing
    """
    __slots__ = ()
    error = common.pyqtSignal(str)
    on_change = common.pyqtSignal(list)


class DeviceListener(QThread):
    """
    trigger a callback when a device has been plugged in or out
    """
    __slots__ = ("signals", "disks", "is_running", "change")

    def __init__(self):
        utils_logger.info("Starting USB drive listener")

        super().__init__()
        self.setTerminationEnabled(1)

        self.signals = DeviceSignals()
        # check on startup
        self.disks = self.list_drives()
        self.is_running = 0
        self.change = len(self.disks)

    @pyqtSlot()
    def run(self):
        self.is_running = 1
        while self.is_running:
            self.disks = self.list_drives()
            available = len(self.disks)
            if self.change != available:
                self._on_change(self.disks)
                self.change = available
            time.sleep(0.9)

    def list_drives(self) -> list:
        """
        Get a list of drives using psutil
        :return: list of drive str
        """

        try:
            return [i.mountpoint for i in disk_partitions() if "removable" in i.opts]
        except Exception as e:
            utils_logger.error(f"Error listing drives: {str(e)}")
            self.signals.error.emit("Failed to enumerate drives")
            return []

    def _on_change(self, drives: list):
        """ emit signal of new disks """
        self.signals.on_change.emit(self.disks)

    def close(self):
        utils_logger.info("Stopping USB drive listener")
        self.is_running = 0
        self.quit()
        self.wait()

    def __del__(self):
        self.close()
        del self


class TransferSignals(common.QObject):
    """
    Defines the signals available from a running worker thread.
    Supported signals are:
    finished
    `str` transfer id
    progress
    `int` indicating % progress
    """
    __slots__ = ()
    finished = common.pyqtSignal(str)
    progress = common.pyqtSignal(str, int)
    transferred = common.pyqtSignal(str, float)
    duplicate = common.pyqtSignal(str)


class Transfer(QRunnable):
    """
    File transfer runnable
    Runs on a different thread
    inherits:
        QRunnable
    parameters:
        `src`: str file path
        `dst`: str file/dir path
        `size`: float `src` file size in bytes
        `task`: str copy or move
    """
    __slots__ = (
        "src", "dst", "size", "model", "task",
        "index", "signals", "running", "job_id")

    def __init__(self, src, dst, size, task="copy"):
        super().__init__()
        self.setAutoDelete(True)
        self.src = src
        self.dst = dst
        self.size = size
        self.task = task
        self.signals = TransferSignals()
        self.running = 0
        # Give this job a unique ID.
        self.job_id = str(uuid.uuid4())

    @pyqtSlot()
    def run(self):
        # run the specified function
        if self.task == "copy":
            utils_logger.debug(f"Copying files to '{self.dst}'")
            self.copy(self.src, self.dst)
        elif self.task == "move":
            utils_logger.debug(f"Moving files to '{self.dst}'")
            self.move(self.src, self.dst)

    def _copyfileobj_readinto(self, fsrc, fdst, length=1048576):
        """
        readinto()/memoryview()-based variant of copyfileobj()
        *fsrc* must support readinto() method and both files must be
        open in binary mode.
        """
        utils_logger.debug(f"Transferring, method: readinto, buffer: {length}")
        progress = 0
        self.running = 1
        # localize variable access to minimize overhead
        fsrc_readinto = fsrc.readinto
        fdst_write = fdst.write
        with memoryview(bytearray(length)) as mv:
            try:
                while 1:
                    n = fsrc_readinto(mv)
                    if not n:
                        self.signals.finished.emit(self.job_id)
                        self.running = 0
                        utils_logger.debug("Successful transfer")
                        return 1

                    elif n < length:
                        with mv[:n] as smv:
                            fdst.write(smv)
                    else:
                        fdst_write(mv)
                    progress += n
                    percentage = (progress * 100) / self.size
                    self.signals.transferred.emit(self.job_id, progress)
                    self.signals.progress.emit(self.job_id, percentage)
                    # handle cancel
                    if not self.running:
                        utils_logger.debug("Cancelled transfer")
                        self.signals.progress.emit(self.job_id, 100)
                        self.signals.finished.emit(self.job_id)
                        return 0
            except Exception as e:
                utils_logger.error(f"Error in transferring: {str(e)}")
                self.running = 0
                self.signals.progress.emit(self.job_id, 100)
                self.signals.finished.emit(self.job_id)
                return 0

    def _copyfileobj(self, fsrc, fdst, length=1048576):
        """
        copy data from file-like object fsrc to file-like object fdst
        return 1 on success, 0 otherwise
        """
        utils_logger.debug(
            f"Transferring, method: copy-buffer, buffer: {length}")
        progress = 0
        self.running = 1
        # localize variables to avoid overhead
        fsrc_read = fsrc.read
        fdst_write = fdst.write
        try:
            while 1:
                buff = fsrc_read(length)
                if not buff:
                    self.signals.finished.emit(self.job_id)
                    self.running = 0
                    # break and return success
                    utils_logger.debug("Successful transfer")
                    return 1
                fdst_write(buff)
                progress += len(buff)
                percentage = (progress * 100) / self.size
                self.signals.transferred.emit(self.job_id, progress)
                self.signals.progress.emit(self.job_id, percentage)
                # handle cancel
                if not self.running:
                    utils_logger.debug("Cancelled transfer")
                    self.signals.progress.emit(self.job_id, 100)
                    self.signals.finished.emit(self.job_id)
                    return 0

        except Exception as e:
            utils_logger.error(f"Error in transferring: {str(e)}")
            self.running = 0
            self.signals.progress.emit(self.job_id, 100)
            self.signals.finished.emit(self.job_id)
            return 0

    def _copyfile(self, src, dst):
        """ check if file exists, if same filesystem, else prepare file objects """
        if file_exists(src, dst):
            # end prematurely and return special case 2
            utils_logger.debug(f"File already exists '{dst}'")
            self.signals.duplicate.emit(dst)
            self.signals.progress.emit(self.job_id, 100)
            self.signals.finished.emit(self.job_id)
            return 2

        elif same_filesystem(src, dst) and self.task == "move":
            utils_logger.debug("Renaming same filesystem file")

            # just rename and return success, 1
            os.rename(src, dst)
            self.signals.progress.emit(self.job_id, 100)
            self.signals.finished.emit(self.job_id)
            return 1

        else:
            try:
                # prepare file objects for read/write
                with open(src, 'rb') as fsrc:
                    with open(dst, 'wb') as fdst:
                        if self.size > 0:
                            return self._copyfileobj_readinto(fsrc, fdst, length=min(1048576, self.size))
                        # copy files with 0 sizes
                        return self._copyfileobj(fsrc, fdst)
            except PermissionError:
                self.signals.progress.emit(self.job_id, 100)
                self.signals.finished.emit(self.job_id)
                return 0

    def copy(self, src, dst):
        """ rename folders and prepare files for copying """
        if os.path.isdir(dst):
            dst = os.path.join(dst, common._basename(src))
        done = self._copyfile(src, dst)
        # copy file, then copy file stats
        self.copy_stat(src, dst)
        if not done:
            # clean up incomplete dst file

            utils_logger.debug(f"Deleting incomplete file '{dst}'")
            delete_file(dst)
        return done

    def move(self, src, dst):
        """ copy then delete when done """
        done = self.copy(src, dst)
        # delete only transferred files, leave duplicates alone
        if done == 1:
            # delete source file only on success
            utils_logger.debug(f"File moved. Deleting source file '{src}'")
            delete_file(src)
            # try removing folder
            remove_folder(os.path.dirname(src))

    def copy_stat(self, src, dst):
        try:
            copystat(src, dst)
        except Exception as e:
            utils_logger.error(f"Stats error: {e}")


class ThreadBase(QThread):
    """
    Abstract implementation for `BroadcastUser` and `ReceiveUser`
    """
    __slots__ = ("is_running", )

    def __init__(self):
        super().__init__()
        self.setTerminationEnabled(True)
        self.is_running = 0

    @pyqtSlot()
    def run(self):
        self.is_running = 1
        self.task()
        self.is_running = 0

    def task(self):
        pass


class ReceiveUser(ThreadBase):
    """
    Receive username and IP of other machines
    """
    __slots__ = ("sock", )
    new_user = common.pyqtSignal(tuple)
    local_machine_ip = common.MACHINE_IP

    def task(self):
        """ start receiving task """
        utils_logger.info(">>> Starting MCAST Listening...")
        self.sock = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # allow socket reuse
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.sock.bind(("", common.MCAST_PORT))

        mreq = struct.pack("4s4s", socket.inet_aton(
            common.MCAST_GROUP), socket.inet_aton(self.local_machine_ip))

        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        while self.is_running:
            try:

                data = self.sock.recv(10240).decode("utf-8")

                if data.startswith("asfa"):
                    app_name, username, ipaddr, port = data.split("!")
                    self.new_user.emit((username, (ipaddr, int(port))))
            except Exception:
                pass

            time.sleep(1)

    def close_thread(self):
        """ set running flag to 0, close socket """
        try:
            self.sock.close()
        except Exception:
            pass
        self.is_running = 0
        self.quit()
        self.wait()
        utils_logger.info("Stopped MCAST listening task")

    def __del__(self):
        self.close_thread()
        del self


def close_window(layout):
    """
    delete PyQt5 widgets recursively
    assumes:
        layout is a valid QLayout class
    """

    if layout is not None:
        utils_logger.debug("Deleting widgets in layout")
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                close_window(child.layout())
        utils_logger.debug("Done deleting widgets")


def start_file(filename):
    """
    open file using the default app
    """
    os.startfile(filename)


def file_exists(src, dst) -> bool:
    """ compare file properties """
    if os.path.isdir(dst):
        dst = os.path.join(dst, common._basename(src))
    if os.path.exists(dst):
        # return (os.path.getsize(src) == os.path.getsize(dst))
        return True
    return False


def same_filesystem(src, dst) -> bool:
    if os.path.commonprefix((src, dst)):
        return True
    return False


def delete_file(filename, trash=False):
    """
    permanently delete a file if `trash` is False
    """
    if trash:
        try:
            send2trash(filename)
        except TrashPermissionError as e:
            utils_logger.error(f"Cannot trash file: {e}")
    else:
        try:
            os.unlink(filename)
        except Exception as e:
            utils_logger.error(f"Cannot remove file: {e}")


def remove_folder(folder):
    """ delete empty folder """
    try:
        os.rmdir(folder)
        utils_logger.debug(f"Dir removed: '{folder}'")
    except Exception:
        utils_logger.error("Cannot remove dir, not empty")


def trim_text(txt: str, length: int) -> str:
    """
    reduce the length of a string to the specified length
    """
    if len(txt) > length:
        return f"{txt[:length]}..."
    else:
        return txt


def get_folder_extensions(folder):
    """ scan dir and yield extensions in folder, and file size"""
    for entry in os.scandir(folder):
        try:
            full_path = entry.path
            # avoid listing folder-info files
            if entry.is_file() and not common.isSysFile(full_path):
                size = os.path.getsize(full_path)
                ext = os.path.splitext(full_path)[-1] or "without extensions"
                yield (ext.lower(), size)
        except Exception:
            continue


def get_ext_recursive(folder):
    """ walk through folders and yield unique extensions """
    extensions = set()
    total_size = 0
    for subfolders in get_folders(folder):
        for ext, size in get_folder_extensions(subfolders):
            extensions.add(ext)
            total_size += size
    exts_lst = list(extensions)
    exts_lst.sort(reverse=True)
    return (total_size, exts_lst)


def get_folders(path: str) -> list:
    """
    return all recursive folders in path
    return empty folder if path doesn't exist
    """

    if os.path.exists(path):
        for folder, subfolders, files in os.walk(path):
            if files:
                yield folder


def get_files_folders(path: str):
    """ return a sorted list of files first and lastly folders """
    items = []
    for entry in os.scandir(path):
        if entry.is_file():
            # put files at the beginning
            items.insert(0, entry.path)
        else:
            # put folders at the end
            items.append(entry.path)
    return items
