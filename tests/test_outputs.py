import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAM = Path(os.environ.get("PROGRAM", "/app/xrd_stress_report.py"))


def peak_for_stress(stress_mpa, tilt_deg, *, zero=0.0, d0=0.203, wavelength=0.2291, youngs=210.0, poisson=0.30):
    k = (1.0 + poisson) / (youngs * 1000.0)
    spacing = d0 * (1.0 + k * stress_mpa * math.sin(math.radians(tilt_deg)) ** 2)
    return math.degrees(2.0 * math.asin(wavelength / (2.0 * spacing))) + zero


def measurement(azimuth, stress, tilt, *, quality=0.99, zero=0.0):
    return {"azimuth_deg": azimuth, "tilt_deg": tilt, "peak_2theta_deg": peak_for_stress(stress, tilt, zero=zero), "quality": quality}


def base(measurements, *, zero=0.0, limits=(350.0, 500.0)):
    return {
        "specimen_id": "RB-2026-017",
        "material": "bearing_steel",
        "wavelength_nm": 0.2291,
        "stress_free_d_nm": 0.203,
        "youngs_modulus_gpa": 210.0,
        "poisson_ratio": 0.30,
        "instrument_zero_deg": zero,
        "limits": {"max_tensile_mpa": limits[0], "max_compressive_mpa": limits[1]},
        "measurements": measurements,
    }


def run_process(data):
    process, output_text, _, _ = run_process_with_artifacts(data)
    return process, output_text


