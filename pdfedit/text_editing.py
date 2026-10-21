"""Local PDF text extraction, editable blocks and non-destructive replacement.

Coordinates are relative to the visible, intrinsically rotated source page.
Native text is actually removed before replacement. OCR uses a visible patch;
it is a document editing feature, never a secure-redaction feature.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import ctypes
from functools import lru_cache
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import uuid

from PIL import Image
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics

from .models import Page
from .pdf_source import PDFIUM_LOCK, merge_native
from .text_fonts import FONT_LOCK, font_for, matching_family, validate_glyphs

EDIT_FIELDS = ('text','x','y','width','height','anchor_x','anchor_y','font_family',
               'font_size','color','bold','italic','angle','font_file','background')
MAX_BLOCKS = 2500


def source_size(page):
    unit = 1 if page.is_pdf else 72 / 150
    return page.width * unit, page.height * unit


@lru_cache(maxsize=24)
def _file_hash(path, size, modified):
    h = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def source_signature(path):
    p = Path(path).resolve(strict=True)
    stat = p.stat()
    return _file_hash(str(p), stat.st_size, stat.st_mtime_ns)


def check_source(page):
    if page.text_source_signature and source_signature(page.path) != page.text_source_signature:
        raise ValueError('原文件在文字识别后已改变。请重新添加文件再编辑，以免替换错位置。')


def has_text_output(page):
    return any(b.get('changed') or b.get('deleted') or b['source']=='ocr' for b in page.text_blocks)


def new_block(text, rect, size, *, source='added', anchor=None, **options):
    x,y,w,h=rect
    block={'id':uuid.uuid4().hex,'source':source,'text':text,'x':x,'y':y,'width':w,'height':h,
           'anchor_x':anchor[0] if anchor else x,
           'anchor_y':anchor[1] if anchor else y+h*.82,
           'font_family':'Microsoft YaHei','font_size':size,'font_file':'',
           'color':'#242424','background':'#ffffff','bold':False,'italic':False,'angle':0.,
           'changed':source=='added','deleted':False,'objects':[],
           'source_rect':list(rect),'confidence':1.0}
    block.update(options)
    block['original']={k:deepcopy(block[k]) for k in EDIT_FIELDS}
    return block


def validate_text_state(page):
    if not isinstance(page.text_blocks,list) or len(page.text_blocks)>MAX_BLOCKS:
        raise ValueError('方案中的文字块数量无效。')
    ids=set()
    for b in page.text_blocks:
        if not isinstance(b,dict) or b.get('source') not in {'native','native_scan','ocr','added'}:
            raise ValueError('方案中的文字类型无效。')
        if not isinstance(b.get('id'),str) or b['id'] in ids:
            raise ValueError('方案中的文字标识无效。')
        ids.add(b['id'])
        if not isinstance(b.get('text'),str) or len(b['text'])>12000:
            raise ValueError('文字内容过长或无效。')
        for key in ['x','y','width','height','anchor_x','anchor_y','font_size','angle']:
            if not isinstance(b.get(key),(int,float)) or not math.isfinite(b[key]):
                raise ValueError('方案中的文字位置无效。')
        if not 1<=b['font_size']<=600 or not -360<=b['angle']<=360:
            raise ValueError('字号或文字角度超出范围。')
        if any(abs(b[k])>4 for k in ['x','y','anchor_x','anchor_y']) or not 0<b['width']<=4 or not 0<b['height']<=4:
            raise ValueError('文字区域超出范围。')
        if any(not re.fullmatch(r'#[0-9a-fA-F]{6}',str(b.get(k,''))) for k in ['color','background']):
            raise ValueError('文字颜色无效。')
        if not isinstance(b.get('objects'),list) or any(type(i)!=int or not 0<=i<100000 for i in b['objects']):
            raise ValueError('PDF文字对象无效。')
        rect=b.get('source_rect')
        if not isinstance(rect,(list,tuple)) or len(rect)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>4 for v in rect):
            raise ValueError('原文字区域无效。')
        if not isinstance(b.get('original'),dict) or set(b['original'])!=set(EDIT_FIELDS):
            raise ValueError('原文字记录无效。')
        if not isinstance(b.get('font_family'),str) or not isinstance(b.get('font_file'),str):
            raise ValueError('字体设置无效。')
        if any(type(b.get(k)) is not bool for k in ['bold','italic','changed','deleted']):
            raise ValueError('文字状态无效。')
        original=b['original']
        for key in EDIT_FIELDS:
            value=original[key]
            if key in {'text','font_family','font_file','color','background'} and not isinstance(value,str):
                raise ValueError('原文字记录无效。')
            if key in {'bold','italic'} and type(value) is not bool:
                raise ValueError('原文字样式无效。')
            if key not in {'text','font_family','font_file','color','background','bold','italic'} and (not isinstance(value,(int,float)) or not math.isfinite(value)):
                raise ValueError('原文字位置无效。')
        if not 1<=original['font_size']<=600 or len(original['text'])>12000:
            raise ValueError('原文字记录超出范围。')
        if any(not re.fullmatch(r'#[0-9a-fA-F]{6}',original[k]) for k in ['color','background']):
            raise ValueError('原文字颜色无效。')
    if page.text_source_signature and not re.fullmatch('[0-9a-f]{64}',page.text_source_signature):
        raise ValueError('源文件校验信息无效。')


@contextmanager
def editable_document(path,index):
    doc=pdfium.PdfDocument(str(path))
    page=None
    try:
        doc.init_forms()
        if not 0<=index<len(doc):
            raise ValueError('原PDF页数已改变，请重新添加。')
        page=doc[index]
        result=pdfium.raw.FPDFPage_Flatten(page,pdfium.raw.FLAT_NORMALDISPLAY)
        if result==pdfium.raw.FLATTEN_FAIL:
            raise ValueError('此页表单或批注无法固定，请先另存为普通PDF。')
        yield doc,page
    finally:
        if page:page.close()
        doc.close()


def _point(page,x,y):
    dx,dy=ctypes.c_int(),ctypes.c_int()
    if not pdfium.raw.FPDF_PageToDevice(page,0,0,1000000,1000000,0,x,y,dx,dy):
        raise ValueError('无法转换PDF文字位置。')
    return dx.value/1000000,dy.value/1000000


def _address(obj):
    return ctypes.cast(obj,ctypes.c_void_p).value


def extract_native(page):
    pw,ph=source_size(page)
    raw=pdfium.raw
    with PDFIUM_LOCK,editable_document(page.path,page.frame) as (_,source):
        tp=source.get_textpage()
        try:
            objects=list(source.get_objects(textpage=tp))
            pointers=[_address(obj.raw) for obj in objects if obj.type==raw.FPDF_PAGEOBJ_TEXT]
            if len(pointers)!=len(set(pointers)):
                # Shared Form content cannot be edited as independent instances.
                # OCR supplies individual visible regions for a safe local patch.
                return []
            by_pointer={_address(obj.raw):(i,obj) for i,obj in enumerate(objects) if obj.type==raw.FPDF_PAGEOBJ_TEXT}
            groups={}
            for i in range(tp.count_chars()):
                pointer=_address(raw.FPDFText_GetTextObject(tp,i))
                if pointer in by_pointer:
                    groups.setdefault(pointer,[]).append(i)
            blocks=[]
            for pointer,indices in groups.items():
                object_index,obj=by_pointer[pointer]
                text=obj.extract().replace('\x00','').strip('\r\n')
                if not text.strip() or text.count('\ufffd')>max(1,len(text)*.2):continue
                points=[]
                for i in indices:
                    left,bottom,right,top=tp.get_charbox(i)
                    points.extend(_point(source,x,y) for x,y in [(left,top),(right,top),(right,bottom),(left,bottom)])
                x,y=min(p[0] for p in points),min(p[1] for p in points)
                right,bottom=max(p[0] for p in points),max(p[1] for p in points)
                if right<=0 or bottom<=0 or x>=1 or y>=1 or right-x<=0 or bottom-y<=0:continue
                first=indices[0]
                ox,oy=ctypes.c_double(),ctypes.c_double()
                raw.FPDFText_GetCharOrigin(tp,first,ox,oy)
                anchor=_point(source,ox.value,oy.value)
                matrix=raw.FS_MATRIX();raw.FPDFText_GetMatrix(tp,first,matrix)
                endpoint=_point(source,ox.value+matrix.a,oy.value+matrix.b)
                dx,dy=(endpoint[0]-anchor[0])*pw,(endpoint[1]-anchor[1])*ph
                font_size=max(1,min(600,raw.FPDFText_GetFontSize(tp,first)*math.hypot(dx,dy)))
                angle=math.degrees(math.atan2(dy,dx))
                font=obj.get_font();name=font.get_family_name() or font.get_base_name()
                values=[ctypes.c_uint() for _ in range(4)]
                raw.FPDFPageObj_GetFillColor(obj,*values)
                color='#'+''.join(f'{v.value:02x}' for v in values[:3])
                invisible=raw.FPDFTextObj_GetTextRenderMode(obj)==raw.FPDF_TEXTRENDERMODE_INVISIBLE
                block=new_block(text,(x,y,right-x,bottom-y),font_size,source='native_scan' if invisible else 'native',
                                anchor=anchor,font_family=matching_family(name),bold=font.get_weight()>=600,
                                italic='italic' in name.lower() or 'oblique' in name.lower(),
                                color=color,angle=round(angle,4),objects=[object_index],original_font=name)
                blocks.append(block)
                if len(blocks)>=MAX_BLOCKS:break
            return sorted(blocks,key=lambda b:(round(b['y'],3),b['x']))
        finally:tp.close()


def _overlap(a,b):
    x=max(a['x'],b['x']);y=max(a['y'],b['y'])
    w=max(0,min(a['x']+a['width'],b['x']+b['width'])-x)
    h=max(0,min(a['y']+a['height'],b['y']+b['height'])-y)
    return w*h/max(1e-9,min(a['width']*a['height'],b['width']*b['height']))


def recognize_page(page, *, supplement=False, cancelled=lambda:False):
    check_source(page)
    if page.text_recognized and not supplement:
        return deepcopy(page.text_blocks),page.text_source_signature
    signature=source_signature(page.path)
    blocks=deepcopy(page.text_blocks)
    scan_layer=False
    if page.is_pdf and not page.text_recognized:
        native=extract_native(page)
        scan_layer=any(b['source']=='native_scan' for b in native)
        # Invisible OCR text bounds describe substitute font metrics, not the
        # photographed glyphs. Re-detect the visible regions to avoid old ink
        # escaping the patch when a searchable scan is edited again.
        blocks.extend(b for b in native if b['source']!='native_scan')
    if cancelled():return None
    if supplement or scan_layer or not any(b['source']!='added' for b in blocks):
        from .ocr import recognize_image
        from .imaging import load_image
        image=load_image(page.path,page.frame,max_side=2400).convert('RGB')
        pw,ph=source_size(page)
        for box,text,score in recognize_image(image):
            if cancelled():return None
            x,y=min(v[0] for v in box)/image.width,min(v[1] for v in box)/image.height
            w=(max(v[0] for v in box)-min(v[0] for v in box))/image.width
            h=(max(v[1] for v in box)-min(v[1] for v in box))/image.height
            if w<=0 or h<=0:continue
            line_height=math.hypot(box[3][0]-box[0][0],box[3][1]-box[0][1])/image.height*ph
            angle=math.degrees(math.atan2((box[1][1]-box[0][1])/image.height*ph,(box[1][0]-box[0][0])/image.width*pw))
            size=max(3,min(200,line_height*.9))
            # Patch color is inferred from the perimeter, with a user override.
            border=[]
            x0,y0,x1,y1=round(x*image.width),round(y*image.height),round((x+w)*image.width),round((y+h)*image.height)
            for xx in range(max(0,x0-2),min(image.width,x1+3),max(1,(x1-x0)//24)):
                for yy in [max(0,y0-2),min(image.height-1,y1+2)]:border.append(image.getpixel((xx,yy)))
            bg=tuple(sorted(v[k] for v in border)[len(border)//2] for k in range(3)) if border else (255,255,255)
            block=new_block(text,(x,y,w,h),size,source='ocr',confidence=float(score),angle=angle,
                            replace_text_layer=scan_layer,
                            background='#'+''.join(f'{v:02x}' for v in bg))
            if any(_overlap(block,b)>.45 for b in blocks if b['source']!='added'):continue
            blocks.append(block)
            if len(blocks)>=MAX_BLOCKS:break
    if source_signature(page.path)!=signature:
        raise ValueError('识别过程中源文件发生变化，请重新识别。')
    return blocks,signature


def block_bounds(block,pw,ph):
    if not block.get('changed') or block.get('deleted'):
        return tuple(block[k] for k in ('x','y','width','height'))
    name,_,_=font_for(block['font_family'],block['bold'],block['italic'],block['font_file'])
    size=block['font_size'];lines=block['text'].split('\n') or [' ']
    width=max(pdfmetrics.stringWidth(line or ' ',name,size) for line in lines)
    ascent,descent=pdfmetrics.getAscentDescent(name,size)
    angle=math.radians(block['angle']);co,si=math.cos(angle),math.sin(angle)
    points=[]
    for x,y in [(0,-ascent),(width,-ascent),(width,-descent+(len(lines)-1)*size*1.25),(0,-descent+(len(lines)-1)*size*1.25)]:
        points.append((block['anchor_x']+(x*co-y*si)/pw,block['anchor_y']+(x*si+y*co)/ph))
    x,y=min(v[0] for v in points),min(v[1] for v in points)
    return x,y,max(.003,max(v[0] for v in points)-x),max(.003,max(v[1] for v in points)-y)


def _draw_text(pdf,b,pw,ph,hidden=False):
    if not b['text'] or b.get('deleted'):return
    family=b['font_family'] if not hidden else 'Microsoft YaHei'
    name,fake_bold,fake_italic=font_for(family,b['bold'],b['italic'],b['font_file'] if not hidden else '')
    validate_glyphs(name,b['text'])
    pdf.saveState()
    pdf.translate(b['anchor_x']*pw,ph-b['anchor_y']*ph)
    pdf.rotate(-b['angle'])
    if fake_italic:pdf.transform(1,0,.2,1,0,0)
    pdf.setFillColor(b['color']);pdf.setStrokeColor(b['color'])
    pdf.setLineWidth(b['font_size']*.018)
    text=pdf.beginText();text.setTextOrigin(0,0);text.setFont(name,b['font_size'])
    text.setLeading(b['font_size']*1.25)
    text.setTextRenderMode(3 if hidden else 2 if fake_bold else 0)
    for line in b['text'].split('\n'):text.textLine(line)
    pdf.drawText(text);pdf.restoreState()


def edited_source_pdf(page):
    """Return one normalized edited page. Source files are never written."""
    validate_text_state(page);check_source(page)
    key=json.dumps(page.text_blocks,ensure_ascii=False,sort_keys=True)
    stat=Path(page.path).stat()
    return _edited_cached(page.path,page.frame,page.width,page.height,page.text_source_signature,
                          stat.st_size,stat.st_mtime_ns,key)


@lru_cache(maxsize=4)
def _edited_cached(path,index,width,height,signature,file_size,modified,block_json):
    page=Page(path,index,width,height,text_blocks=json.loads(block_json),text_source_signature=signature)
    pw,ph=source_size(page)
    raster=None;native_bytes=None;raster_native=False
    changed=[b for b in page.text_blocks if b.get('changed') or b.get('deleted')]
    if page.is_pdf:
        with PDFIUM_LOCK,editable_document(path,index) as (doc,source):
            tp=source.get_textpage()
            objects=list(source.get_objects(textpage=tp));removals=[]
            try:
                if any(b.get('replace_text_layer') for b in page.text_blocks):
                    removals.extend(obj for obj in objects if obj.type==pdfium.raw.FPDF_PAGEOBJ_TEXT
                                    and pdfium.raw.FPDFTextObj_GetTextRenderMode(obj)==pdfium.raw.FPDF_TEXTRENDERMODE_INVISIBLE)
                for b in changed:
                    for n in b['objects']:
                        if n>=len(objects) or objects[n].type!=pdfium.raw.FPDF_PAGEOBJ_TEXT:
                            raise ValueError('PDF文字对象已改变，请重新识别。')
                        if objects[n].extract().replace('\x00','').strip('\r\n')!=b['original']['text']:
                            raise ValueError('PDF文字内容已改变，请重新识别。')
                        if not any(_address(obj.raw)==_address(objects[n].raw) for obj in removals):
                            removals.append(objects[n])
            finally:tp.close()
            raster_native=any(obj.level>0 for obj in removals) or any(b['source']=='ocr' for b in changed)
            for obj in removals:
                source.remove_obj(obj);obj.close()
            if raster_native:
                # PDFium does not serialize child Form XObject removals. Render
                # the cleaned in-memory page, then restore searchable text below.
                scale=min(300/72,5000/max(source.get_size()))
                bitmap=source.render(scale=scale,draw_annots=True)
                try:raster=bitmap.to_pil().convert('RGB').copy()
                finally:bitmap.close()
            else:
                if removals:source.gen_content()
                stream=BytesIO();doc.save(stream);native_bytes=stream.getvalue()
    else:
        from .imaging import load_image
        raster=load_image(path,index).convert('RGBA')
    stream=BytesIO()
    with FONT_LOCK:
        canvas=Canvas(stream,pagesize=(pw,ph),pageCompression=1)
        if raster is not None:
            canvas.drawImage(ImageReader(raster),0,0,pw,ph,mask='auto')
        # Clear only the old scanned glyph region. All patches precede new text.
        for b in changed:
            if b['source'] in {'ocr','native_scan'}:
                x,y,w,h=b['source_rect'];pad=.8
                canvas.setFillColor(b['background'])
                canvas.rect(x*pw-pad,ph-(y+h)*ph-pad,w*pw+2*pad,h*ph+2*pad,fill=1,stroke=0)
        for b in page.text_blocks:
            if b.get('deleted'):continue
            visible=b.get('changed') or b['source']=='added'
            hidden=not visible and (b['source']=='ocr' or raster_native and b['source'] in {'native','native_scan'})
            if visible or hidden:_draw_text(canvas,b,pw,ph,hidden=hidden)
        canvas.showPage();canvas.save()
    overlay=PdfReader(BytesIO(stream.getvalue()));writer=PdfWriter()
    native=None
    try:
        destination=writer.add_page(overlay.pages[0])
        if native_bytes:
            native=PdfReader(BytesIO(native_bytes))
            merge_native(destination,native.pages[index],Page(path,index,width,height), (0,0,pw,ph),ph)
        final=BytesIO();writer.write(final);return final.getvalue()
    finally:
        writer.close();overlay.close()
        if native:native.close()


def render_edited(page,max_side=1800):
    data=edited_source_pdf(page)
    with PDFIUM_LOCK,pdfium.PdfDocument(data) as document:
        source=document[0]
        try:
            bitmap=source.render(scale=max_side/max(source.get_size()))
            try:return bitmap.to_pil().convert('RGBA').copy()
            finally:bitmap.close()
        finally:source.close()


def clear_text_cache():
    _edited_cached.cache_clear()
