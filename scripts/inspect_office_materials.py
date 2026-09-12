#!/usr/bin/env python3
"""Portable, read-only OOXML preflight for XLSX, PPTX and DOCX inputs.

This script inventories package structure only. It never converts Office files,
recalculates formulas, expands hidden content, executes macros, or authorizes a
formal evidence bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from path_safety import first_link_component, is_link_or_junction


SUPPORTED = {".xlsx": "xlsx", ".pptx": "pptx", ".docx": "docx"}
UNSUPPORTED_OFFICE = {".doc", ".xls", ".xlsm", ".ppt", ".pptm"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
BLOCKED_CODES = {
    "INPUT_LINK_UNSAFE",
    "MATERIAL_READ_FAILED",
    "OFFICE_ENCRYPTED_OR_CORRUPT",
    "OFFICE_FORMAT_UNSUPPORTED",
    "OFFICE_PACKAGE_TYPE_MISMATCH",
    "OFFICE_PACKAGE_UNSAFE",
    "OFFICE_SOURCE_CHANGED",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def technical_skip(path: Path) -> tuple[str, str] | None:
    if path.name.startswith("~$"):
        return "Office 临时锁文件；不读取内容", "OFFICE_TEMP_LOCKFILE"
    if path.name.lower() == ".ds_store":
        return "系统元数据文件；不作为材料读取", "OFFICE_SYSTEM_METADATA"
    return None


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def relationship_map(zf: zipfile.ZipFile, rels_part: str) -> dict[str, str]:
    if rels_part not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(rels_part))
    return {
        rel.attrib.get("Id", ""): rel.attrib.get("Target", "")
        for rel in root.iter()
        if rel.tag.endswith("Relationship") and rel.attrib.get("Id")
    }


def resolve_part(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def external_relationship_count(zf: zipfile.ZipFile) -> int:
    count = 0
    for name in zf.namelist():
        if not name.endswith(".rels") or name.endswith("/"):
            continue
        try:
            root = ET.fromstring(zf.read(name))
        except (ET.ParseError, KeyError):
            continue
        count += sum(
            1
            for rel in root.iter()
            if rel.tag.endswith("Relationship") and rel.attrib.get("TargetMode") == "External"
        )
    return count


def zip_safety(zf: zipfile.ZipFile) -> list[str]:
    total = 0
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            return ["OFFICE_PACKAGE_UNSAFE"]
        if info.is_dir():
            continue
        total += info.file_size
        if info.file_size > 512 * 1024 * 1024 or total > 2 * 1024 * 1024 * 1024:
            return ["OFFICE_PACKAGE_UNSAFE"]
        if info.compress_size and info.file_size / info.compress_size > 1000:
            return ["OFFICE_PACKAGE_UNSAFE"]
    return []


def package_kind(zf: zipfile.ZipFile) -> str | None:
    root = ET.fromstring(zf.read("[Content_Types].xml"))
    content_types = {node.attrib.get("ContentType", "") for node in root.iter()}
    if "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml" in content_types:
        return "xlsx"
    if "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml" in content_types:
        return "pptx"
    if "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" in content_types:
        return "docx"
    return None


def inspect_xlsx(zf: zipfile.ZipFile) -> tuple[dict[str, Any], list[str]]:
    names = set(zf.namelist())
    workbook_part = "xl/workbook.xml"
    if workbook_part not in names:
        raise ValueError("缺少 xl/workbook.xml")
    workbook = ET.fromstring(zf.read(workbook_part))
    rels = relationship_map(zf, "xl/_rels/workbook.xml.rels")

    print_areas: dict[int, str] = {}
    for node in workbook.iter():
        if node.tag.endswith("definedName") and node.attrib.get("name") == "_xlnm.Print_Area":
            local_id = node.attrib.get("localSheetId")
            if local_id is not None:
                print_areas[int(local_id)] = node.text or ""

    sheets: list[dict[str, Any]] = []
    codes: list[str] = []
    for index, sheet in enumerate((n for n in workbook.iter() if n.tag.endswith("sheet")), start=1):
        rid = sheet.attrib.get(f"{{{REL_NS}}}id", "")
        target = rels.get(rid, "")
        part = resolve_part(workbook_part, target) if target else ""
        state = sheet.attrib.get("state", "visible")
        entry: dict[str, Any] = {
            "sheet_index": index,
            "sheet_name": sheet.attrib.get("name", ""),
            "state": state,
            "part": part,
            "print_area": print_areas.get(index - 1),
            "hidden_rows": [],
            "hidden_columns": [],
            "formula_count": 0,
            "formula_cache_missing_count": 0,
        }
        if state != "visible":
            codes.append("OFFICE_HIDDEN_CONTENT")
        if not entry["print_area"]:
            codes.append("OFFICE_PRINT_SCOPE_UNRESOLVED")
        if part not in names:
            codes.append("OFFICE_PACKAGE_TYPE_MISMATCH")
            sheets.append(entry)
            continue
        xml = ET.fromstring(zf.read(part))
        for row in (n for n in xml.iter() if n.tag.endswith("row")):
            if row.attrib.get("hidden") in {"1", "true"}:
                entry["hidden_rows"].append(row.attrib.get("r"))
        for col in (n for n in xml.iter() if n.tag.endswith("col")):
            if col.attrib.get("hidden") in {"1", "true"}:
                entry["hidden_columns"].append(f"{col.attrib.get('min')}:{col.attrib.get('max')}")
        for cell in (n for n in xml.iter() if n.tag.endswith("c")):
            has_formula = any(child.tag.endswith("f") for child in cell)
            if not has_formula:
                continue
            entry["formula_count"] += 1
            if not any(child.tag.endswith("v") and child.text is not None for child in cell):
                entry["formula_cache_missing_count"] += 1
        if entry["hidden_rows"] or entry["hidden_columns"]:
            codes.append("OFFICE_HIDDEN_CONTENT")
        if entry["formula_cache_missing_count"]:
            codes.append("OFFICE_FORMULA_CACHE_UNVERIFIED")
        sheets.append(entry)

    external_links = sum(1 for name in names if name.startswith("xl/externalLinks/externalLink") and name.endswith(".xml"))
    external_relationships = external_relationship_count(zf)
    comments = sum(
        1
        for name in names
        if (name.startswith("xl/comments") or name.startswith("xl/threadedComments/") or name.startswith("xl/persons/"))
        and name.endswith(".xml")
    )
    embedded = sum(1 for name in names if name.startswith("xl/embeddings/") and not name.endswith("/"))
    media = sum(1 for name in names if name.startswith("xl/media/") and not name.endswith("/"))
    charts = sum(1 for name in names if name.startswith("xl/charts/") and name.endswith(".xml"))
    macros = any("vbaProject" in name for name in names)
    if external_links or external_relationships:
        codes.append("OFFICE_EXTERNAL_LINKS")
    if comments:
        codes.append("OFFICE_COMMENTS_PRESENT")
    if embedded:
        codes.append("OFFICE_EMBEDDED_OBJECT")
    if macros:
        codes.append("OFFICE_MACRO_PRESENT")
    return {
        "worksheets": sheets,
        "external_links": external_links,
        "external_relationships": external_relationships,
        "comments": comments,
        "embedded_objects": embedded,
        "media_files": media,
        "charts": charts,
        "macros_present": macros,
    }, unique(codes)


def inspect_pptx(zf: zipfile.ZipFile) -> tuple[dict[str, Any], list[str]]:
    names = set(zf.namelist())
    presentation_part = "ppt/presentation.xml"
    if presentation_part not in names:
        raise ValueError("缺少 ppt/presentation.xml")
    presentation = ET.fromstring(zf.read(presentation_part))
    rels = relationship_map(zf, "ppt/_rels/presentation.xml.rels")
    slides: list[dict[str, Any]] = []
    codes: list[str] = []
    slide_nodes = [node for node in presentation.iter() if node.tag.endswith("sldId")]
    for index, slide in enumerate(slide_nodes, start=1):
        rid = slide.attrib.get(f"{{{REL_NS}}}id", "")
        target = rels.get(rid, "")
        part = resolve_part(presentation_part, target) if target else ""
        hidden = slide.attrib.get("show") in {"0", "false"}
        if part not in names:
            codes.append("PPT_SLIDE_ORDER_OR_VISIBILITY_UNRESOLVED")
        else:
            slide_root = ET.fromstring(zf.read(part))
            hidden = hidden or slide_root.attrib.get("show") in {"0", "false"}
            shape_ids = [
                node.attrib.get("id", "")
                for node in slide_root.iter()
                if node.tag.endswith("cNvPr") and node.attrib.get("id")
            ]
        if part not in names:
            shape_ids = []
        if hidden:
            codes.append("PPT_SLIDE_ORDER_OR_VISIBILITY_UNRESOLVED")
        slides.append({"slide_index": index, "part": part, "hidden": hidden, "shape_ids": shape_ids})

    notes = sum(1 for name in names if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml"))
    comments = sum(1 for name in names if name.startswith("ppt/comments/") and name.endswith(".xml"))
    comment_authors = "ppt/commentAuthors.xml" in names
    embedded = sum(1 for name in names if name.startswith("ppt/embeddings/") and not name.endswith("/"))
    media = sum(1 for name in names if name.startswith("ppt/media/") and not name.endswith("/"))
    charts = sum(1 for name in names if name.startswith("ppt/charts/") and name.endswith(".xml"))
    macros = any("vbaProject" in name for name in names)
    external_relationships = external_relationship_count(zf)
    if notes or comments or comment_authors:
        codes.append("PPT_NOTES_OR_COMMENTS_PRESENT")
    if embedded:
        codes.append("PPT_EMBEDDED_OBJECT")
    if macros:
        codes.append("OFFICE_MACRO_PRESENT")
    if external_relationships:
        codes.append("OFFICE_EXTERNAL_LINKS")
    return {
        "slides": slides,
        "notes_parts": notes,
        "comments": comments,
        "comment_authors_present": comment_authors,
        "embedded_objects": embedded,
        "media_files": media,
        "charts": charts,
        "macros_present": macros,
        "external_relationships": external_relationships,
    }, unique(codes)


def inspect_docx(zf: zipfile.ZipFile) -> tuple[dict[str, Any], list[str]]:
    names = set(zf.namelist())
    document_part = "word/document.xml"
    if document_part not in names:
        raise ValueError("缺少 word/document.xml")
    document = ET.fromstring(zf.read(document_part))
    codes: list[str] = []
    comments = sum(
        1
        for name in names
        if name.startswith("word/comments") and name.endswith(".xml")
    )
    revisions = sum(
        1
        for node in document.iter()
        if node.tag.endswith(("}ins", "}del", "}moveFrom", "}moveTo"))
    )
    hidden_text = sum(1 for node in document.iter() if node.tag.endswith("}vanish"))
    embedded = sum(
        1
        for name in names
        if (name.startswith("word/embeddings/") or name.startswith("word/oleObject"))
        and not name.endswith("/")
    )
    media = sum(1 for name in names if name.startswith("word/media/") and not name.endswith("/"))
    headers = sum(1 for name in names if name.startswith("word/header") and name.endswith(".xml"))
    footers = sum(1 for name in names if name.startswith("word/footer") and name.endswith(".xml"))
    macros = any("vbaProject" in name for name in names)
    external_relationships = external_relationship_count(zf)
    if comments:
        codes.append("OFFICE_COMMENTS_PRESENT")
    if revisions:
        codes.append("OFFICE_TRACKED_CHANGES_PRESENT")
    if hidden_text:
        codes.append("OFFICE_HIDDEN_CONTENT")
    if embedded:
        codes.append("OFFICE_EMBEDDED_OBJECT")
    if macros:
        codes.append("OFFICE_MACRO_PRESENT")
    if external_relationships:
        codes.append("OFFICE_EXTERNAL_LINKS")
    return {
        "document_part": document_part,
        "parts": sorted(
            name for name in names
            if name == document_part
            or (name.startswith("word/header") and name.endswith(".xml"))
            or (name.startswith("word/footer") and name.endswith(".xml"))
        ),
        "comments": comments,
        "tracked_changes": revisions,
        "hidden_text_runs": hidden_text,
        "embedded_objects": embedded,
        "media_files": media,
        "headers": headers,
        "footers": footers,
        "macros_present": macros,
        "external_relationships": external_relationships,
    }, unique(codes)


def status_for(codes: list[str], errors: list[str]) -> str:
    if errors or any(code in BLOCKED_CODES for code in codes):
        return "BLOCKED"
    return "HOLD" if codes else "PASS"


def inspect_office(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    expected = SUPPORTED[path.suffix.lower()]
    record: dict[str, Any] = {
        "relative_path": relative,
        "format": expected,
        "classification": "office_source",
        "source_snapshot": {},
        "package_inspection": {},
        "failure_codes": [],
        "errors": [],
    }
    if is_link_or_junction(path):
        record["failure_codes"] = ["INPUT_LINK_UNSAFE"]
        record["status"] = "BLOCKED"
        return record
    try:
        before_stat = path.stat()
        before_hash = sha256(path)
        record["source_snapshot"] = {
            "size": before_stat.st_size,
            "mtime_ns": before_stat.st_mtime_ns,
            "sha256": before_hash,
            "read_only": True,
        }
        with zipfile.ZipFile(path) as zf:
            safety_codes = zip_safety(zf)
            if safety_codes:
                record["failure_codes"].extend(safety_codes)
            else:
                actual = package_kind(zf)
                record["package_inspection"]["detected_format"] = actual
                if actual != expected:
                    record["failure_codes"].append("OFFICE_PACKAGE_TYPE_MISMATCH")
                elif expected == "xlsx":
                    details, codes = inspect_xlsx(zf)
                    record["package_inspection"].update(details)
                    record["failure_codes"].extend(codes)
                elif expected == "pptx":
                    details, codes = inspect_pptx(zf)
                    record["package_inspection"].update(details)
                    record["failure_codes"].extend(codes)
                else:
                    details, codes = inspect_docx(zf)
                    record["package_inspection"].update(details)
                    record["failure_codes"].extend(codes)
        after_stat = path.stat()
        after_hash = sha256(path)
        unchanged = (
            before_stat.st_size == after_stat.st_size
            and before_stat.st_mtime_ns == after_stat.st_mtime_ns
            and before_hash == after_hash
        )
        record["source_snapshot"]["unchanged"] = unchanged
        if not unchanged:
            record["failure_codes"].append("OFFICE_SOURCE_CHANGED")
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, ValueError) as exc:
        record["failure_codes"].append("OFFICE_ENCRYPTED_OR_CORRUPT")
        record["errors"].append(f"Office 包损坏、加密或结构不可读：{type(exc).__name__}: {exc}")
    except Exception as exc:
        record["failure_codes"].append("MATERIAL_READ_FAILED")
        record["errors"].append(f"Office 文件读取失败：{type(exc).__name__}: {exc}")
    record["failure_codes"] = unique(record["failure_codes"])
    record["status"] = status_for(record["failure_codes"], record["errors"])
    return record


def resolve_output(root: Path, raw_output: Path, overwrite: bool) -> Path:
    candidate = raw_output.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if is_link_or_junction(candidate):
        raise SystemExit("盘点输出不得是符号链接或目录联接")
    probe = candidate
    while probe != probe.parent:
        if probe.exists() and is_link_or_junction(probe):
            raise SystemExit("盘点输出父级不得是符号链接或目录联接")
        probe = probe.parent
    output = candidate.resolve()
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise SystemExit(f"盘点输出不得写入材料目录：{output}")
    if output.exists() and output.is_dir():
        raise SystemExit(f"盘点输出必须是文件：{output}")
    if output.exists() and not overwrite:
        raise SystemExit(f"拒绝覆盖已存在盘点输出：{output}；如确需覆盖请使用 --overwrite")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="只读预检 XLSX/PPTX/DOCX 包结构；不转换、不生成证据卷")
    parser.add_argument("material_dir", help="材料目录")
    parser.add_argument("--output", required=True, help="Office 预检 JSON 输出路径")
    parser.add_argument("--overwrite", action="store_true", help="显式允许覆盖既有预检 JSON")
    args = parser.parse_args()

    raw_root = Path(args.material_dir).expanduser()
    if not raw_root.is_absolute():
        raw_root = Path.cwd() / raw_root
    if first_link_component(raw_root) is not None:
        raise SystemExit("材料目录不得经过符号链接或目录联接")
    root = raw_root.resolve()
    if not root.is_dir():
        raise SystemExit(f"材料目录不存在：{root}")
    output_path = resolve_output(root, Path(args.output), args.overwrite)
    records: list[dict[str, Any]] = []
    technical_skips: list[dict[str, str]] = []
    ignored_non_office: list[str] = []
    candidates = (path for path in root.rglob("*") if path.is_file() and path.resolve() != output_path)
    for path in sorted(candidates, key=lambda item: str(item).lower()):
        relative = path.relative_to(root).as_posix()
        if is_link_or_junction(path):
            technical_skips.append({"relative_path": relative, "reason": "符号链接或目录联接；不读取内容", "failure_code": "INPUT_LINK_UNSAFE"})
            continue
        skip = technical_skip(path)
        if skip:
            reason, code = skip
            technical_skips.append({"relative_path": relative, "reason": reason, "failure_code": code})
        elif path.suffix.lower() in SUPPORTED:
            records.append(inspect_office(path, root))
        elif path.suffix.lower() in UNSUPPORTED_OFFICE:
            records.append(
                {
                    "relative_path": relative,
                    "format": path.suffix.lower().lstrip("."),
                    "classification": "unsupported_office",
                    "source_snapshot": {},
                    "package_inspection": {},
                    "failure_codes": ["OFFICE_FORMAT_UNSUPPORTED"],
                    "errors": ["v18 仅执行 XLSX/PPTX/DOCX OOXML 预检；旧二进制格式不自动转换"],
                    "status": "BLOCKED",
                }
            )
        else:
            ignored_non_office.append(relative)

    statuses = [item["status"] for item in records]
    overall = "BLOCKED" if "BLOCKED" in statuses else ("HOLD" if "HOLD" in statuses else "PASS")
    output = {
        "schema_version": 1,
        "inspector_version": "18.0",
        "root_label": root.name,
        "office_file_count": len(records),
        "technical_skip_count": len(technical_skips),
        "ignored_non_office_count": len(ignored_non_office),
        "files": records,
        "technical_skips": technical_skips,
        "ignored_non_office": ignored_non_office,
        "overall_status": overall,
        "read_only": True,
        "formal_bundle_authorized": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"已预检 {len(records)} 个 Office 文件；跳过 {len(technical_skips)} 个技术文件；"
        f"状态 {overall}。未转换源文件，未生成证据卷。"
    )
    if overall != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
