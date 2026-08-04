import { useEffect, useState } from 'react'

import { TeacherMatrix, type HarnessBoard } from './components/TeacherMatrix'

const API = import.meta.env.VITE_API_BASE ?? '/api'

interface Execution {
  name: string
  status: string
  startDate: string
}

interface TraceCall {
  tick: number
  applied_alpha: number
  parsed_alpha: number | null
  latency_sec: number
  fallback: string | null
  error: string | null
  raw_output: string
  observation: Record<string, Record<string, unknown>> | null
  trace_id: string | null
}

const STATUS_COLOR: Record<string, string> = {
  RUNNING: 'var(--series-1)',
  SUCCEEDED: 'var(--good)',
  FAILED: 'var(--critical)',
  ABORTED: 'var(--text-muted)',
}

export default function HarnessApp() {
  const [boards, setBoards] = useState<HarnessBoard[]>([])
  const [executions, setExecutions] = useState<Execution[]>([])
  const [apiOk, setApiOk] = useState<boolean | null>(null)

  // trace browser state
  const [traceTask, setTraceTask] = useState<{ matrix: string; task: string } | null>(null)
  const [trace, setTrace] = useState<{ calls: TraceCall[] } | null>(null)
  const [traceTick, setTraceTick] = useState(0)
  const [traceErr, setTraceErr] = useState<string | null>(null)

  // submit form state
  const [name, setName] = useState('')
  const [arnOrUrl, setArnOrUrl] = useState('')
  const [submitMsg, setSubmitMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const refresh = () => {
    fetch(`${API}/harness/leaderboards`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        setBoards(d.boards)
        setApiOk(true)
      })
      .catch(() => setApiOk(false))
    fetch(`${API}/harness/executions`)
      .then((r) => (r.ok ? r.json() : { executions: [] }))
      .then((d) => setExecutions(d.executions ?? []))
      .catch(() => {})
  }

  useEffect(() => {
    refresh()
    const t = window.setInterval(refresh, 30000)
    return () => window.clearInterval(t)
  }, [])

  const submit = async () => {
    setSubmitting(true)
    setSubmitMsg(null)
    try {
      const body: Record<string, string> = { name: name.trim() }
      if (arnOrUrl.trim().startsWith('arn:')) body.runtime_arn = arnOrUrl.trim()
      else body.endpoint_url = arnOrUrl.trim()
      const r = await fetch(`${API}/harness/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail ?? `HTTP ${r.status}`)
      setSubmitMsg({ ok: true, text: `已受理：${d.execution}。标准场景评测约 15-20 分钟，完成后自动出现在 arena 榜单。` })
    } catch (e) {
      setSubmitMsg({ ok: false, text: String(e instanceof Error ? e.message : e) })
    } finally {
      setSubmitting(false)
    }
  }

  const loadTrace = (matrix: string, task: string) => {
    setTraceTask({ matrix, task })
    setTrace(null)
    setTraceErr(null)
    setTraceTick(0)
    fetch(`${API}/harness/trace/${matrix}/${task}`)
      .then((r) => (r.ok ? r.json() : r.json().then((d) => Promise.reject(new Error(d.detail ?? r.status)))))
      .then(setTrace)
      .catch((e) => setTraceErr(String(e instanceof Error ? e.message : e)))
  }

  const arenaBoards = boards.filter((b) => b.matrix_id.startsWith('arena'))
  const matrixBoards = boards.filter((b) => !b.matrix_id.startsWith('arena'))

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', padding: '0 20px 60px' }}>
      <header style={{ padding: '18px 0 14px', display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap' }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>AdSim Harness · AWS 云端评测管道</h1>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          Step Functions × Fargate × AgentCore × S3 × Lambda · 实时数据
        </span>
        <span style={{ flex: 1 }} />
        <a href="./index.html" className="tab-btn" style={{ textDecoration: 'none' }}>
          ← 返回实验台主页
        </a>
      </header>

      {apiOk === false && (
        <div className="card" style={{ color: 'var(--critical)', marginBottom: 20 }}>
          后端未连接（demo/server/api.py 未启动或无 AWS 权限）。本页所有数据来自 AWS 实时接口，静态模式下不可用。
        </div>
      )}

      <div style={{ display: 'grid', gap: 20 }}>
        {/* pipeline explainer */}
        <div className="card">
          <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>这条管道是什么</h2>
          <p className="mono" style={{ margin: '0 0 8px', fontSize: 12, color: 'var(--text-secondary)' }}>
            实验矩阵 YAML → Step Functions (adsim-matrix) → N × Fargate 并行模拟器（48 广告主市场）
            <br />
            &nbsp;&nbsp;&nbsp;&nbsp;→ 每时段调用被测 agent（Bedrock / Mantle GPT / AgentCore Runtime / 任意 HTTPS 端点）
            <br />
            &nbsp;&nbsp;&nbsp;&nbsp;→ 产物落 S3 → Lambda 自动聚合排名 → 本页榜单（30 秒自动刷新）
            <br />
            &nbsp;&nbsp;&nbsp;&nbsp;→ 决策级 trace 进 CloudWatch（namespace adsim：延迟 / fallback / alpha）
          </p>
          <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
            从提交到出分全程无人值守。评测口径：官方 NeurIPS 数据流量（arena）或参数化流量（教师矩阵），
            500k PV × 48 时段在线模拟，对手实时竞价，同 seed 配对保证公平。
          </p>
        </div>

        {/* recent executions */}
        <div className="card">
          <h2 style={{ margin: '0 0 8px', fontSize: 16 }}>最近执行（Step Functions）</h2>
          <table className="data" style={{ fontSize: 12 }}>
            <thead>
              <tr><th>执行</th><th>状态</th><th>开始时间</th></tr>
            </thead>
            <tbody>
              {executions.map((e) => (
                <tr key={e.name}>
                  <td className="mono">{e.name}</td>
                  <td style={{ color: STATUS_COLOR[e.status] ?? 'inherit', fontWeight: 600 }}>{e.status}</td>
                  <td>{new Date(e.startDate).toLocaleString()}</td>
                </tr>
              ))}
              {!executions.length && (
                <tr><td colSpan={3} style={{ color: 'var(--text-muted)' }}>（暂无）</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* arena */}
        <div className="card">
          <h2 style={{ margin: '0 0 4px', fontSize: 16 }}>Arena 竞技场 · 提交你的 agent</h2>
          <p style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 12 }}>
            任何实现了 AgentEndpoint 契约（收 observation JSON → 回{' '}
            <span className="mono">{'{"action":"set_alpha","alpha":...}'}</span>）的 agent
            都可以参赛：AgentCore Runtime 填 ARN，自部署服务填 HTTPS 地址。服务端固定考卷
            （官方 period-7/8 × 500k PV × 2 episodes），每个名字每小时限提交一次。
          </p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="参赛名（字母数字_-）"
              style={{ padding: '6px 8px', border: '1px solid var(--grid)', borderRadius: 6, width: 200 }}
            />
            <input
              value={arnOrUrl}
              onChange={(e) => setArnOrUrl(e.target.value)}
              placeholder="arn:aws:bedrock-agentcore:...:runtime/xxx 或 https://..."
              className="mono"
              style={{ padding: '6px 8px', border: '1px solid var(--grid)', borderRadius: 6, flex: 1, minWidth: 320 }}
            />
            <button
              className="tab-btn active"
              disabled={!name.trim() || !arnOrUrl.trim() || submitting}
              style={{ opacity: !name.trim() || !arnOrUrl.trim() || submitting ? 0.5 : 1 }}
              onClick={submit}
            >
              {submitting ? '提交中…' : '提交评测'}
            </button>
          </div>
          {submitMsg && (
            <div style={{ fontSize: 13, color: submitMsg.ok ? 'var(--good)' : 'var(--critical)', marginBottom: 10 }}>
              {submitMsg.ok ? '✓ ' : '✗ '}{submitMsg.text}
            </div>
          )}
          {arenaBoards.map((b) => (
            <div key={b.matrix_id}>
              <div style={{ fontSize: 13, fontWeight: 600, margin: '10px 0 6px' }}>
                Arena 榜单（官方数据流量 · 标准考卷）
              </div>
              <table className="data" style={{ fontSize: 12 }}>
                <thead>
                  <tr><th>#</th><th>参赛者</th><th>竞赛得分</th><th>转化</th><th>实际CPA</th><th>预算利用</th></tr>
                </thead>
                <tbody>
                  {b.candidates.map((c, i) => (
                    <tr key={c.task_id}>
                      <td style={{ color: 'var(--text-muted)' }}>{i + 1}</td>
                      <td className="mono">{c.task_id.replace(/_s\d+$/, '')}</td>
                      <td style={{ fontWeight: 600 }}>{c.score_mean?.toFixed(2)}</td>
                      <td>{c.conversions_mean?.toFixed(1)}</td>
                      <td>{c.actual_cpa_mean > 1e6 ? '∞' : c.actual_cpa_mean?.toFixed(1)}</td>
                      <td>{(c.budget_utilization_mean * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>

        {/* teacher matrices (live from S3) */}
        <TeacherMatrix boards={matrixBoards} onPick={loadTrace} />

        {/* decision trace browser */}
        <div className="card">
          <h2 style={{ margin: '0 0 4px', fontSize: 16 }}>决策 Trace 浏览器</h2>
          <p style={{ margin: '0 0 10px', color: 'var(--text-muted)', fontSize: 12 }}>
            点击上方任意榜单行加载该任务的完整决策轨迹（S3 原始记录；CloudWatch 里有同源的
            EMF 指标，namespace <span className="mono">adsim</span>，日志组{' '}
            <span className="mono">/adsim/decisions</span>）。
          </p>
          {!traceTask && <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>（未选择任务）</div>}
          {traceTask && (
            <div style={{ fontSize: 13, marginBottom: 8 }}>
              <b className="mono">{traceTask.matrix} / {traceTask.task}</b>
              {!trace && !traceErr && <span style={{ color: 'var(--text-muted)' }}> 加载中…</span>}
              {traceErr && <span style={{ color: 'var(--critical)' }}> {traceErr}</span>}
            </div>
          )}
          {trace && (
            <>
              <div style={{ display: 'flex', gap: 2, marginBottom: 12, flexWrap: 'wrap' }}>
                {trace.calls.map((c) => (
                  <button
                    key={`${c.tick}-${c.trace_id ?? ''}`}
                    onClick={() => setTraceTick(trace.calls.indexOf(c))}
                    title={`tick ${c.tick} · alpha ${c.applied_alpha} · ${c.latency_sec}s${c.fallback ? ` · fallback:${c.fallback}` : ''}`}
                    style={{
                      width: 13, height: 26, padding: 0, cursor: 'pointer', borderRadius: 3,
                      border: trace.calls.indexOf(c) === traceTick ? '2px solid var(--text-primary)' : '1px solid var(--border)',
                      background: c.fallback ? 'var(--critical)' : 'var(--series-1)',
                      opacity: 0.35 + 0.65 * Math.min(c.applied_alpha / 400, 1),
                    }}
                  />
                ))}
              </div>
              {(() => {
                const c = trace.calls[traceTick]
                if (!c) return null
                return (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                        Tick {c.tick} · observation
                      </div>
                      <pre className="mono" style={{ whiteSpace: 'pre-wrap', background: 'var(--page)', border: '1px solid var(--grid)', borderRadius: 6, padding: 10, maxHeight: 240, overflow: 'auto', margin: 0, fontSize: 11 }}>
                        {c.observation ? JSON.stringify(c.observation, null, 1) : '（无）'}
                      </pre>
                    </div>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                        模型输出 → alpha = {c.applied_alpha}
                        {c.fallback && <span style={{ color: 'var(--critical)', marginLeft: 8 }}>fallback: {c.fallback}</span>}
                        <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 8 }}>{c.latency_sec}s</span>
                      </div>
                      <pre className="mono" style={{ whiteSpace: 'pre-wrap', background: 'var(--page)', border: '1px solid var(--grid)', borderRadius: 6, padding: 10, maxHeight: 240, overflow: 'auto', margin: 0, fontSize: 11 }}>
                        {c.error ? `⚠ ${c.error}\n\n` : ''}{c.raw_output || '（无输出）'}
                      </pre>
                      {c.trace_id && (
                        <div className="mono" style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                          trace_id: {c.trace_id}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}
            </>
          )}
        </div>
      </div>

      <footer style={{ marginTop: 28, color: 'var(--text-muted)', fontSize: 12 }}>
        本页数据实时来自 S3 / Step Functions（30 秒轮询）。搭建过程与复现手册见仓库
        docs/RUNBOOK_harness_setup.md。所有指标为 simulated 结果。
      </footer>
    </div>
  )
}
