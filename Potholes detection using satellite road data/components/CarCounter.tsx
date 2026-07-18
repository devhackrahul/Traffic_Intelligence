'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

type Role = 'public' | 'internal'

interface TypeCounts {
  [key: string]: number
}

interface PeakHour {
  hour: string | null
  label: string | null
  count: number
}

interface CarStats {
  status: string
  error?: string | null
  running: boolean
  role?: Role
  in_count?: number
  out_count?: number
  total: number
  pedestrians?: number
  vehicles_in_frame?: number
  pedestrians_in_frame?: number
  alias: string
  corridor?: string
  by_type?: TypeCounts
  heavy_trucks: number
  heavy_vehicles?: number
  hourly?: Record<string, number>
  peak_hour?: PeakHour
  speed_bands?: Record<string, number>
  congestion?: {
    score: number
    level: string
    vehicles_per_minute?: number
    queue_length?: number
  }
  conflicts?: { near_miss_count: number }
  camera_health?: {
    status: string
    blur_score?: number
    brightness?: number
    last_frame_age_sec?: number | null
  }
  school_zone?: {
    windows: string[]
    counts: { vehicles: number; pedestrians: number; bicycles: number }
  }
  freight_corridor?: {
    name: string
    truck_share: number
    heavy_trucks: number
    total_vehicles: number
  }
  alerts?: Array<{
    id: number
    ts: string
    level: string
    code: string
    message: string
    acknowledged?: number
  }>
  session_started_at?: string | null
  last_event_at?: string | null
  input_source?: 'camera_stream' | 'local_file'
  source_config?: {
    mode: 'auto' | 'live' | 'stream' | 'file' | 'local'
    local_video_path: string
    local_video_loop: boolean
  }
}

interface SourceConfigResponse {
  mode: 'auto' | 'live' | 'stream' | 'file' | 'local'
  local_video_path: string
  local_video_loop: boolean
  running: boolean
  input_source?: 'camera_stream' | 'local_file'
  alias?: string
  restarted?: boolean
}

const API_BASE = '/api/car-counter'

const emptyStats: CarStats = {
  status: 'idle',
  running: false,
  total: 0,
  heavy_trucks: 0,
  alias: 'ffm0',
  congestion: { score: 0, level: 'low' },
}

const TYPE_ORDER = [
  { key: 'car', label: 'Passenger cars' },
  { key: 'motorcycle', label: 'Motorcycles' },
  { key: 'bicycle', label: 'Bicycles' },
  { key: 'pedestrian', label: 'Pedestrians' },
  { key: 'bus', label: 'Buses' },
  { key: 'truck', label: 'Trucks' },
] as const

function headersFor(role: Role): HeadersInit {
  return {
    'X-Role': role,
    'X-Api-Token': 'internal-demo-token',
    'Content-Type': 'application/json',
  }
}

function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

