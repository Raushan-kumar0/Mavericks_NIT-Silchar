import React, { useState } from 'react'
import { fmtDateTime } from '../api.js'

export default function AlertsPanel({ alerts, onAck, onOpen }) {
  const [notes, setNotes] = useState({})
  if (!alerts.length) return <div className="card empty">No open alerts. The twin raises an alert when a spike is predicted within 2 hours.</div>
  return (
    <div className="alerts">
      {alerts.map((a) => (
        <div key={a.id} className={'card alert ' + a.severity}>
          <div className="al-head">
            <span className={'badge ' + a.severity}>{a.severity}</span>
            <b className="link" onClick={() => onOpen(a.patient_id)}>{a.patient_name}</b>
            <small>{a.patient_id} · {fmtDateTime(a.created_at)}</small>
          </div>
          <p>{a.message}</p>
          {a.drivers?.length > 0 && <p className="muted">Main drivers: {a.drivers.join(', ')}</p>}
          <div className="al-act">
            <input placeholder="Action taken (e.g. called patient, advised walk)" value={notes[a.id] || ''} onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} />
            <button onClick={() => onAck(a.id, notes[a.id] || '')}>Acknowledge</button>
          </div>
        </div>
      ))}
    </div>
  )
}
