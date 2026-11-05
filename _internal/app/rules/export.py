"""Export a character sheet as PDF, compact HTML (descriptions on hover), Markdown or JSON."""
import json
from typing import Dict

from . import document
from .sheet_html import to_html, to_pdf
from .character import Character

def to_markdown(char: Character) -> str:
    d = document.build(char)
    md = [f"# {d['name']}", f"*{d['subtitle']} — {d['line']}*", "",
          " · ".join(f"**{k}:** {v}" for k, v in d["info"]), "",
          "| " + " | ".join(t["label"] for t in d["vitals"]) + " |", "|" + "---|" * len(d["vitals"]),
          "| " + " | ".join(t["value"] for t in d["vitals"]) + " |", ""]
    if d["vitals_extra"]:
        md += [" · ".join(d["vitals_extra"]), ""]
    md += ["## Abilities", "| | Score | Mod | Save |", "|---|---|---|---|"]
    md += [f"| {a['name']} | {a['score']} | {a['mod']:+d} | {a['save']:+d}{' ●' if a['save_prof'] else ''} |"
           for a in d["abilities"]]
    md += ["", "## Skills", ", ".join(f"{s['marker']} {s['name']} {s['bonus']:+d}" for s in d["skills"]), "",
           "## Proficiencies"] + [f"- **{k}:** {v}" for k, v in d["proficiencies"]]
    md += ["", "## Attacks", "| Name | Attack | Damage | Notes |", "|---|---|---|---|"]
    md += [f"| {a['name']} | {a['attack']:+d} | {a['damage']} | {a['notes']} |" for a in d["attacks"]]
    if d["casting"] or d["spells"]:
        md += ["", "## Spellcasting"]
        md += [f"- **{c['class']}** ({c['ability']}): save DC {c['dc']}, attack {c['attack']:+d}" for c in d["casting"]]
        if d["slots"]:
            md.append(f"- Slots: {d['slots']}")
        for g in d["spells"]:
            md.append(f"\n**{g['title']}**")
            md += [f"- {s['name']}{' (ritual)' if s['ritual'] else ''}{' (concentration)' if s['concentration'] else ''}"
                   f"{' [' + s['uses'] + ']' if s['uses'] else ''} — {s['school']}, {s['time']}, {s['range']}"
                   for s in g["spells"]]
    if d["resources"]:
        md += ["", "## Resources"] + [f"- {r}" for r in d["resources"]]
    md += ["", "## Equipment"] + [f"- {i['name']} ×{i['qty']}{' (equipped)' if i['equipped'] else ''}"
                                   f"{' (attuned)' if i['attuned'] else ''}" for i in d["inventory"]]
    md += [f"\n{d['currency']} · {d['weight']}", "", "## Features & Traits"]
    for g in d["features"]:
        md.append(f"\n### {g['source']}")
        for f in g["items"]:
            md.append(f"**{f['name']}**" + (f" *(level {f['level']}{', ' + f['book'] if f['book'] else ''})*"
                                             if f["level"] > 1 or f["book"] else "") + f"\n{f['text']}\n")
    if d["details"] or d["story"] or d["notes"]:
        md += ["## Character", " · ".join(f"{k}: {v}" for k, v in d["details"])]
        md += [f"**{k}.** {v}" for k, v in d["story"]] + [f"- {n}" for n in d["notes"]]
    return "\n".join(md) + "\n"


def to_json(char: Character) -> str:
    return json.dumps(char.to_dict(), indent=2, ensure_ascii=False, default=str)


FORMATS: Dict[str, tuple] = {          # key -> (label, extension, renderer); the PDF renderer writes to a path itself
    "pdf": ("PDF", ".pdf", to_pdf),
    "html": ("Printable sheet (HTML)", ".html", to_html),
    "md": ("Markdown", ".md", to_markdown),
    "json": ("Character data (JSON)", ".json", to_json),
}
