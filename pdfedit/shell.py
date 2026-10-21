"""Per-user Explorer verb. No admin, file association or default app changes."""
from __future__ import annotations

import ctypes
from pathlib import Path
import subprocess
import sys
import winreg

from .imaging import EXTENSIONS

VERB = "PDFedit.Merge"
BASE = r"Software\Classes\SystemFileAssociations"


def command_for(root: Path):
    if getattr(sys, "frozen", False):
        args = [str(Path(sys.executable).resolve())]
    else:
        pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
        if not pythonw.is_file():
            raise FileNotFoundError("未找到项目的独立 Python 环境。")
        args = [str(pythonw), "-B", "-s", "-X", "utf8", str(root / "main.py")]
    return subprocess.list2cmdline(args) + ' "%1"'


def install_menu(root: Path):
    command = command_for(root)
    for ext in EXTENSIONS:
        key_path = BASE + "\\" + ext + "\\shell\\" + VERB
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "合并为 PDF（合页）")
            winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            icon = str(Path(sys.executable).resolve()) if getattr(sys, "frozen", False) else str(root / "assets" / "app.ico")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon)
            winreg.SetValueEx(key, "PDFeditOwner", 0, winreg.REG_SZ, "PDFedit-v1")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + "\\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    return "已安装当前用户的右键菜单。\n选中图片或 PDF后右键 → 合并为 PDF（合页）。\n\nWindows 11 通常需要先点「显示更多选项」。\n超过 100 个文件请拖入软件或添加文件夹。\n移动软件文件夹后请重新安装右键菜单。"


def uninstall_menu():
    for ext in EXTENSIONS:
        path = BASE + "\\" + ext + "\\shell\\" + VERB
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                owner = winreg.QueryValueEx(key, "PDFeditOwner")[0]
            if owner != "PDFedit-v1":
                continue
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path + "\\command")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    return "已卸载合页的右键菜单，其他右键项目未改动。"
