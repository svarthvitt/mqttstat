import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function App() {
  const [metrics, setMetrics] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchMetrics = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/metrics`)
      if (!response.ok) {
        throw new Error('Failed to fetch metrics')
      }
      const data = await response.json()
      setMetrics(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchMetrics()
    const interval = setInterval(fetchMetrics, 5000)
    return () => clearInterval(interval)
  }, [])

  return (
    <main style={{ fontFamily: 'system-ui', margin: '2rem auto', maxWidth: 800, padding: '0 1rem' }}>
      <h1>mqttstat dashboard</h1>

      <section>
        <h2>Recent Metrics</h2>
        {loading && <p>Loading metrics...</p>}
        {error && <p style={{ color: 'red' }}>Error: {error}</p>}
        {!loading && !error && metrics.length === 0 && <p>No metrics ingested yet.</p>}

        {!loading && metrics.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #ccc', textAlign: 'left' }}>
                <th style={{ padding: '0.5rem' }}>Time</th>
                <th style={{ padding: '0.5rem' }}>Topic</th>
                <th style={{ padding: '0.5rem' }}>Key</th>
                <th style={{ padding: '0.5rem' }}>Value</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={{ padding: '0.5rem', fontSize: '0.9rem' }}>
                    {new Date(m.observed_at).toLocaleTimeString()}
                  </td>
                  <td style={{ padding: '0.5rem' }}><code>{m.topic}</code></td>
                  <td style={{ padding: '0.5rem' }}>{m.metric_key}</td>
                  <td style={{ padding: '0.5rem', fontWeight: 'bold' }}>{m.numeric_value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <footer style={{ marginTop: '3rem', fontSize: '0.8rem', color: '#666', borderTop: '1px solid #eee', paddingTop: '1rem' }}>
        <p>Backend API: <code>{API_BASE_URL}</code></p>
      </footer>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
