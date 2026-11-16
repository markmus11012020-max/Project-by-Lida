"""CallPilot: a product-style demo for call-center QA automation."""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

CALL_CENTER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CALL_CENTER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CALL_CENTER_DIR))

from app.config import get_settings  # noqa: E402
from app.audio import (  # noqa: E402
    AudioTooLargeError,
    AudioValidationError,
    STTError,
    save_upload_to_temp,
)
from app.queue import create_queue  # noqa: E402
from app.scenarios.call_qa import AUTO_PASS_SCORE, QA_CRITERIA  # noqa: E402
from call_store import CallStore  # noqa: E402

DB_PATH = Path(
    os.getenv(
        "CALLPILOT_DB_PATH",
        str(CALL_CENTER_DIR / "data" / "call_center.db"),
    )
)
STATIC_DIR = CALL_CENTER_DIR / "static"
TEMPLATES_DIR = CALL_CENTER_DIR / "templates"

settings = get_settings().model_copy(update={"database_path": DB_PATH})
store = CallStore(settings, DB_PATH)
QUEUE_DIR = CALL_CENTER_DIR / "data" / "queue" / "audio"
_queue = None


def get_queue():
    global _queue
    if _queue is None:
        _queue = create_queue(
            os.getenv("CALLPILOT_QUEUE_URL", settings.callpilot_queue_url)
        )
    return _queue

app = FastAPI(
    title="Call-Pilot",
    version="1.0.0",
    description="AI-контроль качества и постобработка звонков для колл-центров.",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

INTENT_LABELS = {
    "order_status": "Статус заказа",
    "delivery": "Доставка",
    "refund": "Возврат",
    "billing": "Оплата",
    "technical": "Техническая проблема",
    "complaint": "Жалоба",
    "consultation": "Консультация",
    "other": "Другое",
}
STATUS_LABELS = {
    "new": "Не обработан",
    "pending": "На проверке",
    "confirmed": "Подтверждён",
    "rejected": "Отклонён",
    "auto_pass": "Авто-проверка",
    "manual_review": "Ручная проверка",
    "processed": "Обработан",
    "escalated": "Эскалирован",
    "invalid": "Ошибка JSON",
    "error": "Ошибка LLM",
}
FINDING_LABELS = {
    "pass": "Выполнено",
    "fail": "Нарушение",
    "na": "Не применимо",
}
SEVERITY_LABELS = {
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
    "critical": "Критичный",
}
PRIORITY_LABELS = {
    "critical": "Критичный",
    "high": "Высокий",
    "normal": "Обычный",
}
SENTIMENT_LABELS = {
    "positive": "Позитивный",
    "neutral": "Нейтральный",
    "negative": "Негативный",
}


def _label(mapping: dict[str, str], value: Any) -> str:
    return mapping.get(str(value or ""), str(value or "—"))


def _badge_class(value: Any) -> str:
    value = str(value or "")
    if value in {"confirmed", "auto_pass", "processed", "pass", "positive"}:
        return "badge badge-green"
    if value in {"manual_review", "pending", "escalated", "medium", "na", "neutral"}:
        return "badge badge-amber"
    if value in {"rejected", "invalid", "error", "fail", "critical", "high", "negative"}:
        return "badge badge-red"
    return "badge badge-gray"


def _display_status(call: dict[str, Any]) -> str:
    if call.get("review_status") in {"confirmed", "rejected"}:
        return call["review_status"]
    result = call.get("result") or {}
    if result:
        return result.get("auto_qa_status", "manual_review")
    return "new"


def _duration(ms: Any) -> str:
    try:
        total = int(ms or 0)
    except (TypeError, ValueError):
        total = 0
    minutes, seconds = divmod(total // 1000, 60)
    return f"{minutes}:{seconds:02d}"


def _datetime(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return str(value or "—")


templates.env.filters["label"] = lambda value, mapping: _label(mapping, value)
templates.env.filters["badge"] = _badge_class
templates.env.filters["display_status"] = _display_status
templates.env.filters["duration"] = _duration
templates.env.filters["datetime"] = _datetime
templates.env.globals.update(
    app_name="Call-Pilot",
    intent_labels=INTENT_LABELS,
    status_labels=STATUS_LABELS,
    finding_labels=FINDING_LABELS,
    severity_labels=SEVERITY_LABELS,
    priority_labels=PRIORITY_LABELS,
    sentiment_labels=SENTIMENT_LABELS,
    qa_criteria=QA_CRITERIA,
    qa_criteria_count=len(QA_CRITERIA),
    auto_pass_score=AUTO_PASS_SCORE,
    llm_configured=settings.llm_configured,
    model_name=settings.aitunnel_model,
)


class ConfirmPayload(BaseModel):
    final_result: dict[str, Any]
    reviewer: str = "Менеджер"
    reason: str = ""


class RejectPayload(BaseModel):
    reviewer: str = "Менеджер"
    reason: str = ""


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    metrics = store.metrics()
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={"metrics": metrics},
    )


@app.get("/media/product-demo.mp4")
def product_demo():
    path = CALL_CENTER_DIR / "demo" / "callpilot-demo.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Видео не найдено")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/media/product-demo-poster.png")
def product_demo_poster():
    path = CALL_CENTER_DIR / "screenshots" / "dashboard.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Постер не найден")
    return FileResponse(path, media_type="image/png")


