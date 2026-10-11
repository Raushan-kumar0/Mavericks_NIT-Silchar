import React from 'react'
import {
  ComposedChart, Line, Area, XAxis, YAxis, Tooltip, ReferenceLine, ReferenceArea, ResponsiveContainer,
  Bar, BarChart, Scatter, CartesianGrid,
} from 'recharts'
import { fmtTime } from '../api.js'

// Past 12 h of CGM + the twin's 2-hour forecast (median and 80% band)
export default function GlucoseChart({ timeline, prediction }) {
  if (!timeline?.length) return <div className="empty">No sensor data yet</div>
  const data = timeline.map((r) => ({
    t: new Date(r.timestamp).getTime(),
    glucose: r.glucose_mgdl ?? null,
    steps: r.steps,
    hr: r.heart_rate_bpm,
    meal: r.carbs_logged_g > 0 ? 62 : null,
    carbs: r.carbs_logged_g,
    asleep: r.sleep_stage !== 'awake' ? 1 : 0,
  }))
  const last = data[data.length - 1]
  if (prediction?.forecast) {
    const t0 = last.t
    data[data.length - 1] = { ...last, fc: last.glucose, band: [last.glucose, last.glucose] }
    prediction.forecast.forEach((f) => {
      data.push({ t: t0 + f.minutes_ahead * 60000, fc: f.glucose, band: [f.low, f.high] })
    })
  }
  const max = Math.max(260, ...data.map((d) => d.glucose || 0), ...data.map((d) => (d.band ? d.band[1] : 0)))
  const sleepBlocks = []
  let start = null
  data.forEach((d, i) => {
    if (d.asleep && start == null) start = d.t
    if ((!d.asleep || i === data.length - 1) && start != null) { sleepBlocks.push([start, d.t]); start = null }
  })
  const tick = (v) => fmtTime(v)
  return (
    <div className="chartwrap">
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }} syncId="g">
          <CartesianGrid stroke="#e5e7eb" vertical={false} />
          <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} tickFormatter={tick} minTickGap={40} />
          <YAxis domain={[50, Math.ceil(max / 40) * 40]} ticks={[70, 120, 180, 240, 300, 360].filter((t) => t <= Math.ceil(max / 40) * 40)} width={40} />
          <ReferenceArea y1={70} y2={180} fill="#10b981" fillOpacity={0.06} />
          {sleepBlocks.map(([a, b], i) => <ReferenceArea key={i} x1={a} x2={b} fill="#6366f1" fillOpacity={0.06} />)}
          <ReferenceLine y={180} stroke="#dc2626" strokeDasharray="4 4" label={{ value: '180', position: 'right', fill: '#dc2626', fontSize: 11 }} />
          <ReferenceLine y={70} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: '70', position: 'right', fill: '#b45309', fontSize: 11 }} />
          <ReferenceLine x={last.t} stroke="#334155" label={{ value: 'now', position: 'top', fontSize: 11 }} />
          <Area dataKey="band" stroke="none" fill="#f59e0b" fillOpacity={0.22} isAnimationActive={false} connectNulls />
          <Line dataKey="glucose" stroke="#1d4ed8" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls name="CGM glucose" />
          <Line dataKey="fc" stroke="#d97706" strokeWidth={2.5} strokeDasharray="6 3" dot={{ r: 3 }} isAnimationActive={false} name="Twin forecast" connectNulls />
          <Scatter dataKey="meal" fill="#0f766e" shape="triangle" name="Logged meal" isAnimationActive={false} />
          <Tooltip labelFormatter={tick} formatter={(v, n, p) => {
            if (n === 'Logged meal') return [`${p.payload.carbs} g carbs`, 'Meal']
            if (Array.isArray(v)) return [`${Math.round(v[0])}–${Math.round(v[1])}`, '80% band']
            return [Math.round(v), n]
          }} />
        </ComposedChart>
      </ResponsiveContainer>
      <ResponsiveContainer width="100%" height={70}>
        <BarChart data={data} margin={{ top: 0, right: 20, left: 0, bottom: 0 }} syncId="g">
          <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} hide />
          <YAxis width={40} tick={{ fontSize: 10 }} />
          <Bar dataKey="steps" fill="#14b8a6" isAnimationActive={false} name="Steps / 5 min" />
          <Tooltip labelFormatter={tick} />
        </BarChart>
      </ResponsiveContainer>
      <div className="legend">
        <span><i style={{ background: '#1d4ed8' }} />CGM glucose</span>
        <span><i style={{ background: '#d97706' }} />Twin forecast (+80% band)</span>
        <span><i className="tri" />Logged meal</span>
        <span><i style={{ background: '#14b8a6' }} />Steps</span>
        <span><i style={{ background: '#c7d2fe' }} />Asleep</span>
        <span><i style={{ background: '#d1fae5' }} />Target 70–180</span>
      </div>
    </div>
  )
}
