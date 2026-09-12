#!/usr/bin/env python3
"""Cross-machine contract checks using only synthetic temporary inputs."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from test_v18_provenance import make_xlsx
from qa_bundle import expected_attachment_ids


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
)


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False, cwd=cwd)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    scripts = Path(__file__).resolve().parent
    alias_manifest = {
        "evidence_groups": [{"materials": [
            {"material_id": "M001", "material_aliases": ["M002"]},
            {"material_id": "M002", "canonical_material_id": "M001"},
        ]}]
    }
    assert expected_attachment_ids(alias_manifest) == ["M001"]
    with tempfile.TemporaryDirectory(prefix="evidence-v18-portable-") as temp:
        root = Path(temp)
        inputs = root / "inputs"
        outputs = root / "outputs"
        inputs.mkdir()
        outputs.mkdir()
        (inputs / "image.png").write_bytes(PNG)
        (inputs / "~$locked.xlsx").write_bytes(b"synthetic lock")
        (inputs / ".DS_Store").write_bytes(b"synthetic metadata")
        source = inputs / "source.xlsx"
        make_xlsx(source)

        inventory_path = outputs / "inventory.json"
        inventory_result = run(
            [sys.executable, str(scripts / "inspect_materials.py"), str(inputs), "--output", str(inventory_path)]
        )
        assert inventory_result.returncode == 1
        inventory_text = inventory_path.read_text(encoding="utf-8")
        inventory = json.loads(inventory_text)
        assert "absolute_path" not in inventory_text
        assert "root" not in inventory
        assert inventory["root_label"] == "inputs"

        missing = str(root / "missing-tool")
        capability = run(
            [
                sys.executable,
                str(scripts / "office_capabilities.py"),
                "--json",
                "--office-converter",
                missing,
                "--pdf-rasterizer",
                missing,
                "--ffmpeg",
                missing,
                "--ffprobe",
                missing,
            ]
        )
        assert capability.returncode == 0
        assert missing not in capability.stdout
        capability_json = json.loads(capability.stdout)
        assert capability_json["capabilities"]["office_to_pdf"]["status"] == "unavailable"
        assert capability_json["capabilities"]["office_to_pdf"]["discovery"] == "explicit"

        before = (source.stat().st_size, source.stat().st_mtime_ns, digest(source))
        converted = outputs / "converted"
        result = run(
            [
                sys.executable,
                str(scripts / "convert_office.py"),
                str(source),
                "--workspace-root",
                str(root),
                "--output-dir",
                str(converted),
                "--office-converter",
                missing,
                "--pdf-rasterizer",
                missing,
            ]
        )
        assert result.returncode == 1
        sidecar_path = converted / "office-provenance.json"
        assert sidecar_path.is_file()
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert sidecar["formal_release_gate"]["status"] == "HOLD"
        assert "OFFICE_CONVERTER_UNAVAILABLE" in sidecar["formal_release_gate"]["failure_codes"]
        assert "OFFICE_RASTERIZER_UNAVAILABLE" in sidecar["formal_release_gate"]["failure_codes"]
        assert not list(converted.glob("*.pdf"))
        assert not list(converted.glob("*.png"))
        after = (source.stat().st_size, source.stat().st_mtime_ns, digest(source))
        assert before == after

        relative_output = outputs / "relative-converted"
        relative = run(
            [
                sys.executable,
                str(scripts / "convert_office.py"),
                "inputs/source.xlsx",
                "--workspace-root",
                str(root),
                "--output-dir",
                "outputs/relative-converted",
                "--office-converter",
                missing,
                "--pdf-rasterizer",
                missing,
            ],
            cwd=outputs,
        )
        assert relative.returncode == 1
        assert (relative_output / "office-provenance.json").is_file()

        unsafe_output = outputs / "unsafe-source-id"
        unsafe = run(
            [
                sys.executable,
                str(scripts / "convert_office.py"),
                "inputs/source.xlsx",
                "--workspace-root",
                str(root),
                "--output-dir",
                "outputs/unsafe-source-id",
                "--source-id",
                "../escape",
                "--office-converter",
                missing,
                "--pdf-rasterizer",
                missing,
            ]
        )
        assert unsafe.returncode != 0
        assert not unsafe_output.exists()

        for name in (
            "inspect_materials.py",
            "inspect_office_materials.py",
            "office_capabilities.py",
            "convert_office.py",
            "validate_provenance.py",
            "build_evidence_bundle.py",
            "qa_bundle.py",
            "package_check.py",
        ):
            help_result = run([sys.executable, str(scripts / name), "--help"])
            assert help_result.returncode == 0, f"{name}: {help_result.stdout}{help_result.stderr}"

    print("v18 portability and missing-tool degradation: PASS")


if __name__ == "__main__":
    main()
