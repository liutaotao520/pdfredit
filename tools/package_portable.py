"""Package a verified build without runtime data, and verify every ZIP member."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfedit import __version__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='PDFedit-' + __version__)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', args.name):
        parser.error('Invalid release name')
    release = ROOT / 'dist' / args.name
    report_dir = ROOT / 'reports' / args.name
    accepted = json.loads((report_dir/'release-verification.json').read_text(encoding='utf-8'))
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if accepted.get('status') != 'passed' or accepted.get('sha256') != digest(release/(args.name+'.exe')):
        raise SystemExit('Build has not passed release verification.')
    output = ROOT / 'releases' / f'合页-{__version__}-Windows-x64-便携版.zip'
    output.parent.mkdir(exist_ok=True)
    files = sorted(p for p in release.rglob('*') if p.is_file() and
                   not {'runtime','outputs'}.intersection(p.relative_to(release).parts))
    prefix = Path('合页-' + __version__)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, prefix/path.relative_to(release))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.infolist()) == len(files)
        for path in files:
            member = (prefix/path.relative_to(release)).as_posix()
            assert hashlib.sha256(archive.read(member)).hexdigest() == digest(path)
    report = {'status':'passed','archive':str(output),'bytes':output.stat().st_size,'sha256':digest(output),
              'payload_files':len(files),'all_payload_hashes_verified':True,'excluded':['runtime','outputs']}
    (report_dir/'portable-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
