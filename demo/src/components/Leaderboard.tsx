import type { Comparison } from '../lib/types'

const SERIES_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']

export function Leaderboard({ comp, colorOf }: { comp: Comparison; colorOf: (id: string) => string }) {
  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>策略排行榜</h2>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          {comp.label} · 预算 {comp.budget.toLocaleString()} · 目标CPA {comp.target_cpa} · seed {comp.seed} ·
          配对随机数（同市场同流量）
        </span>
      </div>
      <table className="data">
        <thead>
          <tr>
            <th>#</th>
            <th>策略</th>
            <th>竞赛得分</th>
            <th>转化</th>
            <th>实际CPA</th>
            <th>CPA约束</th>
            <th>预算利用</th>
          </tr>
        </thead>
        <tbody>
          {comp.candidates.map((c, i) => {
            const cpaOk = c.actual_cpa_mean <= comp.target_cpa * 1.05
            return (
              <tr key={c.id}>
                <td style={{ color: 'var(--text-muted)' }}>{i + 1}</td>
                <td>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      background: colorOf(c.id),
                      marginRight: 8,
                    }}
                  />
                  {c.name}
                </td>
                <td style={{ fontWeight: 600 }}>{c.score_mean.toFixed(2)}</td>
                <td>{c.conversions_mean.toFixed(1)}</td>
                <td>{c.actual_cpa_mean > 1e6 ? '∞ (无转化)' : c.actual_cpa_mean.toFixed(1)}</td>
                <td>
                  {cpaOk ? (
                    <span style={{ color: 'var(--good)' }}>✓ 达标</span>
                  ) : (
                    <span style={{ color: 'var(--critical)' }}>
                      ✗ 超 {c.actual_cpa_mean > 1e6 ? '—' : `${Math.round((c.actual_cpa_mean / comp.target_cpa - 1) * 100)}%`}
                    </span>
                  )}
                </td>
                <td>{(c.budget_utilization_mean * 100).toFixed(1)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p style={{ color: 'var(--text-muted)', fontSize: 12, margin: '10px 0 0' }}>
        得分规则（NeurIPS 竞赛）：CPA ≤ 目标时 = 转化数；超标时 × (目标/实际)²。所有数字为 simulated
        结果，未经真实平台校准。
      </p>
    </div>
  )
}

export { SERIES_COLORS }
