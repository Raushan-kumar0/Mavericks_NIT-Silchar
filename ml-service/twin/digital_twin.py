"""
The personalised Digital Twin.

1. prior_params(ehr)        -> starting guess of the patient's physiology from the EHR alone
2. calibrate(ehr, history)  -> refit gb / s / cf so the twin reproduces the patient's own
                               post-meal CGM curves (uses only logged meals + observed steps)
3. what_if(...)             -> run the calibrated twin for the next 24 h under a baseline
                               routine vs. a doctor-chosen scenario (less rice at dinner,
                               a 20-min walk after lunch, better sleep, earlier dinner...)
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .physiology import TwinParams, simulate, DT, STEPS_PER_DAY, time_in_range, count_spikes

MEAL_SLOTS = {"breakfast": (5, 11), "lunch": (11, 16), "snack": (16, 19), "dinner": (19, 24)}


def prior_params(ehr: dict) -> TwinParams:
    labs, vit, gen = ehr.get("labs", {}), ehr.get("vitals", {}), ehr.get("genetics", {})
    fpg = labs.get("fasting_glucose_mgdl", 130)
    hba1c = labs.get("hba1c_pct", 7.5)
    bmi = vit.get("bmi", 26)
    years = next((c.get("onset_years_ago", 0) for c in ehr.get("conditions", []) if c.get("code") == "E11"), 0)
    s = 1.1 - 0.02 * (bmi - 23) - 0.06 * gen.get("TCF7L2_rs7903146_risk_alleles", 0) - 0.01 * years - 0.08 * (hba1c - 7)
    return TwinParams(gb=float(np.clip(fpg - 12, 85, 190)), s=float(np.clip(s, 0.3, 1.3)),
                      cf=float(np.clip(2.05 * 62 / max(40, vit.get("weight_kg", 65)), 1.2, 3.0)))


def _prep(history: pd.DataFrame) -> pd.DataFrame:
    h = history.copy()
    h["timestamp"] = pd.to_datetime(h["timestamp"])
    h = h.sort_values("timestamp").reset_index(drop=True)
    h["g"] = h["glucose_mgdl"].astype(float).interpolate(limit_direction="both")
    h["carbs_logged_g"] = h["carbs_logged_g"].fillna(0).astype(float)
    return h


def _meal_windows(h: pd.DataFrame, length=36):
    idx = np.flatnonzero(h["carbs_logged_g"].values > 0)
    wins = []
    for i in idx:
        if i >= 1 and i + length <= len(h):
            wins.append((i - 1, i - 1 + length))
    return wins


PRIOR_SD = np.array([15.0, 0.20, 0.40])  # how far calibration may move gb, s, cf from the EHR prior


def meal_fit_rmse(p: TwinParams, h: pd.DataFrame, sleep_hours: float = 7.0) -> Optional[float]:
    """How well a twin reproduces the patient's own 3-h post-meal CGM curves (mg/dL)."""
    wins = _meal_windows(h)
    if not wins:
        return None
    mod0 = (h["timestamp"].dt.hour * 60 + h["timestamp"].dt.minute).values
    g, c, st = h["g"].values, h["carbs_logged_g"].values, h["steps"].values.astype(float)
    e = np.concatenate([simulate(p, mod0[a], b - a, g[a], c[a:b], st[a:b], sleep_hours=sleep_hours)[:-2] - g[a + 2:b]
                        for a, b in wins])
    return float(np.sqrt(np.mean(e ** 2)))


def calibrate(ehr: dict, history: pd.DataFrame, sleep_hours: float = 7.0) -> dict:
    """MAP fit: stay close to the EHR prior unless the patient's own CGM data says otherwise."""
    h = _prep(history)
    p0 = prior_params(ehr)
    wins = _meal_windows(h)
    if len(wins) < 2:
        return {"params": p0.to_dict(), "prior": p0.to_dict(), "fit_rmse": None, "prior_rmse": None, "meals_used": len(wins)}
    mod0 = (h["timestamp"].dt.hour * 60 + h["timestamp"].dt.minute).values
    g_obs, carbs, steps = h["g"].values, h["carbs_logged_g"].values, h["steps"].values.astype(float)
    x0 = np.array([p0.gb, p0.s, p0.cf])

    def data_loss(x):
        p = replace(p0, gb=x[0], s=x[1], cf=x[2])
        e = np.concatenate([simulate(p, mod0[a], b - a, g_obs[a], carbs[a:b], steps[a:b], sleep_hours=sleep_hours)[:-2]
                            - g_obs[a + 2:b] for a, b in wins])  # CGM lags blood by ~10 min
        return float(np.mean(np.where(np.abs(e) < 25, e ** 2, 50 * np.abs(e) - 625)))  # Huber

    def loss(x):
        return data_loss(x) + 15.0 * float(np.sum(((x - x0) / PRIOR_SD) ** 2))

    res = minimize(loss, x0, method="Nelder-Mead", options={"maxiter": 250, "xatol": 0.5, "fatol": 1.0})
    x = np.clip(res.x, [80, 0.25, 0.8], [200, 1.5, 4.0])
    p = replace(p0, gb=float(x[0]), s=float(x[1]), cf=float(x[2]))
    return {"params": p.to_dict(), "prior": p0.to_dict(),
            "fit_rmse": round(meal_fit_rmse(p, h, sleep_hours), 1),
            "prior_rmse": round(meal_fit_rmse(p0, h, sleep_hours), 1),
            "meals_used": len(wins)}


