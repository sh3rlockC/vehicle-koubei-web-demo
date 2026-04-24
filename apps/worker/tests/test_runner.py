from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker_app.runner import _collect_existing_artifacts
from worker_app.stages import StageCommand


def test_collect_existing_artifacts_does_not_publish_font_path(tmp_path: Path) -> None:
    terms = tmp_path / "terms.xlsx"
    image = tmp_path / "positive.png"
    font = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    terms.write_text("terms", encoding="utf-8")
    image.write_text("image", encoding="utf-8")
    command = StageCommand(
        name="rendering_wordcloud",
        dependency_name="koubei-wordcloud",
        command=["python", "wordcloud.py"],
        cwd=tmp_path,
        expected_artifacts=(str(terms),),
        optional_artifacts=(str(image),),
        parse_json_stdout=True,
    )

    artifacts, _metadata = _collect_existing_artifacts(
        command,
        json.dumps(
            {
                "excel_path": str(terms),
                "image_paths": [str(image)],
                "font_path": str(font),
            }
        ),
    )

    assert str(terms) in artifacts
    assert str(image) in artifacts
    assert str(font) not in artifacts
