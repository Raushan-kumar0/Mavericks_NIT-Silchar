"""
GlucoTwin physiology core.

A small, explainable glucose-dynamics model for a person with Type 2 Diabetes.
It is used in two places:
  1. data-generator  -> to create synthetic CGM data (with noise + hidden events)
  2. ml-service      -> as the personalised "virtual patient" for what-if simulation

Model (time step dt = 5 min):
  Carbs eaten go into a 2-compartment gut:   Q1 -> Q2 -> blood
      dQ1 = -Q1/tau
      dQ2 =  Q1/tau - Q2/tau
      Ra  =  Q2/tau                    (grams of glucose appearing per minute)
  Blood glucose G (mg/dL):
      dG = cf*Ra  -  k*S_eff*(G - Gb_eff)  -  exercise_uptake  +  stress_release
  where
      S_eff  = personal insulin sensitivity x circadian x sleep-debt x exercise afterglow
      Gb_eff = personal basal glucose + dawn phenomenon (04:00-08:00)

Parameters are deliberately few so a doctor can understand them, and so they can be
calibrated from a few days of a patient's own CGM + meal logs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import List, Optional

import numpy as np

DT = 5  # minutes per step
STEPS_PER_DAY = 24 * 60 // DT
K0 = 0.0105  # base glucose clearance rate per minute at S = 1


@dataclass
class TwinParams:
    """Personal physiology parameters of one virtual patient."""
    gb: float = 125.0          # basal (fasting) glucose, mg/dL
    s: float = 0.8             # insulin sensitivity multiplier (0.3 = very resistant, 1.2 = good)
    cf: float = 2.0            # mg/dL rise per gram of absorbed carbohydrate
    tau: float = 38.0          # gut absorption time constant, minutes
    dawn: float = 15.0         # dawn phenomenon amplitude, mg/dL
    evening_drop: float = 0.15 # fractional drop in sensitivity in the evening
    exercise_gain: float = 0.6 # extra clearance while walking (fraction of S)
    sleep_penalty: float = 0.09  # sensitivity lost per hour of sleep below 7h

    def to_dict(self):
        return asdict(self)


@dataclass
class DayContext:
    """Things that change day to day."""
    sleep_hours_last_night: float = 7.0
    day_factor: float = 1.0  # unexplained day-to-day variation of sensitivity


def circadian_factor(minute_of_day: float, p: TwinParams) -> float:
    """Insulin sensitivity is best in the morning and drops in the evening."""
    h = minute_of_day / 60.0
    # smooth bump: 1.0 in the morning, (1 - evening_drop) around 21:00
    return 1.0 - p.evening_drop * 0.5 * (1 - math.cos(2 * math.pi * (h - 9) / 24))


def dawn_offset(minute_of_day: float, p: TwinParams) -> float:
    h = minute_of_day / 60.0
    if 4 <= h <= 9:
        return p.dawn * math.sin(math.pi * (h - 4) / 5)
    return 0.0


def sleep_factor(sleep_hours: float, p: TwinParams) -> float:
    debt = max(0.0, 7.0 - sleep_hours)
    return max(0.6, 1.0 - p.sleep_penalty * debt)


def simulate(
    p: TwinParams,
    start_minute_of_day: float,
    n_steps: int,
    g0: float,
    carbs: np.ndarray,          # grams eaten at each step, shape (n_steps,)
    steps: np.ndarray,          # step count in each 5-min bin, shape (n_steps,)
    sleep_hours=7.0,            # float, or per-step array (last night's sleep in force at that step)
    stress: Optional[np.ndarray] = None,  # 0..1 stress level per step
    day_factor=1.0,             # float, or per-step array
    q0: tuple = (0.0, 0.0),
    rng: Optional[np.random.Generator] = None,
    process_noise: float = 0.0,
) -> np.ndarray:
    """Run the twin forward and return true blood glucose for each step."""
    g = g0
    q1, q2 = q0
    afterglow = 0.0
    out = np.empty(n_steps)
    sh_arr = np.broadcast_to(np.asarray(sleep_hours, dtype=float), (n_steps,))
    df_arr = np.broadcast_to(np.asarray(day_factor, dtype=float), (n_steps,))
    for i in range(n_steps):
        sh = sh_arr[i]
        mod = (start_minute_of_day + i * DT) % (24 * 60)
        # gut
        q1 += carbs[i]
        ra = q2 / p.tau
        q2 += DT * (q1 / p.tau - q2 / p.tau)
        q1 -= DT * q1 / p.tau
        # exercise: walking > ~300 steps / 5 min
        walking = min(1.0, max(0.0, (steps[i] - 250) / 300.0))
        afterglow = max(walking, afterglow * math.exp(-DT / 120.0))
        s_eff = (p.s * circadian_factor(mod, p) * sleep_factor(sh, p) * df_arr[i]
                 * (1 + p.exercise_gain * walking + 0.15 * afterglow))
        gb_eff = p.gb + dawn_offset(mod, p)
        dg = p.cf * ra - K0 * s_eff * (g - gb_eff) - 0.25 * walking
        if stress is not None:
            dg += 0.12 * stress[i]
        g += DT * dg
        if rng is not None and process_noise > 0:
            g += rng.normal(0, process_noise)
        g = min(450.0, max(45.0, g))
        out[i] = g
    return out


def time_in_range(g: np.ndarray, lo=70, hi=180) -> float:
    return float(np.mean((g >= lo) & (g <= hi)) * 100.0)


def count_spikes(g: np.ndarray, thr=180) -> int:
    above = g >= thr
    return int(np.sum(above[1:] & ~above[:-1]) + (1 if above[0] else 0))
