import { useState } from 'react'

import type { Comparison } from '../lib/types'
import { LineChart, type Series } from './LineChart'

export function Replay({ comp, colorOf }: { comp: Comparison; colorOf: (id: string) => string }) {
  const episodes = comp.candidates[0]?.episodes.map((e) => e.episode) ?? []
  const [ep, setEp] = useState(episodes[0] ?? 0)

  const mk = (pick: (t: import('../lib/types').TickSeries) => (number | null)[]): Series[] =>
    comp.candidates.map((c) => {
      const e = c.episodes.find((x) => x.episode === ep)
      return { name: c.name, color: colorOf(c.id), values: e ? pick(e.ticks) : [] }
    })

  const x = comp.candidates[0]?.episodes.find((e) => e.episode === ep)?.ticks.tick ?? []

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>Episode 回放（48 tick）</h2>
        <div style={{ display: 'flex', gap: 6 }}>
          {episodes.map((e) => (
            <button key={e} className={`tab-btn${e === ep ? ' active' : ''}`} onClick={() => setEp(e)}>
              Episode {e}
            </button>
          ))}
        </div>
      </div>
      <div style={{ display: 'grid', gap: 20 }}>
        <LineChart title="出价系数 alpha（每 tick 的决策）" x={x} series={mk((t) => t.alpha)} />
        <LineChart title="累计花费" x={x} series={mk((t) => t.cum_cost)} formatY={(v) => v.toLocaleString()} />
        <LineChart title="累计转化" x={x} series={mk((t) => t.cum_conversions)} />
        <LineChart title="每 tick 赢得曝光数" x={x} series={mk((t) => t.win_pv)} />
      </div>
    </div>
  )
}
