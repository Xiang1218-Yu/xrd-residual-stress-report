#!/usr/bin/env python3
import json
import math
import sys
from collections import defaultdict


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _regress(points):
    xs = [math.sin(math.radians(row["tilt_deg"])) ** 2 for row in points]
    ys = [row["strain"] for row in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    return slope, math.sqrt(sum(value * value for value in residuals) / len(residuals))


def analyze(data):
    wavelength = float(data["wavelength_nm"])
    d0 = float(data["stress_free_d_nm"])
    youngs_modulus = float(data["youngs_modulus_gpa"])
    poisson_ratio = float(data["poisson_ratio"])
    zero = float(data.get("instrument_zero_deg", 0.0))
    limits = data["limits"]

    grouped = defaultdict(dict)
    issues = []
    for row in data.get("measurements", []):
        required = ("azimuth_deg", "tilt_deg", "peak_2theta_deg", "quality")
        if not all(key in row for key in required):
            issues.append("MALFORMED_MEASUREMENT")
            continue
        if not all(_finite(row[key]) for key in required):
            issues.append("NONFINITE_MEASUREMENT")
            continue
        if row["quality"] < 0 or row["quality"] > 1:
            issues.append("OUT_OF_RANGE_QUALITY")
            continue
        if row["quality"] < 0.8:
            issues.append("LOW_QUALITY")
            continue
        if row["tilt_deg"] < 0 or row["tilt_deg"] > 85 or row["peak_2theta_deg"] <= 0:
            issues.append("OUT_OF_RANGE_MEASUREMENT")
            continue
        corrected = row["peak_2theta_deg"] - zero
        theta = math.radians(corrected / 2.0)
        sine = math.sin(theta)
        if sine <= 0:
            issues.append("INVALID_ANGLE")
            continue
        spacing = wavelength / (2.0 * sine)
        strain = (spacing - d0) / d0
        azimuth = row["azimuth_deg"]
        tilt = row["tilt_deg"]
        candidate = {"tilt_deg": tilt, "strain": strain, "quality": row["quality"]}
        existing = grouped[azimuth].get(tilt)
        if existing is not None:
            issues.append("DUPLICATE_MEASUREMENT")
            if candidate["quality"] <= existing["quality"]:
                continue
        grouped[azimuth][tilt] = candidate

    directions = []
    scale = youngs_modulus * 1000.0 / (1.0 + poisson_ratio)
    for azimuth in sorted(grouped):
        rows = [grouped[azimuth][tilt] for tilt in sorted(grouped[azimuth])]
        if len(rows) < 3:
            issues.append("INSUFFICIENT_POINTS")
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
            "stress_type": "tensile" if stress >= 0 else "compressive",
            "fit_rmse_mpa": rmse * scale,
            "valid_points": len(rows),
        })

    if not directions:
        status = "REVIEW"
        max_tensile = 0.0
        max_compressive = 0.0
        worst = None
    else:
        max_tensile = max((max(item["stress_mpa"], 0.0) for item in directions), default=0.0)
        max_compressive = min((min(item["stress_mpa"], 0.0) for item in directions), default=0.0)
        worst_item = min(directions, key=lambda item: (-abs(item["stress_mpa"]), item["azimuth_deg"]))
        worst = worst_item["azimuth_deg"]
        status = "PASS" if max_tensile <= float(limits["max_tensile_mpa"]) and abs(max_compressive) <= float(limits["max_compressive_mpa"]) else "REJECT"

    return {
        "specimen_id": data["specimen_id"],
        "status": status,
        "directions": directions,
        "summary": {
            "max_tensile_mpa": max_tensile,
            "max_compressive_mpa": max_compressive,
            "worst_azimuth_deg": worst,
        },
        "issues": sorted(set(issues)),
    }


def main(argv):
    if len(argv) != 3:
        print("用法: xrd_stress_report.py 输入资料 输出报告", file=sys.stderr)
        return 2
    try:
        data = _load(argv[1])
        result = analyze(data)
        with open(argv[2], "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
        return 0
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"运行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
