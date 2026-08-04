interface HarnessCandidate {
  task_id: string
  score_mean: number
  conversions_mean: number
  actual_cpa_mean: number
  budget_utilization_mean: number
}

export interface HarnessBoard {
  matrix_id: string
  generated_at: string
  num_candidates: number
  candidates: HarnessCandidate[]
}

const MATRIX_LABELS: Record<string, string> = {
  teacher_matrix_official_v1:
    '教师模型矩阵 · 官方数据流量（9 模型 · 500k PV × 2ep · v2 prompt · 同 seed）',
  teacher_matrix_v1:
    '教师模型矩阵 · 简易流量（6 模型 · 500k PV × 2ep · v2 prompt · 同 seed）',
}

const NAME_LABELS: Record<string, string> = {
  haiku45: 'Claude Haiku 4.5',
  sonnet46: 'Claude Sonnet 4.6',
  sonnet5: 'Claude Sonnet 5',
  opus5: 'Claude Opus 5',
  deepseekr1: 'DeepSeek R1',
  nova2lite: 'Nova 2 Lite',
  gpt56sol: 'GPT-5.6 Sol',
  gpt56terra: 'GPT-5.6 Terra',
  gpt56luna: 'GPT-5.6 Luna',
}

function displayName(taskId: string): string {
  const base = taskId.replace(/_s\d+$/, '')
  return NAME_LABELS[base] ?? base
}

export function TeacherMatrix({ boards }: { boards: HarnessBoard[] }) {
  if (!boards.length) return null
  return (
    <div className="card">
      <h2 style={{ margin: '0 0 4px', fontSize: 16 }}>教师模型矩阵（harness 自动跑批）</h2>
      <p style={{ margin: '0 0 12px', color: 'var(--text-muted)', fontSize: 12 }}>
        由云端 harness 产出：Step Functions 把实验矩阵 fan-out 到并行 Fargate 模拟器，结果落
        S3，Lambda 自动聚合成本榜单。教师选型用于后续蒸馏/GRPO。注意 2 episodes
        为小样本，相邻名次差异需扩样确认。
      </p>
      <div style={{ display: 'grid', gap: 16 }}>
        {boards.map((b) => (
          <div key={b.matrix_id}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
              {MATRIX_LABELS[b.matrix_id] ?? b.matrix_id}
            </div>
            <table className="data" style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  <th>#</th>
                  <th>模型</th>
                  <th>竞赛得分</th>
                  <th>转化</th>
                  <th>实际CPA</th>
                  <th>预算利用</th>
                </tr>
              </thead>
              <tbody>
                {b.candidates.map((c, i) => (
                  <tr key={c.task_id}>
                    <td style={{ color: 'var(--text-muted)' }}>{i + 1}</td>
                    <td>{displayName(c.task_id)}</td>
                    <td style={{ fontWeight: 600 }}>{c.score_mean?.toFixed(2)}</td>
                    <td>{c.conversions_mean?.toFixed(1)}</td>
                    <td>
                      {c.actual_cpa_mean > 1e6 ? '∞' : c.actual_cpa_mean?.toFixed(1)}
                      {c.actual_cpa_mean <= 100 && c.actual_cpa_mean > 0 && (
                        <span style={{ color: 'var(--good)', marginLeft: 4 }}>✓</span>
                      )}
                    </td>
                    <td>{(c.budget_utilization_mean * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              聚合时间：{new Date(b.generated_at).toLocaleString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
