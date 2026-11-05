from .storage import read_json, write_json

CONFIG_FILE = "config.json"

DEFAULTS = {
    "token": "",
    "guild_id": "",
    "channel_id": "",
    "log_channel_id": "",
    "target_pids": "",
    "join_voice": True,
    "stream_audio": True,
    "servers": {},               # per-server options: channels, voice, audio
    "void": False,              # null server selected: nothing is sent to Discord
    "sources": ["PHB", "DMG", "MM"],          # sourcebooks offered by character creation / level-up
}


class ConfigManager:
    @staticmethod
    def load() -> dict:
        data = read_json(CONFIG_FILE, {})
        if not isinstance(data, dict):
            data = {}
        return {**DEFAULTS, **data}

    @staticmethod
    def save(config: dict) -> None:
        try:
            write_json(CONFIG_FILE, config)
        except OSError as e:
            raise RuntimeError(f"Could not save config: {e}")
