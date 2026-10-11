"""
Train + evaluate GlucoTwin models.

  * Spike classifier : P(glucose crosses 180 mg/dL within the next 120 min)
  * Forecasters      : glucose at +30/+60/+90/+120 min (median + 10th/90th percentile bands)
  * Ablation study   : CGM-only vs CGM+wearables vs CGM+EHR vs full fusion
  * Event-level eval : lead time before a spike, false alarms per patient-day
  * Twin fidelity    : calibrated physiology parameters vs hidden ground truth

Patients are split 70/30 by patient id, so test patients are never seen in training.
Outputs: models/*.joblib, models/metrics.json, models/plots/*.png
"""
from __future__ import annotations

import json
import os
import time

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, roc_auc_score, precision_score,
                             recall_score, mean_absolute_error, mean_squared_error, brier_score_loss)

from twin.features import (build_features, add_labels, ALL_FEATURES, CGM_FEATURES, WEARABLE_FEATURES,
                           TIME_FEATURES, EHR_FEATURES, HORIZONS)
from twin.digital_twin import calibrate, meal_fit_rmse, _prep
from twin.physiology import TwinParams

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(HERE, "models")
os.makedirs(os.path.join(OUT, "plots"), exist_ok=True)

CLF_PARAMS = dict(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)


def load():
    ehr = {p["id"]: p for p in json.load(open(os.path.join(DATA, "ehr_patients.json")))}
    ts = pd.read_csv(os.path.join(DATA, "wearable_timeseries.csv"))
    sl = pd.read_csv(os.path.join(DATA, "sleep_summary.csv"))
    frames = []
    for pid, g in ts.groupby("patient_id"):
        f = build_features(g, sl[sl.patient_id == pid], ehr[pid])
        frames.append(add_labels(f))
    return ehr, ts, sl, pd.concat(frames, ignore_index=True)


def event_metrics(df: pd.DataFrame, prob: np.ndarray, thr: float):
    """Spike onsets caught early enough, and false alarm rate."""
    df = df[["patient_id", "timestamp", "g"]].copy()
    df["p"] = prob
    leads, caught, total, false_alarms, days = [], 0, 0, 0, 0.0
    for pid, d in df.groupby("patient_id"):
        d = d.reset_index(drop=True)
        g, p = d["g"].values, d["p"].values
        days += len(d) * 5 / 1440
        above = g >= 180
        onsets = [i for i in range(12, len(g)) if above[i] and not above[i - 6:i].any()]
        alert = np.nan_to_num(p) >= thr
        for o in onsets:
            total += 1
            run = 0
            while run < 24 and o - 1 - run >= 0 and alert[o - 1 - run]:
                run += 1  # contiguous alert run right before the onset
            if run:
                caught += 1
                leads.append(run * 5)
        # alert episodes not followed by any glucose >= 180 within 2 h
        starts = np.flatnonzero(alert[1:] & ~alert[:-1]) + 1
        for s in starts:
            if not above[s:s + 25].any():
                false_alarms += 1
    leads = np.array(leads) if leads else np.array([0])
    return {"spike_events": total, "events_caught_pct": round(100 * caught / max(1, total), 1),
            "median_lead_time_min": float(np.median(leads)),
            "caught_30min_ahead_pct": float(round(100 * np.sum(leads >= 30) / max(1, total), 1)),
            "false_alarms_per_patient_day": round(false_alarms / max(1e-9, days), 2)}