def run_process_with_artifacts(data, *, initial_output=None):
    env = dict(os.environ)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / "input.json"
        output_path = Path(tmp) / "output.json"
        input_path.write_text(json.dumps(data), encoding="utf-8")
        if initial_output is not None:
            output_path.write_bytes(initial_output)
        process = subprocess.run(
            [sys.executable, str(PROGRAM), str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            env=env,
        )
        output_bytes = output_path.read_bytes() if output_path.exists() else None
        files = sorted(path.name for path in Path(tmp).iterdir())
        output_text = output_bytes.decode("utf-8") if output_bytes is not None else None
        return process, output_text, output_bytes, files


def run(data):
    process, output_text = run_process(data)
    if process.returncode != 0 or output_text is None:
        return None
    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        return None


def stress(result, azimuth):
    return next(item["stress_mpa"] for item in result["directions"] if item["azimuth_deg"] == azimuth)


def issue_codes(result):
    """提取报告中的稳定问题标识，避免测试依赖说明文本。"""
    return {item["code"] for item in result["issues"]}


def test_positive_zero_correction():
    """题面要求先扣除正向仪器零点，再按布拉格定律计算应力。"""
    result = run(base([measurement(0, 120.0, tilt, zero=0.12) for tilt in (0, 20, 40, 60)], zero=0.12))
    assert result and len(result["directions"]) == 1
    assert stress(result, 0) == pytest.approx(120.0, rel=1e-4, abs=1e-4)


def test_negative_zero_correction():
    """题面要求负向仪器零点同样参与两倍衍射角修正。"""
    result = run(base([measurement(0, -80.0, tilt, zero=-0.08) for tilt in (0, 25, 50, 70)], zero=-0.08))
    assert result and stress(result, 0) == pytest.approx(-80.0, rel=1e-4, abs=1e-4)


def test_tensile_classification():
    """题面要求正残余应力输出为拉应力，并进入拉应力汇总。"""
    result = run(base([measurement(0, 140.0, tilt, zero=0.12) for tilt in (0, 20, 40, 60)], zero=0.12))
    assert result and result["directions"][0]["stress_type"] == "tensile"
    assert result["summary"]["max_tensile_mpa"] == pytest.approx(140.0, rel=1e-4, abs=1e-4)


def test_compressive_classification():
    """题面要求负残余应力输出为压应力，并进入压应力汇总。"""
    result = run(base([measurement(0, -220.0, tilt, zero=-0.08) for tilt in (0, 20, 40, 60)], zero=-0.08))
    assert result and result["directions"][0]["stress_type"] == "compressive"
    assert result["summary"]["max_compressive_mpa"] == pytest.approx(-220.0, rel=1e-4, abs=1e-4)


def test_directions_are_fitted_separately():
    """题面要求不同方位分别拟合，不能混合成一条回归线。"""
    rows = [measurement(0, 100.0, tilt) for tilt in (0, 25, 50, 70)] + [measurement(90, -220.0, tilt) for tilt in (0, 25, 50, 70)]
    result = run(base(rows))
    assert result and len(result["directions"]) == 2
    assert stress(result, 0) == pytest.approx(100.0, rel=1e-4, abs=1e-4)
    assert stress(result, 90) == pytest.approx(-220.0, rel=1e-4, abs=1e-4)


def test_worst_direction_summary():
    """题面要求最危险方位按应力绝对值最大确定，并正确汇总两种应力。"""
    rows = [measurement(0, 100.0, tilt) for tilt in (0, 25, 50, 70)] + [measurement(90, -220.0, tilt) for tilt in (0, 25, 50, 70)]
    result = run(base(rows))
    assert result and len(result["directions"]) == 2
    assert stress(result, 0) == pytest.approx(100.0, rel=1e-4, abs=1e-4)
    assert stress(result, 90) == pytest.approx(-220.0, rel=1e-4, abs=1e-4)
    assert result["summary"]["max_tensile_mpa"] == pytest.approx(100.0, rel=1e-4, abs=1e-4)
    assert result["summary"]["max_compressive_mpa"] == pytest.approx(-220.0, rel=1e-4, abs=1e-4)
    assert result["summary"]["worst_azimuth_deg"] == 90


def test_low_quality_is_excluded():
    """题面要求质量低于 0.8 的记录不得参与拟合但必须留下问题标记。"""
    rows = [measurement(0, 80.0, tilt) for tilt in (0, 20, 40, 60)]
    rows.append(measurement(0, 900.0, 50, quality=0.2))
    result = run(base(rows))
    assert result and stress(result, 0) == pytest.approx(80.0, rel=1e-4, abs=1e-4)
    assert "LOW_QUALITY" in issue_codes(result) and result["directions"][0]["valid_points"] == 4


def test_duplicate_keeps_higher_quality():
    """题面要求同方位同倾转角重复记录只保留质量更高的一条。"""
    rows = [measurement(45, 80.0, 0), measurement(45, 80.0, 25, quality=0.95), measurement(45, 900.0, 25, quality=0.90), measurement(45, 80.0, 50), measurement(45, 80.0, 70)]
    result = run(base(rows))
    assert result and stress(result, 45) == pytest.approx(80.0, rel=1e-4, abs=1e-4)
    assert result["directions"][0]["valid_points"] == 4 and "DUPLICATE_MEASUREMENT" in issue_codes(result)


def test_duplicate_result_is_order_invariant():
    """题面要求改变测量记录顺序后重复选择和最终报告保持一致。"""
    rows = [measurement(0, 140.0, 0), measurement(0, 140.0, 30), measurement(0, 140.0, 60), measurement(0, 140.0, 60, quality=0.99), measurement(90, -180.0, 0), measurement(90, -180.0, 30), measurement(90, -180.0, 60)]
    shuffled = list(rows)
    random.Random(7).shuffle(shuffled)
    first, second = run(base(rows)), run(base(shuffled))
    assert first and second and first == second
    assert len(first["directions"]) == 2
    assert stress(first, 0) == pytest.approx(140.0, rel=1e-4, abs=1e-4)
    assert stress(first, 90) == pytest.approx(-180.0, rel=1e-4, abs=1e-4)
    assert first["directions"][0]["valid_points"] == 3
    assert first["directions"][1]["valid_points"] == 3
    assert "DUPLICATE_MEASUREMENT" in issue_codes(first)


def test_invalid_measurements_are_reported():
    """题面要求非法倾转角、峰位和质量记录被排除并留下问题标记。"""
    rows = [measurement(0, 100.0, tilt) for tilt in (0, 30, 60)]
    rows += [{"azimuth_deg": 0, "tilt_deg": 90, "peak_2theta_deg": 70, "quality": 0.9}, {"azimuth_deg": 0, "tilt_deg": 20, "peak_2theta_deg": -1, "quality": 0.9}, {"azimuth_deg": 0, "tilt_deg": 20, "peak_2theta_deg": 70, "quality": 1.2}]
    result = run(base(rows))
    assert result and len(result["directions"]) == 1
    assert issue_codes(result) >= {"INVALID_ANGLE", "OUT_OF_RANGE_TILT", "OUT_OF_RANGE_QUALITY"}


def test_insufficient_points_requires_review():
    """题面要求一个方位少于三个有效倾转点时进入复核。"""
    result = run(base([measurement(0, 100.0, 20), measurement(0, 100.0, 40)]))
    assert result and result["status"] == "REVIEW" and result["directions"] == []
    assert "INSUFFICIENT_TILT_POINTS" in issue_codes(result)


def test_equal_quality_duplicate_tie_is_stable():
    """题面要求质量相同的重复记录使用确定性规则且不随输入顺序改变。"""
    rows = [measurement(0, 100.0, 0), measurement(0, 100.0, 30), measurement(0, 100.0, 60), measurement(0, 700.0, 30, quality=0.99)]
    reversed_rows = list(reversed(rows))
    first, second = run(base(rows)), run(base(reversed_rows))
    assert first == second
    assert first and "DUPLICATE_MEASUREMENT" in issue_codes(first)


def test_limit_boundary_passes():
    """题面要求应力等于工艺限值时仍属于不超限，且报告数值必须对应实际边界。"""
    result = run(base([measurement(0, 350.0, tilt) for tilt in (0, 20, 40, 60)], limits=(350.0001, 500.0)))
    assert result and result["status"] == "PASS"
    assert result["summary"]["max_tensile_mpa"] == pytest.approx(350.0, rel=1e-4, abs=1e-4)


def test_limit_exceedance_rejects():
    """题面要求任一方向超出拉压限值时判为拒收。"""
    result = run(base([measurement(0, 420.0, tilt) for tilt in (0, 20, 40, 60)], limits=(350.0, 500.0)))
    assert result and result["status"] == "REJECT"


def test_tensile_boundary_does_not_mask_compressive_exceedance():
    """题面要求拉应力到达上限时仍须检查另一方向，压应力超限不能被边界值掩盖。"""
    rows = [measurement(0, 350.0, tilt) for tilt in (0, 25, 50, 70)]
    rows += [measurement(90, -620.0, tilt) for tilt in (0, 25, 50, 70)]
    result = run(base(rows, limits=(350.0, 500.0)))
    assert result and result["status"] == "REJECT"


def test_near_zero_tilt_variation_requires_review():
    """题面要求有效倾转点几乎没有变化时不能输出应力，必须进入复核。"""
    rows = [
        measurement(0, 100.0, 0.0),
        measurement(0, 100.0, 1e-6),
        measurement(0, 100.0, 2e-6),
    ]
    result = run(base(rows))
    assert result is not None
    assert result["status"] == "REVIEW"
    assert result["directions"] == []
    assert "INSUFFICIENT_TILT_VARIATION" in issue_codes(result)


def test_invalid_limits_are_rejected_without_side_effects():
    """题面要求无效工艺限值拒收，并保持已有报告和临时目录内容不变。"""
    invalid_limits = (
        None,
        {},
        {"max_tensile_mpa": 350.0},
        {"max_compressive_mpa": 500.0},
        {"max_tensile_mpa": -1.0, "max_compressive_mpa": 500.0},
        {"max_tensile_mpa": "350", "max_compressive_mpa": 500.0},
        {"max_tensile_mpa": True, "max_compressive_mpa": 500.0},
    )
    sentinel = b"previous-report\n"
    for limits in invalid_limits:
        data = base([measurement(0, 100.0, tilt) for tilt in (0, 30, 60)])
        data["limits"] = limits
        process, output_text, output_bytes, files = run_process_with_artifacts(data, initial_output=sentinel)
        assert process.returncode != 0
        assert process.stderr.startswith("运行失败: ")
        assert output_bytes == sentinel
        assert files == ["input.json", "output.json"]
