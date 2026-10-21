from __future__ import annotations

from contextlib import ExitStack
from io import BytesIO
import os
from pathlib import Path
import uuid

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader

from .imaging import load_image, watermark_stamp
from .pdf_source import reader_for_export, merge_native
from . import __version__
from .models import Layout, Page, Watermark, page_selection

MM = 72 / 25.4
PAPERS = {"A3": (297 * MM, 420 * MM), "A4": (210 * MM, 297 * MM),
          "A5": (148 * MM, 210 * MM), "Letter": (612, 792)}


class ExportCancelled(Exception):
    pass


def geometry(page: Page, layout: Layout):
    iw, ih = page.rotated_size
    if min(iw, ih) <= 0:
        raise ValueError(f"无效页面尺寸：{page.label}")
    if layout.paper == "original":
        unit = 1.0 if page.is_pdf else 72 / 150
        pw, ph = iw * unit, ih * unit
        # PDF pages stay within widely supported physical dimensions.
        factor = min(1.0, 14400 / max(pw, ph))
        pw, ph = max(10, pw * factor), max(10, ph * factor)
        margin = 0.0
    else:
        pw, ph = PAPERS[layout.paper]
        landscape = layout.orientation == "landscape" or (layout.orientation == "auto" and iw > ih)
        if landscape:
            pw, ph = ph, pw
        margin = min(layout.margin_mm * MM, min(pw, ph) / 3)
    ratio = min((pw - 2 * margin) / iw, (ph - 2 * margin) / ih) * page.zoom
    w, h = iw * ratio, ih * ratio
    x = (pw - w) / 2 + page.offset_x * pw
    y = (ph - h) / 2 + page.offset_y * ph
    return pw, ph, (x, y, w, h)


def stamp_positions(wm: Watermark, pw, ph, sw, sh):
    if wm.tiled:
        if type(wm.density) is not int or not 1 <= wm.density <= 10:
            raise ValueError("平铺密度应为 1 至 10 的整数。")
        # Level 3 preserves existing projects; higher levels reduce spacing on
        # both axes without changing the stamp's size, opacity or rotation.
        spacing = 3 / wm.density
        dx, dy = max(sw + 42, pw / 3) * spacing, max(sh + 42, ph / 5) * spacing
        y, row = -sh / 3, 0
        while y < ph:
            x = -sw / 3 - (dx / 2 if row % 2 else 0)
            while x < pw:
                yield x, y
                x += dx
            y += dy
            row += 1
    else:
        gap = 18
        x = gap if "left" in wm.position else (pw - sw - gap if "right" in wm.position else (pw - sw) / 2)
        y = gap if "top" in wm.position else (ph - sh - gap if "bottom" in wm.position else (ph - sh) / 2)
        yield x, y


def render_preview(page: Page, layout: Layout, watermark: Watermark, number: int, count: int, max_side=1100):
    pw, ph, rect = geometry(page, layout)
    scale = max_side / max(pw, ph)
    canvas = Image.new("RGBA", (max(1, round(pw * scale)), max(1, round(ph * scale))), "white")
    from .text_editing import has_text_output, render_edited
    image = render_edited(page, 1800) if has_text_output(page) else load_image(page.path, page.frame, max_side=1800)
    if page.rotation:
        image = image.rotate(-page.rotation, expand=True)
    x, y, w, h = rect
    image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
    canvas.alpha_composite(image, (round(x * scale), round(y * scale)))
    if watermark.kind != "none" and number in page_selection(watermark.pages, count):
        stamp = watermark_stamp(watermark, pw, scale)
        for x, y in stamp_positions(watermark, pw, ph, stamp.width / scale, stamp.height / scale):
            canvas.alpha_composite(stamp, (round(x * scale), round(y * scale)))
    return canvas.convert("RGB")


