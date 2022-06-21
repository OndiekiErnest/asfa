__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"


import sys
import os
import common
import errno

from PyQt5.QtCore import (
    QAbstractListModel,
    QRect,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    pyqtSlot,
)
from PyQt5.QtGui import QBrush, QColor, QPen, QPainter
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QApplication,
    QListView,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)


downloads_logger = common.logging.getLogger(__name__)
downloads_logger.info(f">>> Initialized {__name__}")


STATUS_WAITING = "waiting"
STATUS_RUNNING = "running"
STATUS_ERROR = "error"
STATUS_COMPLETE = "complete"

STATUS_COLORS = {
    STATUS_RUNNING: "#1a8602",  # green
    STATUS_ERROR: "#e31a1c",  # red
    STATUS_COMPLETE: "#282828",  # dark gray
    STATUS_WAITING: "#cccccc",  # light gray
}

DEFAULT_STATE = {"progress": 0, "status": STATUS_WAITING}
EXISTS_STATE = {"progress": 100, "status": STATUS_COMPLETE}


def unlink_file(filename: str):
    """ delete file; ignore errors """
    try:
        os.unlink(filename)
        downloads_logger.info(f">>> Deleted partial file {filename}")
    except Exception as e:
        downloads_logger.error(f"{e}")


class WorkerSignals(common.QObject):
    """
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        `str` unique job ID

    error
        `tuple` job ID, error str

    progress
        (`str`, `float`, `int`, `float`) indicating job_id, progress, data length, file_size

    status
        `tuple` job ID, status string

    cancelled
        `str` job ID
    """
    __slots__ = ()

    error = common.pyqtSignal(str, str)
    cancelled = common.pyqtSignal(str)

    finished = common.pyqtSignal(str)
    progress = common.pyqtSignal(str, float, int, float)
    status = common.pyqtSignal(str, str)


class Worker(QRunnable):
    """
    Worker thread

    Inherits from QRunnable to handle worker thread setup, signals and wrap-up.

    :param file: str filename
    :param size: file size

    """

    __slots__ = (
        "signals", "job_id", "is_killed", "filename", "file_write",
        "file_size", "cwdir"
    )

    def __init__(self, file: str, cwd: str, size: int, host: tuple):
        super().__init__()

        self.username, self.password, self.addr, self.port = host
        self.filename = common._basename(file)
        self.cwdir = cwd
        self.file_size = size
        # file size or 1024 bytes if file size is 0
        down_size = self.file_size or 1024
        # down_size or 10 MB
        self.blocksize = min(down_size, 10485760)
        # self.addr, self.port = None, 3000
        self.is_killed = 0
        self.transferred = 0
        self.signals = WorkerSignals()

        # give this job a unique ID, which is its dst path
        self.job_id = file
        self.signals.status.emit(self.job_id, STATUS_WAITING)

    def cleanup(self):
        """ close connection and the open file """

        try:
            self.ftp.quit()
        except Exception:
            self.ftp.close()
        self.downloading_file.close()
        self.ftp = None
        self.downloading_file = None
        self.is_killed = 1

    def callback(self, data):

        try:
            self.file_write(data)
            data_len = len(data)
            self.transferred += data_len
            # emit the current progress signal
            self.signals.progress.emit(self.job_id, self.transferred, data_len, self.file_size)
            if self.is_killed:
                self.ftp.abort()
                self.cleanup()
                self.signals.status.emit(self.job_id, STATUS_COMPLETE)
                # delete the partial file
                unlink_file(self.job_id)
                return
        except Exception:
            pass

    @pyqtSlot()
    def run(self):
        """ start file download """
        self.ftp = common.ftp_tls()
        try:
            self.downloading_file = open(self.job_id, "wb")
            # localize write function to reduce overhead
            self.file_write = self.downloading_file.write
            # connect to the remote machine
            self.ftp.connect(self.addr, self.port)
            self.ftp.login(user=self.username, passwd=self.password)
            # set up a secure data channel
            self.ftp.prot_p()
            # switch to the right folder
            self.ftp.cwd(self.cwdir)
            self.signals.status.emit(self.job_id, STATUS_RUNNING)
            # rest is an int for file offset
            self.ftp.retrbinary(f"RETR {self.filename}", self.callback, blocksize=self.blocksize)

        # errror when the file is not found
        except common.error_perm as e:
            # swallow the error and emit signals
            downloads_logger.error(f"Couldn't download: {str(e)}")
            self.signals.error.emit(self.job_id, str(e))
            self.signals.status.emit(self.job_id, STATUS_ERROR)
            self.cleanup()
            unlink_file(self.job_id)

        # write permission denied (PermissionError)
        except Exception as e:
            if not self.is_killed:
                error_msg = str(e)
                self.cleanup()
                if e.errno == errno.WSAECONNREFUSED:
                    error_msg = "No connection could be made."
                downloads_logger.error(f"Couldn't download: {error_msg}")
                self.signals.error.emit(self.job_id, error_msg)
                self.signals.status.emit(self.job_id, STATUS_ERROR)
                # delete partial file
                unlink_file(self.job_id)

        else:
            downloads_logger.info(f"Downloaded: {self.job_id}")
            self.signals.status.emit(self.job_id, STATUS_COMPLETE)
            self.signals.finished.emit(self.job_id)
            self.cleanup()

    def kill(self):
        self.signals.cancelled.emit(self.job_id)
        self.is_killed = 1


