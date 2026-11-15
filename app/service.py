"""End-to-end processing pipeline: input, LLM, QC, audit, action."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.db import Database
from app.llm import LLMClient, LLMError
from app.qc import (
    apply_qc,
    extract_json_object,
    fallback_result,
    validate_result,
)
from app.scenarios.base import ScenarioConfig
from app.integrations import WebhookOutbox
from app.security import (
    Anonymizer,
    EncryptedSQLitePIIVault,
    InMemoryPIIVault,
    PIIVault,
)
from app.schemas import (
    ProcessMeta,
    ProcessResponse,
    ProcessStatus,
    ScenarioKey,
)

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ProcessService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        llm: LLMClient,
        scenarios: dict[ScenarioKey, ScenarioConfig],
        anonymizer: Anonymizer | None = None,
        vault: PIIVault | None = None,
        outbox: WebhookOutbox | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.llm = llm
        self.scenarios = scenarios
        self.anonymizer = anonymizer or Anonymizer()
        if vault is None:
            if settings.pii_vault_key.strip():
                vault = EncryptedSQLitePIIVault(
                    settings.pii_vault_path,
                    settings.pii_vault_key,
                )
            else:
                vault = InMemoryPIIVault()
        self.vault = vault
        if outbox is None and settings.crm_webhook_enabled:
            outbox = WebhookOutbox(settings.crm_outbox_path)
        self.outbox = outbox

    def process(
        self,
        scenario_key: ScenarioKey | str,
        text: str,
        source: str = "api",
        metadata: dict[str, str] | None = None,
        anonymize: bool = False,
    ) -> ProcessResponse:
        scenario = self.scenarios[ScenarioKey(scenario_key)]
        request_id = str(uuid.uuid4())
        created_at = utc_now()
        metadata = metadata or {}
        session = self.anonymizer.session() if anonymize else None
        anonymized = session.anonymize(text) if session is not None else None
        llm_text = anonymized.text if anonymized is not None else text
        input_hash = hashlib.sha256(llm_text.encode("utf-8")).hexdigest()

        started = time.perf_counter()
        status = ProcessStatus.ERROR
        result_dict: dict[str, Any] | None = None
        raw_response: str | None = None
        error: str | None = None
        usage: dict[str, Any] = {}
        model = self.settings.aitunnel_model

        try:
            messages = scenario.build_messages(llm_text)
            llm_response = self.llm.complete_json(messages)
            raw_response = llm_response.content
            usage = llm_response.usage
            model = llm_response.model or model

            data, parse_error = extract_json_object(raw_response)
            if parse_error:
                status = ProcessStatus.INVALID
                error = parse_error
                result_dict = fallback_result(scenario.key, "invalid_json")
            else:
                result, validation_errors = validate_result(
                    data, scenario.result_model
                )
                if validation_errors:
                    status = ProcessStatus.INVALID
                    error = "JSON validation failed: " + "; ".join(
                        validation_errors
                    )
                    result_dict = fallback_result(
                        scenario.key, "validation_error"
                    )
                else:
                    result, status, _reasons = apply_qc(result, scenario)
                    if scenario.postprocess is not None:
                        result = scenario.postprocess(result)
                    result_dict = result.model_dump(mode="json")
        except LLMError as exc:
            status = ProcessStatus.ERROR
            error = str(exc)
            result_dict = fallback_result(scenario.key, "llm_error")
        except Exception as exc:  # defensive boundary for the API
            logger.exception(
                "Unexpected error while processing request %s", request_id
            )
            status = ProcessStatus.ERROR
            error = f"Unexpected error: {type(exc).__name__}"
            result_dict = fallback_result(scenario.key, "internal_error")

        latency_ms = int((time.perf_counter() - started) * 1000)

        if result_dict is None:
            status = ProcessStatus.ERROR
            error = error or "Не удалось сформировать результат"
            result_dict = fallback_result(scenario.key, "internal_error")

        if error:
            error = error[:2000]

        stored_result = result_dict
        response_result = result_dict
        stored_metadata = metadata
        pii_stats: dict[str, int] = {}
        if session is not None:
            stored_result = session.mask_value(result_dict)
            response_result = session.restore_value(stored_result)
            if raw_response is not None:
                raw_response = session.anonymize(raw_response).text
            if error:
                error = session.anonymize(error).text
            stored_metadata = session.mask_value(metadata)
            pii_stats = session.stats()
            if session.mapping:
                self.vault.put(
                    request_id,
                    session.mapping,
                    session.kinds,
                    ttl_seconds=self.settings.pii_vault_ttl_seconds,
                )

        log = {
            "id": request_id,
            "scenario": scenario.key,
            "source": source,
            "input_text": llm_text,
            "input_hash": input_hash,
            "status": status,
            "raw_response": raw_response,
            "error": error,
            "model": model,
            "temperature": self.settings.aitunnel_temperature,
            "latency_ms": latency_ms,
            "usage": usage,
            "metadata": stored_metadata,
            "created_at": created_at,
        }
        self.db.save(log, stored_result)

        if (
            self.outbox is not None
            and session is not None
            and status in {ProcessStatus.PROCESSED, ProcessStatus.ESCALATED}
        ):
            self.outbox.enqueue(
                request_id,
                self._crm_payload(request_id, stored_result, status),
            )

        logger.info(
            "request_id=%s scenario=%s status=%s latency_ms=%s",
            request_id,
            scenario.key.value,
            status.value,
            latency_ms,
        )

        return ProcessResponse(
            request_id=request_id,
            scenario=scenario.key.value,
            status=status,
            result=response_result,
            meta=ProcessMeta(
                model=model,
                temperature=self.settings.aitunnel_temperature,
                latency_ms=latency_ms,
                created_at=created_at,
                usage=usage,
                pii_masked=session is not None,
                pii_entities=pii_stats,
            ),
            error=error,
        )

    @staticmethod
    def _crm_payload(
        request_id: str,
        result: dict[str, Any],
        status: ProcessStatus,
    ) -> dict[str, Any]:
        fields = result.get("fields")
        fields = fields if isinstance(fields, dict) else {}
        allowed = {
            "client_name",
            "contact_name",
            "contact",
            "phone",
            "email",
            "company",
            "organization",
        }
        client_fields = {
            key: value for key, value in fields.items() if key in allowed
        }
        call_score = result.get("qa_score")
        if call_score is None:
            call_score = result.get("score")
        return {
            "request_id": request_id,
            "status": status.value,
            "call_score": call_score,
            "checklist_results": result.get("qa_findings") or [],
            "summary": result.get("summary"),
            "next_action": result.get("next_action"),
            "escalation_flag": bool(result.get("escalate")),
            "client_fields": client_fields,
        }

    def get_pii(self, request_id: str):
        return self.vault.get(request_id)

    # Read-side helpers keep the API layer free of SQL details.

    def list_results(
        self,
        scenario: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.db.list_results(
            scenario=scenario,
            status=status,
            limit=limit,
            offset=offset,
        )

    def get_result(self, request_id: str) -> dict[str, Any] | None:
        return self.db.get_result(request_id)

    def get_audit(
        self,
        request_id: str,
        include_raw: bool | None = None,
    ) -> dict[str, Any] | None:
        if include_raw is None:
            include_raw = self.settings.debug
        return self.db.get_audit(request_id, include_raw=include_raw)

    def stats(self) -> dict[str, Any]:
        return self.db.stats()

    def export_results(self) -> list[dict[str, Any]]:
        return self.db.export_results()

    def export_audit(self) -> list[dict[str, Any]]:
        return self.db.export_audit()
