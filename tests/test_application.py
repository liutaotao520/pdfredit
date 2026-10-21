from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import sys
import uuid

import pytest
from PIL import Image, ImageChops, ImageDraw
from pypdf import PdfReader
import pypdfium2 as pdfium
from PySide6.QtWidgets import QApplication

from pdfedit.engine import ExportCancelled, export_pdf, geometry, render_preview
from pdfedit.imaging import inspect_image, load_image, watermark_stamp
from pdfedit.models import Layout, Page, Watermark, page_selection

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(os.environ.get("PDFEDIT_TEST_DIR", ROOT / ".task_tmp" / "20261016-image-pdf" / "tests"))


@pytest.fixture(scope="session", autouse=True)
def app():
    application = QApplication.instance() or QApplication([])
    return application


@pytest.fixture
def folder():
    path = TEST_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


def image_page(folder, name, color, size=(300, 200)):
    path = folder / name
    Image.new("RGB", size, color).save(path)
    return inspect_image(str(path))[0][0]


@pytest.mark.parametrize("fmt,ext,mode", [
    ("JPEG","jpg","RGB"), ("PNG","png","RGBA"), ("WEBP","webp","RGBA"),
    ("BMP","bmp","RGB"), ("TIFF","tif","RGB"), ("GIF","gif","RGB"),
    ("HEIF","heic","RGB"), ("HEIF","heif","RGB"), ("AVIF","avif","RGB"),
    ("ICO","ico","RGBA"), ("PCX","pcx","RGB"), ("PPM","ppm","RGB"),
    ("PPM","pgm","L"), ("PPM","pbm","1"), ("TGA","tga","RGBA"),
    ("JPEG2000","jp2","RGB"), ("QOI","qoi","RGBA"), ("DDS","dds","RGB")])
def test_formats(folder, fmt, ext, mode):
    path = folder / ("测试 图片." + ext)
    image = Image.new("RGB", (128, 128), "#196bb1").convert(mode)
    image.save(path, format=fmt)
    pages = inspect_image(str(path))
    assert len(pages) == 1
    assert pages[0][0].width > 0 and pages[0][0].height > 0
    output = folder / "result.pdf"
    export_pdf([pages[0][0]], Layout(), Watermark(), str(output))
    assert len(PdfReader(output).pages) == 1


def test_multipage_tiff_and_gif(folder):
    images = [Image.new("RGB", (90,120), c) for c in ["red","green","blue"]]
    path = folder / "three.tiff"
    images[0].save(path,save_all=True,append_images=images[1:])
    pages = inspect_image(str(path))
    assert [p.frame for p,_ in pages] == [0,1,2]
    assert load_image(str(path),2).getpixel((5,5))[:3] == (0,0,255)
    gif = folder / "animated.gif"
    images[0].save(gif,save_all=True,append_images=images[1:],duration=100)
    imported = inspect_image(str(gif))
    assert len(imported) == 1 and "首帧" in imported[0][0].note


def test_svg_and_entity_rejection(folder):
    path = folder / "vector.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="red"/></svg>',encoding="utf-8")
    page = inspect_image(str(path))[0][0]
    assert (page.width,page.height) == (300,200)
    assert load_image(str(path)).getpixel((50,50))[:3] == (255,0,0)
    unsafe = folder / "external.svg"
    unsafe.write_text('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///secret">]><svg/>',encoding="utf-8")
    with pytest.raises(ValueError,match="实体"):
        load_image(str(unsafe))


def test_exif_orientation(folder):
    path = folder / "rotated.jpg"
    image = Image.new("RGB", (180,90), "red")
    exif = image.getexif()
    exif[274] = 6
    image.save(path,exif=exif)
    page = inspect_image(str(path))[0][0]
    assert (page.width,page.height) == (90,180)


def rendered_pdf(path, index=0, scale=1.5):
    document = pdfium.PdfDocument(str(path))
    page = document[index]
    bitmap = page.render(scale=scale)
    result = bitmap.to_pil().convert("RGB").copy()
    bitmap.close()
    page.close()
    document.close()
    return result


