// All calls go to the Spring Boot backend (which talks to the Python ML service).
export const API = import.meta.env.VITE_API_URL || 'http://localhost:8080'

async function req(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  patients: () => req('/api/patients'),
  patient: (id) => req(`/api/patients/${id}`),
  timeline: (id, hours = 12) => req(`/api/patients/${id}/timeline?hours=${hours}`),
  prediction: (id) => req(`/api/patients/${id}/prediction`),
  twin: (id) => req(`/api/patients/${id}/twin`),
  whatIf: (id, scenario) => req(`/api/patients/${id}/whatif`, { method: 'POST', body: scenario }),
  alerts: (open = true) => req(`/api/alerts?open=${open}`),
  ack: (id, note) => req(`/api/alerts/${id}/ack`, { method: 'POST', body: { note } }),
  clock: () => req('/api/clock'),
  setClock: (body) => req('/api/clock', { method: 'POST', body }),
  model: () => req('/api/model'),
  stream: () => new EventSource(API + '/api/stream'),
}

export const fmtTime = (iso) => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
export const fmtDateTime = (iso) => new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
export const trendArrow = (t) => (t == null ? '' : t > 15 ? '⇈' : t > 5 ? '↑' : t < -15 ? '⇊' : t < -5 ? '↓' : '→')
