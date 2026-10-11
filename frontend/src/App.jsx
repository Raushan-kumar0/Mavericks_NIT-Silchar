import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtDateTime } from './api.js'
import PatientList from './components/PatientList.jsx'
import PatientView from './components/PatientView.jsx'
import AlertsPanel from './components/AlertsPanel.jsx'
import ModelView from './components/ModelView.jsx'

export default function App() {
  const [patients, setPatients] = useState([])
  const [selected, setSelected] = useState(null)
  const [clock, setClock] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [tab, setTab] = useState('twin')
  const [tick, setTick] = useState(0)
  const [toast, setToast] = useState(null)
  const [error, setError] = useState(null)
  const selectedRef = useRef(null)
  selectedRef.current = selected

  const refresh = useCallback(async () => {
    try {
      const [p, c, a] = await Promise.all([api.patients(), api.clock(), api.alerts(true)])
      setPatients(p)
      setClock(c)
      setAlerts(a)
      setError(null)
      if (!selectedRef.current && p.length) setSelected(p[0].id)
    } catch (e) {
      setError('Cannot reach backend at ' + (import.meta.env.VITE_API_URL || 'http://localhost:8080'))
    }
  }, [])

  useEffect(() => {
    refresh()
    let es
    try {
      es = api.stream()
      es.addEventListener('tick', (ev) => {
        const d = JSON.parse(ev.data)
        setClock((c) => ({ ...(c || {}), now: d.now, running: d.running, ml_up: d.ml_up ?? c?.ml_up }))
        if (d.new_alerts && d.new_alerts.length) {
          const a = d.new_alerts[0]
          setToast(`${a.severity} risk: ${a.patient_name} — ${a.message}`)
          setTimeout(() => setToast(null), 6000)
        }
        setTick((t) => t + 1)
      })
    } catch (e) { /* SSE optional */ }
    const poll = setInterval(refresh, 15000)
    return () => { es && es.close(); clearInterval(poll) }
  }, [refresh])

  useEffect(() => { if (tick) refresh() }, [tick, refresh])

  const control = async (body) => setClock(await api.setClock(body))
  const ack = async (id, note) => { await api.ack(id, note); refresh() }
  const highCount = patients.filter((p) => p.risk_level === 'HIGH').length

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg width="28" height="28" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="#0f766e" /><path d="M8 18 L13 18 L15 10 L18 24 L20 16 L24 16" stroke="white" strokeWidth="2.5" fill="none" /></svg>
          <div>
            <b>GlucoTwin</b>
            <span>Digital Twin for Type 2 Diabetes · Clinician view</span>
          </div>
        </div>
        <nav className="tabs">
          <button className={tab === 'twin' ? 'on' : ''} onClick={() => setTab('twin')}>Patient twin</button>
          <button className={tab === 'alerts' ? 'on' : ''} onClick={() => setTab('alerts')}>Alerts {alerts.length ? <em>{alerts.length}</em> : null}</button>
          <button className={tab === 'model' ? 'on' : ''} onClick={() => setTab('model')}>Model performance</button>
        </nav>
        <div className="clock">
          <span className={'dot ' + (clock?.ml_up === false ? 'bad' : 'ok')} title={clock?.ml_up === false ? 'ML service offline' : 'ML service online'} />
          <div>
            <small>Live replay clock</small>
            <b>{clock ? fmtDateTime(clock.now) : '—'}</b>
          </div>
          <button onClick={() => control({ running: !clock?.running })}>{clock?.running ? '❚❚ Pause' : '▶ Play'}</button>
          <select value={clock?.minutes_per_tick || 5} onChange={(e) => control({ minutes_per_tick: +e.target.value })} title="simulated minutes per tick">
            <option value={5}>5 min/tick</option>
            <option value={15}>15 min/tick</option>
            <option value={30}>30 min/tick</option>
          </select>
        </div>
      </header>

      {error && <div className="banner">{error}. Start the Spring Boot backend and the ML service (see README).</div>}
      {toast && <div className="toast" onClick={() => setToast(null)}>🔔 {toast}</div>}

      <div className="layout">
        <aside className="sidebar">
          <div className="side-head">
            <b>Patients</b>
            <span>{patients.length} twins · <span className="high">{highCount} high risk</span></span>
          </div>
          <PatientList patients={patients} selected={selected} onSelect={(id) => { setSelected(id); setTab('twin') }} />
        </aside>
        <main className="main">
          {tab === 'twin' && selected && <PatientView id={selected} tick={tick} alerts={alerts.filter((a) => a.patient_id === selected)} onAck={ack} />}
          {tab === 'alerts' && <AlertsPanel alerts={alerts} onAck={ack} onOpen={(id) => { setSelected(id); setTab('twin') }} />}
          {tab === 'model' && <ModelView />}
        </main>
      </div>
      <footer className="foot">Synthetic data only (Synthea-style EHR + simulated wearables). Not a medical device — decision support prototype.</footer>
    </div>
  )
}
