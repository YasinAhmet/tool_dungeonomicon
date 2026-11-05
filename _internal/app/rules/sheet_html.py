"""Compact printable character sheet (HTML) and PDF export.

On screen the sheet shows only numbers and names; hovering shows descriptions and where each number comes from.
When printed (or saved as PDF) a second section lists the descriptions, because paper can't hover.
The character's data rides along in a hidden block, so html_import can turn the sheet back into the character.
"""
import os
import subprocess
import tempfile
from html import escape
from typing import List, Optional

from . import document
from .character import Character
from .html_import import embed


class ExportError(Exception):
    pass


CSS = """
:root{--ink:#1b1b1f;--dim:#6b6558;--line:#d4ccb8;--paper:#fbf8ef;--accent:#7a1f1f;--chip:#efe9d8}
*{box-sizing:border-box}body{font:12px/1.35 'Segoe UI',Arial,sans-serif;color:var(--ink);background:#e9e5d8;margin:0;padding:14px}
.page{max-width:1180px;margin:0 auto;background:var(--paper);padding:14px 18px;border:1px solid var(--line)}
header{display:flex;align-items:baseline;gap:14px;border-bottom:2px solid var(--accent);padding-bottom:4px;margin-bottom:8px}
h1{margin:0;font-size:22px;color:var(--accent)}header span{color:var(--dim)}
h2{font-size:10px;letter-spacing:.09em;text-transform:uppercase;border-bottom:1px solid var(--accent);margin:9px 0 4px;color:var(--accent)}
.band{display:grid;grid-template-columns:repeat(6,1fr);gap:5px;margin-bottom:5px}
.tile{border:1px solid var(--line);background:#fff;text-align:center;padding:2px 2px 3px}
.tile b{display:block;font-size:16px;line-height:1.15}.tile i{font-style:normal;font-size:9.5px;color:var(--dim)}
.tile em{display:block;font-style:normal;font-size:9px;text-transform:uppercase;letter-spacing:.05em;color:var(--dim)}
.cols{display:grid;grid-template-columns:200px 1fr 1fr;gap:12px}
.row{display:flex;justify-content:space-between;border-bottom:1px dotted var(--line);padding:0 2px}
.row span.d{color:var(--dim);font-size:10px;margin-left:4px}
.chips{display:flex;flex-wrap:wrap;gap:3px;margin:0 0 3px}
.chip{background:var(--chip);border-radius:3px;padding:1px 6px;font-size:11px}.chip small{color:var(--dim)}
.dim{color:var(--dim);font-size:10.5px}p{margin:2px 0}
table{border-collapse:collapse;width:100%}td,th{padding:1px 5px;text-align:left;border-bottom:1px solid var(--line)}
[data-tip]{position:relative;cursor:help}
[data-tip]:hover::after{content:attr(data-tip);position:absolute;z-index:10;left:0;top:100%;width:max-content;max-width:380px;
background:#23212b;color:#f2f0f7;padding:7px 10px;border-radius:5px;white-space:pre-line;font-size:11px;line-height:1.4;
box-shadow:0 4px 14px rgba(0,0,0,.35);margin-top:3px;font-weight:400}
.band .tile:nth-child(6n)[data-tip]:hover::after,.cols>div:last-child [data-tip]:hover::after{left:auto;right:0}
.appendix{display:none}
.appendix h3{font-size:11px;margin:8px 0 1px;color:var(--accent)}.appendix p{margin:0 0 3px;white-space:pre-line;font-size:10.5px}
@page{size:A4;margin:9mm}
@media print{body{background:#fff;padding:0;font-size:11px}.page{border:0;max-width:none;padding:0}
[data-tip]:hover::after{display:none}.appendix{display:block;break-before:page}.chip{border:1px solid var(--line)}}
@media(max-width:820px){.cols{grid-template-columns:1fr}.band{grid-template-columns:repeat(3,1fr)}}
"""


def _e(text) -> str:
    return escape(str(text), quote=True).replace("\n", "&#10;")


def _tip(tip: str) -> str:
    return f' data-tip="{_e(tip)}"' if tip else ""


def _chip(text: str, tip: str, note: str = "") -> str:
    return f"<span class='chip'{_tip(tip)}>{_e(text)}{f' <small>{_e(note)}</small>' if note else ''}</span>"


