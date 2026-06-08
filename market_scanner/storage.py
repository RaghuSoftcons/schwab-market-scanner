from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nt_schwab_bridge.models import OptionProposal

from market_scanner.models import ScanResult


class ScannerStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.latest_path = self.root / "latest_scan.json"
        self.history_path = self.root / "scan_history.jsonl"
        self.order_audit_path = self.root / "order_audit.jsonl"

    def save_scan(self, result: ScanResult) -> None:
        payload = result.model_dump(mode="json")
        self.latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def load_latest_scan(self) -> ScanResult | None:
        if not self.latest_path.exists():
            return None
        payload = json.loads(self.latest_path.read_text(encoding="utf-8"))
        return ScanResult.model_validate(payload)

    def find_proposal(self, proposal_id: str) -> OptionProposal | None:
        latest = self.load_latest_scan()
        if latest is None:
            return None
        for candidate in latest.top_candidates:
            for proposal in candidate.proposals:
                if proposal.id == proposal_id:
                    return proposal
        return None

    def append_order_event(self, event: dict[str, Any]) -> None:
        payload = {
            "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            **event,
        }
        with self.order_audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")

    def list_order_events(self) -> list[dict[str, Any]]:
        if not self.order_audit_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.order_audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events
