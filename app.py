from __future__ import annotations

import json
import os
import threading
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory

from jobs import list_jobs, migrate_legacy
from review import apply_decision, sheet_view
from run import ROOT, process_pdf

load_dotenv(ROOT / ".env")

PRESETS = {
    "Groq": {"provider": "groq", "model": "qwen/qwen3.8-27b", "key_env": "GROQ_API_KEY"},
    "OpenAI": {"provider": "openai", "model": "gpt-4o", "key_env": "OPENAI_API_KEY"},
    "OpenAI Codex": {"provider": "codex", "model": "gpt-5-codex", "key_env": "OPENAI_API_KEY"},
}

WEB = ROOT / "web"
OUT = ROOT / "output"
app = Flask(
    __name__,
    template_folder=str(WEB / "templates"),
    static_folder=str(WEB / "static"),
)

_lock = threading.Lock()
_cancel = threading.Event()
_job = {"running": False, "log": [], "metrics": None, "error": None, "thumbs": [], "jobs": []}


def _safe_job(name: str) -> Path | None:
    if not name or ".." in name or "/" in name or "\\" in name:
        return None
    folder = (OUT / name).resolve()
    try:
        folder.relative_to(OUT.resolve())
    except ValueError:
        return None
    if not folder.is_dir():
        return None
    return folder


def _thumbs_from_metrics(metrics: dict | None) -> list[str]:
    if not metrics:
        return []
    thumbs = metrics.get("thumbs") or []
    if thumbs:
        return ["/media/" + t.replace("\\", "/") for t in thumbs]
    job = metrics.get("job")
    if not job:
        return []
    markup = OUT / job / "markup"
    if not markup.exists():
        return []
    return ["/media/" + job + "/markup/" + p.name for p in sorted(markup.glob("*.png"))]


def _load_latest() -> None:
    jobs = list_jobs(OUT)
    _job["jobs"] = jobs
    if not jobs:
        return
    folder = OUT / jobs[0]["id"]
    path = folder / "metrics.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _job["metrics"] = data
        _job["thumbs"] = _thumbs_from_metrics(data)
    except Exception:
        pass


_load_latest()


def _log(msg: str) -> None:
    with _lock:
        _job["log"].append(str(msg).rstrip())


