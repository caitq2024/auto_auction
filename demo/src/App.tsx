import { useEffect, useMemo, useState } from 'react'

import { Leaderboard } from './components/Leaderboard'
import { LLMTrace } from './components/LLMTrace'
import { Replay } from './components/Replay'
import type { DemoData } from './lib/types'

const SERIES = ['#2a78d6', '#eb6834', '#1baf7a'] // validated categorical slots 1-3

export default function App() {
  const [data, setData] = useState<DemoData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [compKey, setCompKey] = useState<string>('')

  useEffect(() => {
    fetch('./demo_data.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: DemoData) => {
        setData(d)
        setCompKey(d.comparisons[0]?.key ?? '')
      })
      .catch((e) => setError(String(e)))
  }, [])

  const comp = data?.comparisons.find((c) => c.key === compKey) ?? data?.comparisons[0]

  // color follows the entity across scenario switches (never repainted by rank)
  const colorOf = useMemo(() => {
    const ids = new Map<string, string>()
    let i = 0
    for (const c of data?.comparisons ?? []) {
      for (const cand of c.candidates) {
        const family = cand.name // stable display identity across scenarios
        if (!ids.has(family)) ids.set(family, SERIES[i++ % SERIES.length])
      }
    }
    return (id: string) => {
      const cand = data?.comparisons.flatMap((c) => c.candidates).find((x) => x.id === id)
      return ids.get(cand?.name ?? id) ?? SERIES[0]
    }
  }, [data])

  if (error)
    return (
      <div style={{ padding: 40 }}>
        加载失败：{error}（需先运行 scripts/export_demo.py 生成 demo_data.json）
      </div>
    )
  if (!data || !comp) return <div style={{ padding: 40, color: 'var(--text-muted)' }}>加载中…</div>

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', padding: '0 20px 60px' }}>
      <header style={{ padding: '18px 0 14px', display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>AdSim 竞价策略实验台</h1>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          AuctionNet 市场 · 48 广告主 · 3 坑位 GSP · simulated results only
        </span>
        <span style={{ flex: 1 }} />
        <div style={{ display: 'flex', gap: 6 }}>
          {data.comparisons.map((c) => (
            <button key={c.key} className={`tab-btn${c.key === comp.key ? ' active' : ''}`} onClick={() => setCompKey(c.key)}>
              {c.label}
            </button>
          ))}
        </div>
      </header>

      <div style={{ display: 'grid', gap: 20 }}>
        <Leaderboard comp={comp} colorOf={colorOf} />
        <Replay comp={comp} colorOf={colorOf} />
        <LLMTrace runs={data.llm_runs} />
      </div>

      <footer style={{ marginTop: 28, color: 'var(--text-muted)', fontSize: 12 }}>
        数据源：auction-sim-platform 实验产物（parquet / 轨迹 JSONL），由 scripts/export_demo.py
        聚合。所有指标为模拟器结果，未经客户数据校准，不代表真实广告平台收益。
      </footer>
    </div>
  )
}
