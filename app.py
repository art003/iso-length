from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory

from run import ROOT, process_pdf

load_dotenv(ROOT / ".env")

PRESETS = {
    "Groq": {"provider": "groq", "model": "qwen/qwen3.8-27b", "key_env": "GROQ_API_KEY"},
    "OpenAI": {"provider": "openai", "model": "gpt-4o", "key_env": "OPENAI_API_KEY"},
    "OpenAI Codex": {"provider": "codex", "model": "gpt-5-codex", "key_env": "OPENAI_API_KEY"},
}

WEB = ROOT / "web"
app = Flask(
    __name__,
    template_folder=str(WEB / "templates"),
    static_folder=str(WEB / "static"),
)

_lock = threading.Lock()
_job = {"running": False, "log": [], "metrics": None, "error": None, "thumbs": []}


def _thumbs() -> list[str]:
    markup = ROOT / "output" / "markup"
    if not markup.exists():
        return []
    return ["/media/markup/" + p.name for p in sorted(markup.glob("*.png"))]


def _load_saved() -> None:
    path = ROOT / "output" / "metrics.json"
    if not path.exists():
        return
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        _job["metrics"] = data
        _job["thumbs"] = _thumbs()
    except Exception:
        pass


_load_saved()


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
        if payload["replay"]:
            os.environ["ISO_LLM_PROVIDER"] = "replay"
            os.environ["ISO_REPLAY_DIR"] = str(ROOT / "output" / "llm_raw")
        pdf = payload["pdf"]
        pages = payload["pages"]
        page_filter = None
        if pages:
            page_filter = {int(x.strip()) for x in pages.split(",") if x.strip()}
        _log(f"старт: {payload['api']} / {os.environ.get('ISO_LLM_MODEL')}")
        metrics = process_pdf(
            pdf,
            ROOT / "output",
            page_filter,
            log=_log,
            use_cache=not payload["fresh"],
        )
        with _lock:
            _job["metrics"] = metrics
            _job["thumbs"] = _thumbs()
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


@app.get("/api/status")
def api_status():
    with _lock:
        return jsonify(
            {
                "running": _job["running"],
                "log": list(_job["log"]),
                "metrics": _job["metrics"],
                "error": _job["error"],
                "thumbs": list(_job["thumbs"] or _thumbs()),
            }
        )


@app.post("/api/open-output")
def api_open_output():
    out = ROOT / "output"
    out.mkdir(parents=True, exist_ok=True)
    os.startfile(out)
    return jsonify({"ok": True})


@app.get("/media/<path:sub>")
def media(sub: str):
    return send_from_directory(ROOT / "output", sub)


def main() -> None:
    url = "http://127.0.0.1:8765"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
