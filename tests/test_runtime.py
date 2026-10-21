"""Startup must keep its files local and reject a redirected runtime directory."""
from pathlib import Path
import logging
import os
from types import SimpleNamespace
import uuid

import pytest

from main import configure_environment


def test_runtime_is_local_and_rejects_junction(monkeypatch):
    root = Path(os.environ["PDFEDIT_TEST_DIR"]) / uuid.uuid4().hex
    root.mkdir(parents=True)
    for key in ("TEMP", "TMP", "TMPDIR", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: None)
    runtime = configure_environment(root)
    assert runtime == root / "runtime"
    assert all(Path(os.environ[key]) == runtime / "temp" for key in ("TEMP", "TMP", "TMPDIR"))
    linked_root = root / "linked"
    linked_root.mkdir()
    redirected = linked_root / "runtime"
    redirected.mkdir()
    original = Path.lstat
    monkeypatch.setattr(Path, "lstat", lambda path, *a, **kw:
                        SimpleNamespace(st_file_attributes=0x400)
                        if path == redirected else original(path, *a, **kw))
    with pytest.raises(RuntimeError, match="不能指向"):
        configure_environment(linked_root)
    assert not (redirected / "temp").exists()
