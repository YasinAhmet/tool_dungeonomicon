"""Every word the user sees comes from the CSV files in app/locale - the code only ever holds the English text.

    app/locale/strings.csv          key,en,tr          interface text (one column per language, `_name` row = language name)
    app/locale/content/*.csv        key,tr             game content: spell, monster, item... names and texts
    <module>/locale/*.csv           key,tr             an installed module's content (app.core.packages)

The key is the English text. A key may hold {0}, {1}... for variable parts; {t0} marks a part that is translated in
turn ('{t0} · AC {1}'). Anything without a translation stays English.

    from app.core.i18n import tr
    tr("Battle map")                          # the interface's language
    tr("Added {0}× {1}", 3, "Goblin")          # placeholders filled after the lookup
    tr(message_from_a_service)                 # whole sentences are matched against the {0} patterns too

The Discord bot translates per player (`/language`): `i18n.t(text, lang)` works line by line and keeps leading emoji
and **bold** marks. `py tools/extract_strings.py` adds every new tr("...") literal to strings.csv.
"""
import csv
import glob
import os
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

from .storage import read_json, write_json

LOCALE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locale")
STRINGS = os.path.join(LOCALE, "strings.csv")
PLAYER_LANG_FILE = "data/discord_lang.json"
DEFAULT = "en"
_edge = re.compile(r"^([^\w`'\"(\[{]*)(.*?)([\s.!?:;…]*)$", re.S)
_slot = re.compile(r"\{(t?)(\d+)\}")


def _loose(key: str) -> bool:
    """A template that starts or ends with a blank and has hardly a word of its own ('{0} more')."""
    return bool(_slot.match(key) or _slot.search(key[-5:])) and len(re.sub(r"\s", "", _slot.sub("", key))) < 6


def read_csv(path: str) -> List[List[str]]:
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))
    except OSError:
        return []


def fill(template: str, args) -> str:
    """'{0}× {1}' + (3, 'Goblin') -> '3× Goblin'. Unlike str.format, stray braces in the text are left alone."""
    return _slot.sub(lambda m: str(args[int(m.group(2))]) if int(m.group(2)) < len(args) else m.group(0), template)


