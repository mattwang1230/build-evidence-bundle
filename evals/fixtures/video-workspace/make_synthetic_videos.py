#!/usr/bin/env python3
"""Generate deterministic synthetic video fixtures with an existing FFmpeg."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def tool_path(explicit: str | None) -> str:
    value = explicit or shutil.which("ffmpeg")
    if not value or not Path(value).is_file():
        raise SystemExit("未找到FFmpeg；请通过 --ffmpeg 指定现有本地可执行文件。")
    return str(Path(value).resolve())


def make_video(ffmpeg: str, output: Path, colors: list[str]) -> None:
    command = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    for color in colors:
        command.extend(["-f", "lavfi", "-i", f"color=c={color}:s=640x360:d=1:r=30"])
    inputs = "".join(f"[{index}:v]" for index in range(len(colors)))
    command.extend(
        [
            "-filter_complex",
            f"{inputs}concat=n={len(colors)}:v=1:a=0,format=yuv420p[v]",
            "-map",
            "[v]",
            "-c:v",
            "mpeg4",
            "-q:v",
            "2",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成不含真实个人信息的合成视频评测夹具")
    parser.add_argument("--ffmpeg", help="现有本地FFmpeg路径；未提供时从PATH查找")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖两个固定夹具文件")
    args = parser.parse_args()
    ffmpeg = tool_path(args.ffmpeg)
    root = Path(__file__).resolve().parent
    input_dir = root / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    outputs = [input_dir / "demo-6s.mp4", input_dir / "dedup-4s.mp4"]
    if any(path.exists() for path in outputs) and not args.overwrite:
        raise SystemExit("夹具已存在；如需重建请显式使用 --overwrite。")
    make_video(ffmpeg, outputs[0], ["blue", "blue", "green", "green", "red", "red"])
    make_video(ffmpeg, outputs[1], ["blue", "green", "blue", "0x0080ff"])
    print("已生成全合成视频夹具；没有读取或写入真实案件材料。")


if __name__ == "__main__":
    main()
