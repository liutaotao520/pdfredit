from __future__ import annotations

from io import BytesIO
from pathlib import Path
import warnings

from PIL import Image, ImageCms, ImageOps
from pillow_heif import register_heif_opener
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from .models import Page, Watermark

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 80_000_000
warnings.filterwarnings("error", category=Image.DecompressionBombWarning)

IMAGE_EXTENSIONS = tuple(sorted({".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".webp",
    ".bmp", ".dib", ".tif", ".tiff", ".gif", ".heic", ".heif", ".hif", ".avif",
    ".svg", ".ico", ".icns", ".tga", ".targa", ".pcx", ".ppm", ".pgm", ".pbm",
    ".pnm", ".dds", ".qoi", ".jp2", ".j2k", ".jpf", ".jpx", ".psd"}))
EXTENSIONS = tuple(sorted((*IMAGE_EXTENSIONS, ".pdf")))
IMAGE_FILTER = "图片 (" + " ".join("*" + x for x in IMAGE_EXTENSIONS) + ");;所有文件 (*)"
FILE_FILTER = "图片和 PDF (" + " ".join("*" + x for x in EXTENSIONS) + ");;PDF 文档 (*.pdf);;" + IMAGE_FILTER


def png_bytes(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def pil_from_qimage(image: QImage) -> Image.Image:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (image.width(), image.height()),
                           bytes(image.bits()), "raw", "RGBA", image.bytesPerLine()).copy()


def _svg(path: str, max_side: int | None = None):
    source = Path(path)
    if source.stat().st_size > 20_000_000:
        raise ValueError("SVG 文件超过 20 MB，请先简化图形。")
    data = source.read_bytes()
    if b"<!ENTITY" in data.upper() or b"<!DOCTYPE" in data.upper():
        raise ValueError("SVG 包含外部实体或文档声明，请另存为普通 SVG / PNG。")
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        raise ValueError("无法读取该 SVG。")
    size = renderer.defaultSize()
    width, height = size.width(), size.height()
    if min(width, height) <= 0:
        raise ValueError("SVG 缺少有效的画布尺寸。")
    ratio = min(1.0, (max_side or 4096) / max(width, height))
    image = QImage(max(1, round(width * ratio)), max(1, round(height * ratio)), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return pil_from_qimage(image), (width, height)


def load_image(path: str, frame: int = 0, max_side: int | None = None) -> Image.Image:
    if Path(path).suffix.lower() == ".pdf":
        from .pdf_source import render_pdf
        return render_pdf(path, frame, max_side)
    if Path(path).suffix.lower() == ".svg":
        return _svg(path, max_side)[0]
    with Image.open(path) as source:
        source.seek(frame)
        profile = source.info.get("icc_profile")
        image = ImageOps.exif_transpose(source).copy()
    if profile and image.mode in ("RGB", "RGBA", "CMYK", "LAB"):
        try:
            image = ImageCms.profileToProfile(image, BytesIO(profile), ImageCms.createProfile("sRGB"), outputMode="RGBA")
        except (OSError, ValueError, ImageCms.PyCMSError):
            pass
    if image.mode.startswith("I;16"):
        image = image.convert("I").point(lambda x: x / 256).convert("L")
    image = image.convert("RGBA")
    if max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return image


def inspect_image(path: str, cancelled=lambda: False):
    path = str(Path(path).resolve(strict=True))
    if Path(path).suffix.lower() == ".pdf":
        from .pdf_source import inspect_pdf
        return inspect_pdf(path, cancelled)
    if Path(path).suffix.lower() == ".svg":
        image, dimensions = _svg(path, 190)
        return [(Page(path, width=dimensions[0], height=dimensions[1], note="SVG 以高清位图导出"), png_bytes(image))]
    with Image.open(path) as source:
        count = getattr(source, "n_frames", 1)
        fmt = source.format
    # TIFF stacks represent document pages; animations use the first visible frame.
    frames = count if fmt == "TIFF" else 1
    if frames > 2000:
        raise ValueError("单个 TIFF 超过 2000 页，请先拆分。")
    result = []
    for frame in range(frames):
        if cancelled():
            break
        image = load_image(path, frame)
        width, height = image.size
        note = f"TIFF 第 {frame + 1}/{count} 页" if frames > 1 else ("多帧图片仅取首帧" if count > 1 else "")
        page = Page(path, frame, width, height, note=note)
        image.thumbnail((190, 150), Image.Resampling.LANCZOS)
        result.append((page, png_bytes(image)))
    return result


def watermark_stamp(watermark: Watermark, page_width_pt: float, scale: float) -> Image.Image:
    if watermark.kind == "image":
        if not watermark.image_path:
            raise ValueError("请先选择水印图片。")
        if Path(watermark.image_path).suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError("图片水印请选择 PNG / JPG 等图片文件。")
        image = load_image(watermark.image_path, max_side=2400)
        target = max(1, round(page_width_pt * watermark.scale * scale))
        image = image.resize((target, max(1, round(image.height * target / image.width))), Image.Resampling.LANCZOS)
    else:
        if not watermark.text.strip():
            raise ValueError("请填写水印文字。")
        font = QFont(watermark.font_family)
        font.setPixelSize(max(1, round(watermark.font_size * scale)))
        # Qt font shaping keeps Chinese and other system fonts consistent in preview and export.
        from PySide6.QtGui import QFontMetricsF
        metrics = QFontMetricsF(font)
        bounds = metrics.boundingRect(QRectF(0, 0, 12000, 12000), 0, watermark.text)
        pad = max(5, round(8 * scale))
        width = max(1, min(14000, round(bounds.width()) + 2 * pad))
        height = max(1, min(14000, round(bounds.height()) + 2 * pad))
        if width * height > 20_000_000:
            raise ValueError("水印文字过长，请缩短文字或减小字号。")
        qimage = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        qimage.fill(0)
        painter = QPainter(qimage)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(QColor(watermark.color))
        painter.drawText(QRectF(pad, pad, width - 2 * pad, height - 2 * pad), 0, watermark.text)
        painter.end()
        image = pil_from_qimage(qimage)
    if watermark.angle:
        image = image.rotate(watermark.angle, resample=Image.Resampling.BICUBIC, expand=True)
    alpha = image.getchannel("A").point(lambda a: round(a * watermark.opacity))
    image.putalpha(alpha)
    return image