def test_export_order_and_transparency(folder):
    red = image_page(folder,"red.png","red")
    blue = image_page(folder,"blue.png","blue")
    alpha = folder / "alpha.png"
    Image.new("RGBA",(100,100),(0,0,0,0)).save(alpha)
    pages = [blue,red,inspect_image(str(alpha))[0][0]]
    output = folder / "ordered.pdf"
    export_pdf(pages,Layout(),Watermark(),str(output))
    assert len(PdfReader(output).pages) == 3
    for i,expected in enumerate([(0,0,255),(255,0,0),(255,255,255)]):
        rendered = rendered_pdf(output,i)
        actual = rendered.getpixel((rendered.width//2,rendered.height//2))
        assert all(abs(a-b) < 5 for a,b in zip(actual,expected))


@pytest.mark.parametrize("quality",["original","high","compact"])
def test_layout_preview_matches_pdf(folder, quality):
    page = image_page(folder,"layout.png","#2469d8",(400,220))
    page.rotation, page.zoom, page.offset_x, page.offset_y = 90,.65,.15,-.12
    layout = Layout("A4","portrait",18,quality)
    wm = Watermark(kind="text",text="合页测试",angle=25,opacity=.5,font_size=34)
    output = folder / "layout.pdf"
    export_pdf([page],layout,wm,str(output))
    rendered = rendered_pdf(output)
    preview = render_preview(page,layout,wm,1,1,max(rendered.size)).resize(rendered.size)
    from PIL import ImageStat
    error = sum(ImageStat.Stat(ImageChops.difference(preview,rendered)).mean)/3
    assert error < 5, error


def test_image_watermark_page_range(folder):
    page = image_page(folder,"white.png","white")
    path = folder / "wm.png"
    Image.new("RGBA",(60,40),(255,0,0,255)).save(path)
    wm = Watermark(kind="image",image_path=str(path),angle=0,opacity=1,pages="2")
    output = folder / "watermark.pdf"
    export_pdf([page,page],Layout(),wm,str(output))
    first, second = rendered_pdf(output,0), rendered_pdf(output,1)
    assert first.getpixel((first.width//2,first.height//2)) == (255,255,255)
    assert second.getpixel((second.width//2,second.height//2))[0] > 250
    assert second.getpixel((second.width//2,second.height//2))[1] < 5


def test_tiled_watermark_changes_multiple_regions(folder):
    page = image_page(folder,"white.png","white")
    wm = Watermark(kind="text",text="内部资料",tiled=True,opacity=.5)
    preview = render_preview(page,Layout(),wm,1,1)
    for x,y in [(0,0),(preview.width//2,preview.height//2)]:
        region = preview.crop((x,y,x+preview.width//2,y+preview.height//2))
        assert ImageChops.difference(region,Image.new("RGB",region.size,"white")).getbbox()


def test_cancel_and_failed_export_preserve_existing_pdf(folder):
    page = image_page(folder,"source.png","red")
    target = folder / "existing.pdf"
    original = b"existing user document"
    target.write_bytes(original)
    with pytest.raises(ExportCancelled):
        export_pdf([page],Layout(),Watermark(),str(target),cancelled=lambda: True,overwrite=True)
    assert target.read_bytes() == original
    with pytest.raises(FileExistsError):
        export_pdf([page],Layout(),Watermark(),str(target))
    page.path = str(folder / "missing.png")
    with pytest.raises(FileNotFoundError):
        export_pdf([page],Layout(),Watermark(),str(target),overwrite=True)
    assert target.read_bytes() == original
    assert not list(folder.glob("*.pending"))


@pytest.mark.parametrize("text",["0","2-1","-3","a","1,,2","1-4"])
def test_invalid_page_range(text):
    with pytest.raises(ValueError):
        page_selection(text,3)


def test_page_range_and_original_geometry():
    assert page_selection("1, 3-5",5) == {1,3,4,5}
    page = Page("sample.png",width=900,height=300)
    pw,ph,rect = geometry(page,Layout(paper="original"))
    assert abs(pw/ph-3)<1e-9 and rect[:2] == (0,0)


def test_corrupt_file(folder):
    path = folder / "broken.png"
    path.write_bytes(b"not an image")
    with pytest.raises(Exception):
        inspect_image(str(path))


def test_gui_reordering_and_project_state(app, folder):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem
    from pdfedit.window import MainWindow
    window = MainWindow(ROOT)
    for name in ["page10.png","page2.png","page1.png"]:
        page = image_page(folder,name,"red")
        item = QListWidgetItem(page.label)
        item.setData(Qt.ItemDataRole.UserRole,page)
        window.page_list.addItem(item)
    window.sort_pages()
    assert [Path(p.path).name for p in window.pages()] == ["page1.png","page2.png","page10.png"]
    window.page_list.setCurrentRow(0)
    window.move_pages(1)
    assert Path(window.pages()[1].path).name == "page1.png"
    window.zoom.setValue(70)
    assert window.current_page().zoom == .7
    window.rotate(90)
    assert window.current_page().rotation == 90
    window.timer.stop()
    window.dirty = False
    window.close()