def to_html(char: Character) -> str:
    d = document.build(char)
    out: List[str] = [f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(d['name'])} - character sheet</title>"
                      f"<style>{CSS}</style></head><body><div class='page'>",
                      f"<header><h1>{_e(d['name'])}</h1><span>{_e(d['subtitle'])} &middot; {_e(d['line'])}</span>"
                      f"<span class='dim'>{_e(' · '.join(f'{k}: {v}' for k, v in d['info'][:3]))}</span></header>"]

    out.append("<div class='band'>")
    for t in d["vitals"]:
        out.append(f"<div class='tile'{_tip(t['tip'])}><em>{_e(t['label'])}</em><b>{_e(t['value'])}</b></div>")
    for a in d["abilities"]:
        out.append(f"<div class='tile'{_tip(a['tip'] + chr(10) + chr(10) + a['save_tip'])}><em>{_e(a['short'])}</em>"
                   f"<b>{a['mod']:+d}</b><i>{a['score']} &middot; save {a['save']:+d}{'●' if a['save_prof'] else ''}</i></div>")
    out.append("</div>")
    if d["vitals_extra"]:
        out.append(f"<div class='dim'>{_e('  ·  '.join(d['vitals_extra']))}</div>")

    out.append("<div class='cols'><div><h2>Skills</h2>")
    for s in d["skills"]:
        out.append(f"<div class='row'{_tip(s['tip'])}><span>{s['marker']} {_e(s['name'])}<span class='d'>{_e(s['ability'])}</span></span>"
                   f"<b>{s['bonus']:+d}</b></div>")
    out.append("<h2>Proficiencies</h2>")
    out += [f"<p class='dim'><b>{_e(k)}:</b> {_e(v)}</p>" for k, v in d["proficiencies"]]
    out.append("</div><div><h2>Attacks</h2><table>")
    for a in d["attacks"]:
        out.append(f"<tr{_tip(a['tip'])}><td>{_e(a['name'])}</td><td>{a['attack']:+d}</td><td>{_e(a['damage'])}</td></tr>")
    out.append("</table>")
    if d["casting"] or d["spells"]:
        out.append("<h2>Spellcasting</h2>")
        for c in d["casting"]:
            out.append(f"<p{_tip(c['tip'])}><b>{_e(c['class'])}</b> &middot; DC {c['dc']} &middot; {c['attack']:+d} to hit</p>")
        if d["slots"]:
            out.append(f"<p class='dim'>Slots: {_e(d['slots'])}</p>")
        for g in d["spells"]:
            out.append(f"<p class='dim'><b>{_e(g['title'])}</b></p><div class='chips'>"
                       + "".join(_chip(s["name"] + (" (R)" if s["ritual"] else "") + (" (C)" if s["concentration"] else ""),
                                      s["tip"], s["uses"]) for s in g["spells"]) + "</div>")
    if d["resources"]:
        out.append("<h2>Resources</h2>" + "".join(f"<p class='dim'>{_e(r)}</p>" for r in d["resources"]))
    out.append("<h2>Equipment</h2><div class='chips'>"
               + "".join(_chip(i["name"] + (f" ×{i['qty']}" if i["qty"] != 1 else ""), i["tip"],
                               ("⚔" if i["equipped"] else "") + ("✦" if i["attuned"] else "")) for i in d["inventory"])
               + f"</div><p class='dim'>{_e(d['currency'])} &middot; {_e(d['weight'])}</p>")
    out.append("</div><div><h2>Features &amp; traits</h2>")
    for g in d["features"]:
        out.append(f"<p class='dim'><b>{_e(g['source'])}</b></p><div class='chips'>"
                   + "".join(_chip(f["name"], f["tip"], f"L{f['level']}" if f["level"] > 1 else "") for f in g["items"]) + "</div>")
    if d["details"] or d["story"] or d["notes"]:
        out.append("<h2>Character</h2>")
        if d["details"]:
            out.append(f"<p class='dim'>{_e('  ·  '.join(f'{k}: {v}' for k, v in d['details']))}</p>")
        out.append("<div class='chips'>" + "".join(_chip(k, f"{k}\n\n{v}") for k, v in d["story"])
                   + "".join(_chip(f"Note {i + 1}", f"Note\n\n{n}") for i, n in enumerate(d["notes"])) + "</div>")
    out.append("</div></div>")

    # ---- printed pages: descriptions (hidden on screen, where they appear on hover)
    out.append("<div class='appendix'><h2>Feature descriptions</h2>")
    for g in d["features"]:
        out.append(f"<h3>{_e(g['source'])}</h3>")
        for f in g["items"]:
            lvl = f" (level {f['level']})" if f["level"] > 1 else ""
            out.append(f"<p><b>{_e(f['name'])}</b>{lvl}. {_e(f['text'])}</p>")
    spells = [s for g in d["spells"] for s in g["spells"]]
    if spells:
        out.append("<h2>Spells</h2>")
        for s in spells:
            out.append(f"<p><b>{_e(s['name'])}</b> &mdash; {_e(s['school'])}, {_e(s['time'])}, {_e(s['range'])}, "
                       f"{_e(s['components'])}, {_e(s['duration'])}. {_e(s['text'])}"
                       f"{(' At higher levels: ' + _e(s['higher'])) if s['higher'] else ''}</p>")
    out.append("</div></div>" + embed(char) + "</body></html>")      # the exact character, so the sheet can be imported back
    return "".join(out)


# ---------------------------------------------------------------------- PDF
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_browser() -> Optional[str]:
    return next((p for p in BROWSERS if os.path.exists(p)), None)


def to_pdf(char: Character, path: str) -> None:
    """Render the sheet to a PDF with the installed Edge or Chrome (no extra Python packages needed)."""
    browser = find_browser()
    if not browser:
        raise ExportError("PDF export needs Microsoft Edge or Google Chrome. Export the HTML sheet and print it to PDF instead.")
    with tempfile.TemporaryDirectory() as tmp:
        html = os.path.join(tmp, "sheet.html")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write(to_html(char))
        target = os.path.abspath(path)
        if os.path.exists(target):
            os.remove(target)
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={os.path.join(tmp, 'profile')}",
               f"--print-to-pdf={target}", "file:///" + html.replace("\\", "/")]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ExportError(f"The browser couldn't create the PDF: {e}")
    if not os.path.exists(target) or os.path.getsize(target) < 500:
        raise ExportError("The browser didn't produce a PDF. Export the HTML sheet and print it to PDF instead.")
