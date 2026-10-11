"""
GlucoTwin synthetic data generator.

Creates a cohort of virtual Indian adults with Type 2 Diabetes and two data streams:

  STATIC / HISTORICAL  -> data/ehr_patients.json   (FHIR-inspired EHR: demographics,
                                                    diagnoses, labs, meds, genetic markers)
  DYNAMIC / REAL-TIME  -> data/wearable_timeseries.csv  (5-min CGM, heart rate, HRV,
                                                    steps, sleep stage, app meal log)
                          data/sleep_summary.csv   (nightly summary from the wearable)

Hidden ground truth (NOT used by the model, only for evaluation / transparency):
                          data/ground_truth_meals.csv, data/ground_truth_params.json

No real patient data is used anywhere (DPDP Act / HIPAA sandbox rule).
Distributions are loosely informed by published Indian T2D cohort statistics
(e.g. Asian-Indian phenotype: higher insulin resistance at lower BMI, high-carbohydrate
rice/wheat meals, late dinners). They are illustrative, not clinical reference values.

Usage:  python generate.py --patients 80 --days 14 --seed 42
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ml-service"))
from twin.physiology import TwinParams, simulate, DT, STEPS_PER_DAY  # noqa: E402

FIRST_M = ["Aarav", "Vivaan", "Aditya", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan", "Rohan", "Kabir",
           "Suresh", "Ramesh", "Manoj", "Debashish", "Biswajit", "Farhan", "Imran", "Joseph", "Harpreet", "Venkat"]
FIRST_F = ["Ananya", "Diya", "Saanvi", "Aadhya", "Kavya", "Meera", "Priya", "Lakshmi", "Pooja", "Riya",
           "Sunita", "Geeta", "Anjali", "Bhavana", "Nandini", "Fatima", "Mary", "Simran", "Rupali", "Tanuja"]
LAST = ["Sharma", "Reddy", "Iyer", "Das", "Nair", "Patel", "Singh", "Gupta", "Rao", "Chakraborty",
        "Bora", "Khan", "Menon", "Joshi", "Kulkarni", "Banerjee", "Pillai", "Verma", "Naidu", "Dey"]
CITIES = [("Bengaluru", "Karnataka"), ("Chennai", "Tamil Nadu"), ("Hyderabad", "Telangana"),
          ("Kolkata", "West Bengal"), ("Mumbai", "Maharashtra"), ("New Delhi", "Delhi"),
          ("Guwahati", "Assam"), ("Silchar", "Assam"), ("Kochi", "Kerala"), ("Pune", "Maharashtra")]

START = datetime(2026, 9, 1, 0, 0)


def make_patient(i: int, rng: np.random.Generator) -> dict:
    sex = rng.choice(["male", "female"])
    age = int(np.clip(rng.normal(52, 10), 30, 78))
    height = rng.normal(168 if sex == "male" else 155, 6)
    bmi = float(np.clip(rng.normal(26.5, 3.8), 19, 40))
    weight = bmi * (height / 100) ** 2
    years_dx = int(np.clip(rng.exponential(6), 0, 25))
    tcf7l2 = int(rng.choice([0, 1, 2], p=[0.52, 0.39, 0.09]))  # rs7903146 risk-allele count
    family_hx = bool(rng.random() < 0.55)
    hypertension = bool(rng.random() < 0.45 + 0.01 * (age - 50))
    dyslipidemia = bool(rng.random() < 0.5)
    smoker = bool(rng.random() < (0.18 if sex == "male" else 0.03))
    diet = rng.choice(["vegetarian", "non-vegetarian", "eggetarian"], p=[0.38, 0.52, 0.10])

    # latent insulin sensitivity: worse with BMI, genetics, disease duration
    s = 1.15 - 0.022 * (bmi - 23) - 0.07 * tcf7l2 - 0.012 * years_dx - 0.004 * (age - 45) + rng.normal(0, 0.08)
    s = float(np.clip(s, 0.35, 1.25))
    gb = float(np.clip(rng.normal(118, 14) + 4 * tcf7l2 + 0.9 * years_dx, 92, 185))

    meds = []
    metformin = rng.random() < 0.85
    if metformin:
        meds.append({"name": "Metformin", "dose": rng.choice(["500 mg BD", "1000 mg BD", "500 mg OD"]), "since_years": min(years_dx, int(rng.integers(0, 10)))})
        s *= 1.12
    su = gb > 135 and rng.random() < 0.6
    if su:
        meds.append({"name": "Glimepiride", "dose": rng.choice(["1 mg OD", "2 mg OD"]), "since_years": int(rng.integers(0, max(1, years_dx)))})
        gb -= 8
    insulin = gb > 150 and rng.random() < 0.5
    if insulin:
        meds.append({"name": "Insulin Glargine (basal)", "dose": f"{int(rng.integers(10, 26))} U at bedtime", "since_years": int(rng.integers(0, 4))})
        gb -= 15
    if hypertension:
        meds.append({"name": rng.choice(["Telmisartan", "Amlodipine"]), "dose": rng.choice(["40 mg OD", "5 mg OD"]), "since_years": int(rng.integers(0, 8))})
    if dyslipidemia:
        meds.append({"name": "Atorvastatin", "dose": "10 mg OD", "since_years": int(rng.integers(0, 6))})

    params = TwinParams(
        gb=gb, s=float(np.clip(s, 0.3, 1.3)),
        cf=float(np.clip(rng.normal(2.05, 0.2) * 62 / weight * 1.0 + 0.0, 1.4, 2.8)),
        tau=float(np.clip(rng.normal(38, 6), 25, 55)),
        dawn=float(np.clip(rng.normal(14, 6), 0, 30)),
        evening_drop=float(np.clip(rng.normal(0.15, 0.05), 0.02, 0.3)),
        exercise_gain=float(np.clip(rng.normal(0.6, 0.15), 0.2, 1.0)),
        sleep_penalty=float(np.clip(rng.normal(0.09, 0.03), 0.02, 0.18)),
    )
    city, state = CITIES[int(rng.integers(len(CITIES)))]
    behaviour = {
        "carb_habit": float(np.clip(rng.normal(1.0, 0.15), 0.7, 1.35)),
        "log_prob": float(np.clip(rng.normal(0.72, 0.15), 0.35, 0.95)),
        "walk_morning_p": float(np.clip(rng.normal(0.35, 0.25), 0, 0.9)),
        "walk_post_meal_p": float(np.clip(rng.normal(0.22, 0.15), 0, 0.7)),
        "base_steps": float(np.clip(rng.normal(22, 9), 6, 50)),
        "bed_hour": float(np.clip(rng.normal(23.3, 0.6), 21.8, 25.0)),
        "sleep_mean": float(np.clip(rng.normal(6.6, 0.6), 5.0, 8.0)),
        "stress_rate": float(np.clip(rng.normal(0.9, 0.5), 0, 2.5)),
        "dinner_hour": float(np.clip(rng.normal(21.0, 0.6), 19.5, 22.5)),
    }
    rhr = float(np.clip(rng.normal(74, 7) + 0.3 * (bmi - 25) + (4 if smoker else 0), 56, 95))
    hrv_base = float(np.clip(48 - 0.45 * (age - 30) + rng.normal(0, 6), 12, 70))
    pid = f"GT-{i:03d}"
    ehr = {
        "resourceType": "Patient",
        "id": pid,
        "name": f"{rng.choice(FIRST_M if sex == 'male' else FIRST_F)} {rng.choice(LAST)}",
        "synthetic": True,
        "gender": sex,
        "age": age,
        "address": {"city": city, "state": state, "country": "IN"},
        "vitals": {"height_cm": round(height, 1), "weight_kg": round(weight, 1), "bmi": round(bmi, 1),
                   "waist_cm": round(float(np.clip(70 + 1.2 * (bmi - 20) + (6 if sex == "male" else 2) + rng.normal(0, 4), 70, 130)), 1),
                   "systolic_bp": int(np.clip(rng.normal(138 if hypertension else 124, 10), 100, 180)),
                   "diastolic_bp": int(np.clip(rng.normal(88 if hypertension else 80, 7), 60, 110)),
                   "resting_hr": round(rhr)},
        "conditions": [{"code": "E11", "system": "ICD-10", "display": "Type 2 diabetes mellitus", "onset_years_ago": years_dx}]
                      + ([{"code": "I10", "system": "ICD-10", "display": "Essential hypertension"}] if hypertension else [])
                      + ([{"code": "E78.5", "system": "ICD-10", "display": "Dyslipidaemia"}] if dyslipidemia else []),
        "medications": meds,
        "genetics": {"TCF7L2_rs7903146_risk_alleles": tcf7l2, "family_history_t2d": family_hx},
        "lifestyle": {"smoker": smoker, "diet": diet, "self_reported_activity": "low" if behaviour["base_steps"] < 15 else ("moderate" if behaviour["base_steps"] < 30 else "high")},
        "labs": {},  # filled after simulation so they are consistent with the glucose profile
    }
    return {"ehr": ehr, "params": params, "behaviour": behaviour, "rhr": rhr, "hrv_base": hrv_base}


def simulate_patient(pt: dict, days: int, rng: np.random.Generator):
    p: TwinParams = pt["params"]
    b = pt["behaviour"]
    n = days * STEPS_PER_DAY
    carbs = np.zeros(n)
    steps = np.zeros(n)
    stress = np.zeros(n)
    asleep = np.zeros(n, dtype=bool)
    stage = np.array(["awake"] * n, dtype=object)
    logged = np.zeros(n)
    sleep_arr = np.full(n, 7.0)
    dayf = np.ones(n)
    meals = []
    nights = []

    def idx(day, hour):
        return int(round((day * 24 + hour) * 60 / DT))

    # ---------- sleep (night d = evening of day d-1 -> morning of day d) ----------
    prev_wake_idx = 0
    last_sleep = b["sleep_mean"]
    for d in range(days + 1):
        bed = b["bed_hour"] + rng.normal(0, 0.6)
        dur = float(np.clip(rng.normal(b["sleep_mean"], 0.9), 3.8, 9.0))
        if rng.random() < 0.12:
            dur = float(rng.uniform(3.8, 5.0))  # occasional short night
        s_i, e_i = idx(d - 1, bed), idx(d - 1, bed + dur)
        if e_i <= 0:
            continue
        s_c, e_c = max(0, s_i), min(n, e_i)
        if s_c < e_c:
            asleep[s_c:e_c] = True
            # stage architecture: 90-min cycles, more deep early, more REM late
            for k in range(s_c, e_c):
                t = (k - s_i) * DT
                cyc, ph = divmod(t, 90)
                deep_w = max(0.0, 0.45 - 0.12 * cyc)
                if ph < 15:
                    st = "light"
                elif ph < 15 + 60 * deep_w + 5:
                    st = "deep"
                elif ph < 75:
                    st = "light"
                else:
                    st = "rem"
                if rng.random() < 0.03:
                    st = "awake"
                stage[k] = st
        if e_i < n:
            seg = stage[s_c:e_c]
            nights.append({
                "night_of": (START + timedelta(days=d - 1)).date().isoformat(),
                "bed_time": (START + timedelta(minutes=s_i * DT)).isoformat(),
                "wake_time": (START + timedelta(minutes=e_i * DT)).isoformat(),
                "sleep_hours": round(dur * (1 - np.mean(seg == "awake") if len(seg) else 1), 2),
                "deep_pct": round(float(np.mean(seg == "deep") * 100) if len(seg) else 0, 1),
                "rem_pct": round(float(np.mean(seg == "rem") * 100) if len(seg) else 0, 1),
                "awakenings": int(np.sum(seg == "awake")),
            })
            sleep_arr[prev_wake_idx:e_i] = last_sleep
            prev_wake_idx = e_i
            last_sleep = dur
            dayf[e_i: e_i + STEPS_PER_DAY] = float(np.clip(rng.normal(1.0, 0.07), 0.8, 1.2))
    sleep_arr[prev_wake_idx:] = last_sleep

    # ---------- meals, walks, stress ----------
    for d in range(days):
        weekend = (START + timedelta(days=d)).weekday() >= 5
        plan = [("breakfast", rng.normal(8.4, 0.5), rng.normal(62, 12)),
                ("lunch", rng.normal(13.6, 0.45), rng.normal(92, 18)),
                ("dinner", b["dinner_hour"] + rng.normal(0, 0.4), rng.normal(85, 18))]
        if rng.random() < 0.65:
            plan.append(("snack", rng.normal(17.2, 0.4), rng.normal(30, 9)))
        if weekend and rng.random() < 0.5:
            plan.append(("festive/sweets", rng.normal(19.0, 1.0), rng.normal(55, 15)))
        for name, hr, g in plan:
            g = max(10.0, g * b["carb_habit"] * (1.15 if weekend else 1.0))
            k = idx(d, hr)
            if 0 <= k < n:
                carbs[k] += g
                was_logged = rng.random() < b["log_prob"]
                if was_logged:
                    logged[k] += round(g * rng.normal(1.0, 0.22))
                meals.append({"timestamp": (START + timedelta(minutes=k * DT)).isoformat(), "meal": name,
                              "carbs_g": round(g, 1), "logged": was_logged})
                if name in ("lunch", "dinner") and rng.random() < b["walk_post_meal_p"]:
                    w0 = k + int(rng.integers(2, 7))
                    wl = int(rng.integers(3, 6))
                    steps[w0:w0 + wl] += rng.normal(520, 50, size=len(steps[w0:w0 + wl]))
        if rng.random() < b["walk_morning_p"]:
            w0 = idx(d, rng.normal(6.6, 0.4))
            wl = int(rng.integers(6, 10))
            steps[w0:w0 + wl] += rng.normal(540, 60, size=len(steps[w0:w0 + wl]))
        for _ in range(rng.poisson(b["stress_rate"])):
            s0 = idx(d, rng.uniform(10, 19))
            sl = int(rng.integers(6, 18))
            stress[s0:s0 + sl] = rng.uniform(0.5, 1.0)

    base = rng.poisson(b["base_steps"], size=n).astype(float)
    steps = np.where(asleep, 0, steps + base)
    steps = np.clip(steps, 0, 900)

    g_true = simulate(p, 0, n, p.gb + 5, carbs, steps, sleep_hours=sleep_arr, stress=stress,
                      day_factor=dayf, rng=rng, process_noise=0.8)

    # ---------- wearable sensors ----------
    g_lag = np.concatenate([[g_true[0]] * 2, g_true[:-2]])  # interstitial lag ~10 min
    cgm = g_lag + rng.normal(0, 4.5, n) + 3 * np.sin(np.arange(n) / 200)
    cgm = np.clip(np.round(cgm), 40, 400)
    cgm[rng.random(n) < 0.008] = np.nan  # sensor dropouts
    hr = pt["rhr"] + 0.045 * steps + 13 * stress + 0.03 * (g_true - 140) - 8 * asleep + rng.normal(0, 2.5, n)
    hrv = pt["hrv_base"] - 7 * stress - 0.035 * (g_true - 140) + 9 * asleep - 0.012 * steps \
        - 2.0 * np.maximum(0, 7 - sleep_arr) + rng.normal(0, 4, n)
    df = pd.DataFrame({
        "patient_id": pt["ehr"]["id"],
        "timestamp": [START + timedelta(minutes=k * DT) for k in range(n)],
        "glucose_mgdl": cgm,
        "heart_rate_bpm": np.round(hr, 0),
        "hrv_rmssd_ms": np.round(np.clip(hrv, 6, 110), 1),
        "steps": steps.astype(int),
        "sleep_stage": np.where(asleep, stage, "awake"),
        "carbs_logged_g": logged,
    })

    # nightly HRV / RHR into sleep summary
    sl = pd.DataFrame(nights)
    if len(sl):
        sl["patient_id"] = pt["ehr"]["id"]
        hrv_n, rhr_n = [], []
        for _, r in sl.iterrows():
            m = (df.timestamp >= pd.Timestamp(r.bed_time)) & (df.timestamp < pd.Timestamp(r.wake_time))
            hrv_n.append(round(float(df.loc[m, "hrv_rmssd_ms"].mean()), 1) if m.any() else None)
            rhr_n.append(round(float(df.loc[m, "heart_rate_bpm"].mean()), 1) if m.any() else None)
        sl["night_hrv_ms"] = hrv_n
        sl["night_rhr_bpm"] = rhr_n

    # ---------- labs consistent with the glucose profile ----------
    mean_g = float(np.mean(g_true))
    hba1c = (mean_g + 46.7) / 28.7  # ADAG relation
    fasting = float(np.mean([g_true[idx(d, 7.0)] for d in range(days)]))
    ehr = pt["ehr"]
    ehr["labs"] = {
        "hba1c_pct": round(hba1c + rng.normal(0, 0.2), 1),
        "fasting_glucose_mgdl": int(round(fasting + rng.normal(0, 6))),
        "ppbg_2h_mgdl": int(round(fasting + 60 + 70 * (1 - p.s) + rng.normal(0, 12))),
        "egfr_ml_min": int(np.clip(rng.normal(92 - 0.5 * (ehr["age"] - 40), 12), 35, 125)),
        "ldl_mgdl": int(np.clip(rng.normal(118, 28), 50, 220)),
        "hdl_mgdl": int(np.clip(rng.normal(41, 8), 22, 75)),
        "triglycerides_mgdl": int(np.clip(rng.normal(165 + 40 * (1 - p.s), 45), 60, 450)),
        "urine_acr_mg_g": int(np.clip(rng.lognormal(3.0, 0.9), 3, 600)),
        "hba1c_history": [
            {"date": "2025-03-10", "value": round(hba1c + rng.normal(0.4, 0.4), 1)},
            {"date": "2025-09-14", "value": round(hba1c + rng.normal(0.2, 0.3), 1)},
            {"date": "2026-03-21", "value": round(hba1c + rng.normal(0.0, 0.3), 1)},
        ],
        "collected_on": "2026-08-25",
    }
    return df, sl, meals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=80)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    os.makedirs(a.out, exist_ok=True)
    ehrs, series, sleeps, meals_all, truth = [], [], [], [], {}
    for i in range(1, a.patients + 1):
        pt = make_patient(i, rng)
        df, sl, meals = simulate_patient(pt, a.days, rng)
        ehrs.append(pt["ehr"])
        series.append(df)
        sleeps.append(sl)
        for m in meals:
            m["patient_id"] = pt["ehr"]["id"]
        meals_all += meals
        truth[pt["ehr"]["id"]] = pt["params"].to_dict()
        print(f"{pt['ehr']['id']}: HbA1c {pt['ehr']['labs']['hba1c_pct']}%  rows={len(df)}")
    with open(os.path.join(a.out, "ehr_patients.json"), "w") as f:
        json.dump(ehrs, f, indent=1)
    ts = pd.concat(series)
    ts["timestamp"] = ts["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    ts.to_csv(os.path.join(a.out, "wearable_timeseries.csv"), index=False)
    pd.concat(sleeps).to_csv(os.path.join(a.out, "sleep_summary.csv"), index=False)
    pd.DataFrame(meals_all).to_csv(os.path.join(a.out, "ground_truth_meals.csv"), index=False)
    with open(os.path.join(a.out, "ground_truth_params.json"), "w") as f:
        json.dump(truth, f, indent=1)
    print("Wrote", len(ehrs), "patients,", len(ts), "sensor rows to", os.path.abspath(a.out))


if __name__ == "__main__":
    main()
