import React, { useEffect, useState } from 'react'
import { api, trendArrow, fmtDateTime } from '../api.js'
import GlucoseChart from './GlucoseChart.jsx'
import WhatIf from './WhatIf.jsx'

const LEVEL_TEXT = {
  HIGH: 'High risk of a glucose spike in the next 2 hours',
  MODERATE: 'Moderate risk of a glucose spike in the next 2 hours',
  LOW: 'Low risk — glucose expected to stay in range',
  ACTIVE_SPIKE: 'Glucose is above 180 mg/dL right now',
}

export default function PatientView({ id, tick, alerts, onAck }) {
  const [detail, setDetail] = useState(null)
  const [timeline, setTimeline] = useState([])
  const [pred, setPred] = useState(null)
  const [twin, setTwin] = useState(null)
  const [hours, setHours] = useState(12)

  useEffect(() => { setDetail(null); setPred(null); setTwin(null); setTimeline([]) }, [id])
  useEffect(() => {
    let live = true
    Promise.all([api.patient(id), api.timeline(id, hours), api.prediction(id).catch(() => null)]).then(([d, t, p]) => {
      if (!live) return
      setDetail(d); setTimeline(t); setPred(p)
    }).catch(() => {})
    return () => { live = false }
  }, [id, tick, hours])
  useEffect(() => { api.twin(id).then(setTwin).catch(() => setTwin(null)) }, [id])

  if (!detail) return <div className="empty">Loading twin…</div>
  const e = detail.ehr
  const s = detail.summary
  const lvl = pred?.risk_level || s.risk_level
  const last = detail.sleep_history?.[detail.sleep_history.length - 1]

  return (
    <div className="pview">
      <section className="card phead">
        <div>
          <h2>{e.name} <small>{e.id} · synthetic patient</small></h2>
          <p>{e.age} y · {e.gender} · {e.address.city}, {e.address.state} · BMI {e.vitals.bmi} · BP {e.vitals.systolic_bp}/{e.vitals.diastolic_bp}</p>
          <div className="chips">
            {e.conditions.map((c) => <span key={c.code} className="chip cond">{c.display}{c.onset_years_ago != null ? ` · ${c.onset_years_ago} y` : ''}</span>)}
            {e.medications.map((m) => <span key={m.name} className="chip med">{m.name} {m.dose}</span>)}
          </div>
        </div>
        <div className="labs">
          <div><small>HbA1c</small><b>{e.labs.hba1c_pct}%</b></div>
          <div><small>Fasting glucose</small><b>{e.labs.fasting_glucose_mgdl}</b></div>
          <div><small>eGFR</small><b>{e.labs.egfr_ml_min}</b></div>
          <div><small>TCF7L2 risk alleles</small><b>{e.genetics.TCF7L2_rs7903146_risk_alleles}</b></div>
          <div><small>Time in range (24 h)</small><b>{s.time_in_range_day ?? '—'}%</b></div>
        </div>
      </section>

      <div className="grid2">
        <section className={'card risk ' + lvl}>
          <small>Twin prediction · next 2 hours</small>
          <div className="risk-main">
            <div className="gauge">
              <b>{pred && !pred.in_spike ? Math.min(99, Math.round(pred.spike_probability_2h * 100)) + '%' : pred?.in_spike ? '>180' : '—'}</b>
              <span>{pred?.in_spike ? 'now' : 'spike risk'}</span>
            </div>
            <div>
              <h3>{LEVEL_TEXT[lvl] || 'Waiting for data'}</h3>
              {pred && (
                <p>Now <b>{Math.round(pred.current_glucose)} mg/dL {trendArrow(pred.trend_mgdl_per_15min)}</b>
                  {' '}· forecast peak <b>{Math.round(pred.expected_peak.glucose)}</b> in {pred.expected_peak.minutes_ahead} min
                  {' '}(likely range {Math.round(pred.expected_peak.low)}–{Math.round(pred.expected_peak.high)})</p>
              )}
            </div>
          </div>
          {pred?.drivers && (
            <div className="drivers">
              <small>Why the twin thinks so</small>
              {pred.drivers.map((d) => (
                <div key={d.feature} className={'drv ' + (d.effect === 'raises risk' ? 'up' : 'down')}>
                  <span>{d.effect === 'raises risk' ? '▲' : '▼'} {d.label}</span>
                  <b>{d.value}</b>
                </div>
              ))}
            </div>
          )}
          {alerts.length > 0 && (
            <div className="inline-alerts">
              {alerts.slice(0, 2).map((a) => (
                <div key={a.id} className="ia">
                  <span>{fmtDateTime(a.created_at)} · {a.message}</span>
                  <button onClick={() => onAck(a.id, 'Reviewed from twin view')}>Acknowledge</button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card twin">
          <small>Personalised twin physiology</small>
          {twin ? (
            <>
              <div className="params">
                <div><b>{twin.params.s.toFixed(2)}</b><span>Insulin sensitivity<br /><em>1.0 = typical; lower = more resistant</em></span></div>
                <div><b>{Math.round(twin.params.gb)}</b><span>Basal glucose<br /><em>mg/dL the body settles to</em></span></div>
                <div><b>{twin.params.cf.toFixed(1)}</b><span>Carb response<br /><em>mg/dL rise per gram</em></span></div>
              </div>
              <p className="muted">Calibrated on {twin.meals_used} logged meals from the last 5 days.
                {twin.fit_rmse != null && <> Post-meal fit error {twin.fit_rmse} mg/dL (EHR-only twin: {twin.prior_rmse}).</>}</p>
            </>
          ) : <p className="muted">Calibrating…</p>}
          {last && (
            <div className="sleep">
              <small>Sleep (last 7 nights, from wearable)</small>
              <div className="sleepbars">
                {detail.sleep_history.map((n) => (
                  <div key={n.wake_time} title={`${n.sleep_hours} h, deep ${n.deep_pct}%`}>
                    <i style={{ height: Math.min(100, n.sleep_hours / 9 * 100) + '%' }} className={n.sleep_hours < 6 ? 'short' : ''} />
                    <span>{new Date(n.wake_time).getDate()}</span>
                  </div>
                ))}
              </div>
              <p className="muted">Last night {last.sleep_hours} h · deep {last.deep_pct}% · overnight HRV {last.night_hrv_ms} ms</p>
            </div>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card-head">
          <b>Continuous glucose + wearable stream</b>
          <div className="seg">
            {[6, 12, 24].map((h) => <button key={h} className={hours === h ? 'on' : ''} onClick={() => setHours(h)}>{h} h</button>)}
          </div>
        </div>
        <GlucoseChart timeline={timeline} prediction={pred} />
      </section>

      <WhatIf id={id} />
    </div>
  )
}
