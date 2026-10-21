"""Build a self-contained Windows folder, keeping scratch files in the task folder."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--name", default="PDFedit-1.4.2")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.task):
        parser.error("Invalid task name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.name):
        parser.error("Invalid release name")
    temp = ROOT / ".task_tmp" / args.task / "build"
    temp.mkdir(parents=True, exist_ok=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(temp)
    output = ROOT / "dist" / args.name
    if output.exists():
        raise SystemExit(f"Refusing to overwrite an existing release: {output}. Use --name with a new release name.")
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    icon = assets / "app.ico"
    if not icon.exists():
        from PIL import Image, ImageDraw
        image = Image.new("RGBA", (256, 256), (0,0,0,0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((12,12,244,244), radius=52, fill="#245bd7")
        draw.rounded_rectangle((51,42,164,198), radius=13, fill="#94b4f4")
        draw.rounded_rectangle((88,63,202,219), radius=13, fill="white")
        draw.line((109,160,132,134,152,157,169,141,184,162), fill="#245bd7", width=10)
        draw.ellipse((112,89,135,112), fill="#245bd7")
        image.save(icon, sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(temp / "pyinstaller-cache")
    command = [sys.executable, "-B", "-s", "-m", "PyInstaller", "--windowed", "--onedir",
        "--name", args.name, "--distpath", str(ROOT / "dist"), "--workpath", str(temp / args.name),
        "--specpath", str(temp), "--icon", str(icon), "--add-data", str(assets) + ";assets",
        "--collect-all", "pillow_heif", "--hidden-import", "PIL.AvifImagePlugin",
        "--exclude-module", "pytest", "--collect-all", "pypdfium2_raw",
        "--collect-all", "rapidocr", "--collect-all", "onnxruntime",
        "--hidden-import", "fontTools.ttLib",
        str(ROOT / "main.py")]
    # Only search this project's runtime and Windows for DLL dependencies.
    # Developer tools on PATH can carry unrelated ICU/OpenSSL DLLs with the same
    # names but incompatible exports, which must not leak into the release.
    env = os.environ.copy()
    system = Path(os.environ.get("SystemRoot", "C:/Windows"))
    env["PATH"] = os.pathsep.join(str(p) for p in [Path(sys.executable).parent,
        Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs", system / "System32", system])
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    license_dir = output / "licenses"
    license_dir.mkdir(exist_ok=True)
    dependencies = []
    for name in ["PySide6-Essentials", "shiboken6", "Pillow", "pillow-heif", "reportlab", "charset-normalizer", "pypdf", "pypdfium2",
                 "rapidocr", "onnxruntime", "fonttools", "numpy", "opencv-python-headless", "pyclipper", "shapely", "pyyaml",
                 "six", "tqdm", "omegaconf", "requests", "colorlog", "flatbuffers", "protobuf", "idna", "urllib3", "certifi"]:
        dist = importlib.metadata.distribution(name)
        dependencies.append({"name": name, "version": dist.version, "license": str(dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See license files")})
        for file in dist.files or []:
            # Some wheels keep notices below licenses/ with ordinary filenames.
            if any(token in str(file).lower() for token in ["license", "copying", "notice"]) and ".dist-info" in str(file):
                path = Path(dist.locate_file(file))
                if path.is_file():
                    target = license_dir / name / str(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(path.read_bytes())
    (license_dir / "dependencies.json").write_text(json.dumps(dependencies, ensure_ascii=False, indent=2), encoding="utf-8")
    if (ROOT / "README.md").exists():
        (output / "使用说明.md").write_bytes((ROOT / "README.md").read_bytes())
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        if (ROOT / name).is_file():
            (output / name).write_bytes((ROOT / name).read_bytes())
    (output / "docs").mkdir(exist_ok=True)
    (output / "docs/USER_GUIDE.md").write_bytes((ROOT / "docs/USER_GUIDE.md").read_bytes())
    (output / "使用说明.txt").write_bytes((ROOT / "packaging/使用说明.txt").read_bytes())
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        (license_dir / "Python-LICENSE.txt").write_bytes(python_license.read_bytes())
    print(json.dumps({"executable": str(output / (args.name + ".exe")), "files": sum(p.is_file() for p in output.rglob("*")), "bytes": sum(p.stat().st_size for p in output.rglob("*") if p.is_file())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
