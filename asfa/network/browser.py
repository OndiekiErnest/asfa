__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"

from common import (
    BasicSignals,
    pyqtSignal,
    isSysFile,
    _basename,
    ftp_tls,
    error_perm,
    logging,
    os
)
import errno


browser_logger = logging.getLogger(__name__)
browser_logger.info(f">>> Initialized {__name__}")


class BrowserSignals(BasicSignals):
    """ extended basic signals class """
    file_exists = pyqtSignal(str)
    refresh = pyqtSignal()


class ServerBrowser:
    def __init__(self):
        self.address = None
        self.port = 3000
        self.dst_dir = None
        self.browser_history = [""]
        self.running = set()
        self.signals = BrowserSignals()

    def updateUser(self, host: tuple):
        self.username, self.password, self.address, self.port = host
        self.browser_history = [""]

    def updateDir(self, path, forward=1):
        if path and (forward):
            self.browser_history.append(path)

    def getFilesList(self):
        """ return a list of files/folders and their sizes """
        ftp = ftp_tls()

        self.signals.refresh.emit()
        try:
            ftp.connect(self.address, self.port)
            ftp.login(user=self.username, passwd=self.password)
            # set up a secure data connection
            ftp.prot_p()
            cwdir = "/".join(self.browser_history)
            ftp.cwd(cwdir)

            browser_logger.debug(f"Fetching files from '{cwdir}'")
            fetched_items = 0
            index = -1
            for index, item in enumerate(ftp.mlsd(facts=["type", "size"])):
                f_exists = 0
                name, size = _basename(item[0]), int(item[1].get("size", 0))
                file_type = "Folder" if item[1]["type"] == "dir" else "File"
                if file_type == "File" and (isSysFile(name)):
                    # skip
                    continue
                local_path = os.path.join(self.dst_dir, name)
                if os.path.exists(local_path) and (os.path.getsize(local_path) == size):
                    f_exists = 1
                    self.signals.file_exists.emit(local_path)
                elif (local_path in self.running):
                    f_exists = 2
                # increment fetched items by one
                fetched_items += 1
                # yield our row
                yield (name, f_exists, file_type, size)
            # quit the connection
            ftp.quit()
            browser_logger.debug(f"Fetched {index + 1:,} items, {fetched_items:,} valid")
            self.signals.success.emit(f"Fetched folder items: {fetched_items:,}")
            self.signals.error.emit("")

        except error_perm as e:
            ftp.close()
            self.on_error(e)
            self.signals.error.emit(str(e))
            yield

        except AttributeError as e:
            ftp.close()
            self.on_error(e)
            self.signals.error.emit("First, set your credentials in the Settings tab.")
            yield

        except Exception as e:
            error_msg = "Something went wrong."
            if e.errno == errno.WSAECONNREFUSED:
                error_msg = "No connection could be made."
            ftp.close()
            self.on_error(e)
            self.signals.error.emit(f"Failed. {error_msg}")
            yield

    def on_error(self, error):
        # get back to Home://
        self.browser_history = [""]
        browser_logger.error(f"Error fetching files: {str(error)}")
        self.signals.success.emit("")
