import { useEffect, useRef, useState } from 'react'

const API = import.meta.env.VITE_API_BASE ?? '/api'

interface ModelInfo {
  key: string
  model_id: string
  price_in_per_1m: number | null
  price_out_per_1m: number | null
}

import type { TickSeries } from '../lib/types'

export interface ExperimentResult {
  model: string
  model_id: string
  pv_num: number
  custom_prompt: boolean
  score_mean: number
  total_input_tokens: number
  total_output_tokens: number
  episodes: {
    episode: number
    score: number
    conversions: number
    cost: number
    actual_cpa: number
    budget_utilization: number
    fallback_rate: number
    ticks: TickSeries
    calls: { tick: number; applied_alpha: number; fallback: string | null; raw_output: string | null }[]
  }[]
}

function getUserId(): string {
  const KEY = 'adsim.uid'
  let uid = localStorage.getItem(KEY)
  if (!uid) {
    uid = 'u_' + crypto.randomUUID().replace(/-/g, '').slice(0, 16)
    localStorage.setItem(KEY, uid)
  }
  return uid
}

interface PromptTemplate {
  key: string
  label: string
  text: string
}

const SAVED_KEY = 'adsim.savedPrompts'

function loadSaved(): { name: string; text: string }[] {
  try {
    return JSON.parse(localStorage.getItem(SAVED_KEY) ?? '[]')
  } catch {
    return []
  }
}

