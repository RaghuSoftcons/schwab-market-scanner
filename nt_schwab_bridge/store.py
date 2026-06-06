"""Signal store for Phase 1 signal intake."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from nt_schwab_bridge.models import OptionProposalResult, SignalDecision, SignalPayload, SignalRecord


@dataclass(frozen=True)
class StoreResult:
    record: SignalRecord
    duplicate: bool


class InMemorySignalStore:
    """Small bounded store suitable for Phase 1 dry-run testing."""

    def __init__(
        self,
        max_records: int = 500,
        duplicate_window_seconds: int = 30,
        audit_log_path: str | Path | None = None,
        proposal_log_path: str | Path | None = None,
    ) -> None:
        self.max_records = max_records
        self.duplicate_window_seconds = duplicate_window_seconds
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None
        self.proposal_log_path = Path(proposal_log_path) if proposal_log_path else None
        self._records: deque[SignalRecord] = deque()
        self._by_id: dict[str, SignalRecord] = {}
        self._fingerprints: dict[str, tuple[str, datetime]] = {}
        self._proposals_by_signal_id: dict[str, OptionProposalResult] = {}
        self._lock = Lock()
        self._load_audit_log()
        self._load_proposal_log()

    def add(
        self,
        payload: SignalPayload,
        decision: SignalDecision | None = None,
        execution_mode: str = "dry_run",
    ) -> StoreResult:
        now = datetime.now(timezone.utc)
        signal_id = payload.signal_id or self._new_id()
        fingerprint = payload.signal_id or payload.duplicate_fingerprint()

        with self._lock:
            duplicate = self._find_duplicate(payload=payload, fingerprint=fingerprint, now=now)
            if duplicate is not None:
                duplicate_record = SignalRecord(
                    id=duplicate.id,
                    payload=payload,
                    received_at=now,
                    status="duplicate",
                    review_status="duplicate",
                    duplicate_of=duplicate.id,
                    proposal_count=duplicate.proposal_count,
                    execution_mode=duplicate.execution_mode,
                    decision=duplicate.decision,
                )
                return StoreResult(record=duplicate_record, duplicate=True)

            review_status = "blocked" if decision is not None and decision.status == "blocked" else "pending_phase_1"
            record = SignalRecord(
                id=signal_id,
                payload=payload,
                received_at=now,
                review_status=review_status,
                execution_mode=execution_mode,
                decision=decision,
            )
            self._insert_record(record, fingerprint=fingerprint, seen_at=now)
            self._append_audit_record(record)
            return StoreResult(record=record, duplicate=False)

    def list_recent(self, limit: int = 100) -> list[SignalRecord]:
        with self._lock:
            return list(self._records)[: max(limit, 0)]

    def get(self, signal_id: str) -> SignalRecord | None:
        with self._lock:
            return self._by_id.get(signal_id)

    def mark_reviewed(self, signal_id: str) -> SignalRecord | None:
        with self._lock:
            record = self._by_id.get(signal_id)
            if record is None:
                return None
            record.review_status = "reviewed"
            self._append_audit_record(record)
            return record

    def save_proposals(
        self,
        signal_id: str,
        result: OptionProposalResult,
        *,
        preserve_existing_successful: bool = False,
    ) -> bool:
        with self._lock:
            record = self._by_id.get(signal_id)
            if record is None:
                return False
            existing = self._proposals_by_signal_id.get(signal_id)
            preserve_existing = (
                preserve_existing_successful
                and not result.proposals
                and existing is not None
                and bool(existing.proposals)
            )
            if preserve_existing:
                record.proposal_count = len(existing.proposals)
            else:
                self._proposals_by_signal_id[signal_id] = result
                record.proposal_count = len(result.proposals)
            self._append_audit_record(record)
            self._append_proposal_result(result)
            return True

    def get_proposals(self, signal_id: str) -> OptionProposalResult | None:
        with self._lock:
            return self._proposals_by_signal_id.get(signal_id)

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def clear(self, *, clear_audit_log: bool = True) -> int:
        with self._lock:
            cleared_count = len(self._records)
            self._records.clear()
            self._by_id.clear()
            self._fingerprints.clear()
            self._proposals_by_signal_id.clear()
            if clear_audit_log and self.audit_log_path is not None:
                self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
                self.audit_log_path.write_text("", encoding="utf-8")
            if clear_audit_log and self.proposal_log_path is not None:
                self.proposal_log_path.parent.mkdir(parents=True, exist_ok=True)
                self.proposal_log_path.write_text("", encoding="utf-8")
            return cleared_count

    def _find_duplicate(
        self,
        payload: SignalPayload,
        fingerprint: str,
        now: datetime,
    ) -> SignalRecord | None:
        if payload.signal_id:
            existing_by_id = self._by_id.get(payload.signal_id)
            if existing_by_id is not None:
                return existing_by_id

        existing = self._fingerprints.get(fingerprint)
        if existing is None:
            return None
        existing_id, seen_at = existing
        if payload.signal_id:
            return self._by_id.get(existing_id)
        if self.duplicate_window_seconds == 0:
            return self._by_id.get(existing_id)
        age_seconds = (now - seen_at).total_seconds()
        if age_seconds <= self.duplicate_window_seconds:
            return self._by_id.get(existing_id)
        self._fingerprints.pop(fingerprint, None)
        return None

    def _insert_record(
        self,
        record: SignalRecord,
        fingerprint: str | None = None,
        seen_at: datetime | None = None,
    ) -> None:
        self._records.appendleft(record)
        self._by_id[record.id] = record
        resolved_fingerprint = fingerprint or record.payload.signal_id or record.payload.duplicate_fingerprint()
        self._fingerprints[resolved_fingerprint] = (record.id, seen_at or record.received_at)
        self._trim()

    def _trim(self) -> None:
        while len(self._records) > self.max_records:
            removed = self._records.pop()
            self._by_id.pop(removed.id, None)
            self._proposals_by_signal_id.pop(removed.id, None)

    def _new_id(self) -> str:
        return f"sig_{uuid4().hex[:12]}"

    def _load_audit_log(self) -> None:
        if self.audit_log_path is None or not self.audit_log_path.exists():
            return

        loaded: list[SignalRecord] = []
        with self.audit_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                payload = line.strip()
                if not payload:
                    continue
                try:
                    loaded.append(SignalRecord.model_validate_json(payload))
                except ValueError:
                    continue

        latest_by_id: dict[str, SignalRecord] = {}
        for record in loaded:
            if record.status == "duplicate":
                continue
            latest_by_id[record.id] = record

        for record in list(latest_by_id.values())[-self.max_records :]:
            self._insert_record(record)

    def _load_proposal_log(self) -> None:
        if self.proposal_log_path is None or not self.proposal_log_path.exists():
            return

        latest_by_signal_id: dict[str, OptionProposalResult] = {}
        with self.proposal_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                payload = line.strip()
                if not payload:
                    continue
                try:
                    result = OptionProposalResult.model_validate_json(payload)
                except ValueError:
                    continue
                existing = latest_by_signal_id.get(result.signal_id)
                if not result.proposals and existing is not None and existing.proposals:
                    continue
                latest_by_signal_id[result.signal_id] = result

        for signal_id, result in latest_by_signal_id.items():
            record = self._by_id.get(signal_id)
            if record is None:
                continue
            self._proposals_by_signal_id[signal_id] = result
            record.proposal_count = len(result.proposals)

    def _append_audit_record(self, record: SignalRecord) -> None:
        if self.audit_log_path is None:
            return

        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_log_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json())
            handle.write("\n")

    def _append_proposal_result(self, result: OptionProposalResult) -> None:
        if self.proposal_log_path is None:
            return

        self.proposal_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.proposal_log_path.open("a", encoding="utf-8") as handle:
            handle.write(result.model_dump_json())
            handle.write("\n")
