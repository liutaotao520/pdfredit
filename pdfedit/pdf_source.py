"""PDF input, bounded previews and native page composition.

All PDFium calls (including handle cleanup) share one lock: PDFium is not
thread safe, while import and preview jobs may run on different Qt workers.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import copy
from io import BytesIO
import math
from pathlib import Path
import threading

import pypdfium2 as pdfium
from pypdf import PdfReader, Transformation
from pypdf.generic import RectangleObject

from .models import Page

PDFIUM_LOCK = threading.RLock()
MAX_PDF_PAGES = 2000


def open_reader(path):
    reader = None
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("此 PDF 需要打开密码，请先在 PDF 阅读器中解密并另存副本，再添加。")
        count = len(reader.pages)
        if not count:
            raise ValueError("此 PDF 没有可导入的页面。")
        if count > MAX_PDF_PAGES:
            raise ValueError("单个 PDF 超过 2000 页，请先拆分。")
        return reader
    except Exception as exc:
        if reader is not None:
            reader.close()
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"无法读取 PDF，文件可能损坏或加密方式不受支持：{exc}") from exc


@contextmanager
def _document(path):
    # Caller holds PDFIUM_LOCK until the document and all its children close.
    try:
        doc = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        if exc.err_code == pdfium.raw.FPDF_ERR_PASSWORD:
            raise ValueError("此 PDF 需要打开密码，请先解密并另存副本，再添加。") from exc
        raise ValueError(f"无法渲染 PDF，文件可能损坏：{exc}") from exc
    try:
        doc.init_forms()
        yield doc
    finally:
        doc.close()


def visible_box(source):
    media, crop = source.mediabox, source.cropbox
    values = (max(float(media.left), float(crop.left)),
              max(float(media.bottom), float(crop.bottom)),
              min(float(media.right), float(crop.right)),
              min(float(media.top), float(crop.top)))
    box = RectangleObject(values)
    if not all(math.isfinite(v) for v in values) or box.width <= 0 or box.height <= 0:
        raise ValueError("PDF 页面尺寸或裁切区域无效。")
    return box


def dimensions(source):
    box = visible_box(source)
    unit = float(source.user_unit)
    if not math.isfinite(unit) or unit <= 0 or source.rotation % 90:
        raise ValueError("PDF 页面的单位或旋转角度无效。")
    size = (float(box.width) * unit, float(box.height) * unit)
    return size[::-1] if source.rotation % 180 else size


def _render(page, max_side):
    width, height = page.get_size()
    if min(width, height) <= 0 or not all(math.isfinite(v) for v in (width, height)):
        raise ValueError("PDF 页面尺寸无效。")
    scale = max_side / max(width, height)
    bitmap = page.render(scale=scale, draw_annots=True)
    try:
        # Copy before releasing PDFium's native bitmap buffer.
        return bitmap.to_pil().convert("RGBA").copy()
    finally:
        bitmap.close()


def render_pdf(path, index=0, max_side=1800):
    with PDFIUM_LOCK, _document(path) as document:
        if not 0 <= index < len(document):
            raise ValueError("原 PDF 页数已改变，请重新添加文件。")
        page = document[index]
        try:
            return _render(page, min(max_side or 1800, 4096))
        finally:
            page.close()


def inspect_pdf(path, cancelled=lambda: False):
    from .imaging import png_bytes
    reader = open_reader(path)
    try:
        result = []
        with PDFIUM_LOCK, _document(path) as document:
            if len(document) != len(reader.pages):
                raise ValueError("PDF 页目录不完整，请修复后重新添加。")
            for index, source in enumerate(reader.pages):
                if cancelled():
                    break
                width, height = dimensions(source)
                page = document[index]
                try:
                    thumbnail = _render(page, 190)
                    thumbnail.thumbnail((190, 150))
                finally:
                    page.close()
                note = "PDF · 保留文字与矢量"
                if source.get("/Annots"):
                    note += " · 批注/表单转为固定内容"
                result.append((Page(str(path), index, width, height, note=note), png_bytes(thumbnail)))
        return result
    finally:
        reader.close()


def reader_for_export(path, indices, cancelled=lambda: False):
    """Flatten visible annotation/form appearances, retaining native page content.

The output is a static merged document, not an interactive form or a copy of
document-level actions, signatures, attachments or bookmarks.
"""
    reader = open_reader(path)
    try:
        if any(index < 0 or index >= len(reader.pages) for index in indices):
            raise ValueError("原 PDF 页数已改变，请重新添加文件。")
        annotated = [i for i in sorted(set(indices)) if reader.pages[i].get("/Annots")]
        if not annotated:
            return reader
        stream = BytesIO()
        with PDFIUM_LOCK, _document(path) as doc:
            for index in annotated:
                if cancelled():
                    from .engine import ExportCancelled
                    raise ExportCancelled("已取消导出，原文件未改动。")
                page = doc[index]
                try:
                    result = pdfium.raw.FPDFPage_Flatten(page, pdfium.raw.FLAT_NORMALDISPLAY)
                    if result == pdfium.raw.FLATTEN_FAIL:
                        raise ValueError(f"PDF 第 {index + 1} 页的批注或表单无法合并，请先另存为普通 PDF。")
                finally:
                    page.close()
            doc.save(stream)
        stream.seek(0)
        flattened = open_reader(stream)
        reader.close()
        return flattened
    except Exception:
        reader.close()
        raise


def merge_native(destination, source, page, rect, paper_height):
    """Map a PDF's visible box to the same top-left rectangle as image preview."""
    source = copy(source)  # Do not mutate the cached source when a page is reused.
    box = visible_box(source)
    source.cropbox = box
    source.pop("/Annots", None)  # Visible appearances were flattened above.
    rotation = (source.rotation + page.rotation) % 360
    transform = Transformation().translate(-float(box.left), -float(box.bottom)).rotate(-rotation)
    corners = [transform.apply_on(point) for point in
               (box.lower_left, box.lower_right, box.upper_left, box.upper_right)]
    left, bottom = min(p[0] for p in corners), min(p[1] for p in corners)
    sw = max(p[0] for p in corners) - left
    sh = max(p[1] for p in corners) - bottom
    x, y, width, height = rect
    transform = transform.translate(-left, -bottom).scale(width / sw, height / sh)
    transform = transform.translate(x, paper_height - y - height)
    destination.merge_transformed_page(source, transform, over=False)
