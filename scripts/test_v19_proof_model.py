#!/usr/bin/env python3
"""Synthetic regression for the v19 request-element-fact-evidence model."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from build_evidence_bundle import (  # noqa: E402
    ManifestError,
    _carrier_path_exists,
    build_proof_coverage_matrix,
    validate_manifest,
)
from path_safety import is_link_or_junction  # noqa: E402
from test_v18_legal_gates import make_legal_fixture  # noqa: E402


def expect_error(data: dict, base: Path, needle: str, *, allow_draft: bool = False) -> None:
    try:
        validate_manifest(data, base, allow_draft=allow_draft)
    except ManifestError as exc:
        assert needle in str(exc), str(exc)
    else:
        raise AssertionError(f"expected error containing {needle}")


def add_second_material(data: dict, base: Path) -> None:
    Image.new("RGB", (64, 64), "#802050").save(base / "synthetic-2.png")
    data["evidence_groups"][0]["materials"].append({
        "material_id": "M002",
        "path": "synthetic-2.png",
        "source": "本测试生成的第二张全合成原图",
        "original_carrier": {"path": "synthetic-2.png", "carrier_type": "native_image"},
        "fact": "紫色合成画面",
        "readability": "clear",
    })


def make_directory_link(link: Path, target: Path) -> bool:
    """Create a directory link where the host permits it for the regression."""

    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        return result.returncode == 0 and is_link_or_junction(link)
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        return False
    return is_link_or_junction(link)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="evidence-v19-proof-") as temp:
        base = Path(temp)
        original = make_legal_fixture(base)
        normalized = validate_manifest(copy.deepcopy(original), base)
        assert normalized["_coverage_matrix"]["status"] == "covered"

        carrier_root = base / "carrier-root"
        carrier_root.mkdir()
        (carrier_root / "carrier.bin").write_bytes(b"carrier")
        assert _carrier_path_exists("carrier-root/carrier.bin", base)
        linked_carrier_root = base / "linked-carrier-root"
        if make_directory_link(linked_carrier_root, carrier_root):
            # A linked directory still resolves to a real file, but it is not
            # an acceptable original-carrier path for a formal manifest.
            assert not _carrier_path_exists("linked-carrier-root/carrier.bin", base)

        material_summary = copy.deepcopy(original)
        material_summary["evidence_groups"][0]["proof_object"] = (
            "证明聊天记录内容；对应本测试第1项请求中的画面颜色核对事实。"
        )
        expect_error(material_summary, base, "仅概括材料名称或内容")
        material_summary_with_generic_purpose = copy.deepcopy(original)
        material_summary_with_generic_purpose["evidence_groups"][0]["proof_object"] = (
            "证明合同内容，用于支持第1项请求。"
        )
        expect_error(material_summary_with_generic_purpose, base, "仅概括材料名称或内容")

        for text in (
            "画面显示蓝色色块；对应法律要件。",
            "画面显示蓝色色块；对应本案诉讼请求。",
        ):
            generic_target = copy.deepcopy(original)
            generic_target["evidence_groups"][0]["proof_object"] = text
            expect_error(generic_target, base, "未说明该材料服务的具体请求")

        for text in (
            "证明账号是被告本人；对应第1项价款请求。",
            "证明被告承担连带责任；对应第1项价款请求。",
            "证明关联裁判已确定本案事实；对应第1项价款请求。",
            "拟证明合同成立；对应第1项请求。",
            "拟证明本案请求应予支持；对应第1项请求。",
        ):
            risky_conclusion = copy.deepcopy(original)
            risky_conclusion["evidence_groups"][0]["proof_object"] = text
            expect_error(risky_conclusion, base, "高风险结论措辞")

        generic_purpose = copy.deepcopy(original)
        generic_purpose["proof_claims"][0]["purpose"] = "用于支持本案诉讼请求。"
        expect_error(generic_purpose, base, "purpose 过于空泛")

        generic_pleading_reference = copy.deepcopy(original)
        generic_pleading_reference["proof_claims"][0]["purpose_basis"]["reference"] = "起诉状"
        expect_error(generic_pleading_reference, base, "书状具体页码")

        missing_fact_level = copy.deepcopy(original)
        missing_fact_level["proof_claims"][0].pop("fact_level")
        expect_error(missing_fact_level, base, "fact_level")
        legacy_draft = validate_manifest(missing_fact_level, base, allow_draft=True)
        assert legacy_draft["_effective_draft"] is True

        missing_targets = copy.deepcopy(original)
        missing_targets.pop("proof_targets")
        missing_targets["proof_claims"][0]["purpose_basis"].pop("target_kind")
        missing_targets["proof_claims"][0]["purpose_basis"].pop("target_id")
        missing_targets["proof_claims"][0]["purpose_basis"].pop("legal_element")
        expect_error(missing_targets, base, "proof_targets")
        old_v2_draft = validate_manifest(missing_targets, base, allow_draft=True)
        assert old_v2_draft["_effective_draft"] is True

        for fact_level in ("element_fact", "indirect_fact", "auxiliary_fact", "procedural_fact"):
            fixture = copy.deepcopy(original)
            fixture["proof_claims"][0]["fact_level"] = fact_level
            validate_manifest(fixture, base)
        invalid_fact_level = copy.deepcopy(original)
        invalid_fact_level["proof_claims"][0]["fact_level"] = "ultimate_conclusion"
        expect_error(invalid_fact_level, base, "fact_level 不合法")

        for role in ("direct", "indirect", "corroborative", "rebuttal"):
            fixture = copy.deepcopy(original)
            fixture["proof_claims"][0]["role"] = role
            validate_manifest(fixture, base)
        invalid_role = copy.deepcopy(original)
        invalid_role["proof_claims"][0]["role"] = "conclusive"
        expect_error(invalid_role, base, "role 不合法")
        linking_without_cross_group = copy.deepcopy(original)
        linking_without_cross_group["proof_claims"][0]["role"] = "linking"
        expect_error(linking_without_cross_group, base, "必须实际跨组回指")

        missing_page = copy.deepcopy(original)
        missing_page["proof_claims"][0]["material_refs"][0].pop("page")
        expect_error(missing_page, base, "缺少 page")
        missing_region = copy.deepcopy(original)
        missing_region["proof_claims"][0]["material_refs"][0].pop("region")
        expect_error(missing_region, base, "缺少 region")
        unknown_material = copy.deepcopy(original)
        unknown_material["proof_claims"][0]["material_refs"][0]["material_id"] = "M999"
        expect_error(unknown_material, base, "回指不存在的材料")

        uncovered = copy.deepcopy(original)
        uncovered["proof_targets"][0]["legal_elements"].append("第二项尚无材料的合成要件")
        expect_error(uncovered, base, "法律要件缺少证据覆盖")
        uncovered_draft = validate_manifest(uncovered, base, allow_draft=True)
        assert any(row["status"] == "uncovered" for row in uncovered_draft["_coverage_matrix"]["coverage"])

        orphan = copy.deepcopy(original)
        add_second_material(orphan, base)
        expect_error(orphan, base, "有材料但无证明用途")
        orphan_draft = validate_manifest(orphan, base, allow_draft=True)
        assert orphan_draft["_coverage_matrix"]["materials_without_purpose"] == ["M002"]

        linked = copy.deepcopy(original)
        add_second_material(linked, base)
        linked["evidence_groups"][0]["materials"] = linked["evidence_groups"][0]["materials"][:1]
        linked["evidence_groups"].append({
            "number": 2,
            "group_id": "G02",
            "evidence_name": "全合成紫色色块",
            "evidence_form": "电子数据打印件",
            "proof_object": "第二张合成画面为紫色色块；对应本测试第1项请求中的组合画面核对事实。",
            "materials": [orphan["evidence_groups"][0]["materials"][1]],
        })
        linked["validation"]["checks"]["proof_scope_checked"]["material_refs"] = ["M001", "M002"]
        linked["validation"]["checks"]["original_carrier_checked"]["material_refs"] = ["M001", "M002"]
        linked_claim = linked["proof_claims"][0]
        linked_claim["role"] = "linking"
        linked_claim["cross_group"] = True
        linked_claim["purpose"] = "结合第1组与第2组证据，用于支持本测试第1项请求中的组合画面核对。"
        linked_claim["material_refs"].append({"material_id": "M002", "page": 1, "region": "全图"})
        linked_result = validate_manifest(linked, base)
        assert linked_result["_coverage_matrix"]["cross_group_links"][0]["role"] == "linking"

        linked_wrong_role = copy.deepcopy(linked)
        linked_wrong_role["proof_claims"][0]["role"] = "direct"
        expect_error(linked_wrong_role, base, "跨证据组共同证明时 role 必须为 linking")
        linked_no_bridge = copy.deepcopy(linked)
        linked_no_bridge["proof_claims"][0]["purpose"] = "用于支持本测试第1项请求中的组合画面核对。"
        expect_error(linked_no_bridge, base, "必须明确说明组间衔接")
        linked_generic_bridge = copy.deepcopy(linked)
        linked_generic_bridge["proof_claims"][0]["purpose"] = "结合证据，用于支持第1项组合画面核对请求。"
        expect_error(linked_generic_bridge, base, "必须明确说明组间衔接")

        conflict = copy.deepcopy(original)
        conflict["evidence_groups"][0]["conflicts"] = ["两张合成说明对颜色命名不一致"]
        conflict_draft = validate_manifest(conflict, base, allow_draft=True)
        assert conflict_draft["_coverage_matrix"]["status"] == "conflict"
        assert conflict_draft["_coverage_matrix"]["unresolved_conflicts"]

        amount_conflict = copy.deepcopy(original)
        amount_conflict["amount_conflicts"] = ["申请额与实际支付额尚未核对"]
        amount_conflict_draft = validate_manifest(amount_conflict, base, allow_draft=True)
        assert amount_conflict_draft["_coverage_matrix"]["status"] == "conflict"
        assert any(
            item["scope"] == "financial"
            for item in amount_conflict_draft["_coverage_matrix"]["unresolved_conflicts"]
        )

        unresolved = copy.deepcopy(original)
        unresolved["validation"]["unresolved_issues"] = [
            "信息缺失[金额][用户选择不提供]：未说明实际支付额；影响：金额口径无法核对。"
        ]
        unresolved_matrix = build_proof_coverage_matrix(unresolved)
        assert unresolved_matrix["status"] == "conflict"
        assert any(item["scope"] == "validation" for item in unresolved_matrix["unresolved_conflicts"])

    with tempfile.TemporaryDirectory(prefix="evidence-v19-cli-") as temp:
        root = Path(temp)
        case = root / "case"
        case.mkdir()
        manifest = make_legal_fixture(case)
        manifest_path = case / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        output = root / "output" / "bundle.docx"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "build_evidence_bundle.py"), str(manifest_path), str(output)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        matrix_path = output.with_name("bundle.coverage-matrix.json")
        assert output.is_file() and matrix_path.is_file()
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        assert matrix["status"] == "covered"
        assert "absolute_path" not in json.dumps(matrix, ensure_ascii=False)
        qa = subprocess.run(
            [sys.executable, str(SCRIPTS / "qa_bundle.py"), str(output), "--manifest", str(manifest_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        qa_result = json.loads(qa.stdout)
        assert qa.returncode == 1 and qa_result["status"] == "HOLD", qa.stdout + qa.stderr
        assert qa_result["failure_codes"] == ["RENDER_REVIEW_UNAVAILABLE"], qa_result

    print("v19 proof model and coverage matrix: PASS")


if __name__ == "__main__":
    main()
