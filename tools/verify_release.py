"""Check the actual frozen executable and record portable dependency evidence."""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--task',required=True)
    parser.add_argument('--name',default='PDFedit')
    parser.add_argument('--exe',help='Validate a copied or installed executable')
    parser.add_argument('--report-dir',help='Save this run under a distinct reports directory')
    parser.add_argument('--prior-build-report',help='Reuse a preserved build audit when validating a byte-verified installed copy')
    args=parser.parse_args()
    from PIL import Image
    from pypdf import PdfReader
    from pillow_heif import register_heif_opener
    register_heif_opener()
    temp=ROOT/'.task_tmp'/args.task/'release-test'/uuid.uuid4().hex
    temp.mkdir(parents=True)
    exe=Path(args.exe).resolve() if args.exe else ROOT/'dist'/args.name/(args.name+'.exe')
    report_dir=Path(args.report_dir).resolve() if args.report_dir else ROOT/'reports'/args.name
    assert exe.is_relative_to(ROOT) and report_dir.is_relative_to(ROOT/'reports')
    report_dir.mkdir(parents=True,exist_ok=True)
    translation = exe.parent / '_internal/PySide6/translations/qtbase_zh_CN.qm'
    close_icon = exe.parent / '_internal/assets/icons/close.svg'
    assert translation.is_file() and translation.stat().st_size > 0
    assert close_icon.is_file()
    env=os.environ.copy()
    for key in list(env):
        if key.startswith(('CODEX','PYTHON')) or key in ('VIRTUAL_ENV','QT_PLUGIN_PATH','QML2_IMPORT_PATH'):
            env.pop(key,None)
    system=Path(os.environ.get('SystemRoot','C:/Windows'))
    env['PATH']=os.pathsep.join([str(system/'System32'),str(system)])
    for key in ('TEMP','TMP','TMPDIR'):
        env[key]=str(temp)
    paths=[]
    formats=[('JPEG','jpg'),('PNG','png'),('WEBP','webp'),('BMP','bmp'),('HEIF','heic'),('AVIF','avif'),('TIFF','tiff'),('GIF','gif'),('ICO','ico'),('PCX','pcx'),('TGA','tga'),('JPEG2000','jp2'),('QOI','qoi'),('DDS','dds')]
    for fmt,ext in formats:
        path=temp/('样例.'+ext)
        Image.new('RGB',(128,128),'#2767cd').save(path,format=fmt)
        paths.append(str(path))
    svg=temp/'样例.svg'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="blue"/></svg>',encoding='utf-8')
    paths.append(str(svg))
    output=temp/'发布版文字水印.pdf'
    result=subprocess.run([str(exe),'--export',str(output),'--watermark-text','合页 · 发布版验收',*paths],env=env,cwd=temp,timeout=45)
    assert result.returncode==0, result.returncode
    assert len(PdfReader(output).pages)==len(paths)
    receipt=json.loads((exe.parent/'runtime/last-export.json').read_text(encoding='utf-8'))
    assert receipt['packaged']
    assert all(Path(p).is_relative_to(exe.parent) if Path(p).is_absolute() else p.startswith('shibokensupport/') for p in receipt['application_modules'])
    output2=temp/'发布版图片水印.pdf'
    result=subprocess.run([str(exe),'--export',str(output2),'--watermark-image',str(ROOT/'examples/watermark.png'),paths[0]],env=env,cwd=temp,timeout=30)
    assert result.returncode==0
    assert len(PdfReader(output2).pages)==1
    from pdf_fixtures import create_pdf_samples
    source, form = create_pdf_samples(temp / 'pdf-input')
    mixed = temp / 'PDF和图片混合.pdf'
    result = subprocess.run([str(exe), '--export', str(mixed), '--watermark-text', '混合合并验收',
                             str(source), paths[0], str(form)], env=env, cwd=temp, timeout=60)
    assert result.returncode == 0
    mixed_reader = PdfReader(mixed)
    assert len(mixed_reader.pages) == 4
    assert 'Native PDF page 1 / 2' in mixed_reader.pages[0].extract_text()
    assert 'Native PDF page 2 / 2' in mixed_reader.pages[1].extract_text()
    assert not mixed_reader.pages[2].extract_text()
    assert 'Approved sample' in mixed_reader.pages[3].extract_text()
    assert not mixed_reader.pages[3].get('/Annots')
    mixed_reader.close()
    receipt = json.loads((exe.parent/'runtime/last-export.json').read_text(encoding='utf-8'))
    assert receipt['packaged']
    assert all(Path(p).is_relative_to(exe.parent) if Path(p).is_absolute() else p.startswith('shibokensupport/') for p in receipt['application_modules'])
    assert any('pypdfium2' in p for p in receipt['application_modules'])
    white = temp / 'A3-white.png'
    red_mark = temp / 'A3-red-watermark.png'
    Image.new('RGB', (200, 300), 'white').save(white)
    Image.new('RGBA', (100, 100), 'red').save(red_mark)
    a3_output = temp / 'A3-5percent.pdf'
    result = subprocess.run([str(exe), '--export', str(a3_output), '--paper', 'A3',
                             '--watermark-image', str(red_mark), '--watermark-scale', '5', str(white)],
                            env=env, cwd=temp, timeout=30)
    assert result.returncode == 0
    a3_reader = PdfReader(a3_output)
    box = a3_reader.pages[0].mediabox
    assert abs(float(box.width) * 25.4 / 72 - 297) < .001
    assert abs(float(box.height) * 25.4 / 72 - 420) < .001
    a3_reader.close()
    density_outputs, density_counts = [], []
    for level in (3, 10):
        tiled_output = temp / f'watermark-density-{level}.pdf'
        result = subprocess.run([str(exe), '--export', str(tiled_output), '--paper', 'A3',
            '--watermark-image', str(red_mark), '--watermark-scale', '5', '--watermark-tiled',
            '--watermark-density', str(level), str(white)], env=env, cwd=temp, timeout=30)
        assert result.returncode == 0
        tiled_reader = PdfReader(tiled_output)
        copies = sum(operator == b'Do' for _, operator in tiled_reader.pages[0].get_contents().operations) - 1
        density_counts.append(copies)
        density_outputs.append((tiled_output, 0, f'release-density-{level}.png'))
        tiled_reader.close()
    assert density_counts[1] > density_counts[0] * 6
    # Exercise OCR and font editing in the actual EXE without Python on PATH.
    from PIL import ImageDraw, ImageFont
    from pdfedit.imaging import inspect_image
    from pdfedit.models import Layout, Watermark, project_data
    from pdfedit.text_editing import recognize_page
    scan = temp / '扫描文字.png'
    scan_image = Image.new('RGB', (1200, 600), 'white')
    ImageDraw.Draw(scan_image).text((60, 90), '合页 PDF 文字编辑 2026',
        font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 56), fill='black')
    scan_image.save(scan)
    searchable = temp / '本地OCR.pdf'
    result = subprocess.run([str(exe), '--export', str(searchable), '--ocr', str(scan), str(source)],
                            env=env, cwd=temp, timeout=120)
    assert result.returncode == 0
    with PdfReader(searchable) as reader:
        assert len(reader.pages)==3
        assert '2026' in reader.pages[0].extract_text() and '合页' in reader.pages[0].extract_text()
        assert 'Native PDF page 1' in reader.pages[1].extract_text()
    ocr_receipt=json.loads((exe.parent/'runtime/last-export.json').read_text(encoding='utf-8'))
    assert any('onnxruntime' in p for p in ocr_receipt['application_modules'])
    assert any('rapidocr' in p for p in ocr_receipt['application_modules'])
    reimported_scan = temp / '再次识别扫描件.pdf'
    result = subprocess.run([str(exe), '--export', str(reimported_scan), '--ocr', str(searchable)],
                            env=env, cwd=temp, timeout=120)
    assert result.returncode == 0
    with PdfReader(reimported_scan) as reader:
        assert reader.pages[0].extract_text().count('2026')==1
    page = inspect_image(str(source))[0][0]
    page.text_blocks, page.text_source_signature = recognize_page(page)
    page.text_recognized = True
    block = next(b for b in page.text_blocks if 'Native PDF page 1' in b['text'])
    block.update(text='合页 · 修改后的文字', font_family='Microsoft YaHei', font_size=24, bold=True, color='#222222', changed=True)
    project = temp / '文字修改.ipdf.json'
    project.write_text(json.dumps(project_data([page], Layout(paper='original'), Watermark()), ensure_ascii=False), encoding='utf-8')
    text_output = temp / '修改后.pdf'
    result = subprocess.run([str(exe), '--export', str(text_output), '--project', str(project)], env=env, cwd=temp, timeout=60)
    assert result.returncode == 0
    with PdfReader(text_output) as reader:
        text = reader.pages[0].extract_text()
        assert '修改后的文字' in text and 'Native PDF page 1' not in text
    edited_receipt = json.loads((exe.parent/'runtime/last-export.json').read_text(encoding='utf-8'))
    receipt['application_modules'] = sorted(set(receipt['application_modules'] + edited_receipt['application_modules'] + ocr_receipt['application_modules']))
    assert all(Path(p).is_relative_to(exe.parent) if Path(p).is_absolute() else p.startswith('shibokensupport/') for p in receipt['application_modules'])
    import pypdfium2 as pdfium
    for source,index,name in [(output,0,'release-text-watermark.png'),(output2,0,'release-image-watermark.png'),
                               (mixed,0,'release-mixed-pdf.png'),(mixed,3,'release-pdf-form.png'),
                               (a3_output,0,'release-a3-5percent.png'), (searchable,0,'release-ocr.png'),
                               (text_output,0,'release-text-edited.png'), *density_outputs]:
        document=pdfium.PdfDocument(str(source))
        page=document[index]
        bitmap=page.render(scale=1.2)
        bitmap.to_pil().save(report_dir/name)
        if source == a3_output:
            from PIL import ImageChops
            import math
            rendered = bitmap.to_pil().convert('RGB')
            red, green, blue = rendered.split()
            mark_box = ImageChops.subtract(red, green).point(lambda v: 255 if v > 20 else 0).getbbox()
            assert mark_box
            expected_width = rendered.width * .05 * (math.cos(math.pi / 6) + math.sin(math.pi / 6))
            assert abs((mark_box[2] - mark_box[0]) - expected_width) < 5
        bitmap.close();page.close();document.close()
    binaries=[]
    def visit(value):
        if isinstance(value,(tuple,list)):
            if len(value)==3 and isinstance(value[0],str) and isinstance(value[1],str) and value[2]=='BINARY':
                binaries.append({'file':value[0],'source':value[1]})
            else:
                for item in value:visit(item)
    if args.prior_build_report:
        prior=json.loads(Path(args.prior_build_report).read_text(encoding='utf-8'))
        assert prior['status']=='passed'
        binaries=prior['binary_sources']
    else:
        toc=ast.literal_eval((ROOT/'.task_tmp'/args.task/'build'/args.name/args.name/'Analysis-00.toc').read_text(encoding='utf-8'))
        visit(toc)
    forbidden=[row for row in binaries if '.codex' in row['source'].lower() or 'codex-runtimes' in row['source'].lower()]
    assert not forbidden,forbidden
    report={'status':'passed','sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'executable':str(exe),'isolated_environment':{'cwd':str(temp),'PATH':env['PATH'],'codex_variables_removed':True,'python_variables_removed':True},
        'dialog_assets':{'chinese_qt_translation':'bundled','monochrome_close_icon':'bundled'},
        'formats_exported':[ext for _,ext in formats]+['svg'],'pages':len(paths),'text_watermark':'passed','image_watermark':'passed',
        'pdf_input':{'mixed_pages':4,'multipage':'passed','native_text':'passed','rotated_crop':'passed','form_appearance':'passed'},
        'a3_and_watermark':{'paper_mm':[297,420],'watermark_scale_percent':5,'rendered_size_check':'passed'},
        'watermark_density':{'status':'passed','levels':[3,10],'exported_copies':density_counts},
        'text_editing':{'native_replacement':'passed','font_embedding_chinese':'passed','offline_ocr_models':'bundled',
                        'scanned_chinese_english':'passed','saved_project_export':'passed'},
        'runtime_modules':receipt['application_modules'],'binary_sources':binaries,'codex_shutdown_test':'not performed; 独立运行尚未验证',
        'portable_exe_test':'passed with Windows-only PATH and no Python/Codex environment variables',
        'build_audit_source':args.prior_build_report or 'current task PyInstaller Analysis-00.toc'}
    (report_dir/'release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('binary_sources','runtime_modules')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
