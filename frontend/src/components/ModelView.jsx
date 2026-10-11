import React, { useEffect, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LabelList } from 'recharts'
import { api } from '../api.js'

export default function ModelView() {
  const [m, setM] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { api.model().then(setM).catch(() => setErr('Model metrics unavailable')) }, [])
  if (err) return <div className="card empty">{err}</div>
  if (!m) return <div className="empty">Loading…</div>
  const abl = Object.entries(m.ablation).map(([k, v]) => ({ name: k, auprc: v.auprc, auroc: v.auroc }))
  const c = m.classifier, ev = m.events, tw = m.twin_calibration
  return (
    <div className="model">
      <section className="card">
        <b>Spike prediction (test patients never seen in training)</b>
        <p className="muted">{m.spike_definition}. Split by patient: {m.split.train_patients} train / {m.split.val_patients} validation / {m.split.test_patients} test.</p>
        <div className="kpis">
          <div><small>AUROC</small><b>{c.auroc}</b></div>
          <div><small>AUPRC</small><b>{c.auprc}</b></div>
          <div><small>Sensitivity</small><b>{Math.round(c.sensitivity * 100)}%</b></div>
          <div><small>Precision</small><b>{Math.round(c.precision * 100)}%</b></div>
          <div><small>Spikes caught ≥30 min early</small><b>{ev.caught_30min_ahead_pct}%</b></div>
          <div><small>Median warning time</small><b>{ev.median_lead_time_min} min</b></div>
          <div><small>False alarms / patient-day</small><b>{ev.false_alarms_per_patient_day}</b></div>
        </div>
      </section>
      <div className="grid2">
        <section className="card">
          <b>Data-fusion ablation (AUPRC)</b>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={abl} layout="vertical" margin={{ left: 40, right: 40 }}>
              <XAxis type="number" domain={[0.8, 1]} />
              <YAxis type="category" dataKey="name" width={170} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="auprc" isAnimationActive={false}>
                {abl.map((a, i) => <Cell key={i} fill={i === abl.length - 1 ? '#0f766e' : '#94a3b8'} />)}
                <LabelList dataKey="auprc" position="right" fontSize={11} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>
        <section className="card">
          <b>Glucose forecast error (RMSE, mg/dL)</b>
          <table className="tbl">
            <thead><tr><th>Horizon</th><th>GlucoTwin</th><th>"No change" baseline</th><th>80% band coverage</th></tr></thead>
            <tbody>
              {Object.entries(m.forecast).map(([h, v]) => (
                <tr key={h}><td>{h}</td><td><b>{v.rmse}</b></td><td>{v.persistence_rmse}</td><td>{v.band_80_coverage_pct}%</td></tr>
              ))}
            </tbody>
          </table>
          <b style={{ display: 'block', marginTop: 16 }}>Twin calibration</b>
          <p className="muted">{tw.protocol}. Insulin-sensitivity correlation with hidden truth: EHR prior {tw.corr_sensitivity_prior_vs_truth} → calibrated {tw.corr_sensitivity_calibrated_vs_truth}. Basal glucose: {tw.corr_basal_prior_vs_truth} → {tw.corr_basal_calibrated_vs_truth}.</p>
        </section>
      </div>
    </div>
  )
}
