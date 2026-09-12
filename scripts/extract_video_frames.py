#!/usr/bin/env python3
"""Read a local video and extract time-indexed PNG frames without redaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from path_safety import first_link_component, is_link_or_junction

from PIL import Image, UnidentifiedImageError


ALLOWED_VIDEOS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
SOURCE_KINDS = {"unverified_local_video", "original_recording", "public_demo_copy", "social_media_copy"}
OWNED_OUTPUT = re.compile(r"^frame-\d{4}-\d{2}-\d{2}-\d{2}\.\d{3}\.png$")
SHOWINFO_TIME = re.compile(r"\bpts_time:([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_png(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError(f"媒体工具输出不是PNG：{path.name}")
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError(f"媒体工具输出格式不是PNG：{path.name}")
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"媒体工具输出的PNG无法解码：{path.name}：{exc}") from exc


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _tool(explicit: str | None, name: str, sibling_of: Path | None = None) -> Path:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    if sibling_of is not None:
        suffix = sibling_of.suffix if os.name == "nt" else ""
        candidates.append(str(sibling_of.with_name(f"{name}{suffix}")))
    discovered = shutil.which(name)
    if discovered:
        candidates.append(discovered)
    for candidate in candidates:
        path = Path(candidate).expanduser().resolve()
        if path.is_file():
            return path
    raise ValueError(f"未找到{name}；请通过 --{name} 指定现有本地可执行文件。程序不会自动下载。")


def _run(command: list[str], timeout_seconds: int, *, log: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"媒体工具运行超时（{timeout_seconds}秒）：{Path(command[0]).name}") from exc
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
        detail = " | ".join(lines[-8:]) or f"退出码 {result.returncode}"
        for argument in command:
            candidate = Path(argument)
            if candidate.is_absolute():
                detail = detail.replace(str(candidate), f"<{candidate.name or 'local-path'}>")
        raise ValueError(f"{Path(command[0]).name} 执行失败：{detail}")
    if log and result.stderr:
        return result
    return result


def _version(tool: Path, timeout_seconds: int) -> str:
    result = _run([str(tool), "-version"], timeout_seconds)
    first = result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else ""
    return first


def _fraction(value: Any) -> float | None:
    text = _safe_text(value)
    if not text or text in {"0/0", "N/A"}:
        return None
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            number = float(numerator) / float(denominator)
        else:
            number = float(text)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _rotation(stream: dict[str, Any]) -> int:
    values: list[int] = []
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    if _safe_text(tags.get("rotate")):
        values.append(int(round(float(tags["rotate"]))) % 360)
    side_data = stream.get("side_data_list") if isinstance(stream.get("side_data_list"), list) else []
    for item in side_data:
        if isinstance(item, dict) and _safe_text(item.get("rotation")):
            values.append(int(round(float(item["rotation"]))) % 360)
    distinct = sorted(set(values))
    if len(distinct) > 1:
        raise ValueError(f"视频方向元数据冲突：{distinct}")
    rotation = distinct[0] if distinct else 0
    if rotation not in {0, 90, 180, 270}:
        raise ValueError(f"不支持的视频方向角度：{rotation}")
    return rotation


def _probe(ffprobe: Path, video: Path, stream_index: int | None, timeout_seconds: int) -> dict[str, Any]:
    try:
        result = _run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,duration,time_base:stream_tags=rotate:stream_side_data=rotation:format=duration,format_name",
                "-of",
                "json",
                str(video),
            ],
            timeout_seconds,
        )
    except ValueError as exc:
        raise ValueError(f"视频无法解码：{exc}") from exc
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ffprobe 未返回有效JSON：{exc}") from exc
    streams = [item for item in data.get("streams", []) if isinstance(item, dict) and item.get("codec_type") == "video"]
    if not streams:
        raise ValueError("视频无法解码：文件中没有可用视频流。")
    if stream_index is None:
        if len(streams) != 1:
            indices = [item.get("index") for item in streams]
            raise ValueError(f"文件含多个视频流 {indices}；请用 --stream-index 明确选择。")
        stream = streams[0]
    else:
        matches = [item for item in streams if item.get("index") == stream_index]
        if not matches:
            raise ValueError(f"--stream-index={stream_index} 未对应可用视频流。")
        stream = matches[0]
    format_info = data.get("format") if isinstance(data.get("format"), dict) else {}
    duration = _fraction(stream.get("duration")) or _fraction(format_info.get("duration"))
    if duration is None:
        raise ValueError("视频时长未知，不能建立可复核的自动截帧索引。")
    width = stream.get("width")
    height = stream.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("视频尺寸无效。")
    fps = _fraction(stream.get("avg_frame_rate")) or _fraction(stream.get("r_frame_rate"))
    return {
        "stream_index": int(stream["index"]),
        "codec_name": _safe_text(stream.get("codec_name")),
        "format_name": _safe_text(format_info.get("format_name")),
        "duration_seconds": duration,
        "fps": fps,
        "width": width,
        "height": height,
        "time_base": _safe_text(stream.get("time_base")),
        "rotation_degrees": _rotation(stream),
    }


def _seconds(value: str) -> float:
    text = value.strip()
    if not text:
        raise ValueError("空时间码")
    parts = text.split(":")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            seconds = float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            seconds = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        else:
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"无效时间码：{value}") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"无效时间码：{value}")
    return seconds


def _explicit_times(raw: str | None, duration: float, max_frames: int) -> list[float] | None:
    if raw is None:
        return None
    values = sorted(_seconds(item) for item in raw.split(","))
    if not values:
        raise ValueError("--times 至少需要一个时间码。")
    if len(values) > max_frames:
        raise ValueError(f"显式时间码数量超过 --max-frames={max_frames}。")
    for value in values:
        if value >= duration:
            raise ValueError(f"时间码 {value:.3f} 秒超出视频时长 {duration:.3f} 秒。")
    return values


def _timecode(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"


def _filename(sequence: int, seconds: float) -> str:
    return f"frame-{sequence:04d}-{_timecode(seconds).replace(':', '-')}.png"


def _extract_explicit(
    ffmpeg: Path,
    video: Path,
    stream_index: int,
    times: list[float],
    staging: Path,
    timeout_seconds: int,
) -> list[tuple[Path, float]]:
    records: list[tuple[Path, float]] = []
    for number, timestamp in enumerate(times, start=1):
        path = staging / f"candidate-{number:06d}.png"
        _run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(video),
                "-ss",
                f"{timestamp:.6f}",
                "-map",
                f"0:{stream_index}",
                "-frames:v",
                "1",
                "-an",
                "-sn",
                "-dn",
                "-y",
                str(path),
            ],
            timeout_seconds,
        )
        if not path.is_file():
            raise ValueError(f"时间码 {_timecode(timestamp)} 未生成可用截帧。")
        records.append((path, timestamp))
    return records


def _extract_auto(
    ffmpeg: Path,
    video: Path,
    probe: dict[str, Any],
    staging: Path,
    interval_seconds: float,
    scene_threshold: float,
    max_frames: int,
    timeout_seconds: int,
) -> list[tuple[Path, float]]:
    main_limit = max_frames - 1 if max_frames > 1 else 1
    pattern = staging / "candidate-%06d.png"
    select_filter = (
        f"select=eq(n\\,0)+gt(scene\\,{scene_threshold:.6f})+"
        f"gte(t-prev_selected_t\\,{interval_seconds:.6f}),showinfo"
    )
    result = _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "info",
            "-i",
            str(video),
            "-map",
            f"0:{probe['stream_index']}",
            "-vf",
            select_filter,
            "-fps_mode",
            "vfr",
            "-frames:v",
            str(main_limit),
            "-an",
            "-sn",
            "-dn",
            "-y",
            str(pattern),
        ],
        timeout_seconds,
        log=True,
    )
    paths = sorted(staging.glob("candidate-*.png"))
    timestamps = [float(match.group(1)) for match in SHOWINFO_TIME.finditer(result.stderr)]
    if not paths:
        raise ValueError("视频解码完成但没有生成任何截帧。")
    if len(paths) != len(timestamps):
        raise ValueError(f"截帧数量与FFmpeg时码日志不一致：{len(paths)} != {len(timestamps)}。")
    records = list(zip(paths, timestamps))

    fps = probe.get("fps") or 25.0
    final_time = max(0.0, float(probe["duration_seconds"]) - max(1.0 / fps, 0.001))
    if len(records) < max_frames and final_time - records[-1][1] > 0.001:
        final_path = staging / "candidate-final.png"
        _run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(video),
                "-ss",
                f"{final_time:.6f}",
                "-map",
                f"0:{probe['stream_index']}",
                "-frames:v",
                "1",
                "-an",
                "-sn",
                "-dn",
                "-y",
                str(final_path),
            ],
            timeout_seconds,
        )
        if final_path.is_file():
            records.append((final_path, final_time))
    return sorted(records, key=lambda item: item[1])


def _prepare_output(output_dir: Path, overwrite: bool, index_name: str) -> None:
    if _is_link_or_junction(output_dir):
        raise ValueError(f"输出目录不得是符号链接或目录联接：{output_dir}")
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise ValueError(f"输出路径必须是目录：{output_dir}")
    children = list(output_dir.iterdir())
    if not overwrite:
        raise ValueError(f"拒绝覆盖已有输出目录：{output_dir}；如需重建请显式使用 --overwrite。")
    if not children:
        return
    for child in children:
        if _is_link_or_junction(child):
            raise ValueError(f"输出目录含符号链接或目录联接，拒绝覆盖：{child}")
        if child.is_file() and child.name == index_name:
            continue
        if child.is_dir() and child.name == "frames":
            for frame in child.iterdir():
                if _is_link_or_junction(frame) or not frame.is_file() or not OWNED_OUTPUT.fullmatch(frame.name):
                    raise ValueError(f"frames目录含非本工具文件，拒绝覆盖：{frame}")
            continue
        raise ValueError(f"输出目录含非本工具文件，拒绝覆盖：{child}")


def _remove_owned_output(output_dir: Path, index_name: str) -> None:
    _prepare_output(output_dir, True, index_name)
    for child in list(output_dir.iterdir()):
        if child.is_dir():
            for frame in list(child.iterdir()):
                frame.unlink()
            child.rmdir()
        else:
            child.unlink()
    output_dir.rmdir()


def _publish(staging: Path, output_dir: Path, overwrite: bool, index_name: str) -> None:
    backup: Path | None = None
    if output_dir.exists():
        _prepare_output(output_dir, overwrite, index_name)
        backup = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.backup-", dir=output_dir.parent))
        backup.rmdir()
        output_dir.replace(backup)
    try:
        staging.replace(output_dir)
    except OSError:
        if backup is not None and backup.exists() and not output_dir.exists():
            backup.replace(output_dir)
        raise
    if backup is not None:
        _remove_owned_output(backup, index_name)


def _cleanup_staging(staging: Path) -> None:
    if not staging.exists():
        return
    for child in list(staging.iterdir()):
        if child.is_dir() and child.name == "frames" and not child.is_symlink():
            for frame in list(child.iterdir()):
                if frame.is_file() and not frame.is_symlink():
                    frame.unlink()
            child.rmdir()
        elif child.is_file() and not child.is_symlink():
            child.unlink()
    staging.rmdir()


_is_link_or_junction = is_link_or_junction


def _guard_output_path(path: Path) -> None:
    link_component = first_link_component(path)
    if link_component is not None:
        raise ValueError(f"输出路径不得经过符号链接或目录联接：{link_component}")


def main() -> None:
    parser = argparse.ArgumentParser(description="读取本地视频并自动提取带时间码的PNG帧；不提供脱敏功能")
    parser.add_argument("video", help="本地视频文件；不接受URL")
    parser.add_argument("output_dir", help="隔离输出目录，不得位于原视频所在目录内")
    parser.add_argument("--ffmpeg", help="现有本地FFmpeg路径；未提供时从PATH查找")
    parser.add_argument("--ffprobe", help="现有本地FFprobe路径；未提供时优先查找FFmpeg同目录")
    parser.add_argument("--times", help="可选显式时间码，逗号分隔；如 0,00:00:02,4.5")
    parser.add_argument("--interval-seconds", type=float, default=2.0, help="自动模式最大采样间隔，默认2秒")
    parser.add_argument("--scene-threshold", type=float, default=0.35, help="自动模式场景变化阈值，默认0.35")
    parser.add_argument("--max-frames", type=int, default=120, help="最大输出帧数，默认120")
    parser.add_argument("--stream-index", type=int, help="多视频流文件的绝对流编号")
    parser.add_argument("--source-id", default="V001", help="写入索引的本地视频来源ID，默认V001")
    parser.add_argument("--source-kind", choices=sorted(SOURCE_KINDS), default="unverified_local_video")
    parser.add_argument("--index-name", default="video-frame-index.json", help="输出索引文件名")
    parser.add_argument("--timeout-seconds", type=int, default=300, help="每个媒体命令的超时秒数")
    parser.add_argument("--overwrite", action="store_true", help="仅覆盖本工具生成的固定帧和索引")
    args = parser.parse_args()

    try:
        if "://" in args.video:
            raise ValueError("只接受本地视频文件，不接受URL。")
        video = Path(args.video).expanduser().resolve()
        if not video.is_file():
            raise ValueError(f"视频文件不存在：{video.name or 'local-video'}")
        if first_link_component(video) is not None:
            raise ValueError("视频源路径不得经过符号链接或目录联接。")
        if video.suffix.lower() not in ALLOWED_VIDEOS:
            raise ValueError(f"不支持的视频扩展名：{video.suffix}")
        if args.max_frames < 1 or args.max_frames > 10_000:
            raise ValueError("--max-frames 只接受1至10000。")
        if not math.isfinite(args.interval_seconds) or args.interval_seconds <= 0:
            raise ValueError("--interval-seconds 必须为正数。")
        if not math.isfinite(args.scene_threshold) or not 0 <= args.scene_threshold <= 1:
            raise ValueError("--scene-threshold 必须在0至1之间。")
        if args.timeout_seconds < 1:
            raise ValueError("--timeout-seconds 必须为正整数。")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", args.source_id) or ".." in args.source_id:
            raise ValueError("--source-id 只接受安全的字母、数字、点、下划线和连字符。")
        index_name = Path(args.index_name).name
        if index_name != args.index_name or not index_name.lower().endswith(".json"):
            raise ValueError("--index-name 必须是不含目录的JSON文件名。")

        raw_output = Path(args.output_dir).expanduser()
        absolute_output = raw_output if raw_output.is_absolute() else Path.cwd() / raw_output
        _guard_output_path(absolute_output)
        output_dir = absolute_output.resolve()
        try:
            output_dir.relative_to(video.parent)
        except ValueError:
            pass
        else:
            raise ValueError(f"输出目录不得位于原视频所在目录内（只读保护）：{output_dir}")
        _prepare_output(output_dir, args.overwrite, index_name)
        output_dir.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg = _tool(args.ffmpeg, "ffmpeg")
        ffprobe = _tool(args.ffprobe, "ffprobe", sibling_of=ffmpeg)
        probe = _probe(ffprobe, video, args.stream_index, args.timeout_seconds)
        times = _explicit_times(args.times, float(probe["duration_seconds"]), args.max_frames)
        source_digest = sha256(video)

        staging = Path(tempfile.mkdtemp(prefix=".video-frames-", dir=output_dir.parent)).resolve()
        published = False
        try:
            frames_dir = staging / "frames"
            frames_dir.mkdir()
            if times is None:
                candidates = _extract_auto(
                    ffmpeg,
                    video,
                    probe,
                    frames_dir,
                    args.interval_seconds,
                    args.scene_threshold,
                    args.max_frames,
                    args.timeout_seconds,
                )
                sampling_policy = "scene_and_interval"
            else:
                candidates = _extract_explicit(ffmpeg, video, probe["stream_index"], times, frames_dir, args.timeout_seconds)
                sampling_policy = "explicit_times"

            for candidate_path, _timestamp in candidates:
                _verify_png(candidate_path)

            unique: list[dict[str, Any]] = []
            duplicate_aliases: list[dict[str, Any]] = []
            by_digest: dict[str, dict[str, Any]] = {}
            for candidate_path, timestamp in sorted(candidates, key=lambda item: item[1]):
                digest = sha256(candidate_path)
                if digest in by_digest:
                    duplicate_aliases.append(
                        {
                            "canonical_frame_id": by_digest[digest]["frame_id"],
                            "alias_timestamp_seconds": round(timestamp, 6),
                            "alias_source_timecode": _timecode(timestamp),
                            "sha256": digest,
                        }
                    )
                    candidate_path.unlink()
                    continue
                sequence = len(unique) + 1
                frame_id = f"F{sequence:04d}"
                final_name = _filename(sequence, timestamp)
                final_path = frames_dir / final_name
                candidate_path.replace(final_path)
                record = {
                    "sequence": sequence,
                    "frame_id": frame_id,
                    "path": (Path("frames") / final_name).as_posix(),
                    "timestamp_seconds": round(timestamp, 6),
                    "source_timecode": _timecode(timestamp),
                    "source_frame_index": None,
                    "sha256": digest,
                    "source_video_sha256": source_digest,
                    "video_frame": {
                        "source_id": args.source_id,
                        "source_time_seconds": round(timestamp, 6),
                        "source_timecode": _timecode(timestamp),
                        "source_frame_index": None,
                        "source_stream_index": probe["stream_index"],
                        "source_kind": args.source_kind,
                        "rotation_normalized_by_decoder": True,
                    },
                    "original_carrier": {
                        "source_ref": args.source_id,
                        "filename": video.name,
                        "carrier_type": "video_recording",
                        "source_kind": args.source_kind,
                        "status": (
                            "candidate_original"
                            if args.source_kind == "original_recording"
                            else ("unverified" if args.source_kind == "unverified_local_video" else "derived_copy_not_original")
                        ),
                    },
                    "display_rotation_degrees_clockwise": 0,
                }
                unique.append(record)
                by_digest[digest] = record
            if not unique:
                raise ValueError("所有候选帧均未形成可用输出。")

            index = {
                "schema_version": 1,
                "read_only_source": True,
                "source_video": {
                    "source_id": args.source_id,
                    "filename": video.name,
                    "sha256": source_digest,
                    "size": video.stat().st_size,
                    "source_kind": args.source_kind,
                    **probe,
                },
                "extraction": {
                    "sampling_policy": sampling_policy,
                    "requested_times_seconds": times or [],
                    "interval_seconds": args.interval_seconds if times is None else None,
                    "scene_threshold": args.scene_threshold if times is None else None,
                    "max_frames": args.max_frames,
                    "deduplication": "exact_output_sha256_only",
                    "decoder": "ffmpeg",
                    "ffmpeg_version": _version(ffmpeg, args.timeout_seconds),
                    "ffprobe_version": _version(ffprobe, args.timeout_seconds),
                    "redaction_performed": False,
                },
                "frames": unique,
                "duplicate_aliases": duplicate_aliases,
            }
            (staging / index_name).write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
            if sha256(video) != source_digest:
                raise ValueError("原视频在截帧过程中发生变化，输出已阻断。")
            _publish(staging, output_dir, args.overwrite, index_name)
            published = True
        finally:
            if not published:
                _cleanup_staging(staging)

        print(f"已从本地视频提取 {len(unique)} 个唯一PNG帧；原视频未修改。")
        print(f"索引：{output_dir.name}/{index_name}")
        if args.source_kind != "original_recording":
            print("输入未被确认是案件原始录屏，不能自动认定为原始载体或正式证据来源。")
        print("本工具不执行脱敏；宣传视频发布前须走独立脱敏与公开版本复核流程。")
    except ValueError as exc:
        raise SystemExit(f"视频截帧失败：{exc}") from exc


if __name__ == "__main__":
    main()
