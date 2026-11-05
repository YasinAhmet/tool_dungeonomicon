"""The application runtime: one per process, reached from anywhere with `rt()`.

It owns the settings, the services (characters, dice, battle, players, commands), the Discord bot manager, the
per-server options, the application log and the event bus. Nothing here knows about windows: the editor (app.ui)
and the Discord bot both build on it.

    from app.core.runtime import rt
    rt().characters.damage("Ilya", 5)
    rt().bus.subscribe(events.CHARACTERS, refresh)
"""
import logging
import sys
import threading
import time
import traceback
from collections import deque
from typing import Callable, List, Optional

from ..bot.bot_manager import BotManager
from ..rules.character import Character
from ..rules.data import rules
from ..services.battle import BattleService
from ..services.characters import CharacterService
from ..services.commands import CommandProcessor
from ..services.common import Hooks
from ..services.dice import DiceService
from ..services.duel import DuelService
from ..services.feed import TableFeed
from ..services.players import PlayerManager
from ..services.team import TeamInventory
from ..services.team_notes import TeamNotes
from ..services.world import WorldService
from . import events
from .config import ConfigManager
from .i18n import i18n
from .session_logger import SessionLogger

LOG_LINES = 2500
_instance: Optional["Runtime"] = None


def rt() -> "Runtime":
    """The runtime of this process (made on first use)."""
    global _instance
    if _instance is None:
        _instance = Runtime()
    return _instance


def parse_pids(text) -> list:
    return [int(p) for p in str(text).replace(",", " ").split() if p.isdigit()]


