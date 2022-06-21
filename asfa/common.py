__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"

import sys
import os
import socket
import ctypes
import ipaddress
import logging
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QThread
from ftplib import FTP_TLS, error_perm  # error_perm used by asfaDownloads; network.browser
from hashlib import shake_256
from registry import file_type
from psutil import net_if_addrs


logging.basicConfig(level=logging.INFO)
common_logger = logging.getLogger(__name__)
common_logger.info(f">>> Initialized {__name__}")

SAFEGUARD_PASSWORD = False

# known app paths
# base ( dirname(abspath(__file__)) )
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# system sleep inhibit/release constants
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

INHIBIT = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
RELEASE = ES_CONTINUOUS


def prevent_sleep():
    """ prevent the system from sleeping """
    # Windows
    ctypes.windll.kernel32.SetThreadExecutionState(INHIBIT)
    common_logger.info("Sleep inhibited")


def release_sleep():
    """ release the sleep lock """
    # Windows
    ctypes.windll.kernel32.SetThreadExecutionState(RELEASE)
    common_logger.info("Sleep inhibit released")


def r_path(relpath) -> str:
    """
    Get absolute path
    works even when this app is frozen
    """

    base_path = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(base_path, relpath)


# data folder
DATA_DIR = r_path("data")

MCAST_GROUP = "224.1.1.3"
MCAST_PORT = 12001
MCAST_SIGN = ")tr@P("
MCAST_TTL = 2

file_excludes = {"AlbumArtSmall.jpg", "Folder.jpg", "desktop.ini"}
other_file_excludes = ("AlbumArt_", "~")

CERTF = os.path.join(DATA_DIR, "keycert.pem")
OS_SEP = os.sep

USERNAME = socket.getfqdn()


class Thread(QThread):
    """
    run `func` in re-implemented QThread API
    """
    __slots__ = ("func", "args", "kwargs")
    results = pyqtSignal(object)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.setTerminationEnabled(1)
        self.func = func
        self.args = args
        self.kwargs = kwargs

    @pyqtSlot()
    def run(self):
        try:
            common_logger.debug("Threaded function started")
            finished = self.func(*self.args, **self.kwargs)
            common_logger.debug("Threaded function finished")
            self.results.emit(finished)
        except Exception as e:
            common_logger.error(f"Error running function in thread: {str(e)}")


class BasicSignals(QObject):

    error = pyqtSignal(str)
    success = pyqtSignal(str)


def isPortAvailable(port) -> bool:
    """
    test and see if a port number is open
    """
    _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = _sock.connect_ex(("127.0.0.1", port))
    _sock.close()
    return not (result == 0)


def get_port() -> int:
    """ get available port """
    for i in range(3000, 6067):
        if isPortAvailable(i):
            return i


def valid_ip(address):
    """ return address if it is a valid ip addresss"""
    try:
        return ipaddress.ip_address(address)
    except ValueError:
        return


def get_machine_ip(family=socket.AF_INET, intf="Wi-Fi") -> str:
    """ get the address of type `family` """
    net_intfs = net_if_addrs()
    default_loopback = "127.0.0.1"

    host = socket.gethostbyname(socket.gethostname())
    if host == default_loopback:
        return host

    for interface, snics in net_intfs.items():
        if interface.startswith(intf):
            #  get all system network interface cards
            return "".join([snic.address for snic in snics if snic.family == family])


MACHINE_IP = get_machine_ip()


def ftp_tls() -> FTP_TLS:
    """ create FTP_TLS instance and return it """
    ftp = FTP_TLS()
    ftp.certfile = CERTF
    ftp.encoding = "utf-8"
    return ftp


def pass_hash(password: str):
    """ return a shake hash """
    if SAFEGUARD_PASSWORD:
        return shake_256(password.encode()).hexdigest(8)
    return password


def _basename(path):
    """ strip trailing slash and return basename """
    # A basename() variant which first strips the trailing slash, if present.
    # Thus we always get the last component of the path, even for directories.
    # borrowed from shutil.py
    sep = os.path.sep + (os.path.altsep or '')
    return os.path.basename(path.rstrip(sep))


def isSysFile(path) -> bool:
    """ is a sys file based on pre-defined criteria """
    filename = _basename(path)
    return (filename.startswith(other_file_excludes) or (filename in file_excludes))


def scan_folder(path: str):
    """ Generator: return a list of folders """
    if os.path.exists(path):
        for entry in os.scandir(path):
            if entry.is_dir():
                # get the path
                yield entry.path
    yield


def to_bytes(value: str) -> float:
    """ convert a str (of the form, 'size unit') to float for sorting """
    try:
        size, unit = value.split(" ")
        size = float(size)
        if unit == "GB":
            return size * 1073741824
        elif unit == "MB":
            return size * 1048576
        elif unit == "KB":
            return size * 1024
        else:
            return size
    except Exception:
        return 0


def convert_bytes(num: float) -> str:
    """ format bytes to respective units for presentation (max GB) """
    try:
        if num >= 1073741824:
            return f"{round(num / 1073741824, 2)} GB"
        elif num >= 1048576:
            return f"{round(num / 1048576, 2)} MB"
        elif num >= 1024:
            return f"{round(num / 1024, 2)} KB"
        else:
            return f"{num} Bytes"
    except Exception:
        return "NaN"


def get_files(folder: str):
    """
    return the file and its stats
    """

    for entry in os.scandir(folder):
        # avoid listing folder-info files
        if entry.is_file() and not isSysFile(entry.path):
            # get the needed details and return them
            yield get_file_details(entry.path)


def get_file_details(filename: str):
    """
    return file name, folder, ext, size
    """
    name, folder = _basename(filename), os.path.dirname(filename)
    ext = file_type(os.path.splitext(name)[-1])  # add file type from registry
    size = os.path.getsize(filename)
    return name, folder, ext, size


def _join(file: str, folder: str = DATA_DIR):
    """ os path join re-implemented """
    return os.path.join(folder, _basename(file))


class Icons(QObject):
    """ all app icon files """

    __slots__ = ()

    app_icon = _join("asfa.png")
    download_icon = _join("download.png")
    done_icon = _join("done.png")
    cancel_icon = _join("cancel.png")
    copy_icon = _join("copy.png")
    cut_icon = _join("cut.png")
    delete_icon = _join("delete.png")
    open_icon = _join("open.png")
    check_icon = _join("check.png")
    search_icon = _join("search.png")
    refresh_icon = _join("refresh.png")
    tick_icon = _join("tick.png")
    arrow_icon = _join("arrow.png")
    loading_icon = _join("load.png")
    error_icon = _join("error.png")
    back_icon = _join("back.png")
    add_folder_icon = _join("add_folder.png")
    show_icon = _join("show.png")
    hide_icon = _join("hide.png")
    switch_icon = _join("switch.png")
    serve_icon = _join("serve.png")
