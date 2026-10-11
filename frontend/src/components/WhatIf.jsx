import React, { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ReferenceArea, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api, fmtTime } from '../api.js'

const PRESETS = [
  { label: '30% less rice at dinner', s: { carb_change_pct: { dinner: -30 } } },
  { label: '20-min walk after lunch & dinner', s: { post_meal_walk_min: { lunch: 20, dinner: 20 } } },
  { label: 'Dinner 1.5 h earlier', s: { dinner_shift_h: -1.5 } },
  { label: 'Sleep 7.5 h', s: { sleep_hours: 7.5 } },
]

export default function WhatIf({ id }) {
  const [form, setForm] = useState({ dinnerCarb: 0, lunchCarb: 0, breakfastCarb: 0, walkLunch: 0, walkDinner: 0, morningWalk: 0, dinnerShift: 0, sleep: '' })
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => { setRes(null) }, [id])

  const scenario = () => {
    const s = { carb_change_pct: {}, post_meal_walk_min: {} }
    if (form.dinnerCarb) s.carb_change_pct.dinner = +form.dinnerCarb
    if (form.lunchCarb) s.carb_change_pct.lunch = +form.lunchCarb
    if (form.breakfastCarb) s.carb_change_pct.breakfast = +form.breakfastCarb
    if (form.walkLunch) s.post_meal_walk_min.lunch = +form.walkLunch
    if (form.walkDinner) s.post_meal_walk_min.dinner = +form.walkDinner
    if (form.morningWalk) s.morning_walk_min = +form.morningWalk
    if (form.dinnerShift) s.dinner_shift_h = +form.dinnerShift
    if (form.sleep) s.sleep_hours = +form.sleep
    return s
  }
  const run = async (s) => {
    setBusy(true); setErr(null)
    try { setRes(await api.whatIf(id, s || scenario())) } catch (e) { setErr('Simulation failed — is the ML service running?') }
    setBusy(false)
  }
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const data = res ? res.timestamps.map((t, i) => ({ t: new Date(t).getTime(), base: res.baseline.glucose[i], sc: res.scenario.glucose[i] })) : []
  const delta = (a, b, inv) => { const d = +(b - a).toFixed(1); const good = inv ? d < 0 : d > 0; return <em className={d === 0 ? '' : good ? 'good' : 'bad'}>{d > 0 ? '+' : ''}{d}</em> }

  return (
    <section className="card whatif">
      <div className="card-head">
        <b>What-if simulator · run the patient's twin for the next 24 h</b>
        <span className="muted">Uses this patient's calibrated physiology and their usual meal routine</span>
      </div>
      <div className="presets">
        {PRESETS.map((p) => <button key={p.label} onClick={() => run(p.s)} disabled={busy}>{p.label}</button>)}
      </div>
      <div className="form">
        <label>Breakfast carbs %<input type="number" step="10" value={form.breakfastCarb} onChange={set('breakfastCarb')} /></label>
        <label>Lunch carbs %<input type="number" step="10" value={form.lunchCarb} onChange={set('lunchCarb')} /></label>
        <label>Dinner carbs %<input type="number" step="10" value={form.dinnerCarb} onChange={set('dinnerCarb')} /></label>
        <label>Walk after lunch (min)<input type="number" step="5" value={form.walkLunch} onChange={set('walkLunch')} /></label>
        <label>Walk after dinner (min)<input type="number" step="5" value={form.walkDinner} onChange={set('walkDinner')} /></label>
        <label>Morning walk (min)<input type="number" step="5" value={form.morningWalk} onChange={set('morningWalk')} /></label>
        <label>Shift dinner (h)<input type="number" step="0.5" value={form.dinnerShift} onChange={set('dinnerShift')} /></label>
        <label>Sleep tonight (h)<input type="number" step="0.5" placeholder="as usual" value={form.sleep} onChange={set('sleep')} /></label>
        <button className="primary" onClick={() => run()} disabled={busy}>{busy ? 'Simulating…' : 'Run simulation'}</button>
      </div>
      {err && <p className="bad">{err}</p>}
      {res && (
        <>
          <div className="wi-metrics">
            <div><small>Time in range</small><b>{res.baseline.time_in_range_pct}% → {res.scenario.time_in_range_pct}%</b>{delta(res.baseline.time_in_range_pct, res.scenario.time_in_range_pct)}</div>
            <div><small>Peak glucose</small><b>{Math.round(res.baseline.peak_mgdl)} → {Math.round(res.scenario.peak_mgdl)}</b>{delta(res.baseline.peak_mgdl, res.scenario.peak_mgdl, true)}</div>
            <div><small>Mean glucose</small><b>{Math.round(res.baseline.mean_mgdl)} → {Math.round(res.scenario.mean_mgdl)}</b>{delta(res.baseline.mean_mgdl, res.scenario.mean_mgdl, true)}</div>
            <div><small>Time above 180</small><b>{res.baseline.time_above_180_pct}% → {res.scenario.time_above_180_pct}%</b>{delta(res.baseline.time_above_180_pct, res.scenario.time_above_180_pct, true)}</div>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#e5e7eb" vertical={false} />
              <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={fmtTime} minTickGap={50} />
              <YAxis domain={[60, 'auto']} width={40} />
              <ReferenceArea y1={70} y2={180} fill="#10b981" fillOpacity={0.06} />
              <ReferenceLine y={180} stroke="#dc2626" strokeDasharray="4 4" />
              <Line dataKey="base" stroke="#94a3b8" strokeWidth={2} dot={false} name="Usual routine" isAnimationActive={false} />
              <Line dataKey="sc" stroke="#0f766e" strokeWidth={2.5} dot={false} name="With change" isAnimationActive={false} />
              <Tooltip labelFormatter={fmtTime} formatter={(v, n) => [Math.round(v) + ' mg/dL', n]} />
            </LineChart>
          </ResponsiveContainer>
          <p className="muted">Usual routine learned from logs: {Object.entries(res.routine).map(([k, v]) => `${k} ~${String(Math.floor(v.hour)).padStart(2, '0')}:${String(Math.round((v.hour % 1) * 60)).padStart(2, '0')} (${v.carbs_g} g)`).join(' · ')}</p>
        </>
      )}
    </section>
  )
}
