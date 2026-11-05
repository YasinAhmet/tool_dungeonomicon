"""The loading window shown while the editor starts: the app's name, what it is doing and a progress bar.

    splash = Splash()
    splash.show()
    splash.step(20, "Reading the rules library...")         # value 0-100; the screen repaints at once
    splash.wait(lambda: done, 60, "Starting the player portal...", 80)   # keeps repainting while a thread works
    splash.close()

It styles itself (the theme may not be applied yet) and paints with plain widgets, so it shows within a moment of
QApplication existing. While the main thread is busy (building the editor) it can't repaint; wait() is for the parts
that run on other threads, and moves the bar slowly towards its target so the window never looks stuck.
"""
import time
from typing import Callable

from PySide6.QtCore import QElapsedTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from .theme import COLORS

QSS = """
#card {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}
QLabel {{ background: transparent; color: {text}; }}
#name {{ font-size: 20pt; font-weight: 600; }}
#mark {{ background: {accent_dim}; border: 1px solid {accent}; border-radius: 9px; color: #ffffff;
         font-size: 15pt; font-weight: 700; }}
#tag {{ color: {dim}; font-size: 9pt; }}
#status {{ color: {text}; font-size: 10pt; }}
#detail {{ color: {dim}; font-size: 8pt; }}
QProgressBar {{ background: {input}; border: 1px solid {border}; border-radius: 4px; height: 8px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
"""

MARK = "DM"                                            # the short name, on its badge


class Splash(QWidget):
    def __init__(self, title: str = "Dungeonomicon", tagline: str = "Dungeon Master's table for D&D 5e"):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)       # a taskbar button too: the app is starting
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(QSS.format(**COLORS))
        self.setFixedSize(460, 210)
        card = QFrame(self, objectName="card")
        card.setGeometry(0, 0, 460, 210)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(14)
        mark = QLabel(MARK, objectName="mark", alignment=Qt.AlignCenter)
        mark.setFixedSize(52, 52)
        head.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(QLabel(title, objectName="name"))
        names.addWidget(QLabel(tagline, objectName="tag"))
        head.addLayout(names, 1)
        lay.addLayout(head)
        lay.addStretch(1)
        self.status = QLabel("Starting...", objectName="status")
        lay.addWidget(self.status)
        self.bar = QProgressBar(textVisible=False, maximum=1000)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)
        self.detail = QLabel("", objectName="detail")
        lay.addWidget(self.detail)
        screen = QGuiApplication.primaryScreen()
        if screen:
            self.move(screen.availableGeometry().center() - self.rect().center())

    def show(self):
        super().show()
        self.raise_()
        self.activateWindow()
        self._pump()

    def step(self, value: float, status: str = "", detail: str = ""):
        """Jump the bar to value (0-100) and say what comes next; repaints before returning."""
        if status:
            self.status.setText(status)
        self.detail.setText(detail)
        self.bar.setValue(max(self.bar.value(), int(value * 10)))
        self._pump()

    def wait(self, done: Callable[[], bool], timeout: float, status: str = "", until: float = 0, detail="") -> bool:
        """Keep the window alive until done() is true or timeout seconds pass, easing the bar towards `until`;
        True when done() came true. `detail` may be a function: its text is shown as it changes."""
        live = detail if callable(detail) else None
        if status:
            self.step(self.bar.value() / 10, status, "" if live else detail)
        start, top = self.bar.value(), int(until * 10)
        clock = QElapsedTimer()
        clock.start()
        while not done():
            elapsed = clock.elapsed() / 1000
            if elapsed >= timeout:
                return False
            if top > start:                                 # fast at first, slower as the wait goes on
                frac = 1 - 1 / (1 + elapsed / max(timeout / 6, 0.5))
                self.bar.setValue(max(self.bar.value(), start + int((top - start) * frac)))
            if live:
                self.detail.setText(live())
            self._pump()
            time.sleep(0.015)
        return True

    @staticmethod
    def _pump():
        QApplication.processEvents()
