"""
Data fusion: turn (EHR record + wearable time-series + nightly sleep summary)
into one feature row per 5-minute timestamp.

The SAME function is used for training (whole history) and for live serving
(the last few hours sent by the backend), so there is no train/serve skew.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = [30, 60, 90, 120]  # minutes ahead
SPIKE_MGDL = 180
WINDOW_STEPS_NEEDED = 36       # 3 hours of history needed for all rolling features

CGM_FEATURES = ["g", "g_lag5", "g_lag15", "g_lag30", "g_lag60", "d15", "d30", "d60", "accel",
                "g_mean60", "g_std60", "g_max60", "g_mean180", "g_std180", "g_min180", "g_max180",
                "frac_above_180_3h"]
WEARABLE_FEATURES = ["steps30", "steps60", "steps180", "hr30", "hr_dev30", "hrv60", "asleep",
                     "carbs_log60", "carbs_log120", "carbs_log180", "mins_since_log",
                     "sleep_hours", "deep_pct", "night_hrv", "night_rhr", "awakenings"]
TIME_FEATURES = ["hour_sin", "hour_cos", "weekend"]
EHR_FEATURES = ["age", "male", "bmi", "waist", "hba1c", "fpg", "ppbg", "years_dx", "tcf7l2",
                "family_hx", "metformin", "sulfonylurea", "insulin", "hypertension", "egfr",
                "tg", "hdl", "sbp"]
ALL_FEATURES = CGM_FEATURES + WEARABLE_FEATURES + TIME_FEATURES + EHR_FEATURES

FRIENDLY = {
    "g": "current glucose", "g_lag5": "glucose 5 min ago", "g_lag15": "glucose 15 min ago",
    "g_lag30": "glucose 30 min ago", "g_lag60": "glucose 1 h ago", "g_mean60": "1-h average glucose",
    "g_std60": "1-h glucose variability", "g_max60": "1-h peak glucose", "g_std180": "3-h glucose variability",
    "hr30": "heart rate (30 min)", "asleep": "asleep now", "night_rhr": "overnight resting HR",
    "awakenings": "night awakenings", "weekend": "weekend", "male": "sex (EHR)", "waist": "waist (EHR)",
    "family_hx": "family history (EHR)", "metformin": "on metformin (EHR)", "sulfonylurea": "on sulfonylurea (EHR)",
    "hypertension": "hypertension (EHR)", "egfr": "eGFR (EHR)", "tg": "triglycerides (EHR)", "hdl": "HDL (EHR)",
    "sbp": "systolic BP (EHR)", "d15": "glucose trend (15 min)", "d30": "glucose trend (30 min)",
    "d60": "glucose trend (60 min)", "accel": "glucose acceleration", "g_mean180": "3-h average glucose",
    "g_max180": "3-h peak glucose", "g_min180": "3-h lowest glucose", "frac_above_180_3h": "time above 180 (3 h)",
    "steps30": "steps in last 30 min", "steps60": "steps in last hour", "steps180": "steps in last 3 h",
    "hr_dev30": "heart rate above resting", "hrv60": "heart-rate variability (1 h)",
    "carbs_log60": "carbs logged (last 1 h)", "carbs_log120": "carbs logged (last 2 h)",
    "carbs_log180": "carbs logged (last 3 h)", "mins_since_log": "time since last logged meal",
    "sleep_hours": "last night's sleep", "deep_pct": "deep sleep %", "night_hrv": "overnight HRV",
    "hour_sin": "time of day", "hour_cos": "time of day", "hba1c": "HbA1c (EHR)", "fpg": "fasting glucose (EHR)",
    "ppbg": "post-meal glucose (EHR)", "bmi": "BMI (EHR)", "tcf7l2": "TCF7L2 risk alleles (EHR)",
    "years_dx": "years since diagnosis (EHR)", "insulin": "on basal insulin (EHR)", "age": "age (EHR)",
}


def ehr_vector(ehr: dict) -> dict:
    meds = " ".join(m["name"].lower() for m in ehr.get("medications", []))
    conds = " ".join(c["display"].lower() for c in ehr.get("conditions", []))
    t2d = next((c for c in ehr.get("conditions", []) if c.get("code") == "E11"), {})
    labs, vit, gen = ehr.get("labs", {}), ehr.get("vitals", {}), ehr.get("genetics", {})
    return {
        "age": ehr.get("age"), "male": 1 if ehr.get("gender") == "male" else 0,
        "bmi": vit.get("bmi"), "waist": vit.get("waist_cm"), "sbp": vit.get("systolic_bp"),
        "hba1c": labs.get("hba1c_pct"), "fpg": labs.get("fasting_glucose_mgdl"), "ppbg": labs.get("ppbg_2h_mgdl"),
        "egfr": labs.get("egfr_ml_min"), "tg": labs.get("triglycerides_mgdl"), "hdl": labs.get("hdl_mgdl"),
        "years_dx": t2d.get("onset_years_ago", 0), "tcf7l2": gen.get("TCF7L2_rs7903146_risk_alleles", 0),
        "family_hx": 1 if gen.get("family_history_t2d") else 0,
        "metformin": int("metformin" in meds), "sulfonylurea": int("glimepiride" in meds or "gliclazide" in meds),
        "insulin": int("insulin" in meds), "hypertension": int("hypertension" in conds),
    }


def build_features(ts: pd.DataFrame, sleep: pd.DataFrame, ehr: dict) -> pd.DataFrame:
    """ts: one patient's 5-min rows sorted by time. Returns ts with feature columns added."""
    df = ts.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    g = df["glucose_mgdl"].astype(float).interpolate(limit=3, limit_direction="both")
    df["g"] = g
    for k, name in [(1, "g_lag5"), (3, "g_lag15"), (6, "g_lag30"), (12, "g_lag60")]:
        df[name] = g.shift(k)
    df["d15"] = g - df["g_lag15"]
    df["d30"] = g - df["g_lag30"]
    df["d60"] = g - df["g_lag60"]
    df["accel"] = df["d15"] - (df["g_lag15"] - g.shift(6))
    r12, r36 = g.rolling(12, min_periods=6), g.rolling(36, min_periods=18)
    df["g_mean60"], df["g_std60"], df["g_max60"] = r12.mean(), r12.std(), r12.max()
    df["g_mean180"], df["g_std180"] = r36.mean(), r36.std()
    df["g_min180"], df["g_max180"] = r36.min(), r36.max()
    df["frac_above_180_3h"] = (g >= SPIKE_MGDL).astype(float).rolling(36, min_periods=18).mean()

    st = df["steps"].astype(float)
    df["steps30"], df["steps60"], df["steps180"] = st.rolling(6, 1).sum(), st.rolling(12, 1).sum(), st.rolling(36, 1).sum()
    df["hr30"] = df["heart_rate_bpm"].astype(float).rolling(6, 1).mean()
    rhr = (ehr.get("vitals") or {}).get("resting_hr", 72)
    df["hr_dev30"] = df["hr30"] - rhr
    df["hrv60"] = df["hrv_rmssd_ms"].astype(float).rolling(12, 1).mean()
    df["asleep"] = (df["sleep_stage"] != "awake").astype(int)
    c = df["carbs_logged_g"].fillna(0).astype(float)
    df["carbs_log60"], df["carbs_log120"], df["carbs_log180"] = c.rolling(12, 1).sum(), c.rolling(24, 1).sum(), c.rolling(36, 1).sum()
    last_log = df["timestamp"].where(c > 0).ffill()
    df["mins_since_log"] = ((df["timestamp"] - last_log).dt.total_seconds() / 60).fillna(720).clip(upper=720)

    # last completed night of sleep at each timestamp
    sl_cols = ["sleep_hours", "deep_pct", "night_hrv", "night_rhr", "awakenings"]
    if sleep is not None and len(sleep):
        s = sleep.copy()
        s["wake_time"] = pd.to_datetime(s["wake_time"])
        s = s.rename(columns={"night_hrv_ms": "night_hrv", "night_rhr_bpm": "night_rhr"}).sort_values("wake_time")
        df = pd.merge_asof(df, s[["wake_time"] + sl_cols], left_on="timestamp", right_on="wake_time", direction="backward")
        df = df.drop(columns=["wake_time"])
    for col in sl_cols:
        if col not in df:
            df[col] = np.nan

    h = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60
    df["hour_sin"], df["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    df["weekend"] = (df["timestamp"].dt.weekday >= 5).astype(int)
    for k, v in ehr_vector(ehr).items():
        df[k] = v
    return df


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Targets: future glucose at each horizon, and 'new spike within 2 h' flag."""
    g = df["g"]
    for h in HORIZONS:
        df[f"y_g{h}"] = g.shift(-h // 5)
    fut_max = pd.concat([g.shift(-k) for k in range(1, 25)], axis=1).max(axis=1, skipna=False)
    df["y_spike"] = ((g < SPIKE_MGDL) & (fut_max >= SPIKE_MGDL)).astype(float)
    df.loc[fut_max.isna(), "y_spike"] = np.nan
    df.loc[g >= SPIKE_MGDL, "y_spike"] = np.nan  # already high: not a "prediction" case
    return df
