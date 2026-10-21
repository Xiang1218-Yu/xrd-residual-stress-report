#!/usr/bin/env python3
import json
import math
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = Path(os.environ.get("PROGRAM", "/app/xrd_stress_report.py"))


def peak_for_stress(stress_mpa, tilt_deg, *, zero=0.0, d0=0.203, wavelength=0.2291, E=210.0, nu=0.30):
    k = (1.0 + nu) / (E * 1000.0)
    d = d0 * (1.0 + k * stress_mpa * math.sin(math.radians(tilt_deg)) ** 2)
    return math.degrees(2.0 * math.asin(wavelength / (2.0 * d))) + zero


def row(azimuth, stress, tilt, *, quality=0.99, zero=0.0):
    return {
        "azimuth_deg": azimuth,
        "tilt_deg": tilt,
        "peak_2theta_deg": peak_for_stress(stress, tilt, zero=zero),
        "quality": quality,
    }


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


def run(data):
    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / "input.json"
        out_path = Path(tmp) / "output.json"
        in_path.write_text(json.dumps(data), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(PROGRAM), str(in_path), str(out_path)], capture_output=True, text=True)
        if proc.returncode != 0 or not out_path.exists():
            return None
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None


def close(a, b, tol=1e-5):
    return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)


def test_physics_and_zero():
    data = base([row(0, 120.0, t, zero=0.12) for t in (0, 20, 40, 60)], zero=0.12)
    result = run(data)
    if not result or len(result["directions"]) != 1:
        return False
    item = result["directions"][0]
    return item["azimuth_deg"] == 0 and close(item["stress_mpa"], 120.0, 1e-4) and item["stress_type"] == "tensile" and close(result["summary"]["max_compressive_mpa"], 0.0)


def test_directional_stress():
    measurements = [row(0, 100.0, t, zero=-0.08) for t in (0, 25, 50, 70)]
    measurements += [row(90, -220.0, t, zero=-0.08) for t in (0, 25, 50, 70)]
    result = run(base(measurements, zero=-0.08))
    if not result or len(result["directions"]) != 2:
        return False
    by_az = {item["azimuth_deg"]: item for item in result["directions"]}
    return close(by_az[0]["stress_mpa"], 100.0, 1e-4) and close(by_az[90]["stress_mpa"], -220.0, 1e-4) and result["summary"]["worst_azimuth_deg"] == 90


def test_quality_and_duplicate():
    measurements = [
        row(45, 80.0, 0),
        row(45, 80.0, 25, quality=0.95),
        row(45, 900.0, 25, quality=0.90),
        row(45, 80.0, 50),
        row(45, 80.0, 70),
        row(45, -700.0, 60, quality=0.20),
    ]
    result = run(base(measurements))
    if not result or len(result["directions"]) != 1:
        return False
    item = result["directions"][0]
    return item["valid_points"] == 4 and close(item["stress_mpa"], 80.0, 1e-4) and "LOW_QUALITY" in result["issues"] and "DUPLICATE_MEASUREMENT" in result["issues"]


def test_insufficient_points():
    result = run(base([row(0, 100.0, 20), row(0, 100.0, 40)]))
    return bool(result) and result["status"] == "REVIEW" and result["directions"] == [] and "INSUFFICIENT_POINTS" in result["issues"]


def test_limit_rejection():
    data = base([row(0, 420.0, t) for t in (0, 20, 40, 60)], limits=(350.0, 500.0))
    result = run(data)
    if not result or result["status"] != "REJECT" or len(result["directions"]) != 1:
        return False
    return close(result["directions"][0]["stress_mpa"], 420.0, 1e-4)


def test_order_invariance():
    measurements = [
        row(0, 140.0, 0),
        row(0, 140.0, 30),
        row(0, 140.0, 60),
        row(0, 140.0, 60, quality=0.50),
        row(90, -180.0, 0),
        row(90, -180.0, 30),
        row(90, -180.0, 60),
    ]
    first = run(base(measurements))
    shuffled = list(measurements)
    random.Random(7).shuffle(shuffled)
    second = run(base(shuffled))
    if first is None or second is None or first != second:
        return False
    if len(first["directions"]) != 2:
        return False
    by_az = {item["azimuth_deg"]: item for item in first["directions"]}
    return close(by_az[0]["stress_mpa"], 140.0, 1e-4) and close(by_az[90]["stress_mpa"], -180.0, 1e-4)


def main():
    tests = [
        (0.25, test_physics_and_zero),
        (0.25, test_directional_stress),
        (0.20, test_quality_and_duplicate),
        (0.15, test_insufficient_points),
        (0.10, test_limit_rejection),
        (0.05, test_order_invariance),
    ]
    score = 0.0
    failures = []
    for weight, fn in tests:
        try:
            ok = bool(fn())
        except Exception as exc:
            ok = False
            failures.append(f"{fn.__name__}: {exc}")
        if ok:
            score += weight
        else:
            failures.append(fn.__name__)
    print(json.dumps({"score": round(score, 3), "failures": failures}, ensure_ascii=False))
    return 0 if score >= 0.999 else 1


if __name__ == "__main__":
    raise SystemExit(main())
