#!/usr/bin/env python3
"""Read-only material inventory with real image decoding and duplicate aliases.

The inventory is deliberately best-effort at the per-file boundary: one locked,
unreadable, or malformed file must not prevent the JSON inventory from being
written. Non-image files remain non-image files; Office preflight is provided
by ``inspect_office_materials.py`` and is never silently folded into this
image-only pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from path_safety import first_link_component, is_link_or_junction

ALLOWED_IMAGES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff"}


def technical_skip_reason(path: Path) -> tuple[str, str] | None:
    """Return (reason, failure_code) for known non-material technical files."""

    if path.name.startswith("~$"):
        return "Office 临时锁文件；不读取内容", "OFFICE_TEMP_LOCKFILE"
    if path.name.lower() == ".ds_store":
        return "系统元数据文件；不作为材料读取", "OFFICE_SYSTEM_METADATA"
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_sha256(path: Path) -> tuple[str | None, str | None]:
    """Hash one file without allowing a single read error to abort the batch."""

    try:
        return sha256(path), None
    except Exception as exc:
        return None, f"文件摘要读取失败：{type(exc).__name__}: {exc}"


def inspect_image(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "is_image": path.suffix.lower() in ALLOWED_IMAGES,
        "decode_status": "not_image",
        "readability": "unreadable",
        "warnings": [],
        "errors": [],
        "exif_orientation": None,
        "exif_transposed": False,
        "display_rotation_degrees_clockwise": 0,
    }
    if not record["is_image"]:
        record["warnings"].append("非标准图片扩展名；正式卷只接受图片")
        return record
    try:
        from PIL import Image, ImageOps

        # Inspect dimensions before any pixel load; avoid Pillow's bomb guard
        # turning a reportable extreme-size warning into a false decode error.
        Image.MAX_IMAGE_PIXELS = None

        # Keep verify immediately after open for strict Pillow wrappers.
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            record["format"] = image.format
            record["width"], record["height"] = image.size
            record["mode"] = image.mode
            record["exif_orientation"] = image.getexif().get(274)
            if max(int(record["width"]), int(record["height"])) > 200_000 or int(record["width"]) * int(record["height"]) > 200_000_000:
                record["errors"].append("图片尺寸极端，拒绝加载以避免内存风险")
                record["decode_status"] = "ok"
                return record
            image.load()
            normalized = ImageOps.exif_transpose(image)
            normalized.load()
            record["normalized_width"], record["normalized_height"] = normalized.size
            record["normalized_mode"] = normalized.mode
        width = int(record["normalized_width"])
        height = int(record["normalized_height"])
        pixels = width * height
        ratio = max(width, height) / max(1, min(width, height))
        record["pixels"] = pixels
        record["aspect_ratio"] = round(ratio, 3)
        record["exif_transposed"] = bool(record["exif_orientation"] not in (None, 1))
        record["decode_status"] = "ok"
        if max(width, height) > 200_000 or pixels > 200_000_000:
            record["errors"].append("图片尺寸极端，无法安全嵌入")
        elif max(width, height) > 100_000 or pixels > 100_000_000:
            record["warnings"].append("图片尺寸很大，可能造成内存或分页风险")
        if ratio >= 8:
            record["warnings"].append("长图：缩放后文字可能不可读，建议全貌页加局部页")
        if min(width, height) < 600 or pixels < 500_000:
            record["warnings"].append("源像素较低，缩放后存在不可读风险")
        record["readability"] = "unreadable" if record["errors"] else ("warning" if record["warnings"] else "clear")
    except ImportError as exc:
        record["errors"].append(f"缺少 Pillow，无法实际解码图片：{exc}")
    except Exception as exc:
        record["errors"].append(f"图片损坏或不可读（corrupt image）：图片解码失败：{exc}")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="只读盘点案件材料并计算 SHA-256、图片解码和 EXIF 信息")
    parser.add_argument("material_dir", help="案件材料目录")
    parser.add_argument("--output", required=True, help="盘点 JSON 输出路径")
    parser.add_argument("--overwrite", action="store_true", help="显式允许覆盖已存在的盘点 JSON")
    args = parser.parse_args()

    raw_root = Path(args.material_dir).expanduser()
    if not raw_root.is_absolute():
        raw_root = Path.cwd() / raw_root
    if first_link_component(raw_root) is not None:
        raise SystemExit("材料目录不得经过符号链接或目录联接")
    root = raw_root.resolve()
    if not root.is_dir():
        raise SystemExit(f"材料目录不存在：{root}")
    raw_output_path = Path(args.output).expanduser()
    if not raw_output_path.is_absolute():
        raw_output_path = Path.cwd() / raw_output_path
    output_path = raw_output_path.resolve()
    link_component = first_link_component(raw_output_path)
    if link_component is not None:
        raise SystemExit("盘点输出不得经过符号链接或目录联接")
    try:
        output_path.relative_to(root)
    except ValueError:
        pass
    else:
        raise SystemExit(f"盘点输出不得写入材料目录（只读保护）：{output_path}")
    if output_path.exists() and output_path.is_dir():
        raise SystemExit(f"盘点输出必须是文件，不能覆盖目录：{output_path}")
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"拒绝覆盖已存在盘点输出（默认保护）：{output_path}；如确需覆盖请显式使用 --overwrite")
    records: list[dict[str, Any]] = []
    technical_skips: list[str] = []
    candidates = (p for p in root.rglob("*") if p.is_file() and p.resolve() != output_path)
    for path in sorted(candidates, key=lambda p: str(p).lower()):
        relative_path = str(path.relative_to(root))
        if any(
            is_link_or_junction(candidate)
            for candidate in (path, *path.parents)
            if candidate != root.parent
        ):
            technical_skips.append(relative_path)
            continue
        skip = technical_skip_reason(path)
        if skip is not None:
            reason, failure_code = skip
            try:
                size: int | None = path.stat().st_size
                error: str | None = None
            except Exception as exc:
                size = None
                error = f"技术文件属性读取失败：{type(exc).__name__}: {exc}"
            record: dict[str, Any] = {
                "relative_path": relative_path,
                "suffix": path.suffix.lower(),
                "size": size,
                "sha256": None,
                "classification": "technical_skip",
                "technical_skip": True,
                "skip_reason": reason,
                "failure_codes": [failure_code],
                "is_image": False,
                "decode_status": "skipped",
                "readability": "not_applicable",
                "warnings": [],
                "errors": [error] if error else [],
                "exif_orientation": None,
                "exif_transposed": False,
                "display_rotation_degrees_clockwise": 0,
            }
            records.append(record)
            technical_skips.append(relative_path)
            continue

        try:
            stat = path.stat()
            size = stat.st_size
        except Exception as exc:
            records.append(
                {
                    "relative_path": relative_path,
                    "suffix": path.suffix.lower(),
                    "size": None,
                    "sha256": None,
                    "classification": "read_error",
                    "technical_skip": False,
                    "is_image": path.suffix.lower() in ALLOWED_IMAGES,
                    "decode_status": "error",
                    "readability": "unreadable",
                    "warnings": [],
                    "errors": [f"文件属性读取失败：{type(exc).__name__}: {exc}"],
                    "failure_codes": ["MATERIAL_READ_FAILED"],
                }
            )
            continue

        image_info = inspect_image(path)
        digest, digest_error = safe_sha256(path)
        errors = list(image_info.get("errors", []))
        failure_codes: list[str] = []
        if digest_error:
            errors.append(digest_error)
            failure_codes.append("MATERIAL_READ_FAILED")
        classification = "image_candidate" if path.suffix.lower() in ALLOWED_IMAGES else "non_image"
        records.append(
            {
                "relative_path": relative_path,
                "suffix": path.suffix.lower(),
                "size": size,
                "sha256": digest,
                "classification": classification,
                "technical_skip": False,
                **image_info,
                "errors": errors,
                "failure_codes": failure_codes,
            }
        )

    by_hash: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        by_hash.setdefault(item["sha256"], []).append(item)
    duplicate_groups: list[dict[str, Any]] = []
    alias_mapping: dict[str, str] = {}
    for digest, items in by_hash.items():
        if not digest:
            continue
        if len(items) < 2:
            continue
        canonical = items[0]["relative_path"]
        aliases = [item["relative_path"] for item in items[1:]]
        duplicate_groups.append({"sha256": digest, "canonical": canonical, "aliases": aliases})
        for alias in aliases:
            alias_mapping[alias] = canonical

    output = {
        "schema_version": 2,
        "root_label": root.name,
        "file_count": len(records),
        "files": records,
        "duplicate_groups": duplicate_groups,
        "alias_mapping": alias_mapping,
        "technical_skips": technical_skips,
        "read_only": True,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    invalid_records = [
        item
        for item in records
        if not item.get("technical_skip")
        and (item.get("decode_status") != "ok" or not item.get("is_image") or bool(item.get("errors")))
    ]
    print(f"已盘点 {len(records)} 个文件；完全重复组 {len(duplicate_groups)} 个；材料目录未被修改。")
    if technical_skips:
        print(f"已记录并跳过 {len(technical_skips)} 个技术文件（Office 锁文件或 .DS_Store）。")
    if invalid_records:
        print(f"盘点发现 {len(invalid_records)} 个不可用于正式卷的文件；JSON 已写出，请先修复。")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
