from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
import uuid


@dataclass
class Page:
    path: str
    frame: int = 0
    width: float = 0
    height: float = 0
    rotation: int = 0
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    note: str = ""
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def is_pdf(self) -> bool:
        return Path(self.path).suffix.lower() == ".pdf"

    @property
    def label(self) -> str:
        suffix = f" · 第 {self.frame + 1} 页" if self.is_pdf else (f" · 第 {self.frame + 1} 帧" if self.frame else "")
        return Path(self.path).name + suffix

    @property
    def rotated_size(self):
        return (self.height, self.width) if self.rotation % 180 else (self.width, self.height)


@dataclass
class Layout:
    paper: str = "A4"
    orientation: str = "auto"
    margin_mm: float = 12.0
    quality: str = "original"


@dataclass
class Watermark:
    kind: str = "none"
    text: str = "仅供参考"
    image_path: str = ""
    font_family: str = "Microsoft YaHei"
    font_size: int = 36
    color: str = "#526580"
    opacity: float = 0.25
    angle: int = 30
    position: str = "center"
    scale: float = 0.28
    tiled: bool = False
    pages: str = ""
    density: int = 3


def natural_key(value):
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", str(value))]


def page_selection(text: str, count: int) -> set[int]:
    """Return 1-based page numbers; reject typos instead of silently skipping pages."""
    if not text.strip():
        return set(range(1, count + 1))
    result = set()
    for part in text.replace("，", ",").split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if not match:
            raise ValueError("水印页码请填写 1,3-5 这样的格式；留空表示全部页。")
        first, last = int(match[1]), int(match[2] or match[1])
        if first < 1 or last < first or last > count:
            raise ValueError(f"水印页码应在 1 至 {count} 之间，且范围从小到大。")
        result.update(range(first, last + 1))
    return result


def project_data(pages, layout, watermark):
    return {"version": 1, "pages": [asdict(x) for x in pages],
            "layout": asdict(layout), "watermark": asdict(watermark)}
