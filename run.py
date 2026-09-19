from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from annotate import annotate_final, overlay_candidate_ids
from extract import extract_pdf
from llm_client import LlmClient
from pricing import estimate_cost_usd, PRICES_USD_PER_M
from report import SheetResult, build_formula, decide_status, write_csv, write_json, write_xlsx


def process_pdf(
    pdf_path: Path,
    out_dir: Path,
    page_filter: set[int] | None = None,
    log=print,
    use_cache: bool = True,
) -> dict:
    t0 = time.perf_counter()
    sheets = extract_pdf(pdf_path, page_filter)
    if not sheets:
        raise RuntimeError("Не удалось извлечь листы из PDF (проверьте файл и --pages).")
    client = LlmClient()
    results: list[SheetResult] = []
    markup_dir = out_dir / "markup"
    overlay_dir = out_dir / "overlays"
    raw_dir = out_dir / "llm_raw"
    markup_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    for sheet in sheets:
        cand_dicts = [
            {
                "id": c.cid,
                "value_mm": c.value_mm,
                "local_hint": c.local_hint,
                "nearby": c.nearby,
            }
            for c in sheet.candidates
        ]
        overlay = overlay_candidate_ids(sheet.pixmap_png, sheet.candidates, sheet.render_scale)
        (overlay_dir / f"sheet_{sheet.sheet_no:02d}_{sheet.line_id}_ids.png").write_bytes(overlay)

        calls_before = client.usage.calls
        raw_path = raw_dir / f"sheet_{sheet.sheet_no:02d}.json"
        wanted = {c["id"] for c in cand_dicts}
        llm = None
        if use_cache and raw_path.exists():
            try:
                cached = json.loads(raw_path.read_text(encoding="utf-8"))
                got = {it.get("id") for it in (cached.get("items") or [])}
                if wanted <= got:
                    llm = cached
                    log(f"Лист {sheet.sheet_no:02d} уже есть, пропускаю")
            except json.JSONDecodeError:
                llm = None
        if llm is None:
            llm = client.classify_sheet(sheet.sheet_no, sheet.line_id, cand_dicts, overlay)
            raw_path.write_text(json.dumps(llm, ensure_ascii=False, indent=2), encoding="utf-8")
            if client.provider == "groq" and sheet is not sheets[-1]:
                pause = int(os.getenv("GROQ_PAUSE_S", "70"))
                log(f"пауза {pause} с (лимит Groq), следующий лист...")
                time.sleep(pause)
            elif client.provider == "openrouter":
                time.sleep(8)

        by_id = {c.cid: c for c in sheet.candidates}
        decisions: dict[str, str] = {}
        included, excluded, ambiguous = [], [], []
        notes = list(llm.get("notes") or [])
        for item in llm.get("items") or []:
            cid = item.get("id")
            if cid not in by_id:
                continue
            dec = item.get("decision") or "ambiguous"
            if dec not in ("include", "exclude_nested", "not_length", "ambiguous"):
                dec = "ambiguous"
            decisions[cid] = dec
            rec = {
                "id": cid,
                "value_mm": by_id[cid].value_mm,
                "role": item.get("role"),
                "reason": item.get("reason"),
            }
            if dec == "include":
                included.append(rec)
            elif dec == "ambiguous":
                ambiguous.append(rec)
            else:
                excluded.append(rec)
        for c in sheet.candidates:
            if c.cid not in decisions:
                decisions[c.cid] = "ambiguous"
                ambiguous.append({"id": c.cid, "value_mm": c.value_mm, "role": "other", "reason": "модель этот id не вернула"})

        # суммирование только программно
        length_mm = sum(int(x["value_mm"]) for x in included)
        formula = build_formula(included, length_mm)
        if ambiguous:
            notes.append("глянуть: " + ", ".join(f"{a['id']}={a['value_mm']}" for a in ambiguous))
        status = decide_status(ambiguous, notes, included)
        remarks = "; ".join(notes)

        title = f"Лист {sheet.sheet_no}  {sheet.line_id}"
        png_name = f"sheet_{sheet.sheet_no:02d}_{sheet.line_id}.png"
        annotate_final(
            sheet.pixmap_png,
            sheet.candidates,
            decisions,
            sheet.render_scale,
            title,
            formula,
            length_mm,
            status,
            markup_dir / png_name,
        )

        line_id = (llm.get("line_id") or sheet.line_id or "").strip() or sheet.line_id
        results.append(
            SheetResult(
                sheet_no=int(sheet.sheet_no),
                line_id=line_id,
                length_mm=length_mm,
                length_m=round(length_mm / 1000.0, 3),
                formula=formula,
                status=status,
                remarks=remarks,
                included=included,
                excluded=excluded,
                ambiguous=ambiguous,
                llm_raw=llm,
                ai_calls=client.usage.calls - calls_before,
            )
        )
        log(
            f"Лист {sheet.sheet_no:02d} {line_id}: {length_mm} мм ({length_mm/1000:.3f} м) [{status}]"
        )

    elapsed = time.perf_counter() - t0
    usage = client.usage
    cost = estimate_cost_usd(usage)
    pages = max(len(results), 1)
    cost_per_page = cost / pages
    calls_per_page = usage.calls / pages

    write_csv(out_dir / "lengths.csv", results)
    write_xlsx(out_dir / "lengths.xlsx", results)

    inn_p, out_p = PRICES_USD_PER_M.get(usage.model.lower(), (0.30, 2.50))
    replay = usage.provider == "replay"
    metrics = {
        "pdf": pdf_path.name,
        "provider": "без API" if replay else usage.provider,
        "model": usage.model,
        "ocr": "нет, текст из pdf (pymupdf)",
        "pages": len(results),
        "total_time_s": round(elapsed, 2),
        "ai_calls_total": 0 if replay else usage.calls,
        "ai_retries": 0 if replay else usage.retries,
        "ai_calls_avg_per_page": 0 if replay else round(calls_per_page, 2),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "tariff_date": "2026-09-18",
        "tariff_usd_per_1m_tokens": {"input": inn_p, "output": out_p},
        "cost_total_usd": round(cost, 6),
        "cost_per_page_usd": round(cost_per_page, 6),
        "cost_formula": (
            f"({usage.input_tokens} / 1e6) * {inn_p} + ({usage.output_tokens} / 1e6) * {out_p}"
        ),
        "note": (
            "API не вызывал, ответы из llm_raw. Чтобы посчитать $ - python run.py с ключом."
            if replay
            else "Считал по токенам из ответа API."
        ),
        "sheets": [
            {
                "sheet_no": r.sheet_no,
                "line_id": r.line_id,
                "length_mm": r.length_mm,
                "length_m": r.length_m,
                "formula": r.formula,
                "status": r.status,
                "remarks": r.remarks,
                "included": r.included,
                "excluded": r.excluded,
                "ambiguous": r.ambiguous,
                "ai_calls": r.ai_calls,
            }
            for r in results
        ],
    }
    write_json(out_dir / "metrics.json", metrics)
    (out_dir / "metrics.txt").write_text(_metrics_text(metrics), encoding="utf-8")
    log(_metrics_text(metrics))
    return metrics


