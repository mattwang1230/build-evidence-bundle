#!/usr/bin/env python3
"""Portable local capability probe. No downloads, uploads, or private path output."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from path_safety import redact_local_paths


def package_status(distribution: str, module: str) -> dict[str, str]:
    try:
        version = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return {"status": "unavailable", "version": ""}
    try:
        importlib.import_module(module)
    except Exception:
        return {"status": "failed", "version": version}
    return {"status": "available", "version": version}


def discover(explicit: str | None, names: list[str]) -> tuple[str | None, str]:
    if explicit:
        path = Path(explicit).expanduser()
        return (str(path), "explicit") if path.is_file() else (None, "explicit")
    for name in names:
        found = shutil.which(name)
        if found:
            return found, "PATH"
    return None, "none"


def safe_version(executable: str, arguments: list[str]) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            [executable, *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "failed", ""
    if completed.returncode != 0:
        return "failed", ""
    line = next((item.strip() for item in completed.stdout.splitlines() if item.strip()), "")
    if not line:
        return "unknown", ""
    return "available", redact_local_paths(line)[:200]


def tool_status(explicit: str | None, names: list[str], version_args: list[str]) -> dict[str, str]:
    executable, discovery = discover(explicit, names)
    if not executable:
        return {"status": "unavailable", "tool": "none", "version": "", "discovery": discovery}
    status, version = safe_version(executable, version_args)
    return {
        "status": status,
        "tool": Path(executable).name,
        "version": version,
        "discovery": discovery,
    }


def probe(args: argparse.Namespace) -> dict[str, Any]:
    office = tool_status(args.office_converter, ["soffice", "libreoffice"], ["--version"])
    rasterizer = tool_status(args.pdf_rasterizer, ["pdftoppm", "mutool"], ["-v"])
    ffmpeg = tool_status(args.ffmpeg, ["ffmpeg"], ["-version"])
    ffprobe = tool_status(args.ffprobe, ["ffprobe"], ["-version"])
    video_status = "available" if ffmpeg["status"] == ffprobe["status"] == "available" else "unavailable"
    return {
        "schema_version": 1,
        "platform": {
            "system": platform.system(),
            "python": platform.python_version(),
            "arch": platform.machine(),
        },
        "capabilities": {
            "python_pillow": package_status("Pillow", "PIL.Image"),
            "python_docx": package_status("python-docx", "docx"),
            "office_to_pdf": office,
            "pdf_to_png": rasterizer,
            "video": {"status": video_status, "ffmpeg": ffmpeg, "ffprobe": ffprobe},
        },
        "network_required": False,
        "executable_paths_exposed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="检测本地可移植运行能力；不下载工具、不读取案件材料")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--office-converter", help="显式指定 soffice/libreoffice 可执行文件")
    parser.add_argument("--pdf-rasterizer", help="显式指定 pdftoppm/mutool 可执行文件")
    parser.add_argument("--ffmpeg", help="显式指定 ffmpeg")
    parser.add_argument("--ffprobe", help="显式指定 ffprobe")
    args = parser.parse_args()
    result = probe(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for name, value in result["capabilities"].items():
        status = value.get("status", "unknown")
        print(f"{name}: {status}")


if __name__ == "__main__":
    main()