export function RunExperiment({ onResult }: { onResult?: (r: ExperimentResult) => void }) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [defaultPrompt, setDefaultPrompt] = useState('')
  const [templates, setTemplates] = useState<PromptTemplate[]>([])
  const [publicDemo, setPublicDemo] = useState<{
    enabled: boolean
    models: string[]
    max_pv: number
    max_episodes: number
    remaining_today: number
  } | null>(null)
  const [savedPrompts, setSavedPrompts] = useState(loadSaved)
  const [apiOk, setApiOk] = useState<boolean | null>(null)

  // Bedrock key: memory only — never persisted, never echoed
  const [bedrockKey, setBedrockKey] = useState('')
  const [model, setModel] = useState('claude-haiku-4-5')
  const [pvNum, setPvNum] = useState(50000)
  const [episodes, setEpisodes] = useState(1)
  const [prompt, setPrompt] = useState('')
  const [showPrompt, setShowPrompt] = useState(false)

  const [taskId, setTaskId] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [detail, setDetail] = useState('')
  const [result, setResult] = useState<ExperimentResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    fetch(`${API}/models`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        setModels(d.models)
        setDefaultPrompt(d.default_system_prompt)
        setPrompt(d.default_system_prompt)
        setTemplates(d.prompt_templates ?? [])
        setPublicDemo(d.public_demo?.enabled ? d.public_demo : null)
        setApiOk(true)
      })
      .catch(() => setApiOk(false))
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [])

  const start = async () => {
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API}/experiments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Bedrock-Key': bedrockKey.trim(),
          'X-User-Id': getUserId(),
        },
        body: JSON.stringify({
          model,
          pv_num: pvNum,
          episodes,
          system_prompt: prompt.trim() === defaultPrompt.trim() ? null : prompt,
        }),
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string }
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      const { task_id } = (await res.json()) as { task_id: string }
      setTaskId(task_id)
      setProgress(0)
      pollRef.current = window.setInterval(async () => {
        const r = await fetch(`${API}/experiments/${task_id}`, {
          headers: { 'X-User-Id': getUserId() },
        })
        if (!r.ok) return
        const t = (await r.json()) as {
          status: string
          progress: number
          detail: string
          result: ExperimentResult | null
          error: string | null
        }
        setProgress(t.progress)
        setDetail(t.detail)
        if (t.status !== 'running') {
          if (pollRef.current) window.clearInterval(pollRef.current)
          setTaskId(null)
          if (t.status === 'done') {
            setResult(t.result)
            if (t.result) onResult?.(t.result)
          } else setError(t.error ?? '未知错误')
        }
      }, 2000)
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e))
    }
  }

  if (apiOk === false)
    return (
      <div className="card">
        <h2 style={{ margin: 0, fontSize: 16 }}>自己跑一个 LLM 竞价实验</h2>
        <p style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          实验后端未启动（demo/server/api.py）。静态浏览模式下此区不可用。
        </p>
      </div>
    )

  const selected = models.find((m) => m.key === model)

  return (
    <div className="card">
      <h2 style={{ margin: '0 0 4px', fontSize: 16 }}>自己跑一个 LLM 竞价实验</h2>
      <p style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 12 }}>
        粘贴你的 Bedrock API key（只保存在本页内存与实验任务中，不落盘、不回显），选一个模型，
        可选地修改指令 prompt，就能把它扔进 48 广告主市场里当竞价 agent。一轮实验 = 每 episode
        48 次 LLM 决策。
      </p>

      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Bedrock API Key（us-west-2）{publicDemo && '· 可留空'}
          <input
            type="password"
            value={bedrockKey}
            onChange={(e) => setBedrockKey(e.target.value)}
            placeholder={publicDemo ? '留空 = 免费演示额度' : 'bedrock-api-key…'}
            style={{ width: '100%', marginTop: 4, padding: '6px 8px', border: '1px solid var(--grid)', borderRadius: 6 }}
          />
        </label>
        <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          模型
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            style={{ width: '100%', marginTop: 4, padding: '6px 8px', border: '1px solid var(--grid)', borderRadius: 6 }}
          >
            {models.map((m) => (
              <option key={m.key} value={m.key}>
                {m.price_in_per_1m != null
                  ? `${m.key}（$${m.price_in_per_1m}/$${m.price_out_per_1m} per 1M tok）`
                  : `${m.key}（价格未公布）`}
              </option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          市场规模（PV）
          <select
            value={pvNum}
            onChange={(e) => setPvNum(Number(e.target.value))}
            style={{ width: '100%', marginTop: 4, padding: '6px 8px', border: '1px solid var(--grid)', borderRadius: 6 }}
          >
            <option value={20000}>20,000（最快）</option>
            <option value={50000}>50,000</option>
            <option value={100000}>100,000</option>
            <option value={500000}>500,000（论文标准市场，模拟最慢）</option>
          </select>
        </label>
        <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Episodes
          <select
            value={episodes}
            onChange={(e) => setEpisodes(Number(e.target.value))}
            style={{ width: '100%', marginTop: 4, padding: '6px 8px', border: '1px solid var(--grid)', borderRadius: 6 }}
          >
            <option value={1}>1（48 次决策）</option>
            <option value={2}>2（96 次决策）</option>
          </select>
        </label>
      </div>

      <div style={{ marginTop: 10 }}>
        <button className="tab-btn" onClick={() => setShowPrompt(!showPrompt)}>
          {showPrompt ? '收起 prompt ▲' : '查看/修改指令 prompt ▼'}
        </button>
        {showPrompt && (
          <div style={{ marginTop: 8 }}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>加载模板：</span>
              {templates.map((t) => (
                <button
                  key={t.key}
                  className={`tab-btn${prompt === t.text ? ' active' : ''}`}
                  title={t.label}
                  onClick={() => setPrompt(t.text)}
                >
                  {t.key === 'v1' ? 'v1 基础版' : t.key === 'v2' ? 'v2 pacing版' : t.label}
                </button>
              ))}
              {savedPrompts.map((sp) => (
                <span key={sp.name} style={{ display: 'inline-flex', alignItems: 'center' }}>
                  <button
                    className={`tab-btn${prompt === sp.text ? ' active' : ''}`}
                    onClick={() => setPrompt(sp.text)}
                  >
                    ⭐ {sp.name}
                  </button>
                  <button
                    className="tab-btn"
                    title={`删除 ${sp.name}`}
                    style={{ padding: '6px 8px', marginLeft: -1 }}
                    onClick={() => {
                      const next = savedPrompts.filter((x) => x.name !== sp.name)
                      setSavedPrompts(next)
                      localStorage.setItem(SAVED_KEY, JSON.stringify(next))
                    }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={10}
              maxLength={4000}
              className="mono"
              style={{ width: '100%', padding: 10, border: '1px solid var(--grid)', borderRadius: 6, resize: 'vertical' }}
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
              <button className="tab-btn" onClick={() => setPrompt(defaultPrompt)}>
                恢复默认
              </button>
              <button
                className="tab-btn"
                onClick={() => {
                  const name = window.prompt('给这个 prompt 起个名字（保存在你的浏览器本地）：')?.trim()
                  if (!name) return
                  const next = [...savedPrompts.filter((x) => x.name !== name), { name, text: prompt }]
                  setSavedPrompts(next)
                  localStorage.setItem(SAVED_KEY, JSON.stringify(next))
                }}
              >
                保存当前 prompt
              </button>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', alignSelf: 'center' }}>
                v1→v2 的实测差异见上方"策略简介"栏（Haiku 5.74→6.55）。以任一模板为底修改后可保存
                （仅存你的浏览器 localStorage）。解析失败会触发 fallback，实验不会崩。
              </span>
            </div>
          </div>
        )}
      </div>

      <div style={{ marginTop: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
        <button
          className="tab-btn active"
          disabled={(!bedrockKey.trim() && !publicDemo) || taskId != null}
          onClick={start}
          style={{ opacity: (!bedrockKey.trim() && !publicDemo) || taskId != null ? 0.5 : 1 }}
        >
          {taskId ? '运行中…' : bedrockKey.trim() ? '启动实验' : publicDemo ? '免费启动实验' : '启动实验'}
        </button>
        {publicDemo && !bedrockKey.trim() && !taskId && (
          <span style={{ fontSize: 11, color: 'var(--good)' }}>
            演示模式：限 {publicDemo.models.join(' / ')} · PV ≤ {publicDemo.max_pv.toLocaleString()} ·{' '}
            {publicDemo.max_episodes} episode · 今日剩余 {publicDemo.remaining_today} 次
          </span>
        )}
        {taskId && (
          <>
            <div style={{ flex: 1, maxWidth: 320, height: 8, background: 'var(--grid)', borderRadius: 4 }}>
              <div
                style={{ width: `${progress * 100}%`, height: '100%', background: 'var(--series-1)', borderRadius: 4, transition: 'width .5s' }}
              />
            </div>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{detail}</span>
          </>
        )}
        {selected && !taskId && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            预计 LLM 调用 <b>{episodes * 48} 次</b>（每时段 1 次 × 48 时段 × {episodes} episode，与
            PV 规模无关）
            {selected.price_in_per_1m != null && selected.price_out_per_1m != null && (
              <>
                {' '}· 成本 ≈ $
                {(((episodes * 48 * 550) / 1e6) * selected.price_in_per_1m + ((episodes * 48 * 300) / 1e6) * selected.price_out_per_1m).toFixed(3)}
                （按 ~550 in / ~300 out tok/次）
              </>
            )}
            {' '}· 时长 ≈ LLM {episodes * 3}–{episodes * 7} 分钟 + 模拟
            {' '}{Math.ceil((pvNum / 500000) * 6 * episodes)} 分钟
          </span>
        )}
      </div>

      {error && (
        <div style={{ marginTop: 10, color: 'var(--critical)', fontSize: 13 }}>✗ {error}</div>
      )}

      {result && (
        <div style={{ marginTop: 14 }}>
          <h3 style={{ fontSize: 14, margin: '0 0 6px' }}>
            结果：{result.model} · score {result.score_mean.toFixed(2)}
            {result.custom_prompt && '（自定义 prompt）'}
            <span style={{ fontWeight: 400, fontSize: 12, color: 'var(--good)', marginLeft: 10 }}>
              ✓ 已加入下方排行榜与 Episode 回放（
              {result.pv_num >= 200000 ? '500k PV 全规模' : '50k PV 快速实验'}场景——榜单已自动切换，
              两个场景的分数不可互比，可用顶部按钮切回）
            </span>
          </h3>
          <table className="data" style={{ fontSize: 12 }}>
            <thead>
              <tr>
                <th>episode</th>
                <th>得分</th>
                <th>转化</th>
                <th>花费</th>
                <th>实际CPA</th>
                <th>预算利用</th>
                <th>fallback率</th>
              </tr>
            </thead>
            <tbody>
              {result.episodes.map((e) => (
                <tr key={e.episode}>
                  <td>{e.episode}</td>
                  <td style={{ fontWeight: 600 }}>{e.score.toFixed(2)}</td>
                  <td>{e.conversions}</td>
                  <td>{e.cost.toFixed(0)}</td>
                  <td>{e.actual_cpa > 1e6 ? '∞' : e.actual_cpa.toFixed(1)}</td>
                  <td>{(e.budget_utilization * 100).toFixed(1)}%</td>
                  <td>{(e.fallback_rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
            tokens {result.total_input_tokens.toLocaleString()} in /{' '}
            {result.total_output_tokens.toLocaleString()} out · 对比参考：同场景 PID ≈ 3.2（50k）/
            6.2（500k），IQL ≈ 17.8（500k）
          </div>
        </div>
      )}
    </div>
  )
}
