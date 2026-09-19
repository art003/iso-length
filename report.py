from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook


@dataclass
class SheetResult:
    sheet_no: int
    line_id: str
    length_mm: int
    length_m: float
    formula: str
    status: str
    remarks: str
    included: list[dict]
    excluded: list[dict]
    ambiguous: list[dict]
    llm_raw: dict
    ai_calls: int


def decide_status(ambiguous: list, notes: list[str], included: list) -> str:
    if not included:
        return "error"
    if ambiguous:
        return "review"
    return "ok"


def build_formula(included: list[dict], length_mm: int) -> str:
    if not included:
        return "нет включённых размеров"
    parts = [str(x["value_mm"]) for x in included]
    return " + ".join(parts) + f" = {length_mm} мм"


def write_csv(path: Path, rows: list[SheetResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(
            [
                "номер_листа",
                "обозначение_линии",
                "длина_мм",
                "длина_м",
                "формула",
                "статус",
                "замечания",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r.sheet_no,
                    r.line_id,
                    r.length_mm,
                    f"{r.length_m:.3f}".replace(".", ","),
                    r.formula,
                    r.status,
                    r.remarks,
                ]
            )


def write_xlsx(path: Path, rows: list[SheetResult]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "длины"
    ws.append(
        [
            "номер_листа",
            "обозначение_линии",
            "длина_мм",
            "длина_м",
            "формула",
            "статус",
            "замечания",
        ]
    )
    for r in rows:
        ws.append([r.sheet_no, r.line_id, r.length_mm, r.length_m, r.formula, r.status, r.remarks])
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["E"].width = 70
    ws.column_dimensions["G"].width = 60
    wb.save(path)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
