"""Resolve locally installed TrueType fonts and embed them in edited PDF text."""
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import threading

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_LOCK = threading.RLock()
FONT_CHOICES = [
    ("微软雅黑", "Microsoft YaHei"), ("宋体", "SimSun"), ("黑体", "SimHei"),
    ("楷体", "KaiTi"), ("仿宋", "FangSong"), ("Arial", "Arial"),
    ("Times New Roman", "Times New Roman"), ("Courier New", "Courier New"),
]
FILES = {
    "Microsoft YaHei": ("msyh.ttc", "msyhbd.ttc", "msyh.ttc", "msyhbd.ttc"),
    "SimSun": ("simsun.ttc",)*4, "SimHei": ("simhei.ttf",)*4,
    "KaiTi": ("simkai.ttf",)*4, "FangSong": ("simfang.ttf",)*4,
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Courier New": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
}


def matching_family(name):
    lower = name.lower().replace(" ", "")
    for token, family in [("yahei","Microsoft YaHei"),("微软雅黑","Microsoft YaHei"),
                          ("simsun","SimSun"),("宋体","SimSun"),("simhei","SimHei"),
                          ("黑体","SimHei"),("kaiti","KaiTi"),("fangsong","FangSong"),
                          ("times","Times New Roman"),("courier","Courier New"),
                          ("arial","Arial"),("helvetica","Arial")]:
        if token in lower:
            return family
    return "Microsoft YaHei"


@lru_cache(maxsize=64)
def font_for(family, bold=False, italic=False, custom=""):
    index = int(bool(bold)) + 2 * int(bool(italic))
    if custom:
        path = Path(custom).expanduser().resolve(strict=True)
        if path.suffix.lower() not in {".ttf", ".ttc"}:
            raise ValueError("编辑字体仅支持 TrueType .ttf / .ttc 文件。")
    else:
        family = family if family in FILES else matching_family(family)
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / FILES[family][index]
        if not path.is_file():
            raise ValueError(f"本机未安装字体“{family}”，请在文字编辑中改选字体或导入 TTF。")
    # Inspect embedding permission, rather than distributing OS font files.
    from fontTools.ttLib import TTFont as InspectFont
    with InspectFont(str(path), fontNumber=0, lazy=True) as inspected:
        if "OS/2" in inspected and inspected["OS/2"].fsType & (0x0002 | 0x0100 | 0x0200):
            raise ValueError("该字体限制嵌入或字形子集，请选择允许嵌入的字体。")
        names = inspected["name"]
        style = (names.getDebugName(2) or "").lower()
        actual_bold = "bold" in style or "黑" in style
        actual_italic = "italic" in style or "oblique" in style
    token = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    name = "HeyeEdit_" + token
    with FONT_LOCK:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=0))
    return name, bool(bold and not actual_bold), bool(italic and not actual_italic)


def validate_glyphs(font_name, text):
    face = pdfmetrics.getFont(font_name).face
    missing = sorted({c for c in text if not c.isspace() and ord(c) not in face.charToGlyph})
    if missing:
        raise ValueError("所选字体不包含这些字符：" + " ".join(missing[:12]) + "。请换用微软雅黑、宋体或导入合适字体。")