def main():
    t0 = time.time()
    ehr, ts, sl, df = load()
    pids = sorted(df.patient_id.unique())
    rng = np.random.default_rng(7)
    test_p = set(rng.choice(pids, size=int(0.3 * len(pids)), replace=False))
    train_all = df[~df.patient_id.isin(test_p)]
    val_p = set(rng.choice(sorted(train_all.patient_id.unique()), size=8, replace=False))
    tr, va, te = train_all[~train_all.patient_id.isin(val_p)], train_all[train_all.patient_id.isin(val_p)], df[df.patient_id.isin(test_p)]
    print(f"rows train/val/test = {len(tr)}/{len(va)}/{len(te)}; patients {len(pids) - len(test_p) - 8}/8/{len(test_p)}")

    metrics = {"split": {"train_patients": len(pids) - len(test_p) - 8, "val_patients": 8, "test_patients": len(test_p)},
               "spike_definition": "glucose currently < 180 mg/dL and crosses >= 180 mg/dL within the next 120 min"}

    def fit_clf(cols, data):
        d = data.dropna(subset=["y_spike"])
        m = lgb.LGBMClassifier(**CLF_PARAMS)
        m.fit(d[cols], d["y_spike"])
        return m

    # ---------- ablation ----------
    groups = {
        "CGM only": CGM_FEATURES + TIME_FEATURES,
        "CGM + wearables": CGM_FEATURES + WEARABLE_FEATURES + TIME_FEATURES,
        "CGM + EHR": CGM_FEATURES + TIME_FEATURES + EHR_FEATURES,
        "EHR + wearables (no CGM)": WEARABLE_FEATURES + TIME_FEATURES + EHR_FEATURES,
        "Full fusion (EHR + all wearables)": ALL_FEATURES,
    }
    te_l = te.dropna(subset=["y_spike"])
    abl = {}
    for name, cols in groups.items():
        m = fit_clf(cols, tr)
        p = m.predict_proba(te_l[cols])[:, 1]
        abl[name] = {"auroc": round(roc_auc_score(te_l.y_spike, p), 4), "auprc": round(average_precision_score(te_l.y_spike, p), 4)}
        print("ablation", name, abl[name])
    metrics["ablation"] = abl
    metrics["prevalence"] = round(float(te_l.y_spike.mean()), 4)

    # ---------- final classifier ----------
    clf = fit_clf(ALL_FEATURES, tr)
    va_l = va.dropna(subset=["y_spike"])
    pv = clf.predict_proba(va_l[ALL_FEATURES])[:, 1]
    # threshold: highest one that still gives >= 85% sensitivity on validation patients
    thr = 0.5
    for t in np.arange(0.9, 0.05, -0.01):
        if recall_score(va_l.y_spike, pv >= t) >= 0.85:
            thr = round(float(t), 2)
            break
    clf = fit_clf(ALL_FEATURES, pd.concat([tr, va]))
    pt = clf.predict_proba(te_l[ALL_FEATURES])[:, 1]
    metrics["classifier"] = {
        "threshold": thr, "high_risk_threshold": 0.7,
        "auroc": round(roc_auc_score(te_l.y_spike, pt), 4),
        "auprc": round(average_precision_score(te_l.y_spike, pt), 4),
        "sensitivity": round(recall_score(te_l.y_spike, pt >= thr), 4),
        "precision": round(precision_score(te_l.y_spike, pt >= thr), 4),
        "specificity": round(float(np.mean((pt < thr)[te_l.y_spike.values == 0])), 4),
        "brier": round(brier_score_loss(te_l.y_spike, pt), 4),
    }
    p_all = np.full(len(te), np.nan)
    p_all[te["y_spike"].notna().values] = pt
    metrics["events"] = event_metrics(te, p_all, thr)
    print("classifier", metrics["classifier"], metrics["events"])

    # ---------- forecasters ----------
    fc, fmet = {}, {}
    trv = pd.concat([tr, va])
    for h in HORIZONS:
        y = f"y_g{h}"
        d = trv.dropna(subset=[y])
        dt = te.dropna(subset=[y])
        fc[h] = {}
        for q, alpha in [("p50", 0.5), ("p10", 0.1), ("p90", 0.9)]:
            m = lgb.LGBMRegressor(objective="quantile", alpha=alpha, n_estimators=300, learning_rate=0.05,
                                  num_leaves=31, min_child_samples=50, verbose=-1)
            m.fit(d[ALL_FEATURES], d[y] - d["g"])
            fc[h][q] = m
        pred = dt["g"] + fc[h]["p50"].predict(dt[ALL_FEATURES])
        lo = dt["g"] + fc[h]["p10"].predict(dt[ALL_FEATURES])
        hi = dt["g"] + fc[h]["p90"].predict(dt[ALL_FEATURES])
        fmet[f"{h}min"] = {
            "mae": round(mean_absolute_error(dt[y], pred), 2),
            "rmse": round(float(np.sqrt(mean_squared_error(dt[y], pred))), 2),
            "persistence_rmse": round(float(np.sqrt(mean_squared_error(dt[y], dt["g"]))), 2),
            "band_80_coverage_pct": round(float(np.mean((dt[y] >= lo) & (dt[y] <= hi)) * 100), 1),
        }
        print("forecast", h, fmet[f"{h}min"])
    metrics["forecast"] = fmet

    # ---------- feature importance ----------
    imp = pd.Series(clf.booster_.feature_importance("gain"), index=ALL_FEATURES).sort_values(ascending=False)
    metrics["top_features_gain"] = {k: round(float(v / imp.sum() * 100), 2) for k, v in imp.head(15).items()}

    # ---------- twin fidelity: calibrate on 5 days, test on the following 2 days ----------
    truth = json.load(open(os.path.join(DATA, "ground_truth_params.json")))
    rows = []
    for pid in sorted(test_p):
        hist = ts[ts.patient_id == pid]
        fit_part, hold_part = hist.iloc[-288 * 7:-288 * 2], hist.iloc[-288 * 2:]
        cal = calibrate(ehr[pid], fit_part)
        hp = _prep(hold_part)
        rows.append({"patient": pid, "true_s": truth[pid]["s"], "cal_s": cal["params"]["s"], "prior_s": cal["prior"]["s"],
                     "true_gb": truth[pid]["gb"], "cal_gb": cal["params"]["gb"], "prior_gb": cal["prior"]["gb"],
                     "holdout_rmse_prior": meal_fit_rmse(TwinParams(**cal["prior"]), hp),
                     "holdout_rmse_calibrated": meal_fit_rmse(TwinParams(**cal["params"]), hp)})
    cr = pd.DataFrame(rows)
    metrics["twin_calibration"] = {
        "patients": len(cr), "protocol": "calibrate on 5 days of CGM + meal logs, evaluate on the next 2 days",
        "holdout_postmeal_rmse_ehr_prior_mgdl": round(float(cr.holdout_rmse_prior.median()), 1),
        "holdout_postmeal_rmse_calibrated_mgdl": round(float(cr.holdout_rmse_calibrated.median()), 1),
        "patients_improved_pct": round(float(np.mean(cr.holdout_rmse_calibrated < cr.holdout_rmse_prior) * 100), 1),
        "corr_sensitivity_prior_vs_truth": round(float(cr.prior_s.corr(cr.true_s)), 3),
        "corr_sensitivity_calibrated_vs_truth": round(float(cr.cal_s.corr(cr.true_s)), 3),
        "corr_basal_prior_vs_truth": round(float(cr.prior_gb.corr(cr.true_gb)), 3),
        "corr_basal_calibrated_vs_truth": round(float(cr.cal_gb.corr(cr.true_gb)), 3),
    }
    print("twin", metrics["twin_calibration"])

    joblib.dump({"clf": clf, "forecasters": fc, "features": ALL_FEATURES, "threshold": thr}, os.path.join(OUT, "glucotwin_models.joblib"))
    metrics["train_seconds"] = round(time.time() - t0, 1)
    json.dump(metrics, open(os.path.join(OUT, "metrics.json"), "w"), indent=2)
    plots(te, p_all, fc, abl, imp, cr, thr)
    print("done in", metrics["train_seconds"], "s")


