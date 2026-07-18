'use client'

import CarCounter from '@/components/CarCounter'

export default function Home() {
  return (
    <div className="container">
      <header className="header">
        <h1>Traffic Intelligence</h1>
        <p>
          Congestion, freight, safety conflicts, school-zone volumes, and planning exports
        </p>
      </header>

      <div className="main-content car-counter-layout">
        <div className="card">
          <h2>Operations dashboard</h2>
          <CarCounter />
        </div>
      </div>
    </div>
  )
}
