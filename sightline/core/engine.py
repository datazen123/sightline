"""Run one audit end to end: plugin -> findings -> ledger -> store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from agents.llm import reset_ledger
from sightline.core import store
from sightline.core.plugins import get_plugin
from sightline.core.schema import AuditResult


def run_audit(corpus: str, files: list[Path] | None = None, persist: bool = True) -> tuple[AuditResult, object]:
    plugin = get_plugin(corpus)
    files = files or sorted(p for p in plugin.config.data_dir.iterdir()
                            if p.suffix.lower() in plugin.config.accepts)
    led = reset_ledger()
    findings = plugin.audit(files)
    result = AuditResult(
        run_id=datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6],
        corpus=corpus, findings=findings, stats=plugin.stats,
        rejected_mappings=plugin.rejected_mappings, llm_usage=led.summary_rows(), llm_cost_usd=led.total_cost,
    )
    if persist:
        store.save(result, datetime.now(UTC).isoformat(timespec="seconds"),
                   getattr(plugin, "lines", None))
    return result, plugin
