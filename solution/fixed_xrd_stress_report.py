#!/usr/bin/env python3
import json
import math
import sys
from collections import defaultdict

REQUIRED_TOP = ("specimen_id", "material", "wavelength_nm", "stress_free_d_nm", "youngs_modulus_gpa", "poisson_ratio", "limits", "measurements")
REQUIRED_ROW = ("azimuth_deg", "tilt_deg", "peak_2theta_deg", "quality")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _load(path):
    def reject_constant(value):
        raise ValueError(f"不允许非有限数字: {value}")

    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle, parse_constant=reject_constant)


def _regress(points):
    xs = [math.sin(math.radians(item["tilt_deg"])) ** 2 for item in points]
    ys = [item["strain"] for item in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 1e-15:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    return slope, math.sqrt(sum(value * value for value in residuals) / len(residuals))


def _validate_header(data):
    if not isinstance(data, dict) or any(key not in data for key in REQUIRED_TOP):
        raise ValueError("输入资料缺少必要字段")
    for key in ("wavelength_nm", "stress_free_d_nm", "youngs_modulus_gpa", "poisson_ratio"):
        if not _finite(data[key]):
            raise ValueError(f"{key} 不是有限数字")
    if data["wavelength_nm"] <= 0 or data["stress_free_d_nm"] <= 0 or data["youngs_modulus_gpa"] <= 0:
        raise ValueError("材料参数必须为正数")
    if not -1.0 < data["poisson_ratio"] < 0.5:
        raise ValueError("泊松比超出范围")
    limits = data["limits"]
    if not isinstance(limits, dict) or not all(_finite(limits.get(key)) and limits[key] >= 0 for key in ("max_tensile_mpa", "max_compressive_mpa")):
        raise ValueError("工艺限值无效")
    if "instrument_zero_deg" in data and not _finite(data["instrument_zero_deg"]):
        raise ValueError("仪器零点不是有限数字")
    if not isinstance(data["measurements"], list):
        raise ValueError("measurements 必须是数组")


def analyze(data):
    _validate_header(data)
    wavelength = float(data["wavelength_nm"])
    d0 = float(data["stress_free_d_nm"])
    youngs_modulus = float(data["youngs_modulus_gpa"])
    poisson_ratio = float(data["poisson_ratio"])
    zero = float(data.get("instrument_zero_deg", 0.0))
    limits = data["limits"]
    grouped = defaultdict(dict)
    issues = []

    for row in data["measurements"]:
        if not isinstance(row, dict) or not all(key in row for key in REQUIRED_ROW):
            issues.append("MALFORMED_MEASUREMENT")
            continue
        if not all(_finite(row[key]) for key in REQUIRED_ROW):
            issues.append("NONFINITE_MEASUREMENT")
            continue
        quality = float(row["quality"])
        if not 0.0 <= quality <= 1.0:
            issues.append("OUT_OF_RANGE_QUALITY")
            continue
        if quality < 0.8:
            issues.append("LOW_QUALITY")
            continue
        tilt = float(row["tilt_deg"])
        peak = float(row["peak_2theta_deg"])
        if not 0.0 <= tilt <= 85.0:
            issues.append("OUT_OF_RANGE_TILT")
            continue
        if peak <= 0.0:
            issues.append("INVALID_ANGLE")
            continue
        corrected_two_theta = peak - zero
        theta = math.radians(corrected_two_theta / 2.0)
        sine = math.sin(theta)
        if not 0.0 < corrected_two_theta < 180.0 or sine <= 0.0:
            issues.append("INVALID_ANGLE")
            continue
        spacing = wavelength / (2.0 * sine)
        strain = (spacing - d0) / d0
        candidate = {"tilt_deg": tilt, "strain": strain, "quality": quality, "peak_2theta_deg": peak}
        azimuth = float(row["azimuth_deg"])
        existing = grouped[azimuth].get(tilt)
        if existing is not None:
            issues.append("DUPLICATE_MEASUREMENT")
            if (candidate["quality"], -candidate["peak_2theta_deg"]) <= (existing["quality"], -existing["peak_2theta_deg"]):
                continue
        grouped[azimuth][tilt] = candidate

    scale = youngs_modulus * 1000.0 / (1.0 + poisson_ratio)
    directions = []
    for azimuth in sorted(grouped):
        rows = [grouped[azimuth][tilt] for tilt in sorted(grouped[azimuth])]
        if len(rows) < 3:
            issues.append("INSUFFICIENT_TILT_POINTS")
            continue
        fit = _regress(rows)
        if fit is None:
            issues.append("INSUFFICIENT_TILT_VARIATION")
            continue
        slope, rmse = fit
        stress = slope * scale
        directions.append({
            "azimuth_deg": azimuth,
            "stress_mpa": stress,
            "stress_type": "tensile" if stress >= 0.0 else "compressive",
            "fit_rmse_mpa": rmse * scale,
            "valid_points": len(rows),
        })

    if not directions:
        status, max_tensile, max_compressive, worst = "REVIEW", 0.0, 0.0, None
    else:
        max_tensile = max((max(item["stress_mpa"], 0.0) for item in directions), default=0.0)
        max_compressive = min((min(item["stress_mpa"], 0.0) for item in directions), default=0.0)
        worst = min(directions, key=lambda item: (-abs(item["stress_mpa"]), item["azimuth_deg"]))["azimuth_deg"]
        tensile_limit = float(limits["max_tensile_mpa"])
        compressive_limit = float(limits["max_compressive_mpa"])
        tensile_ok = max_tensile <= tensile_limit or math.isclose(max_tensile, tensile_limit, rel_tol=1e-9, abs_tol=1e-9)
        compressive_ok = abs(max_compressive) <= compressive_limit or math.isclose(abs(max_compressive), compressive_limit, rel_tol=1e-9, abs_tol=1e-9)
        status = "PASS" if tensile_ok and compressive_ok else "REJECT"

    issue_messages = {
        "DUPLICATE_MEASUREMENT": "重复测量已去重",
        "INVALID_ANGLE": "修正后两倍角无法用于布拉格计算",
        "INSUFFICIENT_TILT_POINTS": "有效倾转点少于 3 个",
        "INSUFFICIENT_TILT_VARIATION": "有效倾转点没有变化",
        "LOW_QUALITY": "峰拟合质量低于 0.8",
        "MALFORMED_MEASUREMENT": "测量记录缺少必要字段",
        "NONFINITE_MEASUREMENT": "测量记录包含非有限数字",
        "OUT_OF_RANGE_QUALITY": "峰拟合质量超出 0 到 1",
        "OUT_OF_RANGE_TILT": "倾转角超出 0 到 85 度",
    }
    issue_report = [
        {"code": code, "count": issues.count(code), "message": issue_messages.get(code, code)}
        for code in sorted(set(issues))
    ]
    return {
        "specimen_id": data["specimen_id"],
        "status": status,
        "directions": directions,
        "summary": {"max_tensile_mpa": max_tensile, "max_compressive_mpa": max_compressive, "worst_azimuth_deg": worst},
        "issues": issue_report,
    }


def main(argv):
    if len(argv) != 3:
        print("用法: xrd_stress_report.py 输入资料 输出报告", file=sys.stderr)
        return 2
    try:
        result = analyze(_load(argv[1]))
        with open(argv[2], "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
        return 0
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"运行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
