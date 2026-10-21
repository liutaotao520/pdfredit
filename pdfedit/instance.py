"""Aggregate Explorer's per-file launches into one GUI via local named pipes."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import getpass
import hashlib
import json
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class Instance(QObject):
    pathsReceived = Signal(list)

    def __init__(self, root):
        super().__init__()
        ident = hashlib.sha256((str(root).casefold() + getpass.getuser()).encode("utf-8")).hexdigest()[:24]
        self.name = "PDFedit-" + ident
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        self.handle = kernel.CreateMutexW(None, False, "Local\\" + self.name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != 183
        self.connections = {}
        if self.primary:
            self.server = QLocalServer(self)
            self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            if not self.server.listen(self.name):
                raise RuntimeError(self.server.errorString())
            self.server.newConnection.connect(self.accept)

    def forward(self, paths):
        # The elected primary may still be starting. Retry without starting a second window.
        for _ in range(30):
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(350):
                payload = json.dumps(paths, ensure_ascii=False).encode("utf-8") + b"\n"
                socket.write(payload)
                socket.waitForBytesWritten(3000)
                if socket.waitForReadyRead(5000) and bytes(socket.readAll()) == b"ok":
                    socket.disconnectFromServer()
                    return True
            socket.abort()
            time.sleep(0.1)
        return False

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.connections[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self.read(s))
            socket.disconnected.connect(lambda s=socket: self.release(s))
            self.read(socket)

    def read(self, socket):
        if socket not in self.connections:
            return
        buffer = self.connections[socket]
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > 4_000_000:
            socket.abort()
            return
        if b"\n" in buffer:
            try:
                paths = json.loads(bytes(buffer).split(b"\n", 1)[0])
                if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
                    raise ValueError("Invalid paths")
                self.pathsReceived.emit(paths)
                socket.write(b"ok")
                socket.flush()
                buffer.clear()
            except (ValueError, UnicodeError):
                socket.abort()

    def release(self, socket):
        self.connections.pop(socket, None)
        socket.deleteLater()

    def close(self):
        if self.primary:
            self.server.close()
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
