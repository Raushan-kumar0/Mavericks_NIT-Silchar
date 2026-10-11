# GlucoTwin demo video script (target: about 19 minutes; the form allows 15–20)

**Format:** screen recording (OBS or the PowerPoint "Record" feature) with your voice and an optional webcam bubble. Upload to YouTube as **Unlisted** and paste the link into the README.

**Before recording:**

1. Start all three services (`./start.sh`, or the three terminals in the README).
2. Open the dashboard at `http://localhost:5173`. Pause the clock.
3. Jump the clock to 12:30 on day 8:
   `curl -X POST localhost:8080/api/clock -H "Content-Type: application/json" -d '{"jump_to":"2026-09-08T12:30:00"}'`
4. Open these in tabs: the deck, VS Code with the repo, the ML docs at `http://localhost:8000/docs`, and `ml-service/models/plots/`.

Speaker split: **Raushan** = problem, data, backend and live dashboard demo (rows 1–5, 8). **Chaitanya** = ML model, twin, results and impact (rows 6–7, 9–11). Both speak in row 12.

| # | Time | Screen | Who | What to say (key points) |
|---|---|---|---|---|
| 1 | 0:00–1:00 | Slide 1 | Raushan | Team, college, one-line idea: "a virtual copy of each diabetic patient that warns the doctor 2 hours before a glucose spike." |
| 2 | 1:00–2:30 | Slide 2 | Raushan | 101 million people with diabetes in India. HbA1c every 3 months misses daily spikes. Spikes above 180 mg/dL damage eyes, kidneys and nerves. A CGM gives 288 readings a day, and no doctor can read that for 500 patients. |
| 3 | 2:30–3:30 | Slide 3 | Raushan | The two streams required by the challenge (static EHR + dynamic wearable) → the twin → what the doctor gets. "Proactive, not reactive." |
| 4 | 3:30–5:00 | Slide 4, then VS Code `data/ehr_patients.json` and `wearable_timeseries.csv` | Raushan | Synthetic data only (DPDP/HIPAA). Show one EHR record: ICD-10 codes, medications, HbA1c, TCF7L2. Show the CSV columns. Explain India-specific behaviour: late dinners, rice-heavy lunches, festive sweets, ~70% of meals logged. Run `python data-generator/generate.py --patients 5` live (it takes about 1 second). |
| 5 | 5:00–6:15 | Slide 5 + `docs/architecture.pdf` | Raushan | Walk the diagram: generator → Spring Boot (DataStore, SimulationClock, TwinService, AlertService) → FastAPI ML → React. Why a replay clock: the twin never sees the future. |
| 6 | 6:15–8:15 | Slide 6, then `ml-service/twin/features.py` | Chaitanya | The 54 fused features in 4 groups. The same function runs in training and serving. The spike label definition. Patient-level split. LightGBM classifier + quantile forecasters + TreeSHAP explanations. |
| 7 | 8:15–9:45 | Slide 7, then `twin/physiology.py` and `digital_twin.py` | Chaitanya | The mechanistic model in plain words. EHR prior → calibration on the patient's own post-meal curves → what-if. Calibration results, including the honest note that the median error barely changed. |
| 8 | 9:45–14:45 | **Live dashboard** | Raushan | (a) Patient list sorted by risk. Press **Play**, switch to 15 min/tick, and watch patients turn HIGH after lunch. An alert toast appears. (b) Open a HIGH patient: EHR chips, labs, risk gauge, "why" drivers, forecast band on the chart, meal triangles, steps, sleep shading. (c) Personalised parameters + 7-night sleep bars. (d) What-if: run "30% less rice at dinner", then "20-min walk after lunch & dinner", and compare time in range and peak. Enter a custom scenario. (e) Alerts tab: acknowledge one with a note. (f) Model performance tab. |
| 9 | 14:45–15:30 | `http://localhost:8000/docs` | Chaitanya | Show `/predict` and `/twin/simulate` in Swagger. Show the JSON output: probability, forecast, drivers. |
| 10 | 15:30–17:00 | Slides 8–9 + `models/plots/` | Chaitanya | AUROC 0.95, 85.6% of spikes flagged ≥30 min early, median warning 100 min, 2.15 false alarms per patient-day. Forecast RMSE roughly half the "no change" baseline. Ablation: full fusion is best, EHR + wearables work even without a CGM, and the gains are small (be honest). |
| 11 | 17:00–18:30 | Slides 12–13 | Chaitanya | Impact: remote monitoring at scale, prevention, low-cost path, privacy. Limitations. Roadmap: CGMacros validation, meal detection, ABDM/FHIR, closed loop. |
| 12 | 18:30–19:00 | Slide 14 | Both | Thank you, repo link, MIT license. |

### Recording tips
- Record in 1080p. Zoom the browser to 110% so the charts are readable.
- Record each section separately and join them. Keep the total between 15 and 20 minutes (the submission form says 15–20). Aim for 18–19 so you have a safety margin either way.
- Say "synthetic patient" when you show names, so nobody thinks the data is real.
