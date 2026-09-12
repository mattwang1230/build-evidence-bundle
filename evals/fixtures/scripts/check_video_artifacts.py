#!/usr/bin/env python3
"""Deterministic judge for video-frame artifacts produced in skill-up cases."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"无法读取JSON {path}: {exc}")


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} 必须是对象")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{label} 必须是数组")
    return value


def timecode_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 3:
        fail(f"无效时间码：{value}")
    try:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    except Exception:
        fail(f"无效时间码：{value}")
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        fail(f"无效时间码：{value}")
    return hours * 3600 + minutes * 60 + seconds


def check_extract(expected: dict[str, Any]) -> tuple[dict[str, Any], Path, Path]:
    video = Path(expected["video"])
    index_path = Path(expected["index"])
    if not video.is_file():
        fail(f"原视频不存在：{video}")
    if not index_path.is_file():
        fail(f"截帧索引不存在：{index_path}")

    index = require_dict(load_json(index_path), "截帧索引")
    if index.get("schema_version") != 1:
        fail("截帧索引 schema_version 必须为整数1")
    if index.get("read_only_source") is not True:
        fail("截帧索引必须声明 read_only_source=true")

    source = require_dict(index.get("source_video"), "source_video")
    source_digest = sha256(video)
    source_id = source.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        fail("source_video.source_id 必须是非空字符串")
    if Path(str(source.get("path", ""))).resolve() != video.resolve():
        fail("source_video.path 未回指同一路径的原视频")
    if source.get("sha256") != source_digest:
        fail("source_video.sha256 与原视频不一致")
    if int(source.get("size", -1)) != video.stat().st_size:
        fail("source_video.size 与原视频不一致")
    required_source_kind = expected.get("required_source_kind")
    if required_source_kind and source.get("source_kind") != required_source_kind:
        fail(f"source_video.source_kind 应为 {required_source_kind}")

    extraction = require_dict(index.get("extraction"), "extraction")
    policy = extraction.get("sampling_policy")
    required_policy = expected.get("required_policy")
    if required_policy and policy != required_policy:
        fail(f"sampling_policy 应为 {required_policy}，实际为 {policy}")
    if expected.get("require_exact_dedup_policy") and extraction.get("deduplication") != "exact_output_sha256_only":
        fail("去重策略必须为 exact_output_sha256_only")
    for key in ("interval_seconds", "scene_threshold"):
        expected_value = expected.get(f"expected_{key}")
        if expected_value is not None and abs(float(extraction.get(key, -1)) - float(expected_value)) > 0.0001:
            fail(f"extraction.{key} 不符合固定评测策略")

    manifest_path_text = expected.get("manifest")
    if manifest_path_text:
        manifest_path = Path(manifest_path_text)
        manifest = require_dict(load_json(manifest_path), "Manifest")
        media_sources = require_list(manifest.get("media_sources"), "Manifest media_sources")
        matches = [item for item in media_sources if isinstance(item, dict) and item.get("source_id") == source_id]
        if len(matches) != 1:
            fail("Manifest必须且只能有一个media_sources项回指当前source_id")
        media_source = matches[0]
        manifest_video = (manifest_path.parent / str(media_source.get("path", ""))).resolve()
        manifest_index = (manifest_path.parent / str(media_source.get("frame_index_path", ""))).resolve()
        if manifest_video != video.resolve() or manifest_index != index_path.resolve():
            fail("Manifest media_sources 的视频或截帧索引路径不一致")
        if media_source.get("source_kind") != source.get("source_kind"):
            fail("Manifest media_sources.source_kind 与截帧索引不一致")
        if media_source.get("sha256") != source_digest:
            fail("Manifest media_sources.sha256 与原视频不一致")
        if int(media_source.get("stream_index", -1)) != int(source.get("stream_index", -2)):
            fail("Manifest media_sources.stream_index 与截帧索引不一致")
        if abs(float(media_source.get("duration_seconds", -1)) - float(source.get("duration_seconds", -2))) > 0.05:
            fail("Manifest media_sources.duration_seconds 与截帧索引不一致")

    frames = require_list(index.get("frames"), "frames")
    expected_times = expected.get("expected_times")
    if expected_times is not None and len(frames) != len(expected_times):
        fail(f"预期 {len(expected_times)} 帧，实际 {len(frames)} 帧")
    if len(frames) < int(expected.get("min_frames", 0)):
        fail("截帧数量少于最低要求")
    if len(frames) > int(expected.get("max_frames", 1_000_000)):
        fail("截帧数量超过上限")

    timestamps: list[float] = []
    frame_digests: set[str] = set()
    frame_ids: set[str] = set()
    expected_center_rgb = expected.get("expected_center_rgb")
    if expected_center_rgb is not None and len(expected_center_rgb) != len(frames):
        fail("expected_center_rgb 数量必须与唯一帧数一致")
    for sequence, raw_frame in enumerate(frames, start=1):
        frame = require_dict(raw_frame, f"frames[{sequence - 1}]")
        if frame.get("sequence") != sequence:
            fail("frame.sequence 必须从1连续递增")
        frame_id = frame.get("frame_id")
        if not isinstance(frame_id, str) or not frame_id or frame_id in frame_ids:
            fail("frame_id 必须非空且唯一")
        frame_ids.add(frame_id)
        try:
            timestamp = float(frame["timestamp_seconds"])
        except Exception:
            fail("timestamp_seconds 必须为数字")
        timestamps.append(timestamp)
        if not isinstance(frame.get("source_timecode"), str) or not frame["source_timecode"]:
            fail("每帧必须有 source_timecode")
        if frame.get("source_video_sha256") != source_digest:
            fail("每帧必须回指原视频SHA-256")
        if abs(timecode_seconds(frame["source_timecode"]) - timestamp) > 0.001:
            fail("frame.source_timecode 与数值时码不一致")

        relative_path = Path(str(frame.get("path", "")))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            fail("frame.path 必须是索引目录内的安全相对路径")
        frame_path = index_path.parent / relative_path
        if not frame_path.is_file():
            fail(f"截帧文件不存在：{frame_path}")
        with frame_path.open("rb") as stream:
            if stream.read(8) != PNG_SIGNATURE:
                fail(f"截帧不是可识别PNG：{frame_path}")
        try:
            with Image.open(frame_path) as image:
                rgb_image = image.convert("RGB")
                center_rgb = rgb_image.getpixel((rgb_image.width // 2, rgb_image.height // 2))
        except Exception as exc:
            fail(f"截帧无法真实解码：{frame_path}：{exc}")
        if expected_center_rgb is not None:
            wanted_rgb = expected_center_rgb[sequence - 1]
            rgb_tolerance = int(expected.get("rgb_tolerance", 5))
            if any(abs(int(actual) - int(wanted)) > rgb_tolerance for actual, wanted in zip(center_rgb, wanted_rgb)):
                fail(f"截帧中心像素 {center_rgb} 与视频金样 {wanted_rgb} 不一致")
        frame_digest = sha256(frame_path)
        if frame.get("sha256") != frame_digest:
            fail(f"截帧SHA-256不一致：{frame_path}")
        if frame_digest in frame_digests:
            fail("frames 中仍存在完全相同的重复输出；应记录为alias")
        frame_digests.add(frame_digest)

        video_frame = require_dict(frame.get("video_frame"), "video_frame")
        if abs(float(video_frame.get("source_time_seconds", -1)) - timestamp) > 0.001:
            fail("video_frame.source_time_seconds 与帧时间不一致")
        if video_frame.get("source_id") != source.get("source_id"):
            fail("video_frame.source_id 与 source_video.source_id 不一致")
        if Path(str(video_frame.get("source_video_path", ""))).resolve() != video.resolve():
            fail("video_frame.source_video_path 未回指同一路径的原视频")
        if video_frame.get("source_kind") != source.get("source_kind"):
            fail("video_frame.source_kind 与 source_video.source_kind 不一致")
        carrier = require_dict(frame.get("original_carrier"), "original_carrier")
        carrier_path = Path(str(carrier.get("path", "")))
        if carrier_path.resolve() != video.resolve():
            fail("original_carrier.path 未回指同一路径的原视频")
        if carrier.get("source_kind") != source.get("source_kind"):
            fail("original_carrier.source_kind 与 source_video.source_kind 不一致")

    if timestamps != sorted(timestamps):
        fail("截帧没有按源时间码排序")
    if expected_times is not None:
        tolerance = float(expected.get("time_tolerance", 0.05))
        for actual, wanted in zip(timestamps, expected_times):
            if abs(actual - float(wanted)) > tolerance:
                fail(f"截帧时码 {actual} 超出预期 {wanted} 的容差")

    aliases = require_list(index.get("duplicate_aliases", []), "duplicate_aliases")
    if len(aliases) < int(expected.get("min_aliases", 0)):
        fail("duplicate_aliases 数量少于最低要求")
    alias_times: list[float] = []
    for raw_alias in aliases:
        alias = require_dict(raw_alias, "duplicate_alias")
        if alias.get("canonical_frame_id") not in frame_ids:
            fail("duplicate_aliases 引用了未知 canonical_frame_id")
        if alias.get("sha256") not in frame_digests:
            fail("duplicate_aliases 的SHA-256与canonical不一致")
        try:
            alias_times.append(float(alias["alias_timestamp_seconds"]))
        except Exception:
            fail("duplicate_aliases.alias_timestamp_seconds 必须为数字")

    expected_alias_times = expected.get("expected_alias_times")
    if expected_alias_times is not None:
        tolerance = float(expected.get("time_tolerance", 0.05))
        if len(alias_times) != len(expected_alias_times):
            fail(f"预期 {len(expected_alias_times)} 个alias，实际 {len(alias_times)} 个")
        for actual, wanted in zip(alias_times, expected_alias_times):
            if abs(actual - float(wanted)) > tolerance:
                fail(f"alias时码 {actual} 超出预期 {wanted} 的容差")

    return index, video, index_path


def check_carrier(expected: dict[str, Any], index: dict[str, Any], video: Path, index_path: Path) -> None:
    fragments_path = Path(expected["manifest_fragments"])
    if not fragments_path.is_file():
        fail(f"Manifest片段不存在：{fragments_path}")
    fragments = require_dict(load_json(fragments_path), "Manifest片段")
    materials = require_list(fragments.get("materials"), "Manifest片段 materials")
    frames = require_list(index.get("frames"), "frames")
    if len(materials) != len(frames):
        fail("Manifest片段材料数与截帧数不一致")
    material_ids: set[str] = set()
    for material, frame in zip(materials, frames):
        material = require_dict(material, "material")
        material_id = material.get("material_id")
        if not isinstance(material_id, str) or not material_id or material_id in material_ids:
            fail("material_id 必须非空且唯一")
        material_ids.add(material_id)
        if material.get("source_time") != frame.get("source_timecode"):
            fail("material.source_time 与截帧时间码不一致")
        material_video_frame = require_dict(material.get("video_frame"), "material.video_frame")
        indexed_video_frame = require_dict(frame.get("video_frame"), "frame.video_frame")
        for key in ("source_id", "source_time_seconds", "source_timecode", "source_frame_index"):
            if material_video_frame.get(key) != indexed_video_frame.get(key):
                fail(f"material.video_frame.{key} 与索引帧不一致")
        carrier = require_dict(material.get("original_carrier"), "material.original_carrier")
        carrier_path = Path(str(carrier.get("path", "")))
        if carrier_path.resolve() != video.resolve():
            fail("材料 original_carrier.path 未回指同一路径的原视频")
        material_path = Path(str(material.get("path", "")))
        if not material_path.is_absolute():
            material_path = fragments_path.parent / material_path
        if not material_path.is_file():
            fail("材料 path 未指向截帧文件")
        indexed_path = (index_path.parent / str(frame.get("path", ""))).resolve()
        if material_path.resolve() != indexed_path or sha256(material_path) != frame.get("sha256"):
            fail("材料 path 或摘要与对应索引帧不一致")


def check_docx(expected: dict[str, Any], video: Path) -> None:
    docx_path = Path(expected["docx"])
    if not docx_path.is_file():
        fail(f"DOCX不存在：{docx_path}")
    try:
        with zipfile.ZipFile(docx_path) as archive:
            names = set(archive.namelist())
            document_xml = archive.read("word/document.xml").decode("utf-8")
            settings_xml = archive.read("word/settings.xml").decode("utf-8")
            footer_xml = "".join(
                archive.read(name).decode("utf-8")
                for name in names
                if name.startswith("word/footer") and name.endswith(".xml")
            )
            all_xml = "".join(
                archive.read(name).decode("utf-8", errors="ignore")
                for name in names
                if name.endswith(".xml")
            )
    except Exception as exc:
        fail(f"DOCX无法作为ZIP重开：{exc}")
    if "PAGEREF" not in document_xml:
        fail("DOCX缺少PAGEREF域")
    if "bookmarkStart" not in document_xml:
        fail("DOCX缺少附件书签")
    if "PAGE" not in footer_xml:
        fail("DOCX页脚缺少PAGE域")
    if "updateFields" not in settings_xml:
        fail("DOCX未要求打开时更新域")
    media = [name for name in names if name.startswith("word/media/")]
    if len(media) != int(expected.get("expected_media", len(media))):
        fail("DOCX媒体数量不符合预期")
    video_path_text = str(video.resolve())
    if video_path_text in all_xml or video_path_text.replace("\\", "/") in all_xml:
        fail("Word XML泄漏原视频绝对路径")


def check_social_draft(expected: dict[str, Any], video: Path) -> None:
    formal_path = Path(expected["formal_docx"])
    if formal_path.exists():
        fail("社交媒体派生副本不应生成正式DOCX")
    draft_path = Path(expected["draft_docx"])
    check_docx({"docx": str(draft_path), "expected_media": expected.get("expected_media", 1)}, video)


def main() -> None:
    expected = require_dict(load_json(Path("eval-expected.json")), "eval-expected.json")
    mode = expected.get("mode")
    index, video, index_path = check_extract(expected)
    if mode == "carrier":
        check_carrier(expected, index, video, index_path)
    elif mode == "docx":
        check_docx(expected, video)
    elif mode == "social_draft":
        check_social_draft(expected, video)
    elif mode != "extract":
        fail(f"未知评测模式：{mode}")
    print(f"PASS: {mode}")


if __name__ == "__main__":
    main()