class Runtime:
    SERVER_DEFAULTS = {"channel_id": "", "log_channel_id": "", "log_thread_id": "", "log_kinds": {}, "join_voice": True,
                       "stream_audio": True, "target_pids": "", "volume": 100, "muted": False, "app_volumes": {}, "delay": 0}

    # ------------------------------------------------------------------ construction
    def __init__(self):
        global _instance
        _instance = self
        self.duel: Optional[DuelService] = None              # (made below; `battle` asks it which battle this thread works on)
        self.settings = ConfigManager.load()
        rules.set_active_sources(self.settings["sources"])
        try:
            i18n.set_language(self.settings.get("language") or "en")
        except ValueError:
            pass
        self._log_lock = threading.Lock()
        self.log_lines: "deque[str]" = deque(maxlen=LOG_LINES)
        self.log_count = 0                                    # lines ever logged: windows remember how far they read
        self.echo = bool(getattr(sys.stdout, "isatty", lambda: False)())   # also print the log in a console
        self.report_hook: Optional[Callable[[str, str], None]] = None
        self.session_logger = SessionLogger()                 # first: every log line from here on is kept on disk
        self.bus = events.UiBus(on_error=self.log)
        self.selected_name: Optional[str] = None
        self._pump: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self.bot_manager = BotManager(log_callback=self.log, on_change=lambda: self.bus.emit(events.BOT))
        self.bot_manager.set_app(self)
        hooks = Hooks(log=self.log_action, notify=self.bus.emit, discord_log=self.discord_log,
                      session=self.session_logger, user_name=self.bot_manager.lookup_user_name)
        self.feed = TableFeed(notify=lambda: self.bus.emit(events.FEED))
        self.players = PlayerManager()
        self.characters = CharacterService(hooks, self.players)
        self.dice = DiceService(hooks)
        self._battle = BattleService(hooks, self.characters)
        self.bot_manager.watch_battle(self._battle)
        self._battle.line_sinks.append(self._post_battle_line)
        self.team = TeamInventory(hooks, self.characters, self.players, self._battle)
        self.duel = DuelService(self.bus.emit, self.players, self._battle)
        self.notes = TeamNotes(hooks)
        self.world = WorldService(hooks, self.characters, self.players, self.team)
        self.command_processor = CommandProcessor(self)
        self._migrate_server_settings()
        self._migrate_volume_curve()

    @property
    def battle(self) -> BattleService:
        """The battle tracker: the campaign's - or the duel's on a thread working on it (a player's duel request, and the
        editor while the DM shows the duel on its battle windows; services/duel)."""
        duel = self.duel
        bound = duel.bound() if duel is not None else None
        return bound if bound is not None else self._battle

    @battle.setter
    def battle(self, value: BattleService):
        self._battle = value

    def start_pump(self):
        """Without a window, run the event handlers on a small background thread (scripts, the headless bot)."""
        if self._pump is None:
            self._pump = threading.Thread(target=self._run_pump, daemon=True)
            self._pump.start()

    def _run_pump(self):
        while not self._stop.is_set():
            self.bus.drain()
            time.sleep(0.1)

    # ------------------------------------------------------------------ the Discord log
    def logs_kind(self, kind: str) -> bool:
        """Whether this kind of log line reaches a Discord log channel."""
        return bool(self.bot_manager.log_channel_id) and self.server_settings().get("log_kinds", {}).get(kind, True)

    def discord_log(self, message: str, kind: str):
        """Every kind of log (player_rolls, npc_rolls, xp, battle) goes to the one log target of the selected
        server, if its tick on the Bot window is on (all on by default)."""
        if self.server_settings().get("log_kinds", {}).get(kind, True):
            self.feed.add(kind, message)                       # the table feed shows what the log channel gets
            self.bot_manager.send_log_message(message)

    def _post_battle_line(self, line: str):
        """Battle log lines join the Discord log too; they are already in the local log, so nothing is echoed offline."""
        if self.server_settings().get("log_kinds", {}).get("battle", True):
            self.bot_manager.send_log_message(line, echo=False)

    def _migrate_volume_curve(self):
        """Volumes used to scale the sound straight; now a percent is how loud it sounds (app.bot.volume). Turn the
        saved numbers into the ones that sound the same, once."""
        if self.settings.get("volume_curve") == "loudness":
            return
        from ..bot.volume import percent_for_gain

        def same(v):
            return round(percent_for_gain(float(v) / 100))
        for ss in (self.settings.get("servers") or {}).values():
            if "volume" in ss:
                ss["volume"] = same(ss["volume"])
            ss["app_volumes"] = {k: same(v) for k, v in (ss.get("app_volumes") or {}).items()}
        sound = self.settings.get("sound")
        if isinstance(sound, dict):
            for k in ("volume", "effects"):
                if k in sound:
                    sound[k] = same(sound[k])
            loops = [x for p in sound.get("profiles") or [] for x in p.get("loops") or []]
            for x in loops + list(sound.get("loops") or []) + list(sound.get("events") or []):
                if "volume" in x:
                    x["volume"] = same(x["volume"])
        self.settings["volume_curve"] = "loudness"
        self.save_config()

    def _migrate_server_settings(self):
        """Older configs kept one global set of channel options; give them to the saved server."""
        servers = self.settings.setdefault("servers", {})
        gid = str(self.settings.get("guild_id") or "")
        if gid and gid not in servers:
            servers[gid] = {k: self.settings.get(k, v) for k, v in self.SERVER_DEFAULTS.items()}

    # ------------------------------------------------------------------ the application log
    def log(self, message: str):
        """Add a line to the application log. Safe to call from any thread."""
        with self._log_lock:
            self.log_lines.append(message)
            self.log_count += 1
        self.session_logger.write(message)
        if self.echo:
            try:
                print(message, flush=True)
            except (OSError, UnicodeError, ValueError):     # a console that can't show the text
                pass
        self.bus.emit(events.LOG)

    def log_action(self, message: str):
        self.log(f"[ADMIN] {message}")

    def capture_errors(self):
        """Into the log too: crashes on background threads (the portal, the bot, workers) and the warnings libraries
        report through `logging` (discord.py, the web server)."""
        def thread_hook(a):
            if not issubclass(a.exc_type, SystemExit):
                name = a.thread.name if a.thread else "?"
                self.log(f"[ERROR] thread {name}: " + "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)).rstrip())
        threading.excepthook = thread_hook

        rt_log = self.log

        class _ToLog(logging.Handler):
            def emit(self, record):
                try:
                    rt_log(f"[{record.levelname}] {record.name}: {self.format(record)}")
                except Exception:                           # noqa: BLE001 - logging must never raise
                    pass
        handler = _ToLog(logging.WARNING)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)
        logging.captureWarnings(True)

    def log_since(self, count: int) -> List[str]:
        """Lines logged after the first `count` (as many as are still kept)."""
        with self._log_lock:
            new = self.log_count - count
            return list(self.log_lines)[-new:] if new > 0 else []

    def report(self, message: str, kind: str = "info"):
        """Show a short message to the user (a notification in the editor) and log it."""
        self.log(f"[{kind.upper()}] {message}")
        if self.report_hook:
            self.report_hook(message, kind)

    # ------------------------------------------------------------------ selection
    @property
    def selected_char(self) -> Optional[Character]:
        """The currently selected character, always freshly read from disk."""
        return Character.load(self.selected_name) if self.selected_name else None

    def select_character(self, name: Optional[str]):
        if name == self.selected_name:
            return
        self.selected_name = name
        self.bus.emit(events.SELECTION)

    # ------------------------------------------------------------------ language and sourcebooks
    def set_language(self, code: str):
        """The interface language (stored in the settings)."""
        i18n.set_language(code)
        self.settings["language"] = code
        self.save_config()
        self.bus.emit(events.LANGUAGE)

    def set_sources(self, sources):
        """Choose which sourcebooks creation and level-up offer (stored in the settings)."""
        rules.set_active_sources(sources)
        self.settings["sources"] = list(rules.active_sources)
        self.save_config()
        self.bus.emit(events.RULES)
        self.bus.emit(events.CHARACTERS)

    # ------------------------------------------------------------------ servers and the void
    @property
    def void(self) -> bool:
        """True when the null server is selected: nothing is sent to Discord."""
        return bool(self.settings.get("void"))

    @property
    def guild_id(self) -> Optional[int]:
        if self.void:
            return None
        text = str(self.settings.get("guild_id") or "")
        return int(text) if text.isdigit() else None

    def server_settings(self, guild_id: Optional[int] = None) -> dict:
        """Options of one server (the selected one by default); the void has none."""
        gid = guild_id or self.guild_id
        stored = self.settings.setdefault("servers", {}).get(str(gid), {}) if gid else {}
        return {**self.SERVER_DEFAULTS, **stored}

    def update_server(self, **values):
        """Change options of the selected server and apply them (e.g. the log channel) right away."""
        gid = self.guild_id
        if not gid:
            return
        before = self.server_settings(gid)
        self.settings.setdefault("servers", {})[str(gid)] = {**before, **values}
        self._apply_server()
        self._apply_voice(before, self.server_settings(gid))
        self._apply_music()
        self.save_config()
        self.bus.emit(events.GUILD)

    def _apply_voice(self, before: dict, now: dict):
        """Picking a voice channel joins it, clearing it leaves; stream and volume changes apply to the running stream."""
        if self.void or not self.guild_id or not self.bot_manager.is_ready:
            return
        bm = self.bot_manager
        self._push_audio(now)
        if now["channel_id"] != before["channel_id"]:
            if str(now["channel_id"]).isdigit():
                bm.join_voice(self.guild_id, int(now["channel_id"]), now["stream_audio"], parse_pids(now["target_pids"]))
            else:
                bm.leave_voice()
        elif (now["stream_audio"], now["target_pids"]) != (before["stream_audio"], before["target_pids"]):
            bm.restart_stream(now["stream_audio"], parse_pids(now["target_pids"]))

    @staticmethod
    def _apply_music():
        """The player page streams the selected server's apps too, with the same volumes."""
        from ..services.portal.music import music
        music.refresh()

    def _push_audio(self, ss: dict):
        self.bot_manager.set_audio(ss["volume"], ss["muted"], ss["app_volumes"], ss["delay"])

    def _apply_server(self):
        """Point the bot's log output at the selected server's log channel (the void: nowhere)."""
        log = self._log_target(self.server_settings()) if not self.void else ""
        self.bot_manager.set_log_channel(int(log) if str(log).isdigit() else None)

    @staticmethod
    def _log_target(ss: dict) -> str:
        """A chosen thread or voice channel chat takes the log in place of the log channel."""
        thread = str(ss.get("log_thread_id") or "")
        return thread if thread.isdigit() else str(ss.get("log_channel_id") or "")

    def set_guild(self, guild_id: Optional[int]):
        """Choose the Discord server whose players, channels and options are used."""
        if guild_id == self.guild_id and not self.void:
            return
        self.settings["void"] = False
        self.settings["guild_id"] = str(guild_id or "")
        if guild_id and self.bot_manager.is_ready:
            self.bot_manager.activate_guild(guild_id)
        self._apply_server()
        self._apply_music()
        self.save_config()
        self.bus.emit(events.GUILD)

    def set_void(self):
        """Select the null server: no Discord log messages are sent (handy for testing)."""
        self.settings["void"] = True
        self._apply_server()
        self._apply_music()
        self.save_config()
        self.bus.emit(events.GUILD)

    # ------------------------------------------------------------------ config / bot
    def save_config(self):
        try:
            ConfigManager.save(self.settings)
        except RuntimeError as e:
            self.report(str(e), "error")

    def set_token(self, token: str):
        self.settings["token"] = str(token or "").strip()
        self.save_config()
        self.bus.emit(events.BOT)

    def start_bot(self, quiet: bool = False) -> bool:
        """Start the bot with the saved token and the selected server's options."""
        token = str(self.settings.get("token") or "").strip()
        if not token:
            if not quiet:
                self.report("Enter the bot token first.", "error")
            return False
        self.save_config()
        ss, void = self.server_settings(), self.void
        self._push_audio(ss)
        try:
            self.bot_manager.start(
                token=token, guild_id=str(self.guild_id or ""), channel_id="" if void else ss["channel_id"],
                join_voice=bool(str(ss["channel_id"]).isdigit()) and not void, stream_audio=ss["stream_audio"],
                target_pids=parse_pids(ss["target_pids"]), log_channel_id="" if void else self._log_target(ss))
        except Exception as e:
            self.report(f"Failed to start the bot: {e}", "error")
            return False
        self.session_logger.log_action("bot_start", {"guild": self.guild_id})
        self.log_action("Bot start initiated.")
        return True

    def stop_bot(self):
        self.bot_manager.stop_async()
        self.log_action("Bot stopped.")

    def join_voice(self):
        ss = self.server_settings()
        ch = int(ss["channel_id"] or 0)
        if not self.guild_id or not ch:
            self.report("Pick a voice channel for this server first.", "warn")
            return
        self.bot_manager.join_voice(self.guild_id, ch, ss["stream_audio"], parse_pids(ss["target_pids"]))

    def autostart(self):
        """Bring the bot online at launch when a token is saved."""
        if self.settings.get("token") and self.bot_manager.status == "stopped":
            self.start_bot(quiet=True)
        from ..services import sound                           # the loops that were on when the app closed
        sound.resume()

    def shutdown(self):
        self._stop.set()
        from ..services.portal.controller import portal          # the public link must not outlive the app
        portal.stop()
        from ..services import sound
        sound.close()
        self.save_config()
        if self.bot_manager.is_running:
            self.bot_manager.stop()
        self.session_logger.close()
        from .storage import flush
        flush()                                                   # the battle saved in the background: on disk now
