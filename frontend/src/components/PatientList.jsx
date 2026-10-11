import React from 'react'
import { trendArrow } from '../api.js'

const LEVEL = { HIGH: 'High', MODERATE: 'Moderate', LOW: 'Low', ACTIVE_SPIKE: 'Above range', UNKNOWN: '—' }

export default function PatientList({ patients, selected, onSelect }) {
  return (
    <ul className="plist">
      {patients.map((p) => (
        <li key={p.id} className={(selected === p.id ? 'sel ' : '') + 'lvl-' + p.risk_level} onClick={() => onSelect(p.id)}>
          <div className="pl-top">
            <b>{p.name}</b>
            <span className={'badge ' + p.risk_level}>{LEVEL[p.risk_level] || p.risk_level}</span>
          </div>
          <div className="pl-sub">
            <span>{p.id} · {p.age}{p.gender === 'male' ? 'M' : 'F'} · HbA1c {p.hba1c}%</span>
            <span className="pl-g">
              {p.current_glucose != null ? Math.round(p.current_glucose) : '—'}
              <small> mg/dL {trendArrow(p.trend_per_quarter_hour)}</small>
            </span>
          </div>
          {p.spike_probability != null && p.risk_level !== 'ACTIVE_SPIKE' && (
            <div className="riskbar"><i style={{ width: Math.round(p.spike_probability * 100) + '%' }} /></div>
          )}
          {p.open_alerts > 0 && <span className="pl-alert">{p.open_alerts} open alert{p.open_alerts > 1 ? 's' : ''}</span>}
        </li>
      ))}
    </ul>
  )
}
