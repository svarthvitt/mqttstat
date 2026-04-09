import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const PRESET_RANGES = [
  { label: '1h', hours: 1 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 24 * 7 },
  { label: '30d', hours: 24 * 30 },
]

function toInputValue(date) {
  const pad = (value) => String(value).padStart(2, '0')
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}T${pad(local.getHours())}:${pad(local.getMinutes())}`
}

function buildRange(hours) {
  const to = new Date()
  const from = new Date(to.getTime() - hours * 60 * 60 * 1000)
  return { from: toInputValue(from), to: toInputValue(to) }
}

async function fetchJson(path, params = {}) {
  const url = new URL(path, API_BASE)
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value)
    }
  })

  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`API request failed (${response.status})`)
  }
  return response.json()
}

function LoadingState({ label }) {
  return <div className="state">Loading {label}…</div>
}

function ErrorState({ message }) {
  return <div className="state error">{message}</div>
}

function EmptyState({ label }) {
  return <div className="state">No {label} available for this range.</div>
}

function StatCard({ title, value, hint }) {
  return (
    <article className="stat-card">
      <h3>{title}</h3>
      <p>{value ?? '—'}</p>
      {hint ? <small>{hint}</small> : null}
    </article>
  )
}

function valueOrDash(value, decimals = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  return Number(value).toFixed(decimals)
}

function formatChange(trendValue) {
  if (trendValue === null || trendValue === undefined || Number.isNaN(Number(trendValue))) {
    return '—'
  }
  const num = Number(trendValue)
  const emoji = num > 0 ? '↗' : num < 0 ? '↘' : '→'
  return `${emoji} ${num.toFixed(2)}%`
}

function LineChart({ series }) {
  const width = 900
  const height = 260
  const padding = 24

  const pointsBySeries = useMemo(() => {
    if (!series.length) return []
    const all = series.flatMap((s) => s.points)
    if (!all.length) return []

    const timestamps = all.map((point) => new Date(point.ts).getTime())
    const values = all.map((point) => Number(point.value))
    const minX = Math.min(...timestamps)
    const maxX = Math.max(...timestamps)
    const minY = Math.min(...values)
    const maxY = Math.max(...values)

    return series.map((entry) => {
      const line = entry.points
        .map((point) => {
          const xRaw = new Date(point.ts).getTime()
          const yRaw = Number(point.value)
          const x = maxX === minX
            ? width / 2
            : padding + ((xRaw - minX) / (maxX - minX)) * (width - padding * 2)
          const y = maxY === minY
            ? height / 2
            : height - padding - ((yRaw - minY) / (maxY - minY)) * (height - padding * 2)
          return `${x},${y}`
        })
        .join(' ')

      return { ...entry, line }
    })
  }, [series])

  if (!pointsBySeries.length) {
    return <EmptyState label="chart points" />
  }

  return (
    <div className="chart-container">
      <svg viewBox={`0 0 ${width} ${height}`} className="chart" role="img" aria-label="Metric history chart">
        <rect x="0" y="0" width={width} height={height} fill="transparent" />
        {pointsBySeries.map((entry, index) => (
          <polyline
            key={entry.id}
            points={entry.line}
            fill="none"
            stroke={entry.color}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={index === 0 ? 1 : 0.9}
          />
        ))}
      </svg>
      <ul className="legend">
        {pointsBySeries.map((entry) => (
          <li key={entry.id}>
            <span style={{ backgroundColor: entry.color }} />
            {entry.label}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Dashboard() {
  const [range, setRange] = useState(() => buildRange(24))
  const [dashboard, setDashboard] = useState({ data: null, loading: true, error: null })
  const [topics, setTopics] = useState({ data: [], loading: true, error: null })
  const [selectedSeries, setSelectedSeries] = useState([])
  const [seriesData, setSeriesData] = useState({ data: [], loading: false, error: null })

  useEffect(() => {
    let cancelled = false
    setDashboard((prev) => ({ ...prev, loading: true, error: null }))
    fetchJson('/api/dashboard', { from: range.from, to: range.to })
      .then((data) => {
        if (!cancelled) {
          setDashboard({ data, loading: false, error: null })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setDashboard({ data: null, loading: false, error: error.message })
        }
      })
    return () => {
      cancelled = true
    }
  }, [range])

  useEffect(() => {
    let cancelled = false
    fetchJson('/api/topics')
      .then((data) => {
        if (!cancelled) {
          setTopics({ data: data.topics || [], loading: false, error: null })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setTopics({ data: [], loading: false, error: error.message })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedSeries.length) {
      setSeriesData({ data: [], loading: false, error: null })
      return
    }

    let cancelled = false
    setSeriesData({ data: [], loading: true, error: null })
    fetchJson('/api/timeseries', {
      from: range.from,
      to: range.to,
      series: selectedSeries.join(','),
    })
      .then((data) => {
        if (!cancelled) {
          setSeriesData({ data: data.series || [], loading: false, error: null })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSeriesData({ data: [], loading: false, error: error.message })
        }
      })

    return () => {
      cancelled = true
    }
  }, [selectedSeries, range])

  const cards = dashboard.data?.cards || []

  return (
    <div className="page">
      <header className="topbar">
        <h1>mqttstat dashboard</h1>
        <a href="#/" className="nav-link">Dashboard</a>
      </header>

      <section className="panel filters">
        <div className="filter-row">
          <label>
            From
            <input type="datetime-local" value={range.from} onChange={(event) => setRange((prev) => ({ ...prev, from: event.target.value }))} />
          </label>
          <label>
            To
            <input type="datetime-local" value={range.to} onChange={(event) => setRange((prev) => ({ ...prev, to: event.target.value }))} />
          </label>
        </div>
        <div className="preset-row">
          {PRESET_RANGES.map((preset) => (
            <button key={preset.label} type="button" onClick={() => setRange(buildRange(preset.hours))}>{preset.label}</button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Summary</h2>
        {dashboard.loading ? <LoadingState label="dashboard" /> : null}
        {dashboard.error ? <ErrorState message={dashboard.error} /> : null}
        {!dashboard.loading && !dashboard.error ? (
          cards.length ? (
            <div className="stats-grid">
              {cards.map((card) => (
                <StatCard key={card.key} title={card.label} value={card.value} hint={card.hint} />
              ))}
            </div>
          ) : (
            <EmptyState label="summary stats" />
          )
        ) : null}
      </section>

      <section className="panel">
        <h2>Line charts</h2>
        {topics.loading ? <LoadingState label="topics" /> : null}
        {topics.error ? <ErrorState message={topics.error} /> : null}
        {!topics.loading && !topics.error ? (
          topics.data.length ? (
            <div className="topic-list">
              {topics.data.map((topic) => (
                <label key={`${topic.topic}:${topic.metric}`}>
                  <input
                    type="checkbox"
                    checked={selectedSeries.includes(topic.id)}
                    onChange={(event) => {
                      setSelectedSeries((prev) => {
                        if (event.target.checked) {
                          return [...prev, topic.id]
                        }
                        return prev.filter((value) => value !== topic.id)
                      })
                    }}
                  />
                  <span>{topic.topic} / {topic.metric}</span>
                  <a href={`#/topics/${encodeURIComponent(topic.topic)}?metric=${encodeURIComponent(topic.metric)}`}>Details</a>
                </label>
              ))}
            </div>
          ) : <EmptyState label="topics" />
        ) : null}

        {seriesData.loading ? <LoadingState label="chart data" /> : null}
        {seriesData.error ? <ErrorState message={seriesData.error} /> : null}
        {!seriesData.loading && !seriesData.error ? <LineChart series={seriesData.data} /> : null}
      </section>

      <section className="panel">
        <h2>Core KPIs</h2>
        <div className="stats-grid">
          <StatCard title="Latest" value={valueOrDash(dashboard.data?.kpis?.latest)} />
          <StatCard title="Min" value={valueOrDash(dashboard.data?.kpis?.min)} />
          <StatCard title="Max" value={valueOrDash(dashboard.data?.kpis?.max)} />
          <StatCard title="Average" value={valueOrDash(dashboard.data?.kpis?.avg)} />
          <StatCard title="Count" value={dashboard.data?.kpis?.count ?? '—'} />
          <StatCard title="Trend" value={formatChange(dashboard.data?.kpis?.trend_pct)} />
        </div>
      </section>
    </div>
  )
}

