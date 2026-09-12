#!/usr/bin/env python3
"""Dependency-free v19 checks for shared path and privacy guards."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from path_safety import contains_local_path, first_link_component, is_link_or_junction, redact_local_paths


def make_junction(link: Path, target: Path) -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return result.returncode == 0 and is_link_or_junction(link)


def main() -> None:
    drive_backslash = "C:" + "\\" + "Users" + "\\demo\\case\\source.xlsx"
    drive_slash = "C:" + "/" + "Users/demo/case/source.xlsx"
    unc = "\\\\" + "server\\share\\case\\source.xlsx"
    samples = (
        drive_backslash,
        drive_slash,
        unc,
        "/" + "Users/demo/case/source.xlsx",
        "/" + "home/demo/case/source.xlsx",
        "/private/" + "tmp/demo/source.xlsx",
        "/" + "tmp/demo/source.xlsx",
    )
    for sample in samples:
        assert contains_local_path(sample), sample
        assert "demo" not in redact_local_paths(sample), sample
    assert not contains_local_path("https://example.test/case")

    with tempfile.TemporaryDirectory(prefix="evidence-v19-path-") as temp:
        root = Path(temp)
        target = root / "target"
        target.mkdir()
        junction = root / "junction"
        if make_junction(junction, target):
            nested = junction / "nested" / "output.json"
            assert first_link_component(nested) == junction
            assert is_link_or_junction(junction)

    print("v19 shared path/privacy guards: PASS")


if __name__ == "__main__":
    main()
