"""
GlucoTwin ML service (FastAPI).

POST /predict          EHR + recent wearable window -> 2-h spike risk, 30-120 min forecast, top drivers
POST /twin/calibrate   EHR + history -> personalised physiology parameters
POST /twin/simulate    EHR + history + scenario -> baseline vs what-if 24-h glucose
GET  /model/info       evaluation metrics of the trained models
GET  /health

Run:  uvicorn app:app --port 8000
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from twin.features import build_features, FRIENDLY, HORIZONS, WINDOW_STEPS_NEEDED
from twin.digital_twin import calibrate, what_if

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "models")

app = FastAPI(title="GlucoTwin ML service", version="1.0")
_bundle = None


def bundle():
    global _bundle
    if _bundle is None:
        path = os.path.join(MODELS, "glucotwin_models.joblib")
        if not os.path.exists(path):
            raise HTTPException(503, "Model not trained. Run: python train.py")
        _bundle = joblib.load(path)
    return _bundle


class Reading(BaseModel):
    timestamp: str
    glucose_mgdl: Optional[float] = None
    heart_rate_bpm: Optional[float] = None
    hrv_rmssd_ms: Optional[float] = None
    steps: int = 0
    sleep_stage: str = "awake"
    carbs_logged_g: float = 0


class SleepNight(BaseModel):
    wake_time: str
    sleep_hours: float
    deep_pct: Optional[float] = None
    rem_pct: Optional[float] = None
    awakenings: Optional[int] = None
    night_hrv_ms: Optional[float] = None
    night_rhr_bpm: Optional[float] = None


class PredictRequest(BaseModel):
    ehr: Dict[str, Any]
    window: List[Reading] = Field(..., description="most recent readings, 5-min spacing, >= 3 h")
    last_sleep: Optional[SleepNight] = None


class SimulateRequest(BaseModel):
    ehr: Dict[str, Any]
    history: List[Reading] = Field(..., description="last 3-7 days of readings")
    scenario: Dict[str, Any] = Field(default_factory=dict)
    last_sleep_hours: float = 7.0


def _frame(readings: List[Reading]) -> pd.DataFrame:
    return pd.DataFrame([r.model_dump() for r in readings])


# group closely related features so the explanation shows one line per idea
FAMILY = {**{k: "carbs" for k in ["carbs_log60", "carbs_log120", "carbs_log180", "mins_since_log"]},
          **{k: "level" for k in ["g", "g_lag5", "g_lag15", "g_lag30", "g_lag60", "g_mean60", "g_max60",
                                  "g_mean180", "g_max180", "g_min180", "frac_above_180_3h"]},
          **{k: "trend" for k in ["d15", "d30", "d60", "accel"]},
          **{k: "variability" for k in ["g_std60", "g_std180"]},
          **{k: "time" for k in ["hour_sin", "hour_cos"]},
          **{k: "activity" for k in ["steps30", "steps60", "steps180"]},
          **{k: "heart" for k in ["hr30", "hr_dev30", "hrv60"]},
          **{k: "sleep" for k in ["sleep_hours", "deep_pct", "night_hrv", "night_rhr", "awakenings"]}}
FAMILY_LABEL = {"time": "time of day (meal pattern)"}
BINARY = {"male", "family_hx", "metformin", "sulfonylurea", "insulin", "hypertension", "asleep", "weekend"}


def display_value(name: str, v: float, ts) -> str:
    if name in ("hour_sin", "hour_cos"):
        return pd.Timestamp(ts).strftime("%H:%M")
    if name in BINARY:
        return "yes" if v >= 0.5 else "no"
    if name == "mins_since_log":
        return f"{int(v)} min"
    if name.startswith("carbs_log"):
        return f"{int(v)} g"
    if name in ("g", "g_mean60", "g_max60", "g_mean180", "g_max180", "g_min180") or name.startswith("g_lag"):
        return f"{int(round(v))} mg/dL"
    if name in ("d15", "d30", "d60", "accel"):
        return f"{v:+.0f} mg/dL"
    if name.startswith("steps"):
        return f"{int(v)} steps"
    if name == "sleep_hours":
        return f"{v:.1f} h"
    if name == "frac_above_180_3h":
        return f"{v * 100:.0f}%"
    return f"{v:.3g}"


def risk_level(p: float, thr: float) -> str:
    return "HIGH" if p >= 0.7 else ("MODERATE" if p >= thr else "LOW")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/model/info")
def model_info():
    with open(os.path.join(MODELS, "metrics.json")) as f:
        return json.load(f)


@app.post("/predict")
def predict(req: PredictRequest):
    b = bundle()
    if len(req.window) < WINDOW_STEPS_NEEDED:
        raise HTTPException(400, f"window needs >= {WINDOW_STEPS_NEEDED} readings (3 h)")
    ts = _frame(req.window)
    sleep = pd.DataFrame([req.last_sleep.model_dump()]) if req.last_sleep else None
    feats = build_features(ts, sleep, req.ehr)
    row = feats[b["features"]].iloc[[-1]].astype(float)
    g_now = float(feats["g"].iloc[-1])
    p = float(b["clf"].predict_proba(row)[:, 1][0])
    in_spike = g_now >= 180  # already above range: report as an active spike, not a prediction
    forecast = []
    for h in HORIZONS:
        f = b["forecasters"][h]
        forecast.append({"minutes_ahead": h,
                         "glucose": round(g_now + float(f["p50"].predict(row)[0]), 1),
                         "low": round(g_now + float(f["p10"].predict(row)[0]), 1),
                         "high": round(g_now + float(f["p90"].predict(row)[0]), 1)})
    # per-prediction explanation via LightGBM's built-in SHAP values
    contrib = b["clf"].booster_.predict(row, pred_contrib=True)[0][:-1]
    order = np.argsort(-np.abs(contrib))
    drivers, seen = [], set()
    now_ts = feats["timestamp"].iloc[-1]
    for i in order:
        name = b["features"][i]
        fam = FAMILY.get(name, name)
        if fam in seen or np.isnan(float(row.iloc[0, i])):  # skip missing inputs
            continue
        seen.add(fam)
        drivers.append({"feature": name, "label": FAMILY_LABEL.get(fam, FRIENDLY.get(name, name)),
                        "value": display_value(name, float(row.iloc[0, i]), now_ts),
                        "effect": "raises risk" if contrib[i] > 0 else "lowers risk",
                        "weight": round(float(abs(contrib[i])), 3)})
        if len(drivers) == 5:
            break
    peak = max(forecast, key=lambda x: x["glucose"])
    return {
        "patient_id": req.ehr.get("id"),
        "as_of": str(feats["timestamp"].iloc[-1]),
        "current_glucose": round(g_now, 1),
        "trend_mgdl_per_15min": round(float(feats["d15"].iloc[-1]), 1) if not np.isnan(feats["d15"].iloc[-1]) else None,
        "spike_probability_2h": round(p, 3),
        "risk_level": "ACTIVE_SPIKE" if in_spike else risk_level(p, b["threshold"]),
        "in_spike": in_spike,
        "threshold": b["threshold"],
        "forecast": forecast,
        "expected_peak": peak,
        "drivers": drivers,
    }


@app.post("/twin/calibrate")
def twin_calibrate(req: SimulateRequest):
    return calibrate(req.ehr, _frame(req.history), req.last_sleep_hours)


@app.post("/twin/simulate")
def twin_simulate(req: SimulateRequest):
    h = _frame(req.history)
    if len(h) < 288:
        raise HTTPException(400, "history needs >= 1 day of readings")
    return what_if(req.ehr, h, req.scenario, req.last_sleep_hours)