function TopicDetailPage({ topic, metric }) {
  const [range, setRange] = useState(() => buildRange(24 * 7))
  const [state, setState] = useState({ data: null, loading: true, error: null })

  useEffect(() => {
    let cancelled = false
    setState({ data: null, loading: true, error: null })
    fetchJson(`/api/topics/${encodeURIComponent(topic)}`, {
      from: range.from,
      to: range.to,
      metric,
    })
      .then((data) => {
        if (!cancelled) {
          setState({ data, loading: false, error: null })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ data: null, loading: false, error: error.message })
        }
      })
    return () => {
      cancelled = true
    }
  }, [topic, metric, range])

  const series = state.data?.series ? [state.data.series] : []
  const summary = state.data?.summary || {}

  return (
    <div className="page">
      <header className="topbar">
        <h1>{topic}</h1>
        <a href="#/" className="nav-link">← Back to dashboard</a>
      </header>

      <section className="panel filters">
        <p><strong>Metric:</strong> {metric || 'all metrics'}</p>
        <div className="preset-row">
          {PRESET_RANGES.map((preset) => (
            <button key={preset.label} type="button" onClick={() => setRange(buildRange(preset.hours))}>{preset.label}</button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Historical chart</h2>
        {state.loading ? <LoadingState label="topic history" /> : null}
        {state.error ? <ErrorState message={state.error} /> : null}
        {!state.loading && !state.error ? <LineChart series={series} /> : null}
      </section>

      <section className="panel">
        <h2>Summary stats</h2>
        {state.loading ? null : (
          <div className="stats-grid">
            <StatCard title="Latest" value={valueOrDash(summary.latest)} />
            <StatCard title="Min" value={valueOrDash(summary.min)} />
            <StatCard title="Max" value={valueOrDash(summary.max)} />
            <StatCard title="Average" value={valueOrDash(summary.avg)} />
            <StatCard title="Count" value={summary.count ?? '—'} />
            <StatCard title="Trend" value={formatChange(summary.trend_pct)} />
          </div>
        )}
      </section>
    </div>
  )
}

function parseRoute() {
  const [pathPart, queryPart] = window.location.hash.replace(/^#/, '').split('?')
  const path = pathPart || '/'
  const query = new URLSearchParams(queryPart || '')

  if (path.startsWith('/topics/')) {
    const topic = decodeURIComponent(path.replace('/topics/', ''))
    const metric = query.get('metric')
    return { page: 'topic', topic, metric }
  }

  return { page: 'dashboard' }
}

function AppRouter() {
  const [route, setRoute] = useState(parseRoute)

  useEffect(() => {
    const onChange = () => setRoute(parseRoute())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  if (route.page === 'topic') {
    return <TopicDetailPage topic={route.topic} metric={route.metric} />
  }

  return <Dashboard />
}

createRoot(document.getElementById('root')).render(<AppRouter />)
