import React from 'react'
import { createRoot } from 'react-dom/client'

function App() {
  return (
    <main style={{ fontFamily: 'system-ui', margin: '2rem auto', maxWidth: 720 }}>
      <h1>mqttstat frontend</h1>
      <p>React client is up.</p>
      <ul>
        <li>Frontend URL: <code>http://localhost:5173</code></li>
        <li>Backend URL: <code>http://localhost:8000</code></li>
        <li>API health: <code>http://localhost:8000/health</code></li>
      </ul>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
