"""What the conditions do (PHB appendix A). One table every roll asks, so a Prone or Restrained creature is treated the
same whether it attacks, is attacked, saves or moves.

Seeing is decided by sight.py (Blinded and Invisible work through it); this table holds the rest."""
from typing import Iterable, Optional, Set

INCAPACITATING = {"Incapacitated", "Paralyzed", "Petrified", "Stunned", "Unconscious"}
NO_MOVE = {"Grappled", "Restrained", "Paralyzed", "Petrified", "Stunned", "Unconscious"}
AUTO_FAIL_STR_DEX = {"Paralyzed", "Petrified", "Stunned", "Unconscious"}
ATTACKED_WITH_ADV = {"Paralyzed", "Petrified", "Restrained", "Stunned", "Unconscious"}
ATTACKS_WITH_DIS = {"Poisoned", "Restrained", "Prone", "Frightened"}
CRIT_WITHIN_5 = {"Paralyzed", "Unconscious"}
CHECKS_WITH_DIS = {"Poisoned", "Frightened"}
ALL = ["Blinded", "Charmed", "Deafened", "Frightened", "Grappled", "Incapacitated", "Invisible", "Paralyzed", "Petrified",
       "Poisoned", "Prone", "Restrained", "Stunned", "Unconscious"]

SUMMARY = {
    "Blinded": "can't see: its attacks have disadvantage, attacks against it have advantage",
    "Charmed": "can't attack the charmer",
    "Deafened": "can't hear",
    "Frightened": "disadvantage on attacks and checks; can't move closer to the source",
    "Grappled": "speed 0",
    "Incapacitated": "no actions or reactions",
    "Invisible": "unseen: its attacks have advantage, attacks against it have disadvantage",
    "Paralyzed": "no actions, can't move; fails Str/Dex saves; hits within 5 ft are critical",
    "Petrified": "no actions, can't move; fails Str/Dex saves; resistant to all damage",
    "Poisoned": "disadvantage on attacks and checks",
    "Prone": "disadvantage on its attacks; melee attacks against it have advantage, ranged ones disadvantage; standing costs half its speed",
    "Restrained": "speed 0; disadvantage on its attacks and Dex saves; attacks against it have advantage",
    "Stunned": "no actions, can't move; fails Str/Dex saves; attacks against it have advantage",
    "Unconscious": "no actions, can't move; fails Str/Dex saves; hits within 5 ft are critical",
}


def _set(conds: Optional[Iterable[str]]) -> Set[str]:
    return set(conds or [])


def incapacitated(conds) -> bool:
    return bool(_set(conds) & INCAPACITATING)


def can_move(conds, exhaustion: int = 0) -> bool:
    return not (_set(conds) & NO_MOVE) and exhaustion < 5


def speed_factor(conds, exhaustion: int = 0) -> float:
    """Multiply the walking speed: 0 when held, half from exhaustion 2."""
    if not can_move(conds, exhaustion):
        return 0.0
    return .5 if exhaustion >= 2 else 1.0


def attack_modes(att_conds, tgt_conds, *, melee: bool, within_5: bool, att_exhaustion: int = 0, frightened_sees_source: bool = True):
    """(set of 'adv'/'dis' from the conditions of attacker and target, reasons)."""
    a, t = _set(att_conds), _set(tgt_conds)
    modes, why = set(), []
    for c in sorted(a & ATTACKS_WITH_DIS):
        if c == "Frightened" and not frightened_sees_source:
            continue
        modes.add("dis")
        why.append(f"attacker {c.lower()}")
    if att_exhaustion >= 3:
        modes.add("dis")
        why.append("attacker exhausted")
    for c in sorted(t & ATTACKED_WITH_ADV):
        modes.add("adv")
        why.append(f"target {c.lower()}")
    if "Prone" in t:
        if within_5:                                         # PHB: within 5 ft (a crossbow too) advantage, else disadvantage
            modes.add("adv")
            why.append("target prone")
        else:
            modes.add("dis")
            why.append("target prone (far)")
    return modes, why


def auto_crit(tgt_conds, within_5: bool) -> bool:
    return within_5 and bool(_set(tgt_conds) & CRIT_WITHIN_5)


def save_mode(conds, ability: str, exhaustion: int = 0):
    """'fail' (an automatic failure), 'dis' or None for a saving throw of this creature."""
    s = _set(conds)
    if ability in ("str", "dex") and s & AUTO_FAIL_STR_DEX:
        return "fail"
    if ability == "dex" and "Restrained" in s:
        return "dis"
    if exhaustion >= 3:
        return "dis"
    return None


def check_mode(conds, exhaustion: int = 0) -> Optional[str]:
    s = _set(conds)
    if s & CHECKS_WITH_DIS or exhaustion >= 1:
        return "dis"
    return None


def damage_resist_all(conds) -> bool:
    return "Petrified" in _set(conds)


def combine(modes: Iterable[str]) -> Optional[str]:
    """Advantage and disadvantage cancel out, however many of each."""
    s = set(m for m in modes if m in ("adv", "dis"))
    if s == {"adv"}:
        return "adv"
    if s == {"dis"}:
        return "dis"
    return None