def _metrics_text(m: dict) -> str:
    inn = m["tariff_usd_per_1m_tokens"]["input"]
    out = m["tariff_usd_per_1m_tokens"]["output"]
    return "\n".join(
        [
            f"Модель в коде: {m['provider']} / {m['model']}",
            f"OCR: {m['ocr']}",
            f"Листов: {m['pages']}",
            f"Время, с: {m['total_time_s']}",
            f"Обращений к API: {m['ai_calls_total']} (повторы: {m['ai_retries']})",
            f"Токены: {m['input_tokens']} / {m['output_tokens']}",
            f"Тариф {m['tariff_date']}: ${inn} in / ${out} out за 1M",
            f"Стоимость: ${m['cost_total_usd']}",
            f"На лист: ${m['cost_per_page_usd']}",
            f"Формула: {m['cost_formula']}",
            m.get("note") or "",
        ]
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Расчёт длины трубопроводов по изометриям")
    p.add_argument("pdf", nargs="?", default="", help="PDF с листами изометрий")
    p.add_argument("-o", "--out", default="", help="каталог результатов")
    p.add_argument("--pages", default="", help="номера листов через запятую, например 7 или 1,7")
    p.add_argument("--from-json", default="", help="папка с уже сохранёнными json, без API")
    args = p.parse_args()
    default_pdf = ROOT / "data" / "02_Изометрии_10_листов.pdf"
    pdf = Path(args.pdf) if args.pdf else default_pdf
    if not pdf.exists():
        raise SystemExit(f"PDF не найден: {pdf}")
    out = Path(args.out) if args.out else ROOT / "output"
    page_filter = None
    if args.pages.strip():
        page_filter = {int(x.strip()) for x in args.pages.split(",") if x.strip()}
    if args.from_json.strip():
        os.environ["ISO_LLM_PROVIDER"] = "replay"
        os.environ["ISO_REPLAY_DIR"] = str(Path(args.from_json).resolve())
    process_pdf(pdf, out, page_filter)


if __name__ == "__main__":
    main()
