#!/usr/bin/env python3
"""Structural DOCX QA plus an explicit rendered-page review gate."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from PIL import Image, UnidentifiedImageError
from path_safety import contains_local_path


BOOKMARK = re.compile(r"evidence_page_\d{4}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 顶层必须是对象")
    return value


def expected_attachment_ids(manifest: dict[str, Any]) -> list[str]:
    output: list[str] = []
    groups = manifest.get("evidence_groups", [])
    if not isinstance(groups, list):
        return output
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("materials"), list):
            continue
        for material in group["materials"]:
            if not isinstance(material, dict):
                continue
            material_id = str(material.get("material_id", "")).strip()
            canonical = str(
                material.get("canonical_material_id")
                or material.get("canonical_id")
                or material.get("alias_of")
                or material_id
            ).strip()
            if material_id and canonical == material_id and material_id not in output:
                output.append(material_id)
    return output


def structural_checks(docx: Path, manifest: dict[str, Any] | None) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    facts: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(docx) as zf:
            names = set(zf.namelist())
            required = {"word/document.xml", "word/settings.xml", "[Content_Types].xml"}
            for part in required - names:
                errors.append(f"DOCX_STRUCTURE_MISSING：{part}")
            document = zf.read("word/document.xml").decode("utf-8", errors="replace") if "word/document.xml" in names else ""
            settings = zf.read("word/settings.xml").decode("utf-8", errors="replace") if "word/settings.xml" in names else ""
            footers = "\n".join(
                zf.read(name).decode("utf-8", errors="replace")
                for name in sorted(names)
                if name.startswith("word/footer") and name.endswith(".xml")
            )
            core_xml = zf.read("docProps/core.xml") if "docProps/core.xml" in names else b""
            if core_xml:
                core = ET.fromstring(core_xml)
                private_core_fields = {
                    node.tag.rsplit("}", 1)[-1]: (node.text or "").strip()
                    for node in core.iter()
                    if node.tag.rsplit("}", 1)[-1] in {"creator", "lastModifiedBy", "subject", "keywords", "description"}
                    and (node.text or "").strip()
                }
                facts["private_core_fields"] = private_core_fields
                if private_core_fields:
                    errors.append("DOCX_PRIVATE_METADATA_PRESENT：core properties 含提交人或案件信息")
            media_metadata: list[str] = []
            for name in sorted(names):
                if not name.startswith("word/media/") or name.endswith("/"):
                    continue
                try:
                    with Image.open(io.BytesIO(zf.read(name))) as image:
                        metadata = {str(key): str(value) for key, value in image.info.items()}
                except (OSError, UnidentifiedImageError):
                    continue
                if {"source_sha256", "material_id"} & set(metadata) or contains_local_path("\n".join(metadata.values())):
                    media_metadata.append(name)
            facts["media_with_private_metadata"] = media_metadata
            if media_metadata:
                errors.append("DOCX_PRIVATE_METADATA_PRESENT：内嵌图片含材料编号、摘要或本机路径 metadata")
            bookmarks = set(BOOKMARK.findall(document))
            pageref_count = document.count("PAGEREF")
            media_count = sum(1 for name in names if name.startswith("word/media/") and not name.endswith("/"))
            facts.update(
                {
                    "bookmark_count": len(bookmarks),
                    "pageref_count": pageref_count,
                    "media_part_count": media_count,
                    "page_footer_present": "PAGE" in footers,
                    "update_fields_on_open": "updateFields" in settings,
                    "page_header_present": "页码" in document,
                }
            )
            if "页码" not in document:
                errors.append("DOCX_PAGE_HEADER_MISSING：证据表第三列表头不是“页码”")
            if not bookmarks:
                errors.append("DOCX_BOOKMARK_MISSING：未发现附件页书签")
            if not pageref_count:
                errors.append("DOCX_PAGEREF_MISSING：未发现页码回指域")
            if "PAGE" not in footers:
                errors.append("DOCX_PAGE_FIELD_MISSING：页脚未发现 PAGE 域")
            if "updateFields" not in settings:
                errors.append("DOCX_UPDATE_FIELDS_MISSING：未设置打开时更新域")
            if contains_local_path(document + footers):
                errors.append("DOCX_PRIVACY_PATH_LEAK：Word 正文或页脚出现本机绝对路径")
            if manifest is not None:
                expected_ids = expected_attachment_ids(manifest)
                expected = len(expected_ids)
                facts["expected_attachment_pages"] = expected
                facts["expected_canonical_material_ids"] = expected_ids
                if expected != len(bookmarks):
                    errors.append(
                        f"DOCX_ATTACHMENT_COUNT_MISMATCH：Manifest预计{expected}页，书签实际{len(bookmarks)}页"
                    )
                expected_bookmarks = {f"evidence_page_{number:04d}" for number in range(1, expected + 1)}
                if bookmarks != expected_bookmarks:
                    errors.append("DOCX_ATTACHMENT_ORDER_MISMATCH：附件书签必须从1连续递增并与 canonical 顺序一致")
                if media_count != expected:
                    errors.append(f"DOCX_MEDIA_COUNT_MISMATCH：Manifest预计{expected}张附件图，DOCX实际{media_count}个媒体部件")
                groups = manifest.get("evidence_groups", [])
                group_count = len(groups) if isinstance(groups, list) else 0
                facts["evidence_group_count"] = group_count
                if group_count and pageref_count < group_count:
                    errors.append("DOCX_PAGE_REF_MISMATCH：PAGEREF 数量少于证据组数")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        errors.append(f"DOCX_REOPEN_FAILED：{type(exc).__name__}: {exc}")
    return errors, facts


def render_review_errors(review: dict[str, Any], docx_hash: str) -> list[str]:
    errors: list[str] = []
    if review.get("status") != "PASS" or review.get("docx_sha256") != docx_hash:
        errors.append("RENDER_REVIEW_INVALID：复核状态或 DOCX 摘要不匹配")
    for field in ("no_cropping", "no_overlap", "main_pages_readable", "page_refs_match", "no_abnormal_blank_pages"):
        if review.get(field) is not True:
            errors.append(f"RENDER_REVIEW_INVALID：{field} 未确认")
    if type(review.get("physical_page_count")) is not int or review["physical_page_count"] <= 0:
        errors.append("RENDER_REVIEW_INVALID：physical_page_count 必须是正整数")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="检查证据卷 DOCX 结构，并要求独立页面渲染复核")
    parser.add_argument("docx", help="待检查 DOCX")
    parser.add_argument("--manifest", help="对应 Manifest JSON")
    parser.add_argument("--render-review", help="人工/独立渲染复核 JSON")
    parser.add_argument("--output", help="QA JSON 输出路径；默认只打印")
    args = parser.parse_args()
    docx = Path(args.docx).expanduser().resolve()
    if not docx.is_file():
        raise SystemExit("DOCX 不存在")
    try:
        manifest = load_object(Path(args.manifest).expanduser().resolve()) if args.manifest else None
        errors, facts = structural_checks(docx, manifest)
        render_status = "HOLD"
        render_errors: list[str] = []
        if args.render_review:
            render_errors = render_review_errors(load_object(Path(args.render_review).expanduser().resolve()), sha256(docx))
            render_status = "PASS" if not render_errors else "BLOCKED"
        status = "BLOCKED" if errors or render_errors else ("PASS" if render_status == "PASS" else "HOLD")
        failure_codes = errors + render_errors
        if status == "HOLD":
            failure_codes.append("RENDER_REVIEW_UNAVAILABLE")
        result = {
            "schema_version": 1,
            "status": status,
            "docx_sha256": sha256(docx),
            "structural": facts,
            "render_review": render_status,
            "failure_codes": failure_codes,
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        result = {"schema_version": 1, "status": "BLOCKED", "failure_codes": [f"QA_INPUT_INVALID：{type(exc).__name__}: {exc}"]}
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output).expanduser()
        if target.exists():
            raise SystemExit("拒绝覆盖既有 QA 输出")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
    print(output)
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
