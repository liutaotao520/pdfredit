"""Deterministic sample PDFs shared by release and visual verification tools."""
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.pdfgen.canvas import Canvas


def create_pdf_samples(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / '01-项目资料.pdf'
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(595, 842))
    for number in range(1, 3):
        canvas.setFillColorRGB(.13, .13, .13)
        canvas.setFont('Helvetica-Bold', 28)
        canvas.drawString(54, 750, f'PROJECT NOTES / 0{number}')
        canvas.setFont('Helvetica', 12)
        canvas.setFillColorRGB(.4, .4, .4)
        canvas.drawString(54, 719, 'PDF input verification - native text and vector graphics')
        canvas.setStrokeColorRGB(.8, .8, .8)
        canvas.line(54, 692, 540, 692)
        for i, title in enumerate(('Page order', 'Layout and rotation', 'Text and image watermark')):
            y = 632 - i * 90
            canvas.setFillColorRGB(.13, .13, .13)
            canvas.setFont('Helvetica-Bold', 15)
            canvas.drawString(54, y, f'0{i + 1}  {title}')
            canvas.setFillColorRGB(.4, .4, .4)
            canvas.setFont('Helvetica', 11)
            canvas.drawString(80, y - 26, 'Keep original source content while composing the final document.')
        canvas.setFillColorRGB(.93, .94, .95)
        canvas.rect(54, 140, 486, 170, fill=1, stroke=0)
        canvas.setFillColorRGB(.2, .2, .2)
        for x, height in ((82, 58), (162, 92), (242, 69), (322, 116), (402, 135)):
            canvas.rect(x, 160, 44, height, fill=1, stroke=0)
        canvas.setFont('Helvetica', 10)
        canvas.drawString(54, 70, f'Native PDF page {number} / 2')
        canvas.showPage()
    canvas.save()
    stream.seek(0)
    reader = PdfReader(stream)
    writer = PdfWriter()
    writer.append(reader)
    writer.pages[1].cropbox = RectangleObject((30, 40, 565, 810))
    writer.pages[1].rotate(90)
    writer.write(source)
    writer.close()
    reader.close()

    form = folder / '02-带表单的PDF.pdf'
    canvas = Canvas(str(form), pagesize=(595, 842))
    canvas.setFont('Helvetica-Bold', 24)
    canvas.drawString(54, 750, 'REVIEW RECORD')
    canvas.setFont('Helvetica', 12)
    canvas.drawString(54, 700, 'The filled values remain visible after merging.')
    canvas.acroForm.textfield(name='reviewer', value='Approved sample', x=54, y=610, width=300, height=35)
    canvas.acroForm.checkbox(name='approved', x=54, y=560, checked=True)
    canvas.drawString(90, 565, 'Approved')
    canvas.showPage()
    canvas.save()
    return source, form