class I18n:
    def __init__(self, base: str = LOCALE, player_file: str = PLAYER_LANG_FILE):
        self.base, self.player_file = base, player_file
        self.lock = threading.Lock()
        self.language = DEFAULT
        self._files: List[List[List[str]]] = []
        self._tables: Dict[str, Tuple[dict, list]] = {}
        self._codes: Optional[Tuple[list, set]] = None                     # (files it was read from, language codes)
        self._players: Optional[Tuple[float, dict]] = None                 # (read at, {user id: language})

    # ------------------------------------------------------------------ languages
    def files(self) -> List[str]:
        """strings.csv, the content translations, then the installed modules' (<module>/locale/*.csv)."""
        out = [os.path.join(self.base, "strings.csv")] + sorted(glob.glob(os.path.join(self.base, "content", "*.csv")))
        if self.base == LOCALE:
            from . import packages
            for folder in packages.folders("locale"):
                out += sorted(glob.glob(os.path.join(folder, "*.csv")))
        return out

    def _load(self):
        if not self._files:
            self._files = [read_csv(p) for p in self.files()]

    def languages(self) -> List[Tuple[str, str]]:
        """[(code, name)] in the order of strings.csv's columns, e.g. [('en', 'English'), ('tr', 'Türkçe')]."""
        self._load()
        rows = self._files[0] if self._files else []
        if not rows:
            return [(DEFAULT, "English")]
        names = next((r for r in rows[1:] if r and r[0] == "_name"), [])
        return [(code, names[i] if i < len(names) and names[i] else code) for i, code in enumerate(rows[0]) if i > 0]

    def set_language(self, code: str):
        if code not in dict(self.languages()):
            raise ValueError(f"Unknown language '{code}'.")
        self.language = code

    def reload(self):
        """Read the CSV files again (after editing them)."""
        self._files, self._tables = [], {}

    # ------------------------------------------------------------------ the tables
    def _table(self, lang: str):
        if lang in self._tables:
            return self._tables[lang]
        self._load()
        exact, patterns = {}, []
        for rows in self._files:
            col = rows[0].index(lang) if rows and lang in rows[0] else -1
            if col < 1:
                continue
            for r in rows[1:]:
                if len(r) <= col or not r[0] or r[0].startswith("_") or not r[col]:
                    continue
                key, value = r[0], r[col]
                for k in {key, _edge.match(key).group(2)} - {""}:
                    if k != key and _loose(k):               # '+{0} more' -> '{0} more' would catch any line ending in 'more'
                        continue
                    self._register(exact, patterns, k, value if k == key else _edge.match(value).group(2) or value)
        patterns.sort(key=lambda p: -p[0])                  # the most specific sentence wins
        self._tables[lang] = (exact, patterns)
        return self._tables[lang]

    @staticmethod
    def _register(exact, patterns, key, value):
        if _slot.search(key):
            names, parts = [], []
            for p in re.split(r"(\{t?\d+\})", key):
                m = re.fullmatch(r"\{(t?\d+)\}", p)
                if m:
                    names.append(m.group(1))
                    parts.append(r"([\s\S]+?)")
                else:
                    parts.append(re.escape(p))
            patterns.append((len(_slot.sub("", key)), re.compile("^" + "".join(parts) + "$"), names, value))
            exact.setdefault(key, value)                     # tr("Added {0}", x) looks the template up directly
        elif value != key:
            exact[key] = value

    # ------------------------------------------------------------------ translating
    def _one(self, text: str, table, depth: int = 0) -> str:
        exact, patterns = table
        hit = exact.get(text)
        if hit is not None:
            return hit
        if depth > 2 or len(text) > 3000:
            return text
        for _w, rx, names, value in patterns:
            m = rx.match(text)
            if m:
                args = {n.lstrip("t"): (self._line(m.group(i + 1), table, depth + 1) if n[0] == "t" else m.group(i + 1))
                        for i, n in enumerate(names)}
                return _slot.sub(lambda g: args.get(g.group(2), ""), value)
        return text

    def _line(self, line: str, table, depth: int = 0) -> str:
        if not line.strip():
            return line
        out = self._one(line, table, depth)
        if out != line:
            return out
        pre, core, post = _edge.match(line).groups()          # 'emoji **Name**.' -> try the words inside
        if core and (pre or post):
            out = self._one(core, table, depth)
            if out == core and post:
                out = self._one(core + post.rstrip(), table, depth)
                return pre + out if out != core + post.rstrip() else line
            if out != core:
                return pre + out + post
        return line

    def t(self, text, lang: Optional[str] = None):
        """Translate a whole message (any number of lines) into `lang` (default: the interface language)."""
        lang = lang or self.language
        if not text or lang == DEFAULT or not isinstance(text, str):
            return text
        table = self._table(lang)
        if not table[0] and not table[1]:
            return text
        return "\n".join(self._line(l, table) for l in text.split("\n"))

    def tr(self, text: str, *args) -> str:
        """Interface text. With arguments the key is a template: looked up first, then filled ({t0} parts translated)."""
        if not args:
            return self.t(text)
        template = text if self.language == DEFAULT else self._table(self.language)[0].get(text, text)
        keys = {m.group(2): m.group(1) for m in _slot.finditer(text)}
        return fill(template, [self.t(str(a)) if keys.get(str(i)) == "t" else a for i, a in enumerate(args)])

    # ------------------------------------------------------------------ per-player language of the Discord bot
    def player_language(self, user_id: Optional[int]) -> str:
        """Asked many times for every page the portal sends: the file is read again at most once a second (a change
        made here is seen at once)."""
        now = time.monotonic()
        hit = self._players
        if hit is None or now - hit[0] >= 1.0:
            hit = self._players = (now, read_json(self.player_file, {}) or {})
        lang = hit[1].get(str(user_id), DEFAULT)
        return lang if lang in self._language_codes() else DEFAULT

    def _language_codes(self) -> set:
        self._load()
        hit = self._codes
        if hit is None or hit[0] is not self._files:
            hit = self._codes = (self._files, {code for code, _name in self.languages()})
        return hit[1]

    def set_player_language(self, user_id: int, lang: str) -> str:
        if lang not in dict(self.languages()):
            raise ValueError("Unknown language.")
        with self.lock:
            data = read_json(self.player_file, {}) or {}
            data[str(user_id)] = lang
            write_json(self.player_file, data)
            self._players = None
        return lang


i18n = I18n()
tr = i18n.tr
