from __future__ import annotations

import copy
import re

_NUM = re.compile(r"\d+")
_COORD_WORD = re.compile(r"z\+|координата z|вертикальная координата", re.I)


def apply_guards(candidates, llm: dict) -> tuple[dict, list[str]]:
    """Правивки после модели: метки на чертеже и явные противоречия. Locked не трогаем."""
    if llm.get("locked"):
        return llm, []

    out = copy.deepcopy(llm)
    items = out.get("items") or []
    by_id = {c.cid: c for c in candidates}
    extra: list[str] = []
    hw_vals = {c.value_mm for c in candidates if "handwheel" in c.flags}

    for it in items:
        cid = it.get("id")
        c = by_id.get(cid)
        if not c:
            continue
        flags = c.flags
        if "overall_mark" in flags and it.get("decision") == "include":
            it["decision"] = "exclude_nested"
            it["role"] = "overall_same_run"
            it["reason"] = "метка Н.О."
            extra.append(f"{cid} габарит Н.О.")
        if "overall_pair" in flags and it.get("decision") == "include":
            it["decision"] = "exclude_nested"
            it["role"] = "overall_same_run"
            it["reason"] = "габарит поверх соседнего"
            extra.append(f"{cid} габарит пара")
        if it.get("decision") == "include" and _iso_lt_overall(c):
            it["decision"] = "exclude_nested"
            it["role"] = "overall_same_run"
            it["reason"] = "габарит LT"
            extra.append(f"{cid} габарит LT")
        if it.get("decision") in ("include", "ambiguous") and (
            "handwheel" in flags or c.value_mm in hw_vals
        ):
            it["decision"] = "not_length"
            it["role"] = "valve"
            it["reason"] = "штурвал"
            extra.append(f"{cid} штурвал")
        if "insulation" in flags and it.get("decision") in ("include", "ambiguous"):
            it["decision"] = "not_length"
            it["role"] = "other"
            it["reason"] = "изоляция"
            extra.append(f"{cid} изоляция")
        if "support_repeat" in flags and it.get("decision") == "include":
            it["decision"] = "not_length"
            it["role"] = "support_offset"
            it["reason"] = "повтор опоры"
            extra.append(f"{cid} опора")
        if "near_plant_coord" in flags and c.value_mm >= 9000 and it.get("decision") == "include":
            it["decision"] = "not_length"
            it["role"] = "other"
            it["reason"] = "координата узла"
            extra.append(f"{cid} координата")

    for it in items:
        cid = it.get("id")
        c = by_id.get(cid)
        if not c or it.get("decision") != "include":
            continue
        for other in candidates:
            if other.cid == cid:
                continue
            if str(other.value_mm) not in _NUM.findall(c.nearby or ""):
                continue
            if c.value_mm >= 8000 and c.value_mm >= other.value_mm * 2.2:
                it["decision"] = "exclude_nested"
                it["role"] = "overall_same_run"
                it["reason"] = f"габарит рядом с {other.cid}"
                extra.append(f"{cid} габарит рядом с {other.cid}")
                break

    for it in items:
        cid = it.get("id")
        c = by_id.get(cid)
        if not c:
            continue
        dec = it.get("decision")
        if dec not in ("not_length", "exclude_nested"):
            continue
        if "overall_mark" in c.flags or "overall_pair" in c.flags:
            continue
        if c.value_mm >= 8000:
            continue
        if "near_plant_coord" in c.flags and _COORD_WORD.search(str(it.get("reason") or "")):
            it["decision"] = "include"
            it["role"] = it.get("role") if it.get("role") not in ("overall_same_run", "other") else "main"
            it["reason"] = "длина, рядом координата"
            extra.append(f"{cid} не координата")

    for it in items:
        cid = it.get("id")
        c = by_id.get(cid)
        if not c or it.get("decision") != "exclude_nested":
            continue
        if "overall_mark" in c.flags or "overall_pair" in c.flags:
            continue
        twin = _twin_run(c, candidates)
        if twin:
            it["decision"] = "include"
            it["role"] = it.get("role") if it.get("role") != "overall_same_run" else "main"
            it["reason"] = f"два прогона с {twin}"
            extra.append(f"{cid} два прогона с {twin}")

    decisions = {it.get("id"): it.get("decision") for it in items if it.get("id") in by_id}

    for it in items:
        cid = it.get("id")
        c = by_id.get(cid)
        if not c or it.get("decision") != "exclude_nested":
            continue
        if "overall_mark" in c.flags or "overall_pair" in c.flags or _iso_lt_overall(c):
            continue
        reason = str(it.get("reason") or "")
        cited = [int(n) for n in _NUM.findall(reason)]
        if cited and min(cited) < c.value_mm and "внутри" in reason.lower():
            it["decision"] = "include"
            it["role"] = it.get("role") or "main"
            it["reason"] = "не вложен в меньшее"
            extra.append(f"{cid} вернул в сумму")
            continue
        cand_vals = {x.value_mm for x in candidates}
        larger = [
            int(n)
            for n in _NUM.findall(c.nearby or "")
            if int(n) > c.value_mm and int(n) in cand_vals
        ]
        if larger and not any(_value_included(n, by_id, decisions) for n in larger):
            it["decision"] = "include"
            it["role"] = it.get("role") or "main"
            it["reason"] = "родитель не в сумме"
            extra.append(f"{cid} вернул в сумму")

    if extra:
        notes = list(out.get("notes") or [])
        notes.append("авто: " + ", ".join(extra))
        out["notes"] = notes
    return out, extra


def _iso_lt_overall(c) -> bool:
    bits = [b.strip().upper() for b in (c.nearby or "").split("|")]
    return "LT" in bits and c.value_mm >= 2500


def _dist(a, b) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _twin_run(c, candidates) -> str | None:
    """2000 и 2400 на разных участках — оба длина, не «габарит поверх»."""
    for other in candidates:
        if other.cid == c.cid:
            continue
        if str(other.value_mm) not in _NUM.findall(c.nearby or ""):
            continue
        lo, hi = min(c.value_mm, other.value_mm), max(c.value_mm, other.value_mm)
        if lo <= 0 or hi >= 8000:
            continue
        if hi / lo > 1.35:
            continue
        if _dist(c, other) < 40:
            continue
        return other.cid
    return None


def _value_included(value: int, by_id, decisions: dict) -> bool:
    return any(
        c.value_mm == value and decisions.get(cid) == "include"
        for cid, c in by_id.items()
    )
