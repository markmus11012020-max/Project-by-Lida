"""FastAPI application."""

from __future__ import annotations

import csv
import io
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from app.config import Settings, get_settings
from app.db import Database
from app.llm import AITunnelClient
from app.pricing import cost_from_usage
from app.scenarios.registry import SCENARIOS
from app.schemas import (
    ProcessRequest,
    ProcessResponse,
    ProcessStatus,
    ScenarioInfo,
    ScenarioKey,
)
from app.service import ProcessService


def create_app(
    settings: Settings | None = None,
    service: ProcessService | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if service is not None:
            application.state.service = service
        else:
            db = Database(settings.database_path)
            db.init()
            llm = AITunnelClient(settings)
            application.state.service = ProcessService(
                settings=settings,
                db=db,
                llm=llm,
                scenarios=SCENARIOS,
            )
        yield

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Один конвейер обработки: вход → LLM → JSON → контроль качества "
            "→ действие. Сценарии: поддержка, продажи, документы."
        ),
        lifespan=lifespan,
    )
    if service is not None:
        # Makes TestClient usable without entering the lifespan context.
        application.state.service = service

    def get_service(request: Request) -> ProcessService:
        return request.app.state.service

    @application.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @application.post("/ingest", response_model=ProcessResponse)
    def ingest(
        payload: ProcessRequest,
        svc: ProcessService = Depends(get_service),
    ) -> ProcessResponse:
        return svc.process(
            scenario_key=payload.scenario,
            text=payload.text,
            source=payload.source,
            metadata=payload.metadata,
        )

    @application.get("/scenarios", response_model=list[ScenarioInfo])
    def scenarios() -> list[ScenarioInfo]:
        return [
            ScenarioInfo(
                key=scenario.key.value,
                title=scenario.title,
                description=scenario.description,
                schema_hint=scenario.schema_hint,
                example_input=scenario.example_input,
            )
            for scenario in SCENARIOS.values()
        ]

    @application.get("/results")
    def list_results(
        scenario: ScenarioKey | None = Query(default=None),
        status: ProcessStatus | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        svc: ProcessService = Depends(get_service),
    ) -> dict:
        items = svc.list_results(
            scenario=scenario.value if scenario else None,
            status=status.value if status else None,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "limit": limit, "offset": offset}

    @application.get("/results/{request_id}")
    def get_result(
        request_id: str,
        svc: ProcessService = Depends(get_service),
    ) -> dict:
        item = svc.get_result(request_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Результат не найден")
        return item

    @application.get("/audit/{request_id}")
    def get_audit(
        request_id: str,
        include_raw: bool = Query(default=False),
        svc: ProcessService = Depends(get_service),
    ) -> dict:
        item = svc.get_audit(request_id, include_raw=include_raw)
        if item is None:
            raise HTTPException(status_code=404, detail="Запись аудита не найдена")
        return item

    @application.get("/stats")
    def stats(svc: ProcessService = Depends(get_service)) -> dict:
        return svc.stats()

    @application.get("/health")
    def health(svc: ProcessService = Depends(get_service)) -> dict:
        try:
            db_ok = svc.db.health()
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(
                status_code=503, detail=f"База данных недоступна: {exc}"
            ) from exc
        if not db_ok:
            raise HTTPException(status_code=503, detail="База данных недоступна")
        return {
            "status": "ok",
            "db": "ok",
            "llm_configured": settings.llm_configured,
            "model": settings.aitunnel_model,
            "scenarios": [key.value for key in SCENARIOS],
        }

    @application.get("/export/results.csv")
    def export_results_csv(
        svc: ProcessService = Depends(get_service),
    ) -> Response:
        items = svc.export_results()
        buffer = io.StringIO()
        buffer.write("\ufeff")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "request_id",
                "scenario",
                "status",
                "category",
                "priority",
                "summary",
                "next_action",
                "confidence",
                "escalate",
                "escalate_reason",
                "latency_ms",
                "cost_rub",
                "created_at",
            ]
        )
        for item in items:
            result = item.get("result") or {}
            meta = item.get("meta") or {}
            usage = meta.get("usage") or {}
            writer.writerow(
                [
                    item.get("request_id"),
                    item.get("scenario"),
                    item.get("status"),
                    result.get("category"),
                    result.get("priority"),
                    result.get("summary"),
                    result.get("next_action"),
                    result.get("confidence"),
                    result.get("escalate"),
                    result.get("escalate_reason"),
                    meta.get("latency_ms"),
                    cost_from_usage(usage, meta.get("model", "")),
                    meta.get("created_at"),
                ]
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="results.csv"'
            },
        )

    @application.get("/export/audit.jsonl")
    def export_audit_jsonl(
        svc: ProcessService = Depends(get_service),
    ) -> Response:
        lines = [
            json.dumps(item, ensure_ascii=False)
            for item in svc.export_audit()
        ]
        return Response(
            content="\n".join(lines) + ("\n" if lines else ""),
            media_type="application/x-ndjson; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="audit.jsonl"'
            },
        )

    return application


app = create_app()
