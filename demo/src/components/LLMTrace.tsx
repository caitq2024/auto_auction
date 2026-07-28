import { useState } from 'react'

import type { LLMRun } from '../lib/types'

function ObsGrid({ obs }: { obs: Record<string, Record<string, unknown>> }) {
  const rows: [string, string][] = []
  for (const [group, fields] of Object.entries(obs)) {
    for (const [k, v] of Object.entries(fields)) {
      rows.push([`${group}.${k}`, Array.isArray(v) ? v.join(', ') : String(v)])
    }
  }
  return (
    <div
      className="mono"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: '2px 16px',
        color: 'var(--text-secondary)',
      }}
    >
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ color: 'var(--text-muted)' }}>{k}</span>
          <span>{v}</span>
        </div>
      ))}
    </div>
  )
}

export function LLMTrace({ runs }: { runs: LLMRun[] }) {
  const [runKey, setRunKey] = useState(runs[0]?.key)
  const run = runs.find((r) => r.key === runKey) ?? runs[0]
  const [ep, setEp] = useState(0)
  const episode = run?.episodes.find((e) => e.episode === ep) ?? run?.episodes[0]
  const [tick, setTick] = useState(0)
  const call = episode?.calls.find((c) => c.tick === tick) ?? episode?.calls[0]

  if (!run || !episode || !call) return <div className="card">无 LLM 轨迹数据</div>

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>LLM 决策透视</h2>
        {runs.map((r) => (
          <button key={r.key} className={`tab-btn${r.key === run.key ? ' active' : ''}`} onClick={() => { setRunKey(r.key); setEp(0); setTick(0) }}>
            {r.label}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {run.episodes.map((e) => (
          <button key={e.episode} className={`tab-btn${e.episode === episode.episode ? ' active' : ''}`} onClick={() => { setEp(e.episode); setTick(0) }}>
            Ep {e.episode}
          </button>
        ))}
      </div>

      <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 12 }}>
        {run.model} · fallback 率 {(episode.fallback_rate * 100).toFixed(1)}% · 平均延迟{' '}
        {episode.mean_latency_sec}s/决策
        {run.total_input_tokens != null &&
          ` · tokens ${run.total_input_tokens?.toLocaleString()} in / ${run.total_output_tokens?.toLocaleString()} out`}
      </div>

      {/* tick strip: alpha per tick, fallback marked */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 14, flexWrap: 'wrap' }}>
        {episode.calls.map((c) => (
          <button
            key={c.tick}
            onClick={() => setTick(c.tick)}
            title={`tick ${c.tick} · alpha ${c.applied_alpha}${c.fallback ? ` · fallback:${c.fallback}` : ''}`}
            style={{
              width: 13,
              height: 26,
              border: c.tick === call.tick ? '2px solid var(--text-primary)' : '1px solid var(--border)',
              borderRadius: 3,
              cursor: 'pointer',
              padding: 0,
              background: c.fallback ? 'var(--critical)' : 'var(--series-1)',
              opacity: 0.35 + 0.65 * Math.min(c.applied_alpha / 400, 1),
            }}
          />
        ))}
      </div>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 14 }}>
        每格一个 tick，深浅 = alpha 大小，红 = 触发 fallback。点击查看该 tick 详情。
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
            模型看到的（tick {call.tick} observation）
          </div>
          {call.observation ? <ObsGrid obs={call.observation} /> : <span className="mono">（无）</span>}
        </div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
            模型的回答 → 实际执行 alpha = {call.applied_alpha}
            {call.fallback && (
              <span style={{ color: 'var(--critical)', marginLeft: 8 }}>fallback: {call.fallback}</span>
            )}
            <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 8 }}>
              {call.latency_sec}s
            </span>
          </div>
          <pre
            className="mono"
            style={{
              whiteSpace: 'pre-wrap',
              background: 'var(--page)',
              border: '1px solid var(--grid)',
              borderRadius: 6,
              padding: 10,
              maxHeight: 260,
              overflow: 'auto',
              margin: 0,
            }}
          >
            {call.error ? `⚠ ${call.error}\n\n` : ''}
            {call.raw_output || '（无输出）'}
          </pre>
        </div>
      </div>
    </div>
  )
}
