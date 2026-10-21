from __future__ import annotations

import traceback
from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()

    @Slot()
    def run(self):
        try:
            result = self.function(self.signals)
            self.signals.done.emit(result)
        except Exception as exc:
            import logging
            logging.exception("Background task failed")
            self.signals.failed.emit(str(exc) or type(exc).__name__)
