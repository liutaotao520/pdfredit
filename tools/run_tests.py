"""Run regression tests with project-local scratch files, without desktop windows."""
from pathlib import Path
import argparse
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="tests")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.task):
        parser.error("Invalid task name")
    scratch = ROOT / ".task_tmp" / args.task
    scratch.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(PDFEDIT_TEST_DIR=str(scratch / "tests"), QT_QPA_PLATFORM="offscreen",
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    for name in ("TEMP", "TMP", "TMPDIR"):
        env[name] = str(scratch)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    return subprocess.call([sys.executable, "-B", "-s", "-X", "utf8", "-m", "pytest",
                            "tests", "-q", "-p", "no:cacheprovider",
                            "--junitxml=" + str(reports / "tests.xml")], cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
