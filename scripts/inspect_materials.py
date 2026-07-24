#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="只读盘点案件材料并计算 SHA-256")
    parser.add_argument("material_dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.material_dir).resolve()
    if not root.is_dir():
        raise SystemExit(f"材料目录不存在：{root}")
    output_path = Path(args.output).resolve()

    records = []
    candidates = (p for p in root.rglob("*") if p.is_file() and p.resolve() != output_path)
    for path in sorted(candidates, key=lambda p: str(p).lower()):
        stat = path.stat()
        records.append(
            {
                "relative_path": str(path.relative_to(root)),
                "absolute_path": str(path),
                "suffix": path.suffix.lower(),
                "size": stat.st_size,
                "sha256": sha256(path),
            }
        )

    by_hash = {}
    for item in records:
        by_hash.setdefault(item["sha256"], []).append(item["relative_path"])
    duplicates = [paths for paths in by_hash.values() if len(paths) > 1]

    output = {
        "root": str(root),
        "file_count": len(records),
        "files": records,
        "duplicate_groups": duplicates,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已盘点 {len(records)} 个文件；完全重复组 {len(duplicates)} 个。")


if __name__ == "__main__":
    main()