export default function CarCounter() {
  const [role, setRole] = useState<Role>('internal')
  const [stats, setStats] = useState<CarStats>(emptyStats)
  const [streaming, setStreaming] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(
    'Start a monitoring session to collect live traffic intelligence.'
  )
  const [studyName, setStudyName] = useState('signal-change-study')
  const [studyCompare, setStudyCompare] = useState<any>(null)
  const [incidentKind, setIncidentKind] = useState('stalled_vehicle')
  const [incidentNote, setIncidentNote] = useState('')
  const [incidents, setIncidents] = useState<any[]>([])
  const [sourceMode, setSourceMode] = useState<'auto' | 'live' | 'stream' | 'file' | 'local'>(
    'auto'
  )
  const [localVideoPath, setLocalVideoPath] = useState('')
  const [localVideoLoop, setLocalVideoLoop] = useState(true)
  const [applyingSource, setApplyingSource] = useState(false)

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/stats?role=${role}`, {
        cache: 'no-store',
        headers: headersFor(role),
      })
      if (!res.ok) throw new Error(`Stats failed (${res.status})`)
      const data = (await res.json()) as CarStats
      setStats({ ...emptyStats, ...data })
      if (data.error) setMessage(`Service error: ${data.error}`)
      return data
    } catch {
      setMessage(
        'Unable to reach the analytics service. Confirm the backend is running on port 8000.'
      )
      return null
    }
  }, [role])

  const refreshIncidents = useCallback(async () => {
    if (role !== 'internal') return
    try {
      const res = await fetch(`${API_BASE}/incidents`, { headers: headersFor(role) })
      if (!res.ok) return
      const data = await res.json()
      setIncidents(data.incidents || [])
    } catch {
      /* ignore */
    }
  }, [role])

  const fetchSourceConfig = useCallback(async () => {
    if (role !== 'internal') return
    try {
      const res = await fetch(`${API_BASE}/source`, {
        headers: headersFor(role),
        cache: 'no-store',
      })
      if (!res.ok) return
      const data = (await res.json()) as SourceConfigResponse
      setSourceMode(data.mode)
      setLocalVideoPath(data.local_video_path || '')
      setLocalVideoLoop(Boolean(data.local_video_loop))
    } catch {
      /* ignore */
    }
  }, [role])

  useEffect(() => {
    fetchStats()
    refreshIncidents()
    fetchSourceConfig()
    const id = setInterval(() => {
      fetchStats()
      refreshIncidents()
    }, 2000)
    return () => clearInterval(id)
  }, [fetchStats, refreshIncidents, fetchSourceConfig])

  const postAction = async (path: string, body?: unknown) => {
    setBusy(true)
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: headersFor(role),
        body: body ? JSON.stringify(body) : undefined,
      })
      if (!res.ok) throw new Error(`Request failed (${res.status})`)
      return await res.json()
    } finally {
      setBusy(false)
    }
  }

  const handleStart = async () => {
    try {
      setMessage(
        sourceMode === 'file' || sourceMode === 'local'
          ? 'Opening local video and starting analysis…'
          : 'Connecting to the live camera feed…'
      )
      await postAction('/start')
      setStreaming(true)
      setStreamKey((k) => k + 1)
      setMessage('Monitoring session active.')
    } catch {
      setMessage('Failed to start. Internal role and backend service are required.')
    }
  }

  const handleStop = async () => {
    try {
      await postAction('/stop')
      setStreaming(false)
      setMessage('Session stopped. Metrics are retained until reset.')
    } catch {
      setMessage('Failed to stop the session.')
    }
  }

  const handleReset = async () => {
    try {
      await postAction('/reset')
      setMessage('Session metrics cleared.')
    } catch {
      setMessage('Failed to reset metrics.')
    }
  }

  const handleApplySource = async () => {
    if ((sourceMode === 'file' || sourceMode === 'local') && !localVideoPath.trim()) {
      setMessage('Please enter a local video path before applying Local File mode.')
      return
    }
    setApplyingSource(true)
    try {
      const res = await fetch(`${API_BASE}/source`, {
        method: 'POST',
        headers: headersFor(role),
        body: JSON.stringify({
          mode: sourceMode,
          local_video_path: localVideoPath,
          local_video_loop: localVideoLoop,
          restart_if_running: true,
        }),
      })
      if (!res.ok) {
        throw new Error(`Failed (${res.status})`)
      }
      const data = (await res.json()) as SourceConfigResponse
      setStreaming(Boolean(data.running))
      if (data.running) {
        setStreamKey((k) => k + 1)
      }
      setMessage(
        data.restarted
          ? 'Source updated and session restarted with new input.'
          : 'Source updated. Start a session to begin analysis.'
      )
      fetchStats()
      fetchSourceConfig()
    } catch {
      setMessage(
        'Could not apply source settings. Check local path and ensure backend can read the file.'
      )
    } finally {
      setApplyingSource(false)
    }
  }

  const download = (path: string, filename: string) => {
    const a = document.createElement('a')
    a.href = `${API_BASE}${path}`
    a.download = filename
    // browser will still need headers — use fetch blob for auth headers
    fetch(`${API_BASE}${path}`, { headers: headersFor(role) })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob)
        a.href = url
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch(() => setMessage('Export failed. Internal access required.'))
  }

  const saveStudy = async (phase: 'before' | 'after') => {
    try {
      await postAction('/studies', { name: studyName, phase })
      setMessage(`Saved “${studyName}” ${phase} snapshot.`)
    } catch {
      setMessage('Failed to save study snapshot.')
    }
  }

  const compareStudy = async () => {
    try {
      const res = await fetch(
        `${API_BASE}/studies/${encodeURIComponent(studyName)}/compare`,
        { headers: headersFor(role) }
      )
      if (!res.ok) throw new Error('compare failed')
      setStudyCompare(await res.json())
    } catch {
      setMessage('Study comparison failed. Save both before and after snapshots first.')
    }
  }

  const submitIncident = async () => {
    try {
      await postAction('/incidents', { kind: incidentKind, note: incidentNote })
      setIncidentNote('')
      setMessage('Incident recorded.')
      refreshIncidents()
    } catch {
      setMessage('Failed to record incident.')
    }
  }

  const emailReport = async () => {
    try {
      const result = await postAction('/export/email', { period: 'daily' })
      setMessage(
        result.sent
          ? `Report emailed to ${(result.recipients || []).join(', ')}`
          : result.reason || 'Email not configured.'
      )
    } catch {
      setMessage('Email request failed.')
    }
  }

  const ackAlert = async (id: number) => {
    try {
      await postAction(`/alerts/${id}/ack`)
      fetchStats()
    } catch {
      setMessage('Failed to acknowledge alert.')
    }
  }

  const hourlyEntries = useMemo(() => {
    return Object.entries(stats.hourly || {})
      .map(([hour, count]) => ({ hour, count: Number(count) }))
      .filter((e) => e.count > 0)
      .sort((a, b) => a.hour.localeCompare(b.hour))
  }, [stats.hourly])

  const maxHourly = Math.max(1, ...hourlyEntries.map((e) => e.count), 1)
  const statusClass =
    stats.status === 'error'
      ? 'error'
      : streaming || stats.running
        ? 'detecting'
        : 'success'

  const isInternal = role === 'internal'

  return (
    <div>
      <div className="role-bar">
        <span className="role-label">Access mode</span>
        <button
          type="button"
          className={`tab-button ${role === 'public' ? 'active' : ''}`}
          onClick={() => setRole('public')}
        >
          Public
        </button>
        <button
          type="button"
          className={`tab-button ${role === 'internal' ? 'active' : ''}`}
          onClick={() => setRole('internal')}
        >
          Internal
        </button>
      </div>

      <p className="panel-intro">
        Government traffic intelligence for <strong>{stats.corridor || stats.alias}</strong>.
        Public mode shows summary metrics; internal mode enables operations, exports, and alerts.
      </p>

      {isInternal && (
        <div className="analytics-card source-config-card">
          <h4>Video source</h4>
          <p className="analytics-detail">
            Choose where frames come from. You can switch between live stream and a downloaded
            local file without manual backend restarts.
          </p>
          <div className="study-row">
            <label className="source-label" htmlFor="sourceMode">
              Source mode
            </label>
            <select
              id="sourceMode"
              className="text-input"
              value={sourceMode}
              onChange={(e) =>
                setSourceMode(
                  e.target.value as 'auto' | 'live' | 'stream' | 'file' | 'local'
                )
              }
              disabled={busy || applyingSource}
            >
              <option value="auto">Auto (use local if path is set)</option>
              <option value="live">Live camera stream</option>
              <option value="file">Local video file</option>
            </select>
          </div>
          {(sourceMode === 'auto' || sourceMode === 'file' || sourceMode === 'local') && (
            <div className="study-row source-path-row">
              <label className="source-label" htmlFor="localVideoPath">
                Local file path
              </label>
              <input
                id="localVideoPath"
                className="text-input grow"
                value={localVideoPath}
                onChange={(e) => setLocalVideoPath(e.target.value)}
                placeholder="/Users/you/Videos/traffic-sample.mp4"
                disabled={busy || applyingSource}
              />
            </div>
          )}
          <div className="study-row source-loop-row">
            <label className="source-check-row">
              <input
                type="checkbox"
                checked={localVideoLoop}
                onChange={(e) => setLocalVideoLoop(e.target.checked)}
                disabled={busy || applyingSource}
              />
              Loop local video when it reaches the end
            </label>
          </div>
          <div className="study-row source-actions-row">
            <button
              className="button"
              onClick={handleApplySource}
              disabled={busy || applyingSource}
            >
              {applyingSource ? 'Applying...' : 'Apply source settings'}
            </button>
            <span className="analytics-detail muted">
              Current input: {stats.input_source === 'local_file' ? 'Local file' : 'Live stream'}
            </span>
          </div>
        </div>
      )}

      {isInternal && (
        <div className="controls">
          <button className="button" onClick={handleStart} disabled={busy || streaming}>
            Start session
          </button>
          <button
            className="button button-secondary"
            onClick={handleStop}
            disabled={busy || !streaming}
          >
            Stop session
          </button>
          <button className="button button-secondary" onClick={handleReset} disabled={busy}>
            Reset metrics
          </button>
          <button
            className="button button-secondary"
            onClick={() => download('/export/csv', 'traffic-export.csv')}
            disabled={busy}
          >
            Export CSV
          </button>
          <button
            className="button button-secondary"
            onClick={() => download('/export/pdf?period=daily', 'traffic-daily.pdf')}
            disabled={busy}
          >
            Daily PDF
          </button>
          <button
            className="button button-secondary"
            onClick={() => download('/export/pdf?period=weekly', 'traffic-weekly.pdf')}
            disabled={busy}
          >
            Weekly PDF
          </button>
          <button className="button button-secondary" onClick={emailReport} disabled={busy}>
            Email planners
          </button>
        </div>
      )}

      <div className={`status ${statusClass}`}>{message}</div>

      <div className="car-stats-grid">
        <div className="car-stat-card">
          <span className="car-stat-label">Total vehicles</span>
          <span className="car-stat-value">{stats.total}</span>
          <span className="car-stat-sub">Unique intersection entries</span>
        </div>
        <div className="car-stat-card">
          <span className="car-stat-label">Congestion score</span>
          <span className="car-stat-value">{stats.congestion?.score ?? 0}</span>
          <span className="car-stat-sub">{stats.congestion?.level || 'low'}</span>
        </div>
        <div className="car-stat-card">
          <span className="car-stat-label">Heavy trucks</span>
          <span className="car-stat-value">{stats.heavy_trucks ?? 0}</span>
        </div>
        <div className="car-stat-card">
          <span className="car-stat-label">Camera health</span>
          <span className="car-stat-value cam-status">
            {stats.camera_health?.status || '—'}
          </span>
        </div>
      </div>

      {isInternal && (
        <>
          <div className="car-stats-grid">
            <div className="car-stat-card">
              <span className="car-stat-label">Vehicles / minute</span>
              <span className="car-stat-value">
                {stats.congestion?.vehicles_per_minute ?? 0}
              </span>
            </div>
            <div className="car-stat-card">
              <span className="car-stat-label">Queue length</span>
              <span className="car-stat-value">{stats.congestion?.queue_length ?? 0}</span>
            </div>
            <div className="car-stat-card">
              <span className="car-stat-label">Near-miss events</span>
              <span className="car-stat-value">
                {stats.conflicts?.near_miss_count ?? 0}
              </span>
            </div>
            <div className="car-stat-card">
              <span className="car-stat-label">Pedestrians (session)</span>
              <span className="car-stat-value">{stats.pedestrians ?? 0}</span>
            </div>
          </div>

          <h3 className="car-section-title">Classification & multimodal counts</h3>
          <div className="car-stats-grid car-type-grid-6">
            {TYPE_ORDER.map((type) => (
              <div key={type.key} className="car-stat-card">
                <span className="car-stat-label">{type.label}</span>
                <span className="car-stat-value">
                  {stats.by_type?.[type.key] ?? 0}
                </span>
              </div>
            ))}
          </div>

          <h3 className="car-section-title">Speed estimate bands (planning-grade)</h3>
          <div className="car-stats-grid">
            {(['slow', 'normal', 'fast'] as const).map((band) => (
              <div key={band} className="car-stat-card">
                <span className="car-stat-label">{band}</span>
                <span className="car-stat-value">
                  {stats.speed_bands?.[band] ?? 0}
                </span>
              </div>
            ))}
            <div className="car-stat-card">
              <span className="car-stat-label">Peak traffic hour</span>
              <span className="car-stat-value small-metric">
                {stats.peak_hour?.label || '—'}
              </span>
              <span className="car-stat-sub">
                {stats.peak_hour?.count
                  ? `${stats.peak_hour.count} vehicles`
                  : 'Awaiting data'}
              </span>
            </div>
          </div>
        </>
      )}

      <h3 className="car-section-title">Freight corridor</h3>
      <div className="analytics-card">
        <p className="analytics-metric">
          {stats.freight_corridor?.name || stats.corridor || stats.alias}
        </p>
        <p className="analytics-detail">
          Heavy trucks: {stats.freight_corridor?.heavy_trucks ?? stats.heavy_trucks ?? 0}
          {typeof stats.freight_corridor?.truck_share === 'number'
            ? ` · truck share ${(stats.freight_corridor.truck_share * 100).toFixed(1)}%`
            : ''}
        </p>
      </div>

      {isInternal && (
        <>
          <h3 className="car-section-title">School-zone hours</h3>
          <div className="analytics-card">
            <p className="analytics-detail">
              Windows: {(stats.school_zone?.windows || []).join(', ') || '—'}
            </p>
            <p className="analytics-detail">
              Vehicles: {stats.school_zone?.counts?.vehicles ?? 0} · Pedestrians:{' '}
              {stats.school_zone?.counts?.pedestrians ?? 0} · Bicycles:{' '}
              {stats.school_zone?.counts?.bicycles ?? 0}
            </p>
          </div>

          <h3 className="car-section-title">Alerts</h3>
          <div className="analytics-card">
            {(stats.alerts || []).length === 0 ? (
              <p className="analytics-detail">No active alerts.</p>
            ) : (
              <ul className="alert-list">
                {(stats.alerts || []).map((a) => (
                  <li key={a.id}>
                    <strong>[{a.level}]</strong> {a.message}
                    <button
                      type="button"
                      className="linkish"
                      onClick={() => ackAlert(a.id)}
                    >
                      Acknowledge
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <h3 className="car-section-title">Before / after study</h3>
          <div className="analytics-card study-row">
            <input
              className="text-input"
              value={studyName}
              onChange={(e) => setStudyName(e.target.value)}
              placeholder="Study name"
            />
            <button className="button button-secondary" onClick={() => saveStudy('before')}>
              Save before
            </button>
            <button className="button button-secondary" onClick={() => saveStudy('after')}>
              Save after
            </button>
            <button className="button" onClick={compareStudy}>
              Compare
            </button>
          </div>
          {studyCompare && (
            <div className="analytics-card">
              <p className="analytics-detail">
                Complete: {studyCompare.complete ? 'yes' : 'no (need before & after)'}
              </p>
              {studyCompare.complete && (
                <>
                  <p className="analytics-detail">
                    Delta total vehicles: {studyCompare.delta_total}
                  </p>
                  <p className="analytics-detail">
                    Delta heavy trucks: {studyCompare.delta_heavy_trucks}
                  </p>
                </>
              )}
            </div>
          )}

          <h3 className="car-section-title">Incident tagging</h3>
          <div className="analytics-card study-row">
            <select
              className="text-input"
              value={incidentKind}
              onChange={(e) => setIncidentKind(e.target.value)}
            >
              <option value="stalled_vehicle">Stalled vehicle</option>
              <option value="crash">Crash</option>
              <option value="roadwork">Roadwork</option>
              <option value="debris">Debris</option>
              <option value="other">Other</option>
            </select>
            <input
              className="text-input grow"
              value={incidentNote}
              onChange={(e) => setIncidentNote(e.target.value)}
              placeholder="Optional note"
            />
            <button className="button" onClick={submitIncident}>
              Record
            </button>
          </div>
          <div className="analytics-card">
            {incidents.length === 0 ? (
              <p className="analytics-detail">No incidents recorded this session.</p>
            ) : (
              <ul className="alert-list">
                {incidents.slice(0, 8).map((inc) => (
                  <li key={inc.id}>
                    <strong>{inc.kind}</strong> — {inc.note || 'No note'}{' '}
                    <span className="muted">({formatTime(inc.ts)})</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {isInternal && hourlyEntries.length > 0 && (
        <div className="hourly-chart">
          <h4>Vehicles by hour of day</h4>
          <div className="hourly-bars">
            {hourlyEntries.map((entry) => (
              <div key={entry.hour} className="hourly-bar-row">
                <span className="hourly-label">{entry.hour}:00</span>
                <div className="hourly-bar-track">
                  <div
                    className="hourly-bar-fill"
                    style={{ width: `${(entry.count / maxHourly) * 100}%` }}
                  />
                </div>
                <span className="hourly-count">{entry.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {isInternal && (
        <div className="preview-container car-stream-preview">
          {streaming ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={streamKey}
              src={`${API_BASE}/stream?t=${streamKey}`}
              alt="Live annotated traffic stream"
            />
          ) : (
            <div className="car-stream-placeholder">
              Live annotated video appears here when a session is running.
            </div>
          )}
        </div>
      )}

      <div className="detection-info">
        <h3>Service status</h3>
        <p>State: {stats.status}</p>
        <p>Processing: {stats.running ? 'active' : 'idle'}</p>
        <p>Access: {role}</p>
        {isInternal && (
          <p>
            Source: {stats.input_source === 'local_file' ? 'Local file' : 'Live stream'} ({stats.alias})
          </p>
        )}
        {isInternal && (
          <>
            <p>Session started: {formatTime(stats.session_started_at)}</p>
            <p>Last count: {formatTime(stats.last_event_at)}</p>
          </>
        )}
      </div>
    </div>
  )
}
