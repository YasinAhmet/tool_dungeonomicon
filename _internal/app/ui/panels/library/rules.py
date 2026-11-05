"""The Rules window: every piece of content of the enabled sourcebooks, by book and kind (spells by level, school or
class; items by category, type or rarity; creatures by type or CR...), and the custom rulebooks written here: create,
rename, switch on/off and delete them, and add, edit and delete their races, spells, items, feats, creatures...
Hovering an entry shows its text; picking one shows it in the Inspector."""
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QMenu, QPlainTextEdit, QSplitter, QTreeWidget, QTreeWidgetItem, QWidget

from ....core import events
from ....core.i18n import tr
from ....rules.describe import describe
from ....services import library
from ....services.battle.icons import for_spell
from ... import dialogs, notify
from ...dialogs import Dialog
from ...errors import user_errors
from ...panel import Panel
from ...selection import show_content
from ...theme import COLORS
from ...widgets.common import Combo, FlowLayout, button, check, clear_layout, col, label, line_edit, row, stretch, widget
from ...widgets.icons import game_icon
from ...widgets.text import HoverTips, entry_tip
from .contentform import content_form
from .searches import open_generator
from .sourcebooks import open_sourcebooks

ALL = library.ALL_BOOKS
OPEN_ALL_UNDER = 60                                     # smaller lists start unfolded
ROLE = Qt.UserRole
KIND_ICONS = {"races": "person", "classes": "crossed-swords", "subclasses": "swords-power", "backgrounds": "scroll-unfurled",
              "feats": "laurels-trophy", "spells": "spell-book", "items": "backpack", "monsters": "monster-grasp",
              "optional_features": "sparkles", "languages": "chat-bubble"}


def _book_tip(b: dict) -> str:
    if b["id"] == ALL:
        why = tr("Everything the enabled books offer, together.")
    elif b["id"] == library.CUSTOM_BOOK:
        why = tr("Backgrounds and creatures made in the generators.")
    else:
        why = (tr("Enabled") if b["active"] else tr("Switched off: its content is not offered anywhere.")) + f" · {b['id']}"
    return f"{tr(b['name'])}\n{why}"