def plots(te, p_all, fc, abl, imp, cr, thr):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    P = os.path.join(OUT, "plots")
    # 1. example forecast vs actual
    pid = te.patient_id.iloc[0]
    d = te[te.patient_id == pid].iloc[288 * 9: 288 * 11].copy()
    fig, ax = plt.subplots(2, 1, figsize=(12, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    ax[0].plot(d.timestamp, d.g, label="CGM glucose", color="#1f6feb")
    pred = d.g + fc[60]["p50"].predict(d[ALL_FEATURES])
    ax[0].plot(d.timestamp + pd.Timedelta(minutes=60), pred, label="Twin forecast (+60 min)", color="#d97706", alpha=.9)
    ax[0].axhline(180, ls="--", color="#dc2626", lw=1)
    ax[0].set_ylabel("mg/dL"); ax[0].legend(loc="upper left"); ax[0].set_title(f"{pid}: 60-min forecast and 2-h spike risk (test patient)")
    ax[1].fill_between(d.timestamp, p_all[te.patient_id.values == pid][288 * 9: 288 * 11], color="#dc2626", alpha=.4)
    ax[1].axhline(thr, ls="--", color="k", lw=.8); ax[1].set_ylabel("P(spike<2h)"); ax[1].set_ylim(0, 1)
    plt.tight_layout(); plt.savefig(os.path.join(P, "forecast_example.png"), dpi=120); plt.close()
    # 2. ablation
    fig, ax = plt.subplots(figsize=(8, 4))
    names = list(abl.keys()); vals = [abl[n]["auprc"] for n in names]
    ax.barh(names, vals, color=["#94a3b8"] * (len(names) - 1) + ["#1f6feb"])
    for i, v in enumerate(vals):
        ax.text(v + 0.005, i, f"{v:.3f}", va="center")
    ax.set_xlabel("AUPRC (test patients)"); ax.set_title("Fusing EHR + wearable streams improves spike prediction")
    ax.set_xlim(min(vals) - 0.1, 1); plt.tight_layout(); plt.savefig(os.path.join(P, "ablation.png"), dpi=120); plt.close()
    # 3. importance
    fig, ax = plt.subplots(figsize=(8, 5))
    top = (imp.head(12) / imp.sum() * 100)[::-1]
    ax.barh(top.index, top.values, color="#0f766e"); ax.set_xlabel("% of total gain"); ax.set_title("Top features (spike classifier)")
    plt.tight_layout(); plt.savefig(os.path.join(P, "feature_importance.png"), dpi=120); plt.close()
    # 4. twin calibration on held-out days
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(cr.holdout_rmse_prior, cr.holdout_rmse_calibrated, color="#1f6feb", alpha=.8)
    lim = [min(cr.holdout_rmse_prior.min(), cr.holdout_rmse_calibrated.min()) - 2, max(cr.holdout_rmse_prior.max(), cr.holdout_rmse_calibrated.max()) + 2]
    ax.plot(lim, lim, "k--", lw=.8)
    ax.set_xlabel("EHR-only twin: post-meal RMSE (mg/dL)"); ax.set_ylabel("Calibrated twin: post-meal RMSE (mg/dL)")
    ax.set_title("Twin fidelity on 2 held-out days\n(points below the line = calibration helped)")
    plt.tight_layout(); plt.savefig(os.path.join(P, "twin_calibration.png"), dpi=120); plt.close()

if __name__ == "__main__":
    main()
