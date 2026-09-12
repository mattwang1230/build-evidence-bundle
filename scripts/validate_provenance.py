#!/usr/bin/env python3
"""Validate the v18 Office provenance sidecar with stdlib and Pillow.

Office-derived pages are never accepted on file extension alone.  Every page
must bind the Manifest material to a stable Office source, source locator,
conversion record, rendered page and a PASS release gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, UnidentifiedImageError

from inspect_office_materials import SUPPORTED, inspect_office
from path_safety import contains_local_path, is_link_or_junction


OFFICE_ORIGINS = {"office_derived", "office-derived", "office_render", "office-render"}
V18_ORIGINS = OFFICE_ORIGINS | {"native_image", "scan_image", "photo", "screenshot", "video_frame", "generated_demo"}
ALLOWED_LOCATOR_KINDS = {"xlsx_range", "pptx_slide", "pptx_shape", "docx_part"}
UNKNOWN_VERSION_VALUES = {"", "unknown", "none", "unavailable", "n/a", "na"}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(raw: Any, base_dir: Path, label: str, errors: list[str]) -> Path | None:
    value = _text(raw)
    if not value:
        errors.append(f"{label} 缺少相对路径")
        return None
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        errors.append(f"PROVENANCE_PATH_UNSAFE：{label} 必须是 manifest 目录内的 POSIX 相对路径")
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        errors.append(f"PROVENANCE_PATH_UNSAFE：{label} 必须是 manifest 目录内的安全相对路径")
        return None
    probe = base_dir
    for part in candidate.parts:
        probe = probe / part
        if probe.exists() and is_link_or_junction(probe):
            errors.append(f"PROVENANCE_PATH_UNSAFE：{label} 不得经过符号链接")
            return None
    resolved = (base_dir / candidate).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        errors.append(f"PROVENANCE_PATH_UNSAFE：{label} 越出 manifest 目录")
        return None
    return resolved


def _contains_private_path(text: str) -> bool:
    return contains_local_path(text)


def _pdf_page_count(path: Path) -> int | None:
    data = path.read_bytes()
    count = len(re.findall(rb"/Type\s*/Page(?!s)\b", data))
    return count or None


def _pdf_has_private_path(path: Path) -> bool:
    return _contains_private_path(path.read_bytes().decode("latin-1", errors="ignore"))


def _inspect_rendered_page(path: Path) -> tuple[bool, bool, bool, bool]:
    """Return decodable, blank, header-only and private-metadata flags."""
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            if image.width <= 0 or image.height <= 0:
                return False, False, False, False
            rgb = image.convert("RGB")
            bbox = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white")).getbbox()
            blank = bbox is None
            header_only = bool(bbox and image.height >= 20 and bbox[3] <= max(1, image.height // 4))
            metadata = "\n".join(str(value) for value in image.info.values())
            return True, blank, header_only, _contains_private_path(metadata)
    except (OSError, ValueError, UnidentifiedImageError):
        return False, False, False, False


def _locator_matches(locator: dict[str, Any], inspection: dict[str, Any]) -> bool:
    details = inspection.get("package_inspection", {})
    kind = _text(locator.get("kind"))
    if kind == "xlsx_range" and inspection.get("format") == "xlsx":
        return any(
            sheet.get("sheet_index") == locator.get("sheet_index")
            and sheet.get("sheet_name") == locator.get("sheet_name")
            and sheet.get("part") == locator.get("part")
            and sheet.get("state") == "visible"
            and sheet.get("print_area") == locator.get("cell_range")
            for sheet in details.get("worksheets", [])
        )
    if kind in {"pptx_slide", "pptx_shape"} and inspection.get("format") == "pptx":
        for slide in details.get("slides", []):
            if (
                slide.get("slide_index") == locator.get("slide_index")
                and slide.get("part") == locator.get("part")
                and slide.get("hidden") is False
            ):
                return kind == "pptx_slide" or str(locator.get("shape_id")) in {
                    str(value) for value in slide.get("shape_ids", [])
                }
        return False
    if kind == "docx_part" and inspection.get("format") == "docx":
        return _text(locator.get("part")) in details.get("parts", [])
    return False


def _records(value: Any, name: str, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"Office sidecar 的 {name} 必须是数组")
        return []
    output: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            errors.append(f"Office sidecar 的 {name} 第{index}项必须是对象")
            continue
        output.append(item)
    return output


def _all_materials(data: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    groups = data.get("evidence_groups", [])
    if not isinstance(groups, list):
        return output
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("materials"), list):
            continue
        for material in group["materials"]:
            if isinstance(material, dict):
                output.append(material)
    return output


def _office_materials(data: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for material in _all_materials(data):
        origin = _text(
            material.get("origin_kind") or material.get("material_kind") or material.get("source_kind")
        ).lower()
        if "provenance_ref" in material or origin in OFFICE_ORIGINS or material.get("office_derived") is True:
            output.append(material)
    return output


def _index_unique(records: list[dict[str, Any]], field: str, label: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in records:
        key = _text(item.get(field))
        if not key:
            errors.append(f"{label} 缺少 {field}")
            continue
        if key in index:
            errors.append(f"{label} 的 {field} 重复：{key}")
            continue
        index[key] = item
    return index


def _locator_complete(locator: dict[str, Any]) -> bool:
    kind = _text(locator.get("kind"))
    if kind == "xlsx_range":
        return (
            type(locator.get("sheet_index")) is int
            and locator["sheet_index"] > 0
            and bool(_text(locator.get("sheet_name")))
            and bool(_text(locator.get("cell_range")))
        )
    if kind in {"pptx_slide", "pptx_shape"}:
        if type(locator.get("slide_index")) is not int or locator["slide_index"] <= 0:
            return False
        return kind != "pptx_shape" or bool(_text(locator.get("shape_id")))
    if kind == "docx_part":
        return bool(_text(locator.get("part")))
    return False


def validate_office_provenance(data: dict[str, Any], base_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """Return ``(fatal, blockers, warnings)`` for the v18 sidecar route.

    Office failures are fatal even for ``--allow-draft``: a draft may disclose
    missing facts, but it may not embed an unbound Office-derived page.
    """

    fatal: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []
    all_materials = _all_materials(data)
    materials = _office_materials(data)
    route_declared = any(key in data for key in ("provenance_route", "office_provenance"))
    if data.get("bundle_contract") == "v18":
        for material in all_materials:
            material_id = _text(material.get("material_id")) or "（无 material_id）"
            origin = _text(material.get("origin_kind")).lower()
            if origin not in V18_ORIGINS:
                fatal.append(f"MATERIAL_ORIGIN_REQUIRED：v18 材料 {material_id} 必须显式声明 origin_kind")
    if not materials and not route_declared:
        return fatal, blockers, warnings

    if data.get("bundle_contract") != "v18":
        fatal.append("OFFICE_CONTRACT_REQUIRED：Office 派生材料必须声明 bundle_contract=v18")
    if data.get("provenance_route") != "v2_sidecar":
        fatal.append("OFFICE_PROVENANCE_ROUTE_INVALID：Office 派生材料必须声明 provenance_route=v2_sidecar")
    if not materials:
        fatal.append("OFFICE_PROVENANCE_UNUSED：已声明 Office sidecar，但 Manifest 没有带 provenance_ref 的 Office 派生材料")

    sidecar_path = _safe_relative(data.get("office_provenance"), base_dir, "office_provenance", fatal)
    if sidecar_path is None:
        return fatal, blockers, warnings
    if not sidecar_path.is_file() or is_link_or_junction(sidecar_path):
        fatal.append("OFFICE_PROVENANCE_MISSING：Office sidecar 不存在或为符号链接")
        return fatal, blockers, warnings
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        fatal.append(f"OFFICE_PROVENANCE_INVALID：无法读取 Office sidecar（{type(exc).__name__}）")
        return fatal, blockers, warnings
    if not isinstance(sidecar, dict):
        fatal.append("OFFICE_PROVENANCE_INVALID：Office sidecar 顶层必须是对象")
        return fatal, blockers, warnings
    if sidecar.get("schema_version") != 1 or sidecar.get("route") != "v2_sidecar":
        fatal.append("OFFICE_PROVENANCE_INVALID：Office sidecar 必须为 schema_version=1、route=v2_sidecar")

    snapshots = _records(sidecar.get("source_snapshot"), "source_snapshot", fatal)
    inspections = _records(sidecar.get("package_inspection"), "package_inspection", fatal)
    locators = _records(sidecar.get("source_locators"), "source_locators", fatal)
    conversions = _records(sidecar.get("conversion_record"), "conversion_record", fatal)
    pages = _records(sidecar.get("page_map"), "page_map", fatal)
    snapshot_by_source = _index_unique(snapshots, "source_id", "source_snapshot", fatal)
    inspection_by_source = _index_unique(inspections, "source_id", "package_inspection", fatal)
    conversion_by_source = _index_unique(conversions, "source_id", "conversion_record", fatal)
    locator_by_unit = _index_unique(locators, "unit_id", "source_locators", fatal)

    page_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    pages_by_unit: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        unit_id = _text(page.get("unit_id"))
        pdf_page = page.get("pdf_page")
        if not unit_id or type(pdf_page) is not int or pdf_page <= 0:
            fatal.append("page_map 必须含非空 unit_id 和正整数 pdf_page")
            continue
        key = (unit_id, pdf_page)
        if key in page_by_key:
            fatal.append(f"page_map 重复：{unit_id} / PDF第{pdf_page}页")
            continue
        page_by_key[key] = page
        pages_by_unit.setdefault(unit_id, []).append(page)
        if unit_id not in locator_by_unit:
            fatal.append(f"OFFICE_PAGE_MAP_MISMATCH：page_map 引用未知 unit_id {unit_id}")

    used_sources: set[str] = set()
    used_page_keys: set[tuple[str, int]] = set()
    used_ordinals: set[int] = set()
    for expected_ordinal, material in enumerate(materials, start=1):
        material_id = _text(material.get("material_id")) or "（无 material_id）"
        if data.get("bundle_contract") == "v18":
            origin = _text(material.get("origin_kind")).lower()
            origin_valid = origin in OFFICE_ORIGINS
        else:
            origin = _text(
                material.get("origin_kind") or material.get("material_kind") or material.get("source_kind")
            ).lower()
            origin_valid = origin in OFFICE_ORIGINS or material.get("office_derived") is True
        if not origin_valid:
            fatal.append(f"OFFICE_ORIGIN_REQUIRED：材料 {material_id} 必须显式标记 origin_kind=office_derived")
        ref = material.get("provenance_ref")
        unit_id = ""
        pdf_page: int | None = None
        if isinstance(ref, dict):
            unit_id = _text(ref.get("unit_id"))
            raw_page = ref.get("pdf_page")
            pdf_page = raw_page if type(raw_page) is int and raw_page > 0 else None
        elif isinstance(ref, str):
            unit_id = ref.strip()
            matches = pages_by_unit.get(unit_id, [])
            if len(matches) == 1:
                pdf_page = matches[0].get("pdf_page")
        if not unit_id or pdf_page is None:
            fatal.append(f"OFFICE_PROVENANCE_REF_INVALID：材料 {material_id} 的 provenance_ref 必须唯一定位 unit_id+pdf_page")
            continue
        key = (unit_id, pdf_page)
        page = page_by_key.get(key)
        locator = locator_by_unit.get(unit_id)
        if page is None or locator is None:
            fatal.append(f"OFFICE_PAGE_MAP_MISMATCH：材料 {material_id} 未绑定有效 source locator/page_map")
            continue
        if key in used_page_keys:
            fatal.append(f"OFFICE_PAGE_MAP_DUPLICATE_BINDING：多个材料绑定同一 Office 派生页 {unit_id}/{pdf_page}")
        used_page_keys.add(key)
        if not _locator_complete(locator):
            fatal.append(f"OFFICE_SOURCE_LOCATOR_INCOMPLETE：{unit_id} 缺少 Office 内部定位")
        if locator.get("visibility") != "visible":
            fatal.append(f"OFFICE_SOURCE_LOCATOR_INCOMPLETE：{unit_id} 不是明确可见范围")
        if locator.get("user_confirmed_scope") is not True:
            fatal.append(f"OFFICE_SCOPE_UNCONFIRMED：{unit_id} 的纳入范围尚未由用户确认")
        source_id = _text(locator.get("source_id"))
        if not source_id:
            fatal.append(f"OFFICE_SOURCE_ID_MISSING：{unit_id} 缺少 source_id")
            continue
        used_sources.add(source_id)
        rendered = _safe_relative(page.get("rendered_relative_path"), base_dir, f"page_map {unit_id}/{pdf_page}", fatal)
        material_path = _safe_relative(material.get("path"), base_dir, f"材料 {material_id} path", fatal)
        if rendered is None or material_path is None:
            continue
        if rendered != material_path:
            fatal.append(f"OFFICE_PAGE_MAP_MISMATCH：材料 {material_id} 路径与 page_map 不一致")
        if not rendered.is_file() or is_link_or_junction(rendered):
            fatal.append(f"OFFICE_DERIVED_MISSING：材料 {material_id} 的派生页不存在或为符号链接")
            continue
        declared_hash = _text(page.get("rendered_sha256")).lower()
        if len(declared_hash) != 64 or _sha256(rendered) != declared_hash:
            fatal.append(f"OFFICE_DERIVED_HASH_MISMATCH：材料 {material_id} 的派生页摘要不一致")
        decodable, actual_blank, actual_header_only, private_metadata = _inspect_rendered_page(rendered)
        if not decodable:
            fatal.append(f"OFFICE_RENDERED_ARTIFACT_INVALID：材料 {material_id} 的派生页无法实际解码")
        if actual_blank:
            fatal.append(f"OFFICE_BLANK_PAGE：材料 {material_id} 的派生页实际为空白页")
        if actual_header_only:
            fatal.append(f"OFFICE_RENDER_PAGE_INVALID：材料 {material_id} 的派生页实际仅页头")
        if private_metadata:
            fatal.append(f"OFFICE_PRIVACY_REVIEW_FAILED：材料 {material_id} 的图片元数据含本机路径")
        if page.get("blank_page") is not False or page.get("header_only") is not False:
            fatal.append(f"OFFICE_RENDER_PAGE_INVALID：材料 {material_id} 为空白页或仅页头")
        if page.get("font_substitution") != "none":
            fatal.append(f"OFFICE_FONT_SUBSTITUTION：材料 {material_id} 的字体替换未排除")
        if str(page.get("privacy_review", "")).lower() != "pass":
            fatal.append(f"OFFICE_PRIVACY_REVIEW_REQUIRED：材料 {material_id} 的隐私复核未通过")
        ordinal = page.get("attachment_ordinal")
        if type(ordinal) is not int or ordinal <= 0 or ordinal in used_ordinals:
            fatal.append(f"OFFICE_PAGE_MAP_MISMATCH：材料 {material_id} 的 attachment_ordinal 非法或重复")
        else:
            used_ordinals.add(ordinal)
            if ordinal != expected_ordinal:
                fatal.append(f"OFFICE_PAGE_MAP_MISMATCH：材料 {material_id} 的附件顺序与 Manifest 不一致")
        expected_bookmark = f"evidence_page_{ordinal:04d}" if type(ordinal) is int and ordinal > 0 else ""
        if page.get("docx_bookmark") != expected_bookmark:
            fatal.append(f"OFFICE_PAGE_MAP_MISMATCH：材料 {material_id} 的 docx_bookmark 与生成器不一致")

    if set(page_by_key) != used_page_keys:
        fatal.append("OFFICE_PAGE_MAP_MISMATCH：page_map 必须与 Manifest 中实际使用的 Office 派生页一一对应")
    if set(locator_by_unit) != {unit_id for unit_id, _ in used_page_keys}:
        fatal.append("OFFICE_SOURCE_LOCATOR_INVALID：source_locators 必须与实际使用的 Office unit 一一对应")

    for source_id in sorted(used_sources):
        snapshot = snapshot_by_source.get(source_id)
        inspection = inspection_by_source.get(source_id)
        conversion = conversion_by_source.get(source_id)
        if not snapshot or not inspection or not conversion:
            fatal.append(f"OFFICE_SOURCE_CHAIN_INCOMPLETE：{source_id} 缺少源快照、包预检或转换记录")
            continue
        source_path = _safe_relative(snapshot.get("relative_path"), base_dir, f"source_snapshot {source_id}", fatal)
        current_inspection: dict[str, Any] | None = None
        if source_path is not None:
            if not source_path.is_file() or is_link_or_junction(source_path):
                fatal.append(f"OFFICE_SOURCE_MISSING：{source_id} 原始 Office 文件不存在或为符号链接")
            else:
                stat = source_path.stat()
                declared_hash = _text(snapshot.get("sha256")).lower()
                if (
                    stat.st_size != snapshot.get("size")
                    or stat.st_mtime_ns != snapshot.get("mtime_ns")
                    or len(declared_hash) != 64
                    or _sha256(source_path) != declared_hash
                ):
                    fatal.append(f"OFFICE_SOURCE_CHANGED：{source_id} 当前源文件与快照不一致")
                if source_path.suffix.lower() not in SUPPORTED:
                    fatal.append(f"OFFICE_FORMAT_UNSUPPORTED：{source_id} 不是受支持的 OOXML 格式")
                else:
                    current_inspection = inspect_office(source_path, base_dir)
                    if current_inspection.get("status") != "PASS":
                        fatal.append(f"OFFICE_PACKAGE_INSPECTION_NOT_PASS：{source_id} 当前包结构重新预检未通过")
                    if current_inspection.get("format") != inspection.get("format"):
                        fatal.append(f"OFFICE_PACKAGE_TYPE_MISMATCH：{source_id} 当前格式与 sidecar 不一致")
        if current_inspection is not None:
            for unit_id, locator in locator_by_unit.items():
                if _text(locator.get("source_id")) == source_id and not _locator_matches(locator, current_inspection):
                    fatal.append(f"OFFICE_SOURCE_LOCATOR_INVALID：{unit_id} 与当前 Office 包内部位置不一致")
        if snapshot.get("unchanged") is not True or snapshot.get("read_only") is not True:
            fatal.append(f"OFFICE_SOURCE_CHANGED：{source_id} 未证明只读且读取前后稳定")
        if snapshot.get("source_kind") not in {"native_office", "scan_or_export", "unknown"}:
            fatal.append(f"OFFICE_SOURCE_SNAPSHOT_INVALID：{source_id} 的 source_kind 非法")
        if type(snapshot.get("mtime_ns")) is not int or snapshot.get("mtime_ns") < 0:
            fatal.append(f"OFFICE_SOURCE_SNAPSHOT_INVALID：{source_id} 的 mtime_ns 非法")
        before = _text(snapshot.get("read_before")).lower()
        after = _text(snapshot.get("read_after")).lower()
        if len(before) != 64 or before != after or before != _text(snapshot.get("sha256")).lower():
            fatal.append(f"OFFICE_SOURCE_CHANGED：{source_id} 读取前后摘要不一致")
        if (
            str(inspection.get("status", "")).lower() != "pass"
            or inspection.get("zip_valid") is not True
            or inspection.get("content_type_valid") is not True
            or inspection.get("encrypted") is not False
            or any(inspection.get(key) != "absent" for key in ("macros", "external_links", "comments_notes", "hidden_content", "embedded_objects"))
        ):
            fatal.append(f"OFFICE_PACKAGE_INSPECTION_NOT_PASS：{source_id} 的包预检未通过")
        if (
            str(conversion.get("status", "")).lower() != "pass"
            or conversion.get("profile_isolated") is not True
            or not _text(conversion.get("tool"))
            or not _text(conversion.get("platform"))
            or not _text(conversion.get("arguments_summary"))
            or _text(conversion.get("rasterizer")).lower() in {"", "none"}
        ):
            fatal.append(f"OFFICE_CONVERSION_NOT_PASS：{source_id} 的隔离转换记录未通过")
        if _text(conversion.get("tool_version")).lower() in UNKNOWN_VERSION_VALUES:
            fatal.append(f"OFFICE_CONVERTER_VERSION_UNKNOWN：{source_id} 缺少可复核转换器版本")
        if _text(conversion.get("rasterizer_version")).lower() in UNKNOWN_VERSION_VALUES:
            fatal.append(f"OFFICE_CONVERTER_VERSION_UNKNOWN：{source_id} 缺少可复核栅格化器版本")
        pdf_path = _safe_relative(conversion.get("pdf_relative_path"), base_dir, f"conversion_record {source_id}", fatal)
        if pdf_path is not None:
            pdf_hash = _text(conversion.get("pdf_sha256")).lower()
            if not pdf_path.is_file() or len(pdf_hash) != 64 or _sha256(pdf_path) != pdf_hash:
                fatal.append(f"OFFICE_PDF_HASH_MISMATCH：{source_id} 的 PDF 派生物摘要不一致")
            else:
                actual_count = _pdf_page_count(pdf_path)
                declared_count = conversion.get("pdf_page_count")
                source_pages = [
                    page for page in pages
                    if _text(locator_by_unit.get(_text(page.get("unit_id")), {}).get("source_id")) == source_id
                ]
                page_numbers = [page.get("pdf_page") for page in source_pages]
                if (
                    actual_count is None
                    or type(declared_count) is not int
                    or declared_count != actual_count
                    or page_numbers != list(range(1, actual_count + 1))
                ):
                    fatal.append(f"OFFICE_PAGE_MAP_MISMATCH：{source_id} 的 PDF 实际页数、页序与 page_map 不一致")
                if _pdf_has_private_path(pdf_path):
                    fatal.append(f"OFFICE_PRIVACY_REVIEW_FAILED：{source_id} 的 PDF 元数据含本机路径")

    if used_ordinals and used_ordinals != set(range(1, len(used_ordinals) + 1)):
        fatal.append("OFFICE_PAGE_MAP_MISMATCH：attachment_ordinal 必须从1连续递增")
    gate = sidecar.get("formal_release_gate")
    if not isinstance(gate, dict) or gate.get("status") != "PASS" or gate.get("failure_codes") != []:
        fatal.append("OFFICE_FORMAL_GATE_NOT_PASS：Office sidecar 未达到 PASS；--allow-draft 也不能嵌入派生页")
    return list(dict.fromkeys(fatal)), blockers, warnings


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Manifest 顶层必须是对象")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 Manifest v2 与 v18 Office provenance sidecar 的完整绑定")
    parser.add_argument("manifest", help="Manifest JSON 路径")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    try:
        fatal, blockers, warnings = validate_office_provenance(_load_json(manifest_path), manifest_path.parent)
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as exc:
        fatal, blockers, warnings = [f"OFFICE_PROVENANCE_INVALID：{type(exc).__name__}: {exc}"], [], []
    result = {"status": "PASS" if not fatal and not blockers else "BLOCKED", "fatal": fatal, "blockers": blockers, "warnings": warnings}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["status"])
        for item in fatal + blockers + warnings:
            print(f"- {item}")
    if fatal or blockers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
