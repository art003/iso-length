from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

COORD_RE = re.compile(r"^(X|Y|Z\+?)\s*(\d+)$", re.I)
DN_RE = re.compile(r"^DN\d", re.I)
SUPPORT_RE = re.compile(r"^[ОOФFПP]\d+[АAБB]?$", re.I)
BALLOON_RE = re.compile(r"^<\d+>$")
PURE_INT_RE = re.compile(r"^\d+$")
LINE_ID_RE = re.compile(r"^[A-Z]{1,8}\d{0,3}_\d{3,5}$", re.I)
SHEET_RE = re.compile(r"Лист\s*(\d+)\s*из\s*(\d+)", re.I)


@dataclass
class Span:
    text: str
    x: float
    y: float
    bbox: tuple[float, float, float, float]
    size: float


@dataclass
class Candidate:
    cid: str
    value_mm: int
    x: float
    y: float
    bbox: tuple[float, float, float, float]
    nearby: str
    local_hint: str


@dataclass
class SheetExtract:
    page_index: int
    width: float
    height: float
    line_id: str
    sheet_no: int | None
    sheet_count: int | None
    source_page: str
    spans: list[Span]
    candidates: list[Candidate]
    pre_excluded: list[dict]
    pixmap_png: bytes
    render_scale: float


def _nearby_text(span: Span, spans: list[Span], radius: float = 55.0) -> str:
    bits = []
    for other in spans:
        if other is span:
            continue
        dx = other.x - span.x
        dy = other.y - span.y
        if dx * dx + dy * dy <= radius * radius:
            bits.append(other.text)
    seen = set()
    out = []
    for b in bits:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return " | ".join(out[:12])


def _title_block_cut(width: float, height: float) -> tuple[float, float, float, float]:
    # штамп справа сверху, цифры оттуда не размеры трубы
    return (width * 0.72, 0.0, width, height * 0.28)


def _in_rect(x: float, y: float, rect: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = rect
    return x0 <= x <= x1 and y0 <= y <= y1


def extract_spans(page: pymupdf.Page) -> list[Span]:
    data = page.get_text("dict")
    spans: list[Span] = []
    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                spans.append(
                    Span(
                        text=text,
                        x=(x0 + x1) / 2,
                        y=(y0 + y1) / 2,
                        bbox=(x0, y0, x1, y1),
                        size=float(s.get("size") or 0),
                    )
                )
    return spans


def detect_meta(spans: list[Span]) -> tuple[str, int | None, int | None, str]:
    line_id = ""
    sheet_no = None
    sheet_count = None
    source_page = ""
    for sp in spans:
        t = sp.text.replace("\xa0", " ")
        m = SHEET_RE.search(t)
        if m:
            sheet_no = int(m.group(1))
            sheet_count = int(m.group(2))
        if "Страница" in t or "исходного" in t:
            source_page = t
        compact = t.replace(" ", "")
        if LINE_ID_RE.match(compact) and "_" in compact:
            line_id = compact.upper()
    if not line_id:
        for sp in spans:
            compact = sp.text.replace(" ", "")
            if LINE_ID_RE.match(compact):
                line_id = compact.upper()
                break
    return line_id, sheet_no, sheet_count, source_page


def build_candidates(spans: list[Span], width: float, height: float) -> tuple[list[Candidate], list[dict]]:
    title = _title_block_cut(width, height)
    pre_excluded: list[dict] = []
    raw: list[tuple[Span, int, str]] = []

    for sp in spans:
        text = sp.text.replace("\xa0", " ").strip()
        if COORD_RE.match(text):
            pre_excluded.append({"text": text, "reason": "coordinate_xyz", "bbox": sp.bbox})
            continue
        if DN_RE.match(text.replace(" ", "")):
            pre_excluded.append({"text": text, "reason": "nominal_diameter", "bbox": sp.bbox})
            continue
        if SUPPORT_RE.match(text):
            pre_excluded.append({"text": text, "reason": "support_tag", "bbox": sp.bbox})
            continue
        if BALLOON_RE.match(text):
            pre_excluded.append({"text": text, "reason": "item_balloon", "bbox": sp.bbox})
            continue
        if not PURE_INT_RE.match(text):
            continue
        value = int(text)
        if _in_rect(sp.x, sp.y, title) and value < 100:
            pre_excluded.append({"text": text, "reason": "title_block", "bbox": sp.bbox})
            continue
        if value <= 12:
            pre_excluded.append({"text": text, "reason": "bom_or_weld_index", "bbox": sp.bbox})
            continue
        nearby = _nearby_text(sp, spans)
        hint = "dimension_candidate"
        if "ШТУРВАЛ" in nearby.upper():
            hint = "near_valve_handwheel"
        if "СМ." in nearby or "ПОДКЛЮЧЕНИЕ" in nearby.upper():
            hint = hint + "|near_endpoint"
        raw.append((sp, value, hint))

    candidates: list[Candidate] = []
    for i, (sp, value, hint) in enumerate(raw, start=1):
        candidates.append(
            Candidate(
                cid=f"D{i}",
                value_mm=value,
                x=sp.x,
                y=sp.y,
                bbox=sp.bbox,
                nearby=_nearby_text(sp, spans),
                local_hint=hint,
            )
        )
    return candidates, pre_excluded


def render_page_png(page: pymupdf.Page, dpi: int = 130) -> tuple[bytes, float]:
    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return pix.tobytes("png"), scale


def extract_pdf(path: str | Path, page_filter: set[int] | None = None) -> list[SheetExtract]:
    doc = pymupdf.open(path)
    sheets: list[SheetExtract] = []
    for i, page in enumerate(doc):
        spans = extract_spans(page)
        line_id, sheet_no, sheet_count, source_page = detect_meta(spans)
        resolved_no = sheet_no or (i + 1)
        if page_filter and resolved_no not in page_filter:
            continue
        cands, excluded = build_candidates(spans, page.rect.width, page.rect.height)
        png, scale = render_page_png(page)
        sheets.append(
            SheetExtract(
                page_index=i,
                width=page.rect.width,
                height=page.rect.height,
                line_id=line_id or f"UNKNOWN_{i+1}",
                sheet_no=sheet_no or (i + 1),
                sheet_count=sheet_count or len(doc),
                source_page=source_page,
                spans=spans,
                candidates=cands,
                pre_excluded=excluded,
                pixmap_png=png,
                render_scale=scale,
            )
        )
    return sheets