@app.post("/lead")
def lead_form(
    name: str = Form(..., max_length=120),
    company: str = Form("", max_length=160),
    contact: str = Form(..., max_length=160),
    volume: str = Form("", max_length=40),
    phone_system: str = Form("", max_length=120),
    comment: str = Form("", max_length=600),
    consent: str = Form(""),
):
    if not name.strip() or not contact.strip():
        raise HTTPException(status_code=422, detail="Укажите имя и контакт")
    if consent.lower() not in {"yes", "on", "true", "1"}:
        raise HTTPException(
            status_code=422,
            detail="Нужно согласие на обработку персональных данных",
        )
    store.save_lead(
        name=name,
        company=company,
        contact=contact,
        volume=volume,
        phone_system=phone_system,
        comment=comment,
        consent=True,
    )
    return RedirectResponse(url="/?sent=1#lead", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    status: str = "all",
    qa: str = "all",
    role: str = "manager",
    source: str = "all",
    priority: str = "all",
):
    calls = store.list_calls(source=source)
    metrics = store.metrics()
    if status != "all":
        calls = [call for call in calls if _display_status(call) == status]
    if qa != "all":
        calls = [
            call
            for call in calls
            if (call.get("result") or {}).get("auto_qa_status") == qa
        ]
    if priority != "all":
        calls = [
            call for call in calls if call.get("review_priority") == priority
        ]
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "calls": calls,
            "metrics": metrics,
            "status_filter": status,
            "qa_filter": qa,
            "source_filter": source,
            "priority_filter": priority,
            "role": role,
        },
    )


@app.get("/calls/{call_id}", response_class=HTMLResponse)
def call_detail(request: Request, call_id: str, role: str = "manager"):
    call = store.get_call(call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    draft = call.get("result") or {}
    read_only = call["review_status"] in {"confirmed", "rejected"}
    next_call = (
        store.next_pending_call(call_id)
        if call["review_status"] == "pending"
        else None
    )
    return templates.TemplateResponse(
        request=request,
        name="call_detail.html",
        context={
            "call": call,
            "draft": draft,
            "draft_json": json.dumps(draft, ensure_ascii=False),
            "segments_json": json.dumps(
                call.get("segments", []), ensure_ascii=False
            ),
            "read_only": read_only,
            "role": role,
            "confirmed": call["review_status"] == "confirmed",
            "rejected": call["review_status"] == "rejected",
            "next_call": next_call,
        },
    )


@app.get("/calls/{call_id}/audio")
def call_audio(call_id: str):
    payload = store.get_audio(call_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Аудио не найдено")
    data, mime = payload
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.post("/review/upload")
async def upload_real_call(
    file: UploadFile = File(...),
    title: str = Form("", max_length=200),
    external_id: str = Form("", max_length=120),
):
    if store.stt_client is None:
        raise HTTPException(
            status_code=503,
            detail="STT не настроен: укажите STT_API_URL",
        )

    path = None
    try:
        path = await save_upload_to_temp(file, settings.audio_max_bytes)
        if settings.callpilot_async_upload:
            QUEUE_DIR.mkdir(parents=True, exist_ok=True)
            target = QUEUE_DIR / f"{uuid.uuid4().hex}{path.suffix}"
            shutil.move(str(path), target)
            path = target
            get_queue().enqueue(
                "audio_ingest",
                {
                    "path": str(target),
                    "filename": file.filename or target.name,
                    "title": title,
                    "external_id": external_id.strip() or None,
                },
            )
            path = None
            return RedirectResponse(
                url="/dashboard?queued=1",
                status_code=303,
            )
        call_id = store.ingest_audio(
            path,
            filename=file.filename or path.name,
            title=title,
            external_id=external_id.strip() or None,
        )
        return RedirectResponse(
            url=f"/calls/{call_id}?processed=1",
            status_code=303,
        )
    except AudioTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except AudioValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except STTError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        await file.close()


@app.post("/calls/{call_id}/process")
def process_call(call_id: str):
    try:
        store.process_call(call_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Звонок не найден") from exc
    return RedirectResponse(
        url=f"/calls/{call_id}?processed=1", status_code=303
    )


@app.post("/calls/{call_id}/confirm")
def confirm_call(call_id: str, payload: ConfirmPayload):
    try:
        call = store.confirm_call(
            call_id,
            payload.final_result,
            payload.reviewer,
            payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Звонок не найден") from exc
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Проверьте карточку: {exc}"
        ) from exc
    return JSONResponse(
        {
            "ok": True,
            "redirect": f"/calls/{call_id}?confirmed=1",
            "call": call,
        }
    )


@app.post("/calls/{call_id}/reject")
def reject_call(call_id: str, payload: RejectPayload):
    if not payload.reason.strip():
        raise HTTPException(status_code=422, detail="Укажите причину отклонения")
    try:
        store.reject_call(call_id, payload.reviewer, payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Звонок не найден") from exc
    return JSONResponse({"ok": True, "redirect": f"/calls/{call_id}?rejected=1"})


@app.post("/demo/reset")
def reset_demo():
    store.reset_demo()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/qa", response_class=HTMLResponse)
def qa_dashboard(request: Request):
    metrics = store.metrics()
    return templates.TemplateResponse(
        request=request,
        name="qa.html",
        context={"metrics": metrics, "role": "manager"},
    )


@app.get("/offer", response_class=HTMLResponse)
def offer(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="offer.html",
        context={"metrics": store.metrics()},
    )


@app.get("/health")
def health():
    metrics = store.metrics()
    return {
        "status": "ok",
        "app": "Call-Pilot",
        "llm_configured": settings.llm_configured,
        "model": settings.aitunnel_model,
        "calls": metrics["total"],
        "processed": metrics["processed"],
    }
