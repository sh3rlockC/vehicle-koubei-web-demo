from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.services.dependencies import discover_manifest_path, load_dependency_map
from app.services.tool_runner import ToolRunner


class VehicleResolver:
    def __init__(
        self,
        manifest_path: Path | None = None,
        tool_runner: ToolRunner | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.manifest_path = manifest_path or discover_manifest_path(
            source_path=Path(__file__),
            workspace_root=self.settings.workspace_root_path,
        )
        self.tool_runner = tool_runner or ToolRunner()

    def _load_dependency(self, name: str) -> dict[str, Any]:
        dependency_map = load_dependency_map(self.manifest_path, self.settings.workspace_root_path)
        if name not in dependency_map:
            raise KeyError(f"dependency not found: {name}")
        return dependency_map[name]

    def _normalize_candidate(self, candidate: dict[str, Any] | None, query: str) -> dict[str, Any] | None:
        if not candidate:
            return None
        title = candidate.get("title")
        if not title:
            evidence_text = str(candidate.get("evidence_text") or "").strip()
            title = evidence_text.splitlines()[0].strip() if evidence_text else query
        return {
            "series_id": str(candidate.get("id")) if candidate.get("id") is not None else None,
            "url": candidate.get("url"),
            "title": title,
            "source": candidate.get("source"),
            "evidence_url": candidate.get("evidence_url"),
            "kind": candidate.get("kind"),
            "note": candidate.get("note"),
        }

    def _normalize_platform(self, platform_payload: dict[str, Any] | None, query: str) -> dict[str, Any]:
        platform_payload = platform_payload or {}
        candidates = [
            normalized
            for candidate in platform_payload.get("candidates", [])
            if (normalized := self._normalize_candidate(candidate, query)) is not None
        ]
        best = self._normalize_candidate(platform_payload.get("best"), query)
        return {
            "best": best,
            "candidates": candidates,
        }

    def resolve(self, query: str) -> dict[str, Any]:
        dependency = self._load_dependency("vehicle-id-finder")
        payload = self.tool_runner.run_json(
            [sys.executable, dependency["entrypoint"], query, "--json"],
            cwd=dependency["path"],
            timeout=90,
        )
        return {
            "query": payload.get("query", query),
            "autohome": self._normalize_platform(payload.get("autohome"), query),
            "dongchedi": self._normalize_platform(payload.get("dongchedi"), query),
        }