class RulesPanel(Panel):
    def build(self):
        self.books: List[dict] = []
        self.data: Optional[dict] = None
        self.book_id, self.kind = ALL, "spells"
        self.group_by: Dict[str, str] = {}               # kind -> grouping key
        self.fold: Dict[str, bool] = {}                  # 'book|kind|grouping|group' -> open?
        self.selected: Optional[str] = None              # the id of the entry shown on the right
        self.entry: Optional[dict] = None                # its description

        # ---- books
        self.book_q = line_edit(placeholder=tr("search books…"))
        self.book_q.textChanged.connect(lambda _t: self._render_books())
        self.book_tree = QTreeWidget()
        self.book_tree.setColumnCount(2)
        self.book_tree.setHeaderHidden(True)
        self.book_tree.setRootIsDecorated(False)
        self.book_tree.setItemsExpandable(False)
        self.book_tree.setIndentation(8)
        self.book_tree.header().setStretchLastSection(False)
        self.book_tree.header().setSectionResizeMode(0, self.book_tree.header().ResizeMode.Stretch)
        self.book_tree.header().setSectionResizeMode(1, self.book_tree.header().ResizeMode.ResizeToContents)
        self.book_tree.currentItemChanged.connect(lambda cur, _p: self._book_clicked(cur))
        self.book_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.book_tree.customContextMenuRequested.connect(self._book_menu)
        left = widget(col(self.book_q, self.book_tree,
                          row(button(tr("+ Create rulebook"), lambda: self._edit_book(None), kind="primary",
                                     tip=tr("A book of your own: races, spells, items, feats, creatures... It works like any "
                                            "sourcebook: switch it on or off in the Sourcebooks window.")),
                              button(tr("Sourcebooks…"), lambda: open_sourcebooks(self),
                                     tip=tr("Choose which books creation, level-up and the searches offer"))),
                          spacing=3))

        # ---- the book's header, kinds and listing
        self.head_name = label("")
        self.head_name.setStyleSheet("font-size: 12pt; font-weight: 600;")
        self.head_id = label("", role="dim")
        self.active = check(tr("Enabled"), tip=tr("Offered in character creation, level-up and the searches, like any ticked "
                                                  "sourcebook."), on_change=self._set_active)
        self.edit_book_btn = button(tr("Edit…"), lambda: self._edit_book(self._book()), tip=tr("Rename the rulebook or change its description"))
        self.del_book_btn = button(tr("Delete"), lambda: self._delete_book(self._book()), kind="danger")
        self.head_desc = label("", role="dim", wrap=True)
        self.kinds_host = QWidget()
        self.kinds = FlowLayout(self.kinds_host, spacing=3)
        self.no_kinds = label(tr("This book adds nothing the Rules window lists."), role="dim")
        self.filter = line_edit(placeholder=tr("filter…"))
        self._debounce = QTimer(self, singleShot=True, interval=120)
        self._debounce.timeout.connect(self._render_list)
        self.filter.textChanged.connect(lambda _t: self._debounce.start())
        self.group_box = Combo()
        self.group_box.currentIndexChanged.connect(self._group_changed)
        self.add_btn = button("", self._add_content, kind="primary")
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("Name"), tr("Details"), tr("Book")])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 240)
        self.tree.currentItemChanged.connect(lambda cur, _p: self._entry_clicked(cur))
        self.tree.itemExpanded.connect(lambda it: self._folded(it, True))
        self.tree.itemCollapsed.connect(lambda it: self._folded(it, False))
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._double(it))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._entry_menu)
        self.tips = HoverTips(self.tree, self._tip)
        self.d_edit = button(tr("Edit…"), self._edit_content, tip=tr("Change the selected entry of your rulebook"))
        self.d_delete = button(tr("Delete"), self._delete_content, kind="danger")
        middle = widget(col(
            row(self.head_name, self.head_id, stretch(), self.active, self.edit_book_btn, self.del_book_btn),
            self.head_desc, self.kinds_host, self.no_kinds,
            row(self.filter, self.group_box,
                button("▾", lambda: self._fold_all(True), width=26, tip=tr("Unfold every group")),
                button("▸", lambda: self._fold_all(False), width=26, tip=tr("Fold every group")),
                self.d_edit, self.d_delete, self.add_btn),
            self.tree, spacing=4))

        self.split = QSplitter(Qt.Horizontal)
        for w in (left, middle):
            self.split.addWidget(w)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([210, 760])
        self.layout().addWidget(self.split, 1)
        self.on(events.RULES, self.refresh)
        self._render_detail()

    # ------------------------------------------------------------------ loading
    def _book(self) -> dict:
        return next((b for b in self.books if b["id"] == self.book_id), self.books[0] if self.books else
                    {"id": ALL, "name": "", "counts": {}, "homebrew": False, "active": True})

    def refresh(self):
        books = self.run(library.rule_books)
        if books is None:
            return
        self.books = books
        if not any(b["id"] == self.book_id for b in self.books):
            self.book_id = ALL
        self._render_books()
        self._render_head()
        self._load_list()

    def _load_list(self):
        data = self.run(library.rule_listing, self.book_id, self.kind)
        self.data = data or {"rows": [], "groupings": []}
        if self.selected and not any(r["id"] == self.selected for r in self.data["rows"]):
            self.selected = None
        self._render_list()
        self._render_detail()

    # ------------------------------------------------------------------ books column
    def _render_books(self):
        needle = self.book_q.text().strip().lower()
        t = self.book_tree
        t.blockSignals(True)
        t.clear()
        for key, section in library.BOOK_SECTIONS:
            these = [b for b in self.books if b["section"] == key
                     and (not needle or needle in b["name"].lower() or needle in b["id"].lower() or needle in tr(b["name"]).lower())]
            parent = None
            if section and (these or key == "homebrew"):
                parent = QTreeWidgetItem([tr(section)])
                parent.setFlags(Qt.ItemIsEnabled)
                parent.setFirstColumnSpanned(True)
                fnt = parent.font(0)
                fnt.setBold(True)
                parent.setFont(0, fnt)
                parent.setForeground(0, QColor(COLORS["accent"]))
                t.addTopLevelItem(parent)
                if key == "homebrew" and not these:
                    empty = QTreeWidgetItem([tr("No rulebooks of your own yet.")])
                    empty.setFlags(Qt.ItemIsEnabled)
                    empty.setForeground(0, QColor(COLORS["dim"]))
                    parent.addChild(empty)
            for b in these:
                name = tr(b["name"]) + ("  · " + tr("off") if b["homebrew"] and not b["active"] else "")
                it = QTreeWidgetItem([name, str(b["total"])])
                it.setData(0, ROLE, b["id"])
                it.setToolTip(0, _book_tip(b))
                it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                it.setForeground(1, QColor(COLORS["dim"]))
                if not b["active"]:
                    it.setForeground(0, QColor(COLORS["dim"]))
                (parent.addChild(it) if parent else t.addTopLevelItem(it))
                if b["id"] == self.book_id:
                    t.setCurrentItem(it)
        t.expandAll()
        t.blockSignals(False)

    def _book_clicked(self, it: Optional[QTreeWidgetItem]):
        bid = it.data(0, ROLE) if it else None
        if bid and bid != self.book_id:
            self.select_book(bid)

    def select_book(self, bid: str):
        self.book_id, self.selected = bid, None
        b = self._book()
        if not b.get("homebrew") and not b["counts"].get(self.kind):
            self.kind = next((k for k, _t in library.RULE_KINDS if b["counts"].get(k)), "spells")
        self._render_books()
        self._render_head()
        self._load_list()

    def _book_menu(self, pos):
        it = self.book_tree.itemAt(pos)
        b = next((x for x in self.books if it and x["id"] == it.data(0, ROLE)), None)
        menu = QMenu(self)
        if b and b["homebrew"]:
            menu.addAction(tr("Edit…"), lambda: self._edit_book(b))
            menu.addAction(tr("Switch off") if b["active"] else tr("Switch on"), lambda: self._set_active(not b["active"], b))
            menu.addAction(tr("Delete…"), lambda: self._delete_book(b))
            menu.addSeparator()
        menu.addAction(tr("+ Create rulebook"), lambda: self._edit_book(None))
        menu.addAction(tr("Sourcebooks…"), lambda: open_sourcebooks(self))
        menu.exec(self.book_tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ header + kind buttons
    def _render_head(self):
        b = self._book()
        shown = library.rule_kinds(b)
        if shown and not any(k == self.kind for k, _t, _n in shown):
            self.kind = shown[0][0]
        self.head_name.setText(tr(b["name"]))
        self.head_id.setText(b["id"] if b["id"] not in (ALL, library.CUSTOM_BOOK) else "")
        hb = bool(b.get("homebrew"))
        for w in (self.active, self.edit_book_btn, self.del_book_btn):
            w.setVisible(hb)
        self.active.blockSignals(True)
        self.active.setChecked(bool(b.get("active")))
        self.active.blockSignals(False)
        self.head_desc.setText(b.get("description") or "")
        self.head_desc.setVisible(bool(b.get("description")))
        clear_layout(self.kinds)
        for k, title, n in shown:
            btn = button(f"{tr(title)}  {n}", lambda k=k: self._set_kind(k), checkable=True)
            btn.setChecked(k == self.kind)
            btn.setStyleSheet("padding: 2px 8px;")
            if k in KIND_ICONS:                                  # a picture of the kind beside its name
                btn.setIcon(game_icon(KIND_ICONS[k], 14, "#cbd5e1"))
            self.kinds.addWidget(btn)
        self.kinds_host.setVisible(bool(shown))
        self.no_kinds.setVisible(not shown)
        can = library.can_add(b, self.kind)
        self.add_btn.setVisible(can)
        if can:
            what = tr(library.SINGULAR[self.kind])
            self.add_btn.setText(tr("+ Add {0}", what))
            self.add_btn.setToolTip(tr("Write a new {0} into {1}.", what, tr(b["name"])))

    def _set_kind(self, kind: str):
        self.kind, self.selected = kind, None
        self._render_head()
        self._load_list()

    # ------------------------------------------------------------------ the grouped list
    def _grouping(self) -> Optional[dict]:
        gs = (self.data or {}).get("groupings", [])
        key = self.group_by.get(self.kind)
        if key == "none":
            return None
        return next((g for g in gs if g["key"] == key), gs[0] if gs else None)

    def _group_changed(self, _i):
        self.group_by[self.kind] = self.group_box.currentData()
        self._render_list()

    def _render_list(self):
        if self.data is None:
            return
        self.tips.forget()
        gs = self.data["groupings"]
        g = self._grouping()
        self.group_box.blockSignals(True)
        self.group_box.clear()
        for x in gs:
            self.group_box.addItem(tr("Group by {0}", tr(x["title"]).lower()), x["key"])
        self.group_box.addItem(tr("No groups"), "none")
        self.group_box.setCurrentIndex(max(0, self.group_box.findData(g["key"] if g else "none")))
        self.group_box.blockSignals(False)
        self.group_box.setVisible(bool(gs))
        all_books = self.book_id == ALL
        self.tree.setColumnHidden(2, not all_books)
        needle = self.filter.text().strip().lower()
        rows = [r for r in self.data["rows"] if not needle or needle in r["name"].lower() or needle in (r.get("meta") or "").lower()
                or needle in tr(r["name"]).lower()]
        t = self.tree
        t.blockSignals(True)
        t.clear()
        current = None
        if not self.data["rows"]:
            what = tr(next((title for k, title in library.RULE_KINDS if k == self.kind), "content")).lower()
            self._note(tr('No {0} in this rulebook yet. Use "+ Add {1}" to write one.', what, tr(library.SINGULAR.get(self.kind, "")))
                       if self._book().get("homebrew") else tr("Nothing here."))
        elif not rows:
            self._note(tr("Nothing matches the filter."))
        else:
            for name in (g["order"] if g else [""]):
                members = [r for r in rows if name in r["groups"][g["key"]]] if g else rows
                if not members:
                    continue
                parent = None
                if g:
                    key = f"{self.book_id}|{self.kind}|{g['key']}|{name}"
                    parent = QTreeWidgetItem([f"{tr(name)}  ({len(members)})"])
                    parent.setData(0, ROLE + 1, key)
                    parent.setFlags(Qt.ItemIsEnabled)
                    parent.setFirstColumnSpanned(True)
                    fnt = parent.font(0)
                    fnt.setBold(True)
                    parent.setFont(0, fnt)
                    parent.setForeground(0, QColor(COLORS["accent"]))
                    t.addTopLevelItem(parent)
                for r in members:
                    it = QTreeWidgetItem([tr(r["name"]) + ("  ✎" if r["homebrew"] and all_books else ""), tr(r.get("meta") or ""),
                                          r["groups"].get("book", [r["src"]])[0] if all_books else ""])
                    it.setData(0, ROLE, r)
                    it.setToolTip(0, r["name"])
                    it.setForeground(1, QColor(COLORS["dim"]))
                    it.setForeground(2, QColor(COLORS["dim"]))
                    if r["homebrew"] and all_books:
                        it.setForeground(0, QColor("#c9a3ff"))
                    if self.kind == "spells":                   # the spell's action bar picture
                        it.setIcon(0, game_icon(for_spell(r["name"]), 14, "#c4b5fd"))
                    (parent.addChild(it) if parent else t.addTopLevelItem(it))
                    if current is None and r["id"] == self.selected:
                        current = it
                if parent:
                    parent.setExpanded(bool(needle) or self.fold.get(parent.data(0, ROLE + 1), len(self.data["rows"]) <= OPEN_ALL_UNDER)
                                       or (current is not None and current.parent() is parent))
        if current is not None:
            t.setCurrentItem(current)
            t.scrollToItem(current)
        t.blockSignals(False)

    def _note(self, text: str):
        it = QTreeWidgetItem([text])
        it.setFlags(Qt.ItemIsEnabled)
        it.setFirstColumnSpanned(True)
        it.setForeground(0, QColor(COLORS["dim"]))
        self.tree.addTopLevelItem(it)

    def _folded(self, it: QTreeWidgetItem, opened: bool):
        key = it.data(0, ROLE + 1)
        if key and not self.filter.text().strip():
            self.fold[key] = opened

    def _fold_all(self, opened: bool):
        g = self._grouping()
        if not g:
            return
        for name in g["order"]:
            self.fold[f"{self.book_id}|{self.kind}|{g['key']}|{name}"] = opened
        self._render_list()

    # ------------------------------------------------------------------ the entry
    def _entry_clicked(self, it: Optional[QTreeWidgetItem]):
        r = it.data(0, ROLE) if it else None
        if not isinstance(r, dict):
            return
        self.selected = r["id"]
        self._render_detail()
        show_content(self.kind, r["id"])

    def _double(self, it: QTreeWidgetItem):
        r = it.data(0, ROLE)
        if isinstance(r, dict) and r["homebrew"]:
            self._edit_content()

    def _entry_menu(self, pos):
        it = self.tree.itemAt(pos)
        r = it.data(0, ROLE) if it else None
        if not isinstance(r, dict):
            return
        menu = QMenu(self)
        menu.addAction(tr("Show in the Inspector"), lambda: show_content(self.kind, r["id"]))
        if r["homebrew"]:
            menu.addAction(tr("Edit…"), self._edit_content)
            menu.addAction(tr("Delete…"), self._delete_content)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _render_detail(self):
        """The picked entry (its text is read in the Inspector): Edit and Delete show for one of your rulebook's."""
        self.entry = self.run(describe, self.kind, self.selected) if self.selected else None
        d = self.entry
        for b in (self.d_edit, self.d_delete):
            b.setVisible(bool(d and d["homebrew"]))

    def _tip(self, it: QTreeWidgetItem) -> str:
        """An entry's text on hover: its name, book and rules."""
        r = it.data(0, ROLE)
        if not isinstance(r, dict):
            return ""
        return entry_tip(self.kind, r["id"])

    # ------------------------------------------------------------------ custom rulebooks
    def _edit_book(self, b: Optional[dict]):
        d = Dialog(self, tr("Edit {0}", tr(b["name"])) if b else tr("Create rulebook"), 460)
        name = line_edit(b["name"] if b else "")
        desc = QPlainTextEdit(b.get("description", "") if b else "")
        desc.setPlaceholderText(tr("What the book is about (optional)"))
        desc.setFixedHeight(90)
        d.body.addWidget(label(tr("Name") + " *", role="dim"))
        d.body.addWidget(name)
        d.body.addWidget(label(tr("Description"), role="dim"))
        d.body.addWidget(desc)
        if not b:
            d.body.addWidget(label(tr('The new book is switched on at once. Pick a kind of content and use "+ Add …" to fill it.'),
                                   role="dim", wrap=True))
        saved = {}

        def ok():
            try:
                saved.update(library.save_book(name.text(), desc.toPlainText(), b["id"] if b else None))
            except user_errors() as e:
                d.show_problem(tr(str(e)))
                return
            d.accept()
        d.ok_cancel(tr("Save") if b else tr("Create"), ok)
        d.resize(460, 300)
        name.setFocus()
        if d.exec() != Dialog.Accepted:
            return
        notify.good(tr("Rulebook saved.") if b else tr("Rulebook {0} created ({1}).", saved["name"], saved["id"]))
        self.book_id, self.selected = saved["id"], None
        if not b:
            self.kind = "races"
        self.refresh()

    def _delete_book(self, b: dict):
        n = b.get("total", 0)
        msg = (tr("Delete {0} and its {1} entries?", tr(b["name"]), n) if n else tr("Delete {0}?", tr(b["name"]))) + " " + \
            tr("Characters made with its content keep what they have, but it is no longer offered anywhere. "
               "A copy is kept in backups\\deleted.")
        if not dialogs.confirm(self, msg, tr("Delete rulebook"), yes=tr("Delete")):
            return
        if self.run(lambda: library.delete_book(b["id"]) or True):
            notify.good(tr("Rulebook deleted."))
        self.book_id, self.selected = ALL, None
        self.refresh()

    def _set_active(self, on: bool, b: Optional[dict] = None):
        b = b or self._book()
        if not b.get("homebrew"):
            return
        if self.run(lambda: library.set_book_active(b["id"], bool(on)) or True):
            notify.good(tr("{0} is enabled.", tr(b["name"])) if on else tr("{0} is switched off.", tr(b["name"])))
        self.refresh()

    # ------------------------------------------------------------------ content of a custom rulebook
    def _saved(self, ident: Optional[str] = None, add: bool = False):
        """After a save (also the creature generator's on_saved(id, add_to_battle)): show the entry."""
        self.selected = ident or None
        self.refresh()
        if ident and add:
            self.run(self.rt.battle.add_enemy, ident, 1, None, "average", None, True)

    def _add_content(self):
        b, kind = self._book(), self.kind
        if not library.can_add(b, kind):
            return
        if kind == "monsters":
            open_generator(self, book=b["id"], on_saved=self._saved)
            return
        r = content_form(self, kind, tr("New {0} - {1}", tr(library.SINGULAR[kind]), tr(b["name"])),
                         save=lambda form: library.save_entry(b["id"], kind, form))
        if r:
            notify.good(tr("{0} added to {1}.", tr(r["name"]), tr(b["name"])))
            self._saved(r["id"])

    def _edit_content(self):
        d, ident, kind = self.entry, self.selected, self.kind
        if not d or not d["homebrew"]:
            return
        if kind == "monsters":
            open_generator(self, edit_id=ident, book=d["src"], on_saved=self._saved)
            return
        r = content_form(self, kind, tr("Edit {0}", tr(d["title"])), initial=d.get("form") or {},
                         save=lambda form: library.save_entry(d["src"], kind, form, ident))
        if r:
            notify.good(tr("{0} saved.", tr(r["name"])))
            self._saved(r["id"])

    def _delete_content(self):
        d, ident, kind = self.entry, self.selected, self.kind
        if not d or not d["homebrew"]:
            return
        if not dialogs.confirm(self, tr("Delete {0} from {1}?", tr(d["title"]), tr(d["book"])), tr("Delete"), yes=tr("Delete")):
            return
        if self.run(lambda: library.delete_entry(d["src"], kind, ident) or True):
            notify.good(tr("Deleted."))
        self._saved(None)

    # ------------------------------------------------------------------ layouts
    def save_state(self) -> dict:
        return {"book": self.book_id, "kind": self.kind, "group_by": dict(self.group_by), "selected": self.selected}

    def restore_state(self, state: dict):
        self.book_id = state.get("book") or self.book_id
        self.kind = state.get("kind") or self.kind
        self.group_by.update(state.get("group_by") or {})
        self.selected = state.get("selected")
        self.refresh()
