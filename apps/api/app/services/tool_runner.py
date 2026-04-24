from __future__ import annotations

import json
import subprocess
from pathlib import Path


class ToolRunner:
    def run_json(self, cmd: list[str], *, cwd: str | Path | None = None, timeout: int = 60) -> dict:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"command failed: {cmd!r}")
        stdout = result.stdout.strip()
        if not stdout:
            raise RuntimeError("command produced empty JSON output")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON output: {stdout[:200]}") from exc
