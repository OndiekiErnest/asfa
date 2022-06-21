__author__ = "Ondieki"
__email__ = "ondieki.codes@gmail.com"

# Using examples from https://pythonhosted.org/pyftpdlib/tutorial.html

from pyftpdlib.handlers import ThrottledDTPHandler, TLS_FTPHandler, TLS_DTPHandler
from pyftpdlib.servers import FTPServer
from pyftpdlib.authorizers import DummyAuthorizer, AuthenticationFailed

import common
from time import sleep
import os
from PyQt5.QtCore import QThread


server_logger = common.logging.getLogger(__name__)
server_logger.info(f">>> Initialized {__name__}")


class BroadcastUser(QThread):
    """
    Multicast username and IP of this computer
    inherits:
        QThread
    parameters:
        `name`: str
        `addr`: tuple[str, int]
    """
    __slots__ = ("is_running", "ipaddr", "name")

    def __init__(self, name, addr, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTerminationEnabled(True)

        self.is_running = 0
        self.username = name
        self.ipaddr, self.use_port = addr

    def run(self):
        """ start broadcasting task """
        self.is_running = 1
        # log debugging info
        server_logger.info("Starting MCAST task...")

        self.sckt = common.socket.socket(
            common.socket.AF_INET, common.socket.SOCK_DGRAM, common.socket.IPPROTO_UDP)
        self.sckt.setsockopt(common.socket.IPPROTO_IP,
                             common.socket.IP_MULTICAST_TTL, common.MCAST_TTL)

        while self.is_running:
            try:
                self.sckt.sendto(f"asfa!{self.username}!{self.ipaddr}!{self.use_port}".encode(
                    "utf-8"), (common.MCAST_GROUP, common.MCAST_PORT))
            except Exception:
                pass
            sleep(3)
        self.is_running = 0

    def close_thread(self):
        """ set running flag to 0, close socket """
        try:
            self.sckt.close()
        except Exception:
            pass
        self.is_running = 0
        self.quit()
        self.wait()
        server_logger.info("Stopped MCAST task")

    def __del__(self):
        self.close_thread()
        del self


class asfaServerAuthorizer(DummyAuthorizer):
    """
    custom server authorizer
    inherits:
        DummyAuthorizer
    """

    def validate_authentication(self, username, password, handler):
        """
        Raises AuthenticationFailed if supplied username and
        password don't match the stored credentials, else return
        None.
        """

        msg = "Authentication failed."

        if not self.has_user(username):
            if not username or (username == 'anonymous'):
                msg = "Anonymous access not allowed."
            raise AuthenticationFailed(msg)

        elif username != 'anonymous':
            pwd = common.pass_hash(password)
            try:
                if self.user_table[username]["pwd"] != pwd:
                    server_logger.error("KeyError raised")
                    raise KeyError
            except KeyError:
                raise AuthenticationFailed(msg)


class MixedHandler(ThrottledDTPHandler, TLS_DTPHandler):
    """
    A DTP handler which supports SSL and bandwidth throttling
    inherits:
        ThrottledDTPHandler and TLS_DTPHandler
    """


class Server(QThread):
    """
    FTPS server that supports bandwidth throttling
    inherits:
        QThread
    parameters:
        `username`: str
        `address`: tuple[str, int]
    """

    def __init__(self, username, address, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTerminationEnabled(True)
        server_logger.info(f"Starting server with IP {address}")

        self.address = address

        self.sharedDir = ""
        self.added_users = set()
        self.signals = common.BasicSignals()
        # Data Transfer Protocol handler
        self.dtp_handler = MixedHandler
        self.dtp_handler.read_limit = 10485760
        self.dtp_handler.write_limit = 10485760
        # File Transfer Protocol handler
        self.ftp_handler = TLS_FTPHandler
        self.ftp_handler.log_prefix = "asfa[%(username)s]-%(remote_ip)s"
        self.ftp_handler.dtp_handler = self.dtp_handler
        self.ftp_handler.certfile = common.CERTF
        self.ftp_handler.tls_control_required = True
        self.ftp_handler.tls_data_required = True
        self.ftp_handler.banner = "asfa server"
        # Custom server authorizer
        self.authorizer = asfaServerAuthorizer()
        self.ftp_handler.authorizer = self.authorizer
        # start multicast
        self.multicaster = BroadcastUser(username, self.address, parent=self)
        self.multicaster.start()

    def setUser(self, username, password, path):

        if not os.path.exists(path):
            # notify user of this error
            self.signals.error.emit(f"Server error: '{path}' does not exist")
            return
        if username:
            if username not in self.added_users:
                self.added_users.add(username)
                self.authorizer.add_user(username, password, path)
                server_logger.info(f"""Setting user:
    Username: {username}
    Access Folder: {path}"""
                                   )
            else:
                self.signals.error.emit(
                    f"Username ({username}) already exists. Let's try a different one")
        else:
            self.signals.error.emit("Username not provided")

    def delete_user(self, username: str):
        """ remove authorized username """
        try:
            self.authorizer.remove_user(username)
            self.added_users.remove(username)
            # self.signals.success.emit(
            #     f"Username ({username}) removed successfully")
        except KeyError:
            server_logger.error("KeyError: Could not remove user")
            pass

    def setBandwidth(self, speed: int):
        """ change read/write limits """
        self.dtp_handler.read_limit = speed
        self.dtp_handler.write_limit = speed
        self.ftp_handler.dtp_handler = self.dtp_handler

    def stopServer(self):
        """ stop server and terminate respectifully """
        if self.isRunning():
            self.server.close_all()
            self.quit()
            self.wait()
            # stop multicast
            self.multicaster.close_thread()
            server_logger.info("Stopped server thread")
            self.signals.success.emit(f"Server stopped")

    def run(self):
        try:
            self.server = FTPServer(self.address, self.ftp_handler)
            self.finished.connect(self.stopServer)
            self.signals.success.emit(f"Server running on '{self.address[0]}:{self.address[1]}'")
            self.server.serve_forever()
        except Exception as e:
            server_logger.error(f"Server failed to start. {e}")
            self.signals.error.emit(f"Server failed to start.")

    def __del__(self):
        self.stopServer()
        del self
