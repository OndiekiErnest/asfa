__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"


import sys
import logging
from qss import QSS
from psutil import Process
from main import Controller, os
from PyQt5.QtWidgets import QApplication, QMessageBox


run_logger = logging.getLogger("run")
run_logger.info(">>> Initialized run")


app = QApplication(sys.argv)
app.setStyleSheet(QSS)
app.setStyle("Fusion")


def close_task(task: str):
    tasks = {"transferring": c.worker_manager.cancel, "downloading": c.downloads_win.workers.cancel}
    func = tasks.get(task)
    if func:
        func()


def close_app():
    c.tray.hide()
    c.hide()
    c.usb_thread.close()
    c.IP_monitor.kill()
    c.user_discoverer.close_thread()
    try:
        c.server.stopServer()
    except AttributeError:
        # pass if server is already shut
        pass
    app.quit()
    sys.exit(0)


def close_win():
    app_status = c.app_is_busy()
    if app_status:
        confirmation = c.ask(f"asfa App is busy {app_status}.\n\nDo you want to cancel and close anyway?")
        # if confirmation is YES
        if confirmation == QMessageBox.Yes:
            close_task(app_status)
            close_app()
    else:
        close_app()


c = Controller()
c.tray_menu.quit.clicked.connect(close_win)

# memory usage in MBs
memory_usage = Process(os.getpid()).memory_info().rss / 1048576
print(f"[MEMORY USED] : {memory_usage} MB")

sys.exit(app.exec_())
