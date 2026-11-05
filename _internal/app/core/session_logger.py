import json
import os
import threading
from datetime import datetime

from .storage import write_json_soon

LOGS_FOLDER = "data/logs"
TEXT_LIMIT = 1024 ** 3                                  # a session's text log stops at 1 GB (the old sessions are all kept)


class SessionLogger:
    """Records one run of the app: dice rolls and admin actions to data/logs/session_*.json, and every line of the
    application log (battle lines, refused actions, errors with their tracebacks...) to data/logs/session_*.log."""

    def __init__(self):
        os.makedirs(LOGS_FOLDER, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(LOGS_FOLDER, f"session_{self.session_id}.json")
        self.text_file = os.path.join(LOGS_FOLDER, f"session_{self.session_id}.log")
        self.events = []
        self._lock = threading.Lock()  # events arrive from the GUI and the Discord thread
        self._text = None
        self._text_lock = threading.Lock()
        self._text_size = 0
        self._text_full = False
        self.log_event("session_start", {"message": "Bot session started"})

    def write(self, line: str):
        """One line of the application log, timestamped, into this session's .log - flushed at once, so a crash keeps it."""
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        data = f"{stamp} {line}\n".encode("utf-8", "replace")
        with self._text_lock:
            if self._text_full:
                return
            if self._text_size + len(data) > TEXT_LIMIT - 200:
                data = f"{stamp} [LOG] This session's log reached 1 GB: nothing more is written.\n".encode("utf-8")
                self._text_full = True
            try:
                if self._text is None:
                    self._text = open(self.text_file, "ab")
                self._text.write(data)
                self._text.flush()
                self._text_size += len(data)
            except OSError:                                # a full disk must not stop the app
                pass

    def log_event(self, event_type, data):
        entry = {"timestamp": datetime.now().isoformat(), "type": event_type, "data": data}
        with self._lock:
            self.events.append(entry)
            write_json_soon(self.log_file, self.events)       # the whole log, every roll: by the writer thread
        self.write(f"[{event_type.upper()}] {json.dumps(data, ensure_ascii=False, default=str)}")

    def log_dice_roll(self, user, expression, result):
        self.log_event("dice_roll", {"user": user, "expression": expression, "result": result})

    def log_action(self, action, details=None):
        self.log_event("action", {"action": action, "details": details or {}})

    def close(self):
        self.log_event("session_end", {"message": "Bot session ended"})
        with self._text_lock:
            if self._text is not None:
                self._text.close()
                self._text = None
            self._text_full = True                         # anything logged after closing is dropped
