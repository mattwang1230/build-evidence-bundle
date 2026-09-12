#!/usr/bin/env python3
"""Conservatively convert one OOXML file into review pages and a v18 sidecar.

LibreOffice and a PDF rasterizer are optional local tools.  This command never
downloads them, never uses the user's Office profile, and never edits the
source.  Automatic conversion remains HOLD until source scope, fonts, privacy,
blank pages and rendered appearance are reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inspect_office_materials import SUPPORTED, inspect_office, is_link_or_junction
from office_capabilities import discover, safe_version
from path_safety import first_link_component


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def ensure_inside(path: Path, root: Path, label: str) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if first_link_component(candidate) is not None:
        raise SystemExit(f"{label} 不得经过符号链接或目录联接")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise SystemExit(f"{label} 必须位于 --workspace-root 内")
    probe = root.resolve()
    for part in resolved.relative_to(root.resolve()).parts:
        probe = probe / part
        if is_link_or_junction(probe):
            raise SystemExit(f"{label} 不得经过符号链接或目录联接")
    return resolved


def run_tool(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )


def package_record(source_id: str, preflight: dict[str, Any]) -> dict[str, Any]:
    details = preflight.get("package_inspection", {})
    codes = list(preflight.get("failure_codes", []))
    hold_fields = {
        "OFFICE_HIDDEN_CONTENT",
        "OFFICE_PRINT_SCOPE_UNRESOLVED",
        "OFFICE_FORMULA_CACHE_UNVERIFIED",
        "OFFICE_EXTERNAL_LINKS",
        "OFFICE_COMMENTS_PRESENT",
        "OFFICE_TRACKED_CHANGES_PRESENT",
        "OFFICE_EMBEDDED_OBJECT",
        "OFFICE_MACRO_PRESENT",
        "PPT_NOTES_OR_COMMENTS_PRESENT",
        "PPT_EMBEDDED_OBJECT",
        "PPT_SLIDE_ORDER_OR_VISIBILITY_UNRESOLVED",
    }
    status = "blocked" if preflight.get("status") == "BLOCKED" else ("hold" if set(codes) & hold_fields else "pass")
    return {
        "source_id": source_id,
        "format": preflight.get("format"),
        "zip_valid": preflight.get("status") != "BLOCKED",
        "content_type_valid": "OFFICE_PACKAGE_TYPE_MISMATCH" not in codes,
        "encrypted": "unknown" if preflight.get("status") == "BLOCKED" else False,
        "macros": "present" if details.get("macros_present") else "absent",
        "external_links": "present" if details.get("external_links") or details.get("external_relationships") else "absent",
        "comments_notes": "present" if details.get("comments") or details.get("notes_parts") or details.get("tracked_changes") else "absent",
        "hidden_content": "present" if "OFFICE_HIDDEN_CONTENT" in codes else "absent",
        "embedded_objects": "present" if details.get("embedded_objects") else "absent",
        "failure_codes": codes,
        "status": status,
    }


def automatic_locators(
    source_id: str,
    preflight: dict[str, Any],
    page_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    details = preflight.get("package_inspection", {})
    kind = preflight.get("format")
    locators: list[dict[str, Any]] = []
    failures = ["PROVENANCE_SCOPE_NOT_CONFIRMED", "RENDER_REVIEW_UNAVAILABLE"]
    if kind == "pptx":
        slides = [item for item in details.get("slides", []) if not item.get("hidden")]
        if len(slides) != page_count:
            return [], failures + ["OFFICE_PAGE_MAP_MISMATCH"]
        for page, slide in enumerate(slides, start=1):
            locators.append(
                {
                    "source_id": source_id,
                    "unit_id": f"{source_id}-U{page:03d}",
                    "kind": "pptx_slide",
                    "sheet_index": None,
                    "sheet_name": None,
                    "cell_range": None,
                    "slide_index": slide.get("slide_index"),
                    "part": slide.get("part"),
                    "shape_id": None,
                    "visibility": "visible",
                    "user_confirmed_scope": False,
                }
            )
    elif kind == "xlsx":
        sheets = [item for item in details.get("worksheets", []) if item.get("state") == "visible"]
        if len(sheets) != page_count:
            return [], failures + ["OFFICE_PAGE_MAP_MISMATCH"]
        for page, sheet in enumerate(sheets, start=1):
            if not sheet.get("print_area"):
                failures.append("OFFICE_PRINT_SCOPE_UNRESOLVED")
            locators.append(
                {
                    "source_id": source_id,
                    "unit_id": f"{source_id}-U{page:03d}",
                    "kind": "xlsx_range",
                    "sheet_index": sheet.get("sheet_index"),
                    "sheet_name": sheet.get("sheet_name"),
                    "cell_range": sheet.get("print_area"),
                    "slide_index": None,
                    "part": sheet.get("part"),
                    "shape_id": None,
                    "visibility": "visible",
                    "user_confirmed_scope": False,
                }
            )
    else:
        for page in range(1, page_count + 1):
            locators.append(
                {
                    "source_id": source_id,
                    "unit_id": f"{source_id}-U{page:03d}",
                    "kind": "docx_part",
                    "sheet_index": None,
                    "sheet_name": None,
                    "cell_range": None,
                    "slide_index": None,
                    "part": "word/document.xml",
                    "shape_id": None,
                    "visibility": "visible",
                    "user_confirmed_scope": False,
                }
            )
    return locators, list(dict.fromkeys(failures))


def main() -> None:
    parser = argparse.ArgumentParser(description="隔离转换单个 XLSX/PPTX/DOCX，并生成 v18 Office provenance sidecar")
    parser.add_argument("source", help="Office 源文件")
    parser.add_argument("--workspace-root", required=True, help="包含源文件和输出目录的本地工作区根目录")
    parser.add_argument("--output-dir", required=True, help="全新输出目录；不得覆盖既有目录")
    parser.add_argument("--source-id", default="O001", help="稳定 Office 来源编号")
    parser.add_argument("--office-converter", help="显式指定 soffice/libreoffice")
    parser.add_argument("--pdf-rasterizer", help="显式指定 pdftoppm/mutool")
    args = parser.parse_args()

    raw_root = Path(args.workspace_root).expanduser()
    if first_link_component(raw_root) is not None:
        raise SystemExit("--workspace-root 不得为符号链接或目录联接")
    root = raw_root.resolve()
    if not root.is_dir():
        raise SystemExit("--workspace-root 不存在")
    source = ensure_inside(Path(args.source), root, "源文件")
    output_dir = ensure_inside(Path(args.output_dir), root, "输出目录")
    if not source.is_file() or is_link_or_junction(source):
        raise SystemExit("源文件不存在或为符号链接")
    if source.suffix.lower() not in SUPPORTED:
        raise SystemExit("仅支持 XLSX/PPTX/DOCX；旧二进制 Office 格式不自动转换")
    if output_dir.exists():
        raise SystemExit("拒绝覆盖既有输出目录；请使用全新目录")

    before_stat = source.stat()
    before_hash = sha256(source)
    preflight = inspect_office(source, root)
    source_id = args.source_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", source_id) or ".." in source_id:
        raise SystemExit("--source-id 只能使用安全的字母、数字、点、下划线和连字符")
    package = package_record(source_id, preflight)
    failures = list(package["failure_codes"])
    status = "BLOCKED" if package["status"] == "blocked" else "HOLD"
    started_at = utc_now()
    office, office_discovery = discover(args.office_converter, ["soffice", "libreoffice"])
    rasterizer, raster_discovery = discover(args.pdf_rasterizer, ["pdftoppm", "mutool"])
    office_version_status, office_version = safe_version(office, ["--version"]) if office else ("unavailable", "")
    raster_version_status, raster_version = safe_version(rasterizer, ["-v"]) if rasterizer else ("unavailable", "")
    if not office or office_version_status != "available":
        failures.append("OFFICE_CONVERTER_UNAVAILABLE" if not office else "OFFICE_CONVERTER_FAILED")
    if not rasterizer or raster_version_status != "available":
        failures.append("OFFICE_RASTERIZER_UNAVAILABLE" if not rasterizer else "OFFICE_RASTERIZER_FAILED")

    pdf_final: Path | None = None
    rendered_files: list[Path] = []
    tool_failure = bool({"OFFICE_CONVERTER_UNAVAILABLE", "OFFICE_CONVERTER_FAILED", "OFFICE_RASTERIZER_UNAVAILABLE", "OFFICE_RASTERIZER_FAILED"} & set(failures))
    if not tool_failure and package["status"] == "pass":
        try:
            with tempfile.TemporaryDirectory(prefix="evidence-office-") as temp_name:
                temp = Path(temp_name)
                profile = temp / "profile"
                converted = temp / "converted"
                rendered = temp / "rendered"
                profile.mkdir()
                converted.mkdir()
                rendered.mkdir()
                profile_uri = profile.resolve().as_uri()
                result = run_tool(
                    [
                        office,
                        f"-env:UserInstallation={profile_uri}",
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(converted),
                        str(source),
                    ]
                )
                pdf = converted / f"{source.stem}.pdf"
                if result.returncode != 0 or not pdf.is_file():
                    failures.append("OFFICE_CONVERTER_FAILED")
                else:
                    if Path(rasterizer).name.lower().startswith("mutool"):
                        result = run_tool([rasterizer, "draw", "-r", "180", "-o", str(rendered / "page-%03d.png"), str(pdf)])
                    else:
                        result = run_tool([rasterizer, "-png", "-r", "180", str(pdf), str(rendered / "page")])
                    rendered_files = sorted(rendered.glob("*.png"))
                    if result.returncode != 0 or not rendered_files:
                        failures.append("OFFICE_RASTERIZER_FAILED")
                    else:
                        output_dir.mkdir(parents=True)
                        pdf_final = output_dir / f"{source_id}.pdf"
                        shutil.copy2(pdf, pdf_final)
                        final_pages: list[Path] = []
                        for index, page in enumerate(rendered_files, start=1):
                            target = output_dir / f"{source_id}-page-{index:03d}.png"
                            shutil.copy2(page, target)
                            final_pages.append(target)
                        rendered_files = final_pages
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"OFFICE_CONVERTER_FAILED:{type(exc).__name__}")

    after_stat = source.stat()
    after_hash = sha256(source)
    unchanged = (
        before_stat.st_size == after_stat.st_size
        and before_stat.st_mtime_ns == after_stat.st_mtime_ns
        and before_hash == after_hash
    )
    if not unchanged:
        failures.append("OFFICE_SOURCE_CHANGED")
        status = "BLOCKED"
        for generated in [*rendered_files, *([pdf_final] if pdf_final else [])]:
            if generated.is_file():
                generated.unlink()
        rendered_files = []
        pdf_final = None
        if output_dir.is_dir() and not any(output_dir.iterdir()):
            output_dir.rmdir()
    if rendered_files and pdf_final:
        locators, locator_failures = automatic_locators(source_id, preflight, len(rendered_files))
        failures.extend(locator_failures)
    else:
        locators = []

    failures = list(dict.fromkeys(failures))
    hard_codes = {
        "OFFICE_SOURCE_CHANGED",
        "OFFICE_CONVERTER_FAILED",
        "OFFICE_RASTERIZER_FAILED",
        "OFFICE_PAGE_MAP_MISMATCH",
        "OFFICE_ENCRYPTED_OR_CORRUPT",
        "OFFICE_PACKAGE_TYPE_MISMATCH",
        "OFFICE_PACKAGE_UNSAFE",
    }
    if any(code.split(":", 1)[0] in hard_codes for code in failures):
        status = "BLOCKED"
    page_map = []
    for ordinal, (locator, page) in enumerate(zip(locators, rendered_files), start=1):
        page_map.append(
            {
                "unit_id": locator["unit_id"],
                "pdf_page": ordinal,
                "rendered_relative_path": relative_path(page, root),
                "rendered_sha256": sha256(page),
                "attachment_ordinal": ordinal,
                "docx_bookmark": f"evidence_page_{ordinal:04d}",
                "docx_physical_page": None,
                "blank_page": None,
                "header_only": None,
                "font_substitution": "unknown",
                "privacy_review": "hold",
            }
        )
    snapshot = {
        "source_id": source_id,
        "relative_path": relative_path(source, root),
        "source_kind": "native_office",
        "size": before_stat.st_size,
        "mtime_ns": before_stat.st_mtime_ns,
        "sha256": before_hash,
        "read_before": before_hash,
        "read_after": after_hash,
        "unchanged": unchanged,
        "read_only": True,
    }
    conversion = {
        "source_id": source_id,
        "tool": Path(office).name if office else "none",
        "tool_version": office_version,
        "platform": platform.system(),
        "arguments_summary": "headless; isolated profile; fixed output directory",
        "profile_isolated": True if office else False,
        "started_at": started_at,
        "finished_at": utc_now(),
        "pdf_relative_path": relative_path(pdf_final, root) if pdf_final else "",
        "pdf_sha256": sha256(pdf_final) if pdf_final else "",
        "pdf_page_count": len(rendered_files),
        "rasterizer": Path(rasterizer).name if rasterizer else "none",
        "rasterizer_version": raster_version,
        "discovery": {"office": office_discovery, "rasterizer": raster_discovery},
        "status": "pass" if rendered_files and pdf_final and unchanged else ("blocked" if status == "BLOCKED" else "hold"),
    }
    sidecar = {
        "schema_version": 1,
        "route": "v2_sidecar",
        "path_base": "manifest_dir",
        "source_snapshot": [snapshot],
        "package_inspection": [package],
        "source_locators": locators,
        "conversion_record": [conversion],
        "page_map": page_map,
        "formal_release_gate": {"status": status, "failure_codes": failures},
    }
    if not output_dir.exists():
        output_dir.mkdir(parents=True)
    sidecar_path = output_dir / "office-provenance.json"
    sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{status}: {sidecar_path.name}")
    print("源文件未修改；自动转换结果仍需人工确认范围、字体、空白页、隐私和页面可读性。")
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
