"""Compile a Windows installer from a verified self-contained build."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdfedit import __version__


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--name", default="PDFedit-" + __version__)
    parser.add_argument("--compiler", default="C:/Program Files (x86)/Inno Setup 6/ISCC.exe")
    args = parser.parse_args()
    for value in (args.task, args.name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
            parser.error("Invalid task or release name")
    source = ROOT / "dist" / args.name
    executable = source / (args.name + ".exe")
    verification = ROOT / "reports" / args.name / "release-verification.json"
    if not verification.is_file():
        raise SystemExit("Run tools/verify_release.py for this build before packaging.")
    accepted = json.loads(verification.read_text(encoding="utf-8"))
    if accepted.get("status") != "passed" or accepted.get("sha256") != digest(executable):
        raise SystemExit("Build does not match the successful verification report.")
    output = ROOT / "releases"
    output.mkdir(exist_ok=True)
    exe = output / ("合页-" + __version__ + "-安装程序.exe")
    if exe.exists():
        raise SystemExit("Refusing to overwrite an existing installer")
    report_dir = ROOT / "reports" / args.name / "installer"
    report_dir.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / ".task_tmp" / args.task / "installer-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ("TEMP", "TMP", "TMPDIR"):
        env[key] = str(scratch)
    command = [str(Path(args.compiler).resolve()), "/Qp", "/DProjectRoot=" + str(ROOT),
               "/DAppVersion=" + __version__, "/DReleaseName=" + args.name,
               str(ROOT / "packaging/setup.iss")]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True)
    (report_dir / "compiler.log").write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit("Installer compiler failed. See reports/" + args.name + "/installer/compiler.log")
    report = {"file": exe.name, "bytes": exe.stat().st_size, "sha256": digest(exe),
              "application_sha256": digest(executable), "version": __version__, "signature": "unsigned"}
    (report_dir / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sums = output / "SHA256SUMS.txt"
    existing = sums.read_text(encoding="utf-8") if sums.exists() else ""
    sums.write_text(existing + report["sha256"] + "  " + exe.name + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