def typical_day(history: pd.DataFrame) -> dict:
    """Learn the patient's habitual routine from their own history."""
    h = _prep(history)
    h["hour"] = h["timestamp"].dt.hour + h["timestamp"].dt.minute / 60
    days = max(1.0, (h["timestamp"].iloc[-1] - h["timestamp"].iloc[0]).total_seconds() / 86400)
    meals = {}
    logged = h[h["carbs_logged_g"] > 0]
    for name, (lo, hi) in MEAL_SLOTS.items():
        m = logged[(logged.hour >= lo) & (logged.hour < hi)]
        if len(m) >= max(1, 0.3 * days):
            meals[name] = {"hour": float(m.hour.median()), "carbs_g": float(m.carbs_logged_g.median())}
    step_prof = h.groupby((h["hour"] * 60 // DT).astype(int))["steps"].mean().reindex(range(STEPS_PER_DAY)).fillna(0)
    return {"meals": meals, "steps_profile": step_prof.values}


def what_if(ehr: dict, history: pd.DataFrame, scenario: dict, sleep_hours: float = 7.0,
            params: Optional[dict] = None, hours: int = 24) -> dict:
    h = _prep(history)
    p = TwinParams(**params) if params else TwinParams(**calibrate(ehr, h, sleep_hours)["params"])
    routine = typical_day(h)
    now = h["timestamp"].iloc[-1]
    n = hours * 60 // DT
    start_mod = now.hour * 60 + now.minute

    def build(sc: dict):
        carbs = np.zeros(n)
        steps = np.array([routine["steps_profile"][(start_mod // DT + i) % STEPS_PER_DAY] for i in range(n)])
        meal_marks = []
        for name, m in routine["meals"].items():
            hour = m["hour"]
            if name == "dinner" and sc.get("dinner_shift_h"):
                hour += float(sc["dinner_shift_h"])
            pct = sc.get("carb_change_pct", {}).get(name, sc.get("carb_change_pct", {}).get("all", 0))
            g = m["carbs_g"] * (1 + float(pct) / 100)
            mins_ahead = ((hour * 60 - start_mod) % (24 * 60))
            k = int(mins_ahead // DT)
            if k < n:
                carbs[k] += g
                meal_marks.append({"meal": name, "offset_min": k * DT, "carbs_g": round(g)})
                walk = sc.get("post_meal_walk_min", {}).get(name, 0)
                if walk:
                    w0 = k + 3
                    steps[w0:w0 + int(walk) // DT] = 520
        if sc.get("morning_walk_min"):
            mk = int(((6.5 * 60 - start_mod) % (24 * 60)) // DT)
            steps[mk:mk + int(sc["morning_walk_min"]) // DT] = 540
        return carbs, steps, meal_marks

    # gut content from the last 3 h of logged meals
    tail = h.tail(36)
    q1 = q2 = 0.0
    for c in tail["carbs_logged_g"].values:
        q1 += c
        q2 += DT * (q1 / p.tau - q2 / p.tau)
        q1 -= DT * q1 / p.tau
    g0 = float(h["g"].iloc[-1])
    out = {}
    for label, sc in [("baseline", {}), ("scenario", scenario)]:
        carbs, steps, marks = build(sc)
        sh = float(sc.get("sleep_hours", sleep_hours))
        g = simulate(p, start_mod, n, g0, carbs, steps, sleep_hours=sh, q0=(q1, q2))
        out[label] = {
            "glucose": [round(float(v), 1) for v in g],
            "meals": marks,
            "time_in_range_pct": round(time_in_range(g), 1),
            "time_above_180_pct": round(float(np.mean(g > 180) * 100), 1),
            "peak_mgdl": round(float(g.max()), 1),
            "mean_mgdl": round(float(g.mean()), 1),
            "spikes": count_spikes(g),
        }
    out["timestamps"] = [(now + pd.Timedelta(minutes=DT * (i + 1))).isoformat() for i in range(n)]
    out["params"] = p.to_dict()
    out["routine"] = {k: {"hour": round(v["hour"], 2), "carbs_g": round(v["carbs_g"])} for k, v in routine["meals"].items()}
    b, s = out["baseline"], out["scenario"]
    out["summary"] = (f"Time-in-range {b['time_in_range_pct']}% -> {s['time_in_range_pct']}%, "
                      f"peak {b['peak_mgdl']:.0f} -> {s['peak_mgdl']:.0f} mg/dL, spikes {b['spikes']} -> {s['spikes']}")
    return out
