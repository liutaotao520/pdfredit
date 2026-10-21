"""Versioned project loading shared by GUI and the standalone exporter."""
import json
import math
from pathlib import Path

from .engine import PAPERS
from .models import Page, Layout, Watermark, page_selection
from .text_editing import validate_text_state, check_source


def read_project(path):
    path = Path(path)
    if path.stat().st_size > 80_000_000:
        raise ValueError("编辑方案过大，请拆分为较小的方案。")
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') not in {1, 2}:
        raise ValueError("不支持的方案版本。")
    pages = [Page(**item) for item in data['pages']]
    layout, watermark = Layout(**data['layout']), Watermark(**data['watermark'])
    if layout.paper not in {*PAPERS, 'original'} or layout.orientation not in {'auto','portrait','landscape'} or layout.quality not in {'original','high','compact'}:
        raise ValueError("方案包含无效的页面设置。")
    if not 0 <= layout.margin_mm <= 100 or not math.isfinite(layout.margin_mm):
        raise ValueError("方案中的页面留白无效。")
    if watermark.kind not in {'none','text','image'} or not 0 < watermark.opacity <= 1 or not 8 <= watermark.font_size <= 160 or not .05 <= watermark.scale <= .9:
        raise ValueError("方案包含无效的水印设置。")
    if type(watermark.density) is not int or not 1 <= watermark.density <= 10:
        raise ValueError("方案中的平铺密度应为 1 至 10 的整数。")
    page_selection(watermark.pages, len(pages))
    ids = set()
    for page in pages:
        if not Path(page.path).is_file():
            raise ValueError("方案中的源文件已移动或不存在：" + page.path)
        if page.uid in ids:
            raise ValueError("方案包含重复的页面标识。")
        ids.add(page.uid)
        if type(page.frame) is not int or page.frame < 0 or not all(math.isfinite(v) and v > 0 for v in (page.width,page.height)):
            raise ValueError("方案包含无效的页面尺寸或页码。")
        if not .05 <= page.zoom <= 2.5 or not -1 <= page.offset_x <= 1 or not -1 <= page.offset_y <= 1 or page.rotation not in {0,90,180,270}:
            raise ValueError("方案包含无效的内容位置。")
        validate_text_state(page)
        check_source(page)
    return pages, layout, watermark