def _run_job(payload: dict) -> None:
    try:
        preset = PRESETS[payload["api"]]
        os.environ["ISO_LLM_PROVIDER"] = preset["provider"]
        os.environ["ISO_LLM_MODEL"] = payload["model"] or preset["model"]
        if payload["key"]:
            os.environ[preset["key_env"]] = payload["key"]
        pdf = payload["pdf"]
        job = migrate_legacy(OUT, pdf)
        if payload["replay"]:
            os.environ["ISO_LLM_PROVIDER"] = "replay"
            os.environ["ISO_REPLAY_DIR"] = str(job / "llm_raw")
        pages = payload["pages"]
        page_filter = None
        if pages:
            page_filter = {int(x.strip()) for x in pages.split(",") if x.strip()}
        _log(f"старт: {payload['api']} / {os.environ.get('ISO_LLM_MODEL')}")
        _log(f"PDF: {Path(pdf).name}")
        metrics = process_pdf(
            pdf,
            OUT,
            page_filter,
            log=_log,
            use_cache=not payload["fresh"],
            cancel=_cancel,
        )
        with _lock:
            _job["metrics"] = metrics
            _job["thumbs"] = _thumbs_from_metrics(metrics)
            _job["jobs"] = list_jobs(OUT)
            _job["error"] = None
    except Exception as e:
        _log(f"ошибка: {e}")
        with _lock:
            _job["error"] = str(e)
    finally:
        with _lock:
            _job["running"] = False


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/start")
def api_start():
    with _lock:
        if _job["running"]:
            return jsonify({"error": "уже считается"}), 409
        _job["running"] = True
        _job["log"] = []
        _job["error"] = None
        _cancel.clear()

    use_default = request.form.get("use_default") == "1"
    upload = request.files.get("pdf")
    pdf = ROOT / "data" / "02_Изометрии_10_листов.pdf"
    if upload and upload.filename:
        dest = ROOT / "web" / "uploads"
        dest.mkdir(parents=True, exist_ok=True)
        pdf = dest / Path(upload.filename).name
        upload.save(pdf)
    elif not use_default or not pdf.exists():
        with _lock:
            _job["running"] = False
        return jsonify({"error": "нет PDF"}), 400

    api = request.form.get("api") or "Groq"
    if api not in PRESETS:
        with _lock:
            _job["running"] = False
        return jsonify({"error": "неизвестный API"}), 400

    payload = {
        "api": api,
        "model": (request.form.get("model") or "").strip(),
        "key": (request.form.get("key") or "").strip(),
        "pages": (request.form.get("pages") or "").strip(),
        "replay": request.form.get("replay") == "1",
        "fresh": request.form.get("fresh") == "1",
        "pdf": pdf,
    }
    threading.Thread(target=_run_job, args=(payload,), daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/stop")
def api_stop():
    with _lock:
        running = _job["running"]
    if not running:
        return jsonify({"ok": True, "running": False})
    _cancel.set()
    _log("остановка: дождусь текущий запрос и сохраню что есть")
    return jsonify({"ok": True, "running": True})


@app.get("/api/sheet/<job_id>/<int:sheet_no>")
def api_sheet(job_id: str, sheet_no: int):
    folder = _safe_job(job_id)
    if not folder:
        return jsonify({"error": "нет такой папки"}), 404
    try:
        return jsonify(sheet_view(folder, sheet_no))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/decide")
def api_decide():
    with _lock:
        if _job["running"]:
            return jsonify({"error": "сейчас идёт расчёт — останови или подожди"}), 409
    data = request.get_json(silent=True) or {}
    folder = _safe_job(str(data.get("job") or ""))
    if not folder:
        return jsonify({"error": "нет такой папки"}), 404
    cid = str(data.get("id") or "").strip()
    if not cid:
        return jsonify({"error": "нет id размера"}), 400
    try:
        sheet_no = int(data.get("sheet_no"))
        metrics = apply_decision(folder, sheet_no, cid, data.get("decision"))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    last = metrics.pop("_last_edit", None)
    thumbs = _thumbs_from_metrics(metrics)
    with _lock:
        _job["metrics"] = metrics
        _job["thumbs"] = thumbs
        _job["jobs"] = list_jobs(OUT)
    return jsonify(
        {
            "ok": True,
            "edit": last,
            "metrics": metrics,
            "thumbs": thumbs,
            "jobs": _job["jobs"],
        }
    )


@app.get("/api/status")
def api_status():
    with _lock:
        return jsonify(
            {
                "running": _job["running"],
                "log": list(_job["log"]),
                "metrics": _job["metrics"],
                "error": _job["error"],
                "thumbs": list(_job["thumbs"] or _thumbs_from_metrics(_job["metrics"])),
                "jobs": list(_job["jobs"] or list_jobs(OUT)),
            }
        )


@app.get("/api/jobs")
def api_jobs():
    return jsonify({"jobs": list_jobs(OUT)})


@app.get("/api/job/<job_id>")
def api_job(job_id: str):
    folder = _safe_job(job_id)
    if not folder:
        return jsonify({"error": "нет такой папки"}), 404
    path = folder / "metrics.json"
    if not path.exists():
        return jsonify({"error": "нет metrics.json"}), 404
    data = json.loads(path.read_text(encoding="utf-8"))
    thumbs = _thumbs_from_metrics(data)
    with _lock:
        _job["metrics"] = data
        _job["thumbs"] = thumbs
    return jsonify({"metrics": data, "thumbs": thumbs})


@app.post("/api/open-output")
def api_open_output():
    name = request.form.get("job") or ""
    if request.is_json and request.json:
        name = name or (request.json.get("job") or "")
    folder = _safe_job(name) if name else None
    if folder is None:
        with _lock:
            job = (_job.get("metrics") or {}).get("job")
        folder = _safe_job(job) if job else OUT
    folder = folder or OUT
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(folder)
    return jsonify({"ok": True, "folder": str(folder)})


@app.get("/media/<path:sub>")
def media(sub: str):
    return send_from_directory(OUT, sub)


def main() -> None:
    url = "http://127.0.0.1:8765"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
