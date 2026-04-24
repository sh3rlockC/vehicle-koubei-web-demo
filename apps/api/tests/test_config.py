from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import discover_workspace_root


def test_discover_workspace_root_falls_back_for_shallow_container_path(tmp_path: Path) -> None:
    workspace_root = discover_workspace_root(
        Path("/app/app/config.py"),
        mounted_workspace=tmp_path / "missing-workspace",
        fallback_cwd=tmp_path,
    )

    assert workspace_root == tmp_path.resolve()


def test_discover_workspace_root_prefers_workspace_mount(tmp_path: Path) -> None:
    mounted_workspace = tmp_path / "workspace"
    mounted_workspace.mkdir()

    workspace_root = discover_workspace_root(
        Path("/app/app/config.py"),
        mounted_workspace=mounted_workspace,
        fallback_cwd=tmp_path / "fallback",
    )

    assert workspace_root == mounted_workspace.resolve()
