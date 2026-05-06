from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
from typing import Iterable, TypedDict

from PIL import Image, ImageDraw, ImageFont

KeywordRankItem = dict[str, int | str]


class ToneConfig(TypedDict):
    title: str
    filename: str
    accent: tuple[int, int, int]
    bar: tuple[int, int, int]
    bar_end: tuple[int, int, int]

IMAGE_WIDTH = 1200
IMAGE_HEIGHT = 760

TONE_CONFIG: dict[str, ToneConfig] = {
    "positive": {
        "title": "优点关键词出现次数排名",
        "filename": "keyword_rank_positive.png",
        "accent": (103, 232, 166),
        "bar": (74, 222, 128),
        "bar_end": (22, 163, 74),
    },
    "negative": {
        "title": "槽点关键词出现次数排名",
        "filename": "keyword_rank_negative.png",
        "accent": (248, 113, 113),
        "bar": (248, 113, 113),
        "bar_end": (220, 38, 38),
    },
    "combined": {
        "title": "全部关键词出现次数排名",
        "filename": "keyword_rank_combined.png",
        "accent": (167, 228, 255),
        "bar": (125, 211, 252),
        "bar_end": (56, 189, 248),
    },
}


def _font_candidates() -> Iterable[Path]:
    env_path = os.getenv("KEYWORD_RANK_FONT_PATH")
    if env_path:
        yield Path(env_path).expanduser()

    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ):
        yield Path(path)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _font_candidates():
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text

    ellipsis = "..."
    trimmed = text
    while trimmed and _text_width(draw, f"{trimmed}{ellipsis}", font) > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}{ellipsis}" if trimmed else ellipsis


def _draw_gradient_bar(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    start: tuple[int, int, int],
    end: tuple[int, int, int],
) -> None:
    left, top, right, bottom = box
    width = max(1, right - left)
    for offset in range(width):
        ratio = offset / max(1, width - 1)
        color = tuple(int(start[index] + (end[index] - start[index]) * ratio) for index in range(3))
        draw.line((left + offset, top, left + offset, bottom), fill=color)


def render_keyword_rank_png(
    title: str,
    items: list[KeywordRankItem],
    *,
    accent: tuple[int, int, int],
    bar: tuple[int, int, int],
    bar_end: tuple[int, int, int],
) -> bytes:
    image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), (5, 13, 26))
    draw = ImageDraw.Draw(image)

    title_font = _load_font(46)
    label_font = _load_font(28)
    meta_font = _load_font(22)
    count_font = _load_font(24)

    draw.rectangle((0, 0, IMAGE_WIDTH, IMAGE_HEIGHT), fill=(5, 13, 26))
    draw.rounded_rectangle(
        (32, 32, IMAGE_WIDTH - 32, IMAGE_HEIGHT - 32),
        radius=28,
        fill=(10, 28, 47),
        outline=accent,
        width=2,
    )
    draw.text((72, 62), "WORD RANK", fill=accent, font=meta_font)
    draw.text((72, 96), title, fill=(244, 248, 255), font=title_font)
    draw.text((72, 158), "按关键词出现次数从高到低排序", fill=(178, 196, 224), font=meta_font)

    if not items:
        draw.text((72, 340), "暂无关键词数据", fill=(178, 196, 224), font=label_font)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    max_count = max((int(item["count"]) for item in items if int(item["count"]) > 0), default=1)
    top_items = items[:10]

    label_x = 118
    bar_x = 390
    bar_max_width = 590
    count_x = 1018
    row_top = 218
    row_gap = 48
    bar_height = 22

    for index, item in enumerate(top_items):
        y = row_top + index * row_gap
        term = str(item["term"])
        count = int(item["count"])
        bar_width = max(8, round((count / max_count) * bar_max_width))

        draw.text((72, y - 3), f"{index + 1:02d}", fill=(117, 139, 170), font=meta_font)
        draw.text(
            (label_x, y - 6),
            _fit_text(draw, term, label_font, bar_x - label_x - 28),
            fill=(230, 239, 255),
            font=label_font,
        )
        draw.rounded_rectangle(
            (bar_x, y + 5, bar_x + bar_max_width, y + 5 + bar_height),
            radius=bar_height // 2,
            fill=(22, 39, 62),
        )
        _draw_gradient_bar(
            draw,
            (bar_x, y + 5, bar_x + bar_width, y + 5 + bar_height),
            start=bar,
            end=bar_end,
        )
        draw.rounded_rectangle(
            (bar_x, y + 5, bar_x + bar_width, y + 5 + bar_height),
            radius=bar_height // 2,
            outline=bar_end,
            width=1,
        )
        draw.text((count_x, y - 3), str(count), fill=(244, 248, 255), font=count_font)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_keyword_rank_pngs(rankings: dict[str, list[KeywordRankItem]]) -> list[tuple[str, bytes]]:
    pngs: list[tuple[str, bytes]] = []
    for tone in ("positive", "negative", "combined"):
        config = TONE_CONFIG[tone]
        pngs.append(
            (
                config["filename"],
                render_keyword_rank_png(
                    config["title"],
                    rankings.get(tone, []),
                    accent=config["accent"],
                    bar=config["bar"],
                    bar_end=config["bar_end"],
                ),
            )
        )
    return pngs
