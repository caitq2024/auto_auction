import { useEffect, useMemo, useState } from 'react'

import { Explainer } from './components/Explainer'
import { Leaderboard } from './components/Leaderboard'
import { LLMTrace } from './components/LLMTrace'
import { Replay } from './components/Replay'
import { RunExperiment, type ExperimentResult } from './components/RunExperiment'
import type { Candidate, DemoData } from './lib/types'

// categorical slots 1-3 (validated); LLM strategies get slot-4 yellow with
// direct labels/legend always present as the secondary channel
// baseline series colors; violet #4a3aa7 is RESERVED for user experiments
// 7 slots from the validated 8-hue palette (violet #4a3aa7 stays reserved
// for user experiments); board now has 7 strategy families — no modulo reuse
const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#e34948']

export default function App() {
  const [data, setData] = useState<DemoData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [compKey, setCompKey] = useState<string>('')
  // user-launched experiments, keyed by target comparison
  const [userRuns, setUserRuns] = useState<{ compKey: string; candidate: Candidate }[]>([])

  useEffect(() => {
    fetch('./demo_data.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: DemoData) => {
        setData(d)
        setCompKey(d.comparisons[0]?.key ?? '')
      })
      .catch((e) => setError(String(e)))
  }, [])

  const baseComp = data?.comparisons.find((c) => c.key === compKey) ?? data?.comparisons[0]

  // splice user experiments into the current comparison (nearest pv scale:
  // >=200k joins the 500k board, else the 50k board), re-ranked by score
  const comp = useMemo(() => {
    if (!baseComp) return baseComp
    const extra = userRuns.filter((r) => r.compKey === baseComp.key).map((r) => r.candidate)
    if (!extra.length) return baseComp
    return {
      ...baseComp,
      candidates: [...baseComp.candidates, ...extra].sort((a, b) => b.score_mean - a.score_mean),
    }
  }, [baseComp, userRuns])

  const onExperimentResult = (r: ExperimentResult) => {
    const targetKey = r.pv_num >= 200000 ? 'fullscale_500k' : 'midscale_50k'
    const candidate: Candidate = {
      id: `user_${r.model}_${Date.now()}`,
      name: `⭐ 你的实验 · ${r.model}${r.custom_prompt ? ' (改版prompt)' : ''}`,
      score_mean: r.score_mean,
      conversions_mean: r.episodes.reduce((s, e) => s + e.conversions, 0) / r.episodes.length,
      actual_cpa_mean: r.episodes.reduce((s, e) => s + e.actual_cpa, 0) / r.episodes.length,
      budget_utilization_mean:
        r.episodes.reduce((s, e) => s + e.budget_utilization, 0) / r.episodes.length,
      episodes: r.episodes.map((e) => ({
        episode: e.episode,
        score: e.score,
        conversions: e.conversions,
        cost: e.cost,
        actual_cpa: e.actual_cpa,
        budget_utilization: e.budget_utilization,
        ticks: e.ticks,
      })),
    }
    setUserRuns((prev) => [...prev, { compKey: targetKey, candidate }])
    setCompKey(targetKey)
  }

  // color follows the entity across scenario switches (never repainted by
  // rank); variants of one strategy ("DT (自训 500k/50k)") share a family slot
  const colorOf = useMemo(() => {
    const family = (name: string) => name.split(' ')[0] + (name.startsWith('LLM') ? ` ${name.split(' ')[1]}` : '')
    const ids = new Map<string, string>()
    let i = 0
    for (const c of data?.comparisons ?? []) {
      for (const cand of c.candidates) {
        const f = family(cand.name)
        if (!ids.has(f)) ids.set(f, SERIES[i++ % SERIES.length])
      }
    }
    return (id: string) => {
      if (id.startsWith('user_')) return '#4a3aa7' // user runs: violet, reserved — never assigned to baselines
      const cand = data?.comparisons.flatMap((c) => c.candidates).find((x) => x.id === id)
      return ids.get(family(cand?.name ?? id)) ?? SERIES[0]
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
          <a href="./harness.html" className="tab-btn" style={{ textDecoration: 'none' }}>
            ☁️ AWS Harness 版 →
          </a>
        </div>
      </header>

      <div style={{ display: 'grid', gap: 20 }}>
        <Explainer samples={data.sample_rows ?? []} />
        <Leaderboard comp={comp} colorOf={colorOf} />
        <RunExperiment onResult={onExperimentResult} />
        <Replay comp={comp} colorOf={colorOf} />
        <LLMTrace runs={data.llm_runs} />
      </div>

      <footer style={{ marginTop: 28, color: 'var(--text-muted)', fontSize: 12 }}>
        数据源：auction-sim-platform 实验产物（parquet / 轨迹 JSONL），由 scripts/export_demo.py
        聚合。所有指标为模拟器结果，未经客户数据校准，不代表真实广告平台收益。想动手？
        <a href="https://github.com/caitq2024/auto_auction/tree/main/notebooks" target="_blank" rel="noreferrer" style={{ color: 'inherit' }}>
          教学 notebook：从看懂数据到亲手实现 PID / IQL / DT / LLM 四种策略 →
        </a>
      </footer>
    </div>
  )
}