def export_pdf(pages: list[Page], layout: Layout, watermark: Watermark, output: str,
               cancelled=lambda: False, progress=lambda current, total: None, overwrite=False):
    from .text_editing import has_text_output, edited_source_pdf
    if not pages:
        raise ValueError("请先添加图片或 PDF。")
    target = Path(output).expanduser().resolve()
    if target.suffix.lower() != ".pdf":
        raise ValueError("输出文件扩展名必须是 .pdf。")
    protected = {Path(p.path).resolve() for p in pages}
    if watermark.image_path:
        protected.add(Path(watermark.image_path).resolve())
    if target in protected:
        raise ValueError("不能覆盖原始图片、PDF 或水印图片。")
    if not target.parent.is_dir():
        raise ValueError("保存目录不存在。")
    if target.exists() and not overwrite:
        raise FileExistsError("目标 PDF 已存在，请更换文件名。")
    selected = page_selection(watermark.pages, len(pages)) if watermark.kind != "none" else set()
    # Build in memory so failed or cancelled jobs never leave a partial output on disk.
    stream = BytesIO()
    pdf = Canvas(stream, pageCompression=1)
    pdf.setTitle(target.stem)
    pdf.setAuthor("合页 · PDFedit")
    pdf.setCreator("PDFedit " + __version__)
    for index, page in enumerate(pages, 1):
        if cancelled():
            raise ExportCancelled("已取消导出，原文件未改动。")
        pw, ph, (x, y, w, h) = geometry(page, layout)
        pdf.setPageSize((pw, ph))
        if not page.is_pdf and not has_text_output(page):
            image = load_image(page.path, page.frame)
            if page.rotation:
                image = image.rotate(-page.rotation, expand=True)
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            if layout.quality != "original":
                dpi, quality = (220, 92) if layout.quality == "high" else (144, 82)
                background.thumbnail((max(1, round(w * dpi / 72)), max(1, round(h * dpi / 72))), Image.Resampling.LANCZOS)
                encoded = BytesIO()
                background.save(encoded, "JPEG", quality=quality, subsampling=0)
                encoded.seek(0)
                reader = ImageReader(encoded)
            else:
                reader = ImageReader(background)
            pdf.drawImage(reader, x, ph - y - h, width=w, height=h)
        if index in selected:
            scale = 3.0
            stamp = watermark_stamp(watermark, pw, scale)
            sw, sh = stamp.width / scale, stamp.height / scale
            reader = ImageReader(stamp)
            for sx, sy in stamp_positions(watermark, pw, ph, sw, sh):
                pdf.drawImage(reader, sx, ph - sy - sh, width=sw, height=sh, mask="auto")
        pdf.showPage()
    if cancelled():
        raise ExportCancelled("已取消导出，原文件未改动。")
    pdf.save()
    stream.seek(0)
    with ExitStack() as resources:
        readers = {}
        for page in pages:
            if cancelled():
                raise ExportCancelled("已取消导出，原文件未改动。")
            if page.is_pdf and not has_text_output(page) and page.path not in readers:
                indices = [p.frame for p in pages if p.path == page.path and not has_text_output(p)]
                reader = reader_for_export(page.path, indices, cancelled)
                resources.callback(reader.close)
                readers[page.path] = reader
        overlay = PdfReader(stream)
        resources.callback(overlay.close)
        writer = PdfWriter()
        resources.callback(writer.close)
        # Merging content does not automatically upgrade the file header as
        # adding a source page would. Preserve features from newer input PDFs.
        writer.pdf_header = max(["%PDF-1.7", *(reader.pdf_header for reader in readers.values())])
        writer.add_metadata({"/Title": target.stem, "/Author": "合页 · PDFedit", "/Creator": "PDFedit " + __version__})
        for index, page in enumerate(pages, 1):
            if cancelled():
                raise ExportCancelled("已取消导出，原文件未改动。")
            destination = writer.add_page(overlay.pages[index - 1])
            if has_text_output(page):
                from dataclasses import replace
                edited = PdfReader(BytesIO(edited_source_pdf(page)))
                try:
                    pw, ph, rect = geometry(page, layout)
                    # The edited intermediate is normalized to the source's visible page.
                    merge_native(destination, edited.pages[0], replace(page, frame=0), rect, ph)
                finally:
                    edited.close()
            elif page.is_pdf:
                pw, ph, rect = geometry(page, layout)
                merge_native(destination, readers[page.path].pages[page.frame], page, rect, ph)
            progress(index, len(pages))
        final = BytesIO()
        writer.write(final)
        data = final.getvalue()
    if cancelled():
        raise ExportCancelled("已取消导出，原文件未改动。")
    # A unique adjacent file plus atomic replacement protects any existing PDF.
    pending = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.pending")
    try:
        with pending.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(pending, target)
        else:
            os.rename(pending, target)  # Windows fails if a competing writer created target.
    except Exception as exc:
        # Never permanently delete an incomplete file; report its exact recovery path.
        if pending.exists():
            raise OSError(f"无法完成保存：{exc}\n恢复文件保留于：{pending}") from exc
        raise
    return {"path": str(target), "pages": len(pages), "bytes": len(data)}
