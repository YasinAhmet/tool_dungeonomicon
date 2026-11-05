"""The Sourcebooks window: which books character creation, level-up and the monster and item searches offer."""
from typing import Dict

from PySide6.QtWidgets import QCheckBox, QDialog, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....services import library
from ... import notify
from ...dialogs import Dialog
from ...errors import guard
from ...registry import action
from ...widgets.common import button, label, line_edit, row, scroll, stretch, title


def open_sourcebooks(parent) -> bool:
    """Show the window; True when the choice was applied."""
    sections = guard(library.sourcebook_sections)
    if sections is None:
        return False
    d = Dialog(parent, tr("Sourcebooks"), 560, 680)
    d.body.addWidget(label(tr("Only the ticked books are offered: in character creation and level-up, and in the monster "
                              "and item searches. Characters keep everything they already have."), role="dim", wrap=True))
    boxes: Dict[str, QCheckBox] = {}
    adventures = {b["id"] for _t, books in sections for b in books if b["adventure"]}

    def tick(pick):
        for bid, cb in boxes.items():
            cb.setChecked(pick(bid, cb.isChecked()))

    d.body.addLayout(row(
        button(tr("Core rules only"), lambda: tick(lambda bid, _on: bid in library.CORE_BOOKS)),
        button(tr("Select all"), lambda: tick(lambda _b, _on: True)),
        button(tr("Clear"), lambda: tick(lambda _b, _on: False)),
        button(tr("No adventures"), lambda: tick(lambda bid, on: on and bid not in adventures)), stretch()))
    query = line_edit(placeholder=tr("filter books…"))
    count = label("", role="dim")
    d.body.addLayout(row(query, count))
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 6, 0)
    lay.setSpacing(1)
    heads = []
    for section, books in sections:
        head = title(tr(section))
        lay.addSpacing(6)
        lay.addWidget(head)
        members = []
        for b in books:
            cb = QCheckBox(f"{tr(b['name'])}  ({b['id']})")
            cb.setChecked(b["on"])
            cb.toggled.connect(lambda _on: show_count())
            boxes[b["id"]] = cb
            members.append((cb, f"{b['name']} {b['id']}".lower()))
            lay.addWidget(cb)
        heads.append((head, members))
    lay.addStretch(1)
    d.body.addWidget(scroll(host), 1)

    def show_count():
        count.setText(tr("{0} ticked", sum(cb.isChecked() for cb in boxes.values())))

    def narrow(text: str):
        needle = text.strip().lower()
        for head, members in heads:
            any_shown = False
            for cb, hay in members:
                shown = not needle or needle in hay or needle in cb.text().lower()
                cb.setVisible(shown)
                any_shown |= shown
            head.setVisible(any_shown)
    query.textChanged.connect(narrow)
    show_count()
    d.ok_cancel()
    if d.exec() != QDialog.Accepted:
        return False
    n = guard(library.set_sources, [bid for bid, cb in boxes.items() if cb.isChecked()])
    if n is None:
        return False
    notify.good(tr("{0} sourcebook(s) enabled everywhere.", n))
    return True


@action("library.sourcebooks", "Sourcebooks…", menu="Settings")
def sourcebooks_action(window):
    open_sourcebooks(window)
