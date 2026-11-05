import asyncio
import threading
import traceback
from collections import deque
from typing import Callable, Coroutine, List, Optional

import discord
from discord.ext import commands

from .slash_commands import register_slash_commands

STATUS_STOPPED, STATUS_CONNECTING, STATUS_ONLINE, STATUS_ERROR = "stopped", "connecting", "online", "error"
LOG_LINES = 10                                  # notifications shown in the session's log message


class _VoiceMix(discord.AudioSource):
    """What the voice channel hears: the chosen apps' audio (or silence) with the table's sounds on top."""

    def __init__(self, capture: Optional[discord.AudioSource], player):
        self.capture, self.player = capture, player

    def read(self) -> bytes:
        frame = self.capture.read() if self.capture is not None else b"\x00" * 3840
        if not frame or self.player is None:
            return frame
        from .soundscape import mix_pcm
        return mix_pcm(frame, self.player)

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        if self.capture is not None:
            self.capture.cleanup()


class BotManager:
    """Owns the Discord client thread and exposes thread-safe helpers for the GUI/services."""

    def __init__(self, log_callback: Callable[[str], None] = None,
                 on_change: Callable[[], None] = None):
        self._log_callback = log_callback or (lambda msg: None)
        self._on_change = on_change or (lambda: None)
        self.app = None
        self.status = STATUS_STOPPED
        self.voice_text = "Not connected"
        self.tree = None
        self.members_enabled = True
        self._client: Optional[commands.Bot] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._voice_client: Optional[discord.VoiceClient] = None
        self._guild_id: Optional[int] = None
        self._channel_id: Optional[int] = None
        self._log_channel_id: Optional[int] = None
        self._join_voice = False
        self._stream_audio = False
        self._target_pids: List[int] = []
        self._volume, self._muted, self._app_volumes = 100, False, {}       # percent; per-process percent by pid
        self._delay = 0                                                      # milliseconds the stream is held back
        self._source = None                                                  # the apps' audio currently streamed
        self.sound = None                                                    # the table's sounds (a Soundscape), if any
        self.sound_to_voice = True
        self._reset_log()

    # ---- state ----
    def set_app(self, app):
        self.app = app

    # ---- live /initiative messages ----
    def watch_battle(self, battle):
        """Keep every open /initiative message in step with the battle."""
        self._initiative_views = set()
        battle.listeners.append(self._battle_changed)

    def register_initiative(self, view):
        self._initiative_views.add(view)

    def unregister_initiative(self, view):
        self._initiative_views.discard(view)

    def _battle_changed(self):
        for view in list(getattr(self, "_initiative_views", ())):
            self.run_coro(lambda v=view: v.push(), "initiative refresh")

    @property
    def thread(self):
        return self._thread

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def is_ready(self) -> bool:
        return bool(self._client and self._loop and self._client.is_ready())

    @property
    def voice_connected(self) -> bool:
        return bool(self._voice_client and self._voice_client.is_connected())

    @property
    def log_channel_id(self) -> Optional[int]:
        return self._log_channel_id

    def _set_status(self, status: str):
        self.status = status
        self._on_change()

    def _set_voice(self, text: str):
        self.voice_text = text
        self._on_change()

    # ---- lifecycle ----
    def start(self, token: str, guild_id: str, channel_id: str, join_voice: bool = True,
              stream_audio: bool = True, target_pids: Optional[List[int]] = None,
              log_channel_id: Optional[str] = None):
        if self.is_running:
            self._log_callback("Bot already running.")
            return
        self._guild_id = int(guild_id) if guild_id else None
        self._channel_id = int(channel_id) if channel_id else None
        self._log_channel_id = int(log_channel_id) if log_channel_id else None
        self._reset_log()                                                    # a new session gets a new log message
        self._join_voice = join_voice
        self._stream_audio = stream_audio
        self._target_pids = target_pids or []
        self._set_status(STATUS_CONNECTING)
        self._thread = threading.Thread(target=self._run_bot, args=(token,), daemon=True)
        self._thread.start()

    def _run_bot(self, token: str):
        try:
            # "Server Members Intent" is privileged and may be disabled in the developer portal;
            # fall back to running without it (only players seen by the bot can then be listed).
            for members in (True, False):
                self.members_enabled = members
                intents = discord.Intents.default()
                intents.voice_states = True
                intents.members = members
                self._client = commands.Bot(command_prefix="!", intents=intents)
                self.tree = self._client.tree
                register_slash_commands(self)
                self._client.on_ready = self._on_ready  # discord.py dispatches to client.on_ready
                try:
                    self._client.run(token, log_handler=None)
                    break
                except discord.PrivilegedIntentsRequired:
                    if not members:
                        raise
                    self._log_callback("[WARN] 'Server Members Intent' is disabled for this bot, so the full member "
                                       "list is unavailable. Enable it in the Discord developer portal "
                                       "(Bot > Privileged Gateway Intents) to list every server member.")
            if self.status != STATUS_ERROR:
                self._set_status(STATUS_STOPPED)
        except Exception as e:
            self._log_callback(f"❌ Bot error: {e}\n{traceback.format_exc()}")
            self._set_voice(f"Error: {e}")
            self._set_status(STATUS_ERROR)
        finally:
            self._voice_client = None

    async def _on_ready(self):
        self._loop = asyncio.get_running_loop()
        self._log_callback(f"✅ Bot is online as {self._client.user}")
        self._set_status(STATUS_ONLINE)
        await self._client.change_presence(activity=discord.Game(name="D&D Character Manager"))

        # on_ready also fires after gateway reconnects; only set things up once
        if self._join_voice and self._guild_id and self._channel_id and not self.voice_connected:
            await self._join_voice_channel()

        if not self._guild_id:
            self._log_callback("[INFO] No server selected yet. Pick one on the Voice tab.")
        else:
            self._client.loop.create_task(self._load_members())
        self._log_callback("[INFO] Slash commands are not synced automatically (rate limits). "
                           "Use /sync in Discord or the Console page.")

    async def _load_members(self):
        """Fill the member cache of the active server so the GUI can list its players."""
        guild = self._client.get_guild(self._guild_id) if self._guild_id else None
        if guild and self.members_enabled:
            try:
                await guild.chunk()
            except Exception as e:
                self._log_callback(f"[WARN] Could not load server members: {e}")
        self._on_change()

    # ---- server / channel lookup (for the GUI dropdowns) ----
    def list_members(self, guild_id: Optional[int]) -> List[tuple]:
        """[(display name, user id)] of the non-bot members Discord has told us about."""
        guild = self._client.get_guild(guild_id) if self.is_ready and guild_id else None
        return [(m.display_name, m.id) for m in guild.members if not m.bot] if guild else []

    def lookup_user_name(self, user_id: int) -> Optional[str]:
        """Display name of one user by ID, for manual entry. Uses the REST API, so it works
        without the Server Members Intent. None when offline or not found."""
        if not self.is_ready or int(user_id) <= 0:
            return None

        async def go():
            guild = self._client.get_guild(self._guild_id) if self._guild_id else None
            if guild:
                member = guild.get_member(user_id)
                if member:
                    return member.display_name
                try:
                    return (await guild.fetch_member(user_id)).display_name
                except discord.HTTPException:
                    pass
            try:
                return (await self._client.fetch_user(user_id)).display_name
            except discord.HTTPException:
                return None
        try:
            return asyncio.run_coroutine_threadsafe(go(), self._loop).result(timeout=5)
        except Exception as e:
            self._log_callback(f"[WARN] Could not look up user {user_id}: {e}")
            return None

    def list_guilds(self) -> List[tuple]:
        return [(g.name, g.id) for g in self._client.guilds] if self.is_ready else []

    def guild_icon_urls(self) -> dict:
        """{guild id: icon image url} for the servers that have an icon."""
        if not self.is_ready:
            return {}
        out = {}
        for g in self._client.guilds:
            if g.icon:
                out[g.id] = g.icon.replace(size=64, format="png").url
        return out

    def list_channels(self, guild_id: Optional[int]) -> tuple:
        """(voice channels, text channels) of a guild as [(name, id)] lists."""
        guild = self._client.get_guild(guild_id) if self.is_ready and guild_id else None
        if not guild:
            return [], []
        return ([(c.name, c.id) for c in guild.voice_channels], [(c.name, c.id) for c in guild.text_channels])

    def list_threads(self, guild_id: Optional[int]) -> list:
        """Active threads of a guild as [(parent / thread name, id)]."""
        guild = self._client.get_guild(guild_id) if self.is_ready and guild_id else None
        if not guild:
            return []
        return sorted(((f"{t.parent.name} / {t.name}" if t.parent else t.name, t.id) for t in guild.threads), key=lambda x: x[0].lower())

    def set_log_channel(self, channel_id: Optional[int]):
        if channel_id != self._log_channel_id:
            self._reset_log()
        self._log_channel_id = channel_id

    def activate_guild(self, guild_id: int):
        """Switch the running bot to another server (character channels follow)."""
        if guild_id == self._guild_id:
            return
        self._guild_id = guild_id
        self.run_coro(self._load_members, "Loading members")

    def stop(self):
        """Disconnect and wait for the client thread (blocks up to ~10 s)."""
        self._log_callback("Logging off...")
        if self._client and self._loop and self.is_running:
            try:
                asyncio.run_coroutine_threadsafe(self._client.close(), self._loop).result(timeout=5)
            except Exception as e:
                self._log_callback(f"Error stopping bot: {e}")
        if self._thread:
            self._thread.join(timeout=5)
        self._voice_client = None
        self._loop = None
        self._set_voice("Not connected")
        self._set_status(STATUS_STOPPED)
        self._log_callback("Bot stopped.")

    def stop_async(self):
        threading.Thread(target=self.stop, daemon=True).start()

    # ---- scheduling helpers ----
    def run_coro(self, factory: Callable[[], Coroutine], what: str) -> bool:
        """Run a coroutine on the bot's loop from any thread; failures are logged.

        `factory` builds the coroutine so nothing is created when the bot is offline.
        """
        if not self.is_ready:
            return False
        future = asyncio.run_coroutine_threadsafe(factory(), self._loop)

        def done(fut):
            try:
                fut.result()
            except Exception as e:
                self._log_callback(f"[ERROR] {what} failed: {e}")
        future.add_done_callback(done)
        return True

    def send_dm(self, user_id: int, text: str) -> bool:
        """Send a direct message to a Discord user (False while the bot is offline, or for a player added by hand)."""
        if int(user_id) <= 0:
            return False
        async def go():
            user = self._client.get_user(user_id) or await self._client.fetch_user(user_id)
            await user.send(text)
        return self.run_coro(go, f"Direct message to {user_id}")

    # ---- voice ----
    async def _join_voice_channel(self):
        guild = self._client.get_guild(self._guild_id) if self._guild_id else None
        channel = guild.get_channel(self._channel_id) if guild and self._channel_id else None
        if not channel:
            self._log_callback(f"Voice channel {self._channel_id} not found in guild {self._guild_id}.")
            self._set_voice("Error: channel not found")
            return
        try:
            if self.voice_connected:
                await self._voice_client.disconnect(force=True)
            self._voice_client = await channel.connect()
            self._log_callback(f"✅ Joined voice channel: {channel.name}")
            self._set_voice(f"Connected to {channel.name}")
            self._play()
        except Exception as e:
            self._log_callback(f"❌ Failed to join voice: {e}")
            self._set_voice(f"Error: {e}")

    def _push_gains(self):
        if self._source is not None:
            self._source.set_delay(self._delay)
            from .volume import gain                                      # percents are loudness
            self._source.set_gains(0 if self._muted else gain(self._volume), {int(k): gain(v) for k, v in self._app_volumes.items()})

    def set_audio(self, volume: float = 100, muted: bool = False, app_volumes: Optional[dict] = None, delay: float = 0):
        """Master volume (percent), mute and per-app volumes; applied to the running stream at once."""
        self._volume, self._muted, self._app_volumes, self._delay = volume, bool(muted), dict(app_volumes or {}), delay
        self._push_gains()

    def restart_stream(self, stream_audio: bool, target_pids: List[int]):
        """Re-read which apps are streamed without leaving the voice channel."""
        self._stream_audio, self._target_pids = stream_audio, target_pids or []

        async def go():
            if not self.voice_connected:
                return
            self._voice_client.stop()
            self._play()
        self.run_coro(go, "Restarting the stream")

    def set_sound(self, sound, to_voice: bool):
        """The table's sounds (an app.bot.soundscape.Soundscape) and whether they are mixed into the voice channel;
        a stream already playing picks the change up at once."""
        if (sound, bool(to_voice)) != (self.sound, self.sound_to_voice):
            self.sound, self.sound_to_voice = sound, bool(to_voice)
            self.restart_stream(self._stream_audio, self._target_pids)

    def _play(self):
        """Play the chosen apps and the table's sounds, mixed, in the voice channel (nothing when neither is on)."""
        self._source = None
        if self._stream_audio and self._target_pids:
            from .audio_capture import MultiProcessLoopbackAudioSource
            self._log_callback(f"Audio streaming from PIDs {self._target_pids}")
            self._source = MultiProcessLoopbackAudioSource(self._target_pids, log=self._log_callback)
            self._push_gains()
        player = self.sound.player() if self.sound is not None and self.sound_to_voice else None
        if self._source is None and player is None:
            self._log_callback("Audio streaming disabled or no PIDs provided.")
            return
        self._voice_client.play(_VoiceMix(self._source, player))

    def join_voice(self, guild_id: int, channel_id: int, stream_audio: bool = True,
                   target_pids: Optional[List[int]] = None):
        if not self.is_ready:
            self._log_callback("Bot is not online.")
            return
        self._guild_id, self._channel_id = guild_id, channel_id
        self._stream_audio = stream_audio
        self._target_pids = target_pids or []
        self.run_coro(self._join_voice_channel, "Joining voice")

    def leave_voice(self):
        async def leave():
            if self.voice_connected:
                await self._voice_client.disconnect(force=True)
            self._voice_client = None
            self._source = None
            self._set_voice("Not connected")
            self._log_callback("Left voice channel.")
        self.run_coro(leave, "Leaving voice")

    # ---- Discord channel / log helpers ----
    def _reset_log(self):
        """Forget the session's log message: the next notification starts a new one."""
        self._log_lines = deque(maxlen=LOG_LINES)
        self._log_message = None
        self._log_lock = None
        self._log_version = self._log_shown = 0

    def _render_log(self) -> str:
        width = 2000 // LOG_LINES - 10               # ten bullet lines always fit one Discord message (room for emoji)
        return "\n".join("- " + (s if len(s) <= width else s[:width - 1] + "…")
                         for s in (" ".join(line.split()) for line in self._log_lines))

    async def post_log(self, text: str):
        """Add a notification to the session's log message in the log channel (silently skipped if none).
        One message per session lists the most recent LOG_LINES notifications. While it is the newest
        message in the channel it is edited in place; otherwise it is sent again and the old copy
        deleted, so it stays at the bottom of the channel."""
        if not self._log_channel_id or not self._client:
            return
        self._log_lines.append(text)
        self._log_version += 1
        if self._log_lock is None:
            self._log_lock = asyncio.Lock()
        async with self._log_lock:
            if self._log_shown == self._log_version:  # a later call already showed this line
                return
            version = self._log_version
            content = self._render_log()
            channel = self._client.get_channel(self._log_channel_id)
            if channel is None:
                try:                                 # archived threads are not cached
                    channel = await self._client.fetch_channel(self._log_channel_id)
                except Exception:
                    channel = None
            if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
                if self._log_message is not None and channel.last_message_id == self._log_message.id:
                    try:                             # still the newest message: just update it
                        await self._log_message.edit(content=content)
                        self._log_shown = version
                        return
                    except discord.NotFound:         # deleted by someone: send a new one
                        self._log_message = None
                    except Exception as e:
                        self._log_callback(f"[LOG] Failed to edit: {e}")
                        return
                try:
                    old, self._log_message = self._log_message, await channel.send(content)
                    self._log_shown = version
                except Exception as e:
                    self._log_callback(f"[LOG] Failed to send: {e}")
                    return
                if old is not None:                  # the new copy is up: remove the old one
                    try:
                        await old.delete()
                    except discord.NotFound:         # already deleted by someone
                        pass
                    except Exception as e:
                        self._log_callback(f"[LOG] Failed to delete the old log message: {e}")
            else:
                self._log_callback(f"[LOG] Channel {self._log_channel_id} not found or cannot take messages.")

    def send_log_message(self, message: str, echo: bool = True):
        """Thread-safe: post to the Discord log channel, or note it locally when offline (if `echo`)."""
        if (not self._log_channel_id or not self.run_coro(lambda: self.post_log(message), "Log message")) and echo:
            self._log_callback(f"[LOG] {message}")

    # ---- slash command sync ----
    async def sync_guild_commands(self, guild: discord.Guild) -> List[str]:
        """Clear and re-register this bot's slash commands on a guild."""
        self.tree.clear_commands(guild=guild)
        await self.tree.sync(guild=guild)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        names = [cmd.name for cmd in self.tree.get_commands(guild=guild)]
        self._log_callback(f"[SYNC] Registered commands: {', '.join(names)}")
        return names

    def sync_commands_from_gui(self) -> str:
        if not self.is_ready:
            return "❌ Bot is not online. Start the bot first."
        guild = self._client.get_guild(self._guild_id) if self._guild_id else None
        if not guild:
            return "❌ Guild not found."

        async def do_sync():
            await self.sync_guild_commands(guild)
            self.app.log_action("Discord slash commands synced successfully")
        self.run_coro(do_sync, "Slash command sync")
        return "✅ Sync started. Check the Logs tab for progress."