class WorkerManager(QAbstractListModel):
    """
    Manager to handle our worker queues and state.
    Also functions as a Qt data model for a view
    displaying progress for each worker.

    """

    __slots__ = ("downloads_threadpool", "total_errors", "readable_total_size",
                 "readable", "status_timer", "download_progress", "total_files_size")

    _workers = {}
    _state = {}
    _total_sizes = {}

    status = common.pyqtSignal(str)
    current_task_progress = common.pyqtSignal(str)
    worker_started = common.pyqtSignal()
    all_done = common.pyqtSignal()

    def __init__(self):
        super().__init__()

        # Create a threadpool for our workers.
        self.downloads_threadpool = QThreadPool()
        self.active_workers = set()
        self.total_errors = 0
        self.total_files_size = 0
        self.download_progress = 0
        self.readable = common.convert_bytes
        self.readable_total_size = self.readable(0)
        # set files to download at a time
        self.downloads_threadpool.setMaxThreadCount(1)
        downloads_logger.debug(f"Can download {self.downloads_threadpool.maxThreadCount()} file(s) at a time")

        self.status_timer = QTimer()
        self.status_timer.setInterval(100)
        self.status_timer.timeout.connect(self.notify_status)
        self.status_timer.start()

    def notify_status(self):
        """ update the user of the remaining downloads """

        self.status.emit(f"{len(self._workers)} remaining, {self.total_errors} errors")

    def enqueue(self, worker):
        """
        Enqueue a worker to run (at some point) by passing it to the QThreadPool.
        """
        size = worker.file_size
        name = worker.job_id

        self.active_workers.add(name)
        self.worker_started.emit()
        worker.signals.error.connect(self.receive_error)
        worker.signals.status.connect(self.receive_status)
        worker.signals.progress.connect(self.receive_progress)
        worker.signals.finished.connect(self.done)

        self._total_sizes[name] = size
        self.total_files_size += size
        self.readable_total_size = self.readable(self.total_files_size)

        self._workers[name] = worker
        self._state[name] = DEFAULT_STATE.copy()

        self.downloads_threadpool.start(worker)
        self.layoutChanged.emit()

    def receive_status(self, job_id, status):
        try:
            self._state[job_id]["status"] = status
            self.layoutChanged.emit()
        except KeyError:
            pass

    def receive_progress(self, job_id, transferred, data_length, file_size):
        try:
            # total downloads size
            self.download_progress += data_length
            # % of total size
            percentage = (transferred * 100) / file_size
            self._state[job_id]["progress"] = percentage
            self.current_task_progress.emit(f"{self.readable(self.download_progress)} / {self.readable_total_size}")
            self.layoutChanged.emit()
        except KeyError:
            self.current_task_progress.emit("")

    def receive_error(self, job_id, message):
        downloads_logger.error(f"Error downloading: {message}")
        self.total_errors += 1
        self.remove_filesize(job_id)
        self.done(job_id)

    def done(self, job_id):
        """
        Task/worker complete. Remove it from the active workers
        dictionary. We leave it in _state, as this is used to
        to display past/complete workers.
        """
        try:
            del self._workers[job_id]
            self.active_workers.remove(job_id)
            if not self._workers:
                # signal to close downloads tab
                self.all_done.emit()
                self.download_progress = 0
                self.current_task_progress.emit("")
            self.layoutChanged.emit()
        except KeyError:
            pass

    def remove_filesize(self, job_id):
        """ decrement total size by job_id value """
        try:
            size = self._total_sizes.pop(job_id)
            self.total_files_size -= size
            self.readable_total_size = self.readable(self.total_files_size)
        except Exception:
            pass

    def cleanup(self):
        """ temporarily remove items from view """
        # avoid RuntimeError: dictionary changed size during iteration
        items = self._state.copy().items()
        for job_id, s in items:
            if s["status"] in (STATUS_COMPLETE, STATUS_ERROR):
                del self._state[job_id]
        self.total_errors = 0
        self.layoutChanged.emit()

    def kill(self, job_id):
        """ cancel one job with `job_id` """

        self.remove_filesize(job_id)
        if job_id in self._workers:
            self._workers[job_id].kill()
            del self._state[job_id]
            # delete job_id and emit layout change
            self.done(job_id)

    def cancel(self):
        """ cancel and close everything """
        # avoid RuntimeError: dictionary changed size during iteration
        items = self._workers.copy().items()
        for job_id, worker in items:
            worker.kill()
            del self._state[job_id]
            # remove file size
            self.remove_filesize(job_id)
            # delete job_id and emit layout change
            self.done(job_id)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:

            job_ids = list(self._state.keys())
            job_id = job_ids[index.row()]
            return job_id, self._state[job_id]

    def rowCount(self, index):
        return len(self._state)

    def add_row(self, name: str):
        """ add row to model if name is of a file that exists """
        self._state[name] = EXISTS_STATE.copy()


class ProgressBarDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index):
        # data is our status dict, containing progress, id, status
        job_id, data = index.model().data(index, Qt.DisplayRole)
        if data["progress"] > 0:
            color = QColor(STATUS_COLORS[data["status"]])

            brush = QBrush()
            brush.setColor(color)
            brush.setStyle(Qt.SolidPattern)

            width = option.rect.width() * data["progress"] / 100

            #  Copy of the rect, so we can modify.
            rect = QRect(option.rect)
            rect.setWidth(width)

        else:
            color = QColor(STATUS_COLORS[data["status"]])
            brush = QBrush()
            brush.setColor(color)
            brush.setStyle(Qt.SolidPattern)
            rect = option.rect

        if option.state & QStyle.State_Selected:
            brush = QBrush()
            brush.setColor(QColor("#03afff"))
            brush.setStyle(Qt.SolidPattern)

        pen = QPen()
        pen.setColor(Qt.black)
        painter.fillRect(rect, brush)
        painter.drawText(option.rect, Qt.AlignLeft, job_id)


class DownloadsWindow(QWidget):
    """
    window for displaying downloading files
    inherits:
        QWidget
    """

    def __init__(self):
        super().__init__()

        self.setObjectName("downloadsWin")
        self.workers = WorkerManager()
        self.download_location = ""
        main_layout = QVBoxLayout()
        btns_layout = QHBoxLayout()
        bottom_layout = QHBoxLayout()

        main_layout.addLayout(btns_layout)

        self.d_location_label = QLabel()
        self.d_location_label.setAlignment(Qt.AlignRight)

        self.progress_view = QListView()
        self.progress_view.clicked.connect(self.change_cancel_btn)
        self.progress_view.setModel(self.workers)
        delegate = ProgressBarDelegate()
        self.progress_view.setItemDelegate(delegate)

        main_layout.addWidget(self.progress_view)

        self.stop_btn = QPushButton("Cancel")
        self.stop_btn.setToolTip("Stop downloading selected files")
        self.stop_btn.setDisabled(True)
        self.stop_btn.clicked.connect(self.stop_worker)

        clear = QPushButton("Clear")
        clear.setToolTip("Temporarily clear the files list from view")
        clear.pressed.connect(self.workers.cleanup)

        self.now_downloading = QLabel()

        status_bar = QLabel()
        self.workers.status.connect(status_bar.setText)
        self.workers.current_task_progress.connect(self.now_downloading.setText)

        btns_layout.addWidget(self.stop_btn)
        btns_layout.addWidget(clear)
        btns_layout.addWidget(self.now_downloading)
        btns_layout.addStretch()

        bottom_layout.addWidget(status_bar)
        bottom_layout.addWidget(self.d_location_label)

        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)

    def change_cancel_btn(self):
        """ enable cancel btn when item clicked """
        selected = self.progress_view.selectedIndexes()
        if selected:
            _, status = self.workers.data(selected[0])
            if status.get("status") == "running":
                self.stop_btn.setEnabled(True)
            else:
                self.stop_btn.setDisabled(True)

    def stop_worker(self):
        selected = self.progress_view.selectedIndexes()
        if selected:
            for idx in selected:
                # add file/job_id to files to be deleted on close
                job_id, _ = self.workers.data(idx)
                self.workers.kill(job_id)
                downloads_logger.debug(f"Downloading cancelled: '{job_id}'")
            self.stop_btn.setDisabled(True)

    def change_title(self, text: str):
        """ change title info """
        if text:
            self.download_location = text
            self.d_location_label.setText(f"Download location: '{self.download_location}'")


if __name__ == "__main__":

    app = QApplication(sys.argv)
    window = DownloadsWindow()
    window.show()
    app.exec_()
