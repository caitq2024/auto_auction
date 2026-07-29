import { useMemo, useRef, useState } from 'react'

export interface Series {
  name: string
  color: string
  values: (number | null)[]
}

interface Props {
  title: string
  x: number[]
  series: Series[]
  yLabel?: string
  height?: number
  formatY?: (v: number) => string
}

const M = { top: 16, right: 110, bottom: 28, left: 56 }

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0]
  const raw = max / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((s) => s * mag).find((s) => s >= raw) ?? raw
  // extend to the first tick AT OR ABOVE max — otherwise the axis tops out
  // below the data (e.g. max 2900 with step 1000 gave a 2000 top, clipping
  // every line above it)
  const top = Math.ceil((max - 1e-9) / step) * step
  const ticks: number[] = []
  for (let v = 0; v <= top + 1e-9; v += step) ticks.push(v)
  return ticks
}

export function LineChart({ title, x, series, yLabel, height = 240, formatY }: Props) {
  const [hoverI, setHoverI] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const width = 760
  const iw = width - M.left - M.right
  const ih = height - M.top - M.bottom

  const yMax = useMemo(() => {
    let m = 0
    for (const s of series) for (const v of s.values) if (v != null && v > m) m = v
    return m || 1
  }, [series])
  const ticks = niceTicks(yMax)
  const yTop = ticks[ticks.length - 1] || yMax

  const px = (i: number) => M.left + (i / Math.max(x.length - 1, 1)) * iw
  const py = (v: number) => M.top + ih - (v / yTop) * ih
  const fmt = formatY ?? ((v: number) => v.toLocaleString())

  const onMove = (e: React.MouseEvent) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return
    const mx = ((e.clientX - rect.left) / rect.width) * width
    const i = Math.round(((mx - M.left) / iw) * (x.length - 1))
    setHoverI(i >= 0 && i < x.length ? i : null)
  }

  return (
    <div>
      <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 4 }}>{title}</div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', display: 'block' }}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverI(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={M.left + iw} y1={py(t)} y2={py(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={M.left - 8} y={py(t) + 4} textAnchor="end" fontSize={11} fill="var(--text-muted)">
              {fmt(t)}
            </text>
          </g>
        ))}
        <line x1={M.left} x2={M.left + iw} y1={py(0)} y2={py(0)} stroke="var(--baseline)" strokeWidth={1} />
        {[0, Math.floor(x.length / 2), x.length - 1].map((i) => (
          <text key={i} x={px(i)} y={height - 8} textAnchor="middle" fontSize={11} fill="var(--text-muted)">
            {x[i]}
          </text>
        ))}
        {yLabel && (
          <text x={M.left} y={M.top - 4} fontSize={11} fill="var(--text-muted)">
            {yLabel}
          </text>
        )}

        {series.map((s) => {
          const d = s.values
            .map((v, i) => (v == null ? null : `${i === 0 || s.values[i - 1] == null ? 'M' : 'L'}${px(i)},${py(v)}`))
            .filter(Boolean)
            .join(' ')
          return <path key={s.name} d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        })}

        {hoverI != null && (
          <g>
            <line x1={px(hoverI)} x2={px(hoverI)} y1={M.top} y2={M.top + ih} stroke="var(--baseline)" strokeWidth={1} />
            {series.map((s) => {
              const v = s.values[hoverI]
              if (v == null) return null
              return (
                <g key={s.name}>
                  <circle cx={px(hoverI)} cy={py(v)} r={5} fill={s.color} stroke="var(--surface-1)" strokeWidth={2} />
                </g>
              )
            })}
          </g>
        )}

        {/* legend (always present for >=2 series) */}
        {series.length >= 2 &&
          series.map((s, si) => (
            <g key={s.name} transform={`translate(${M.left + iw + 10},${M.top + si * 18})`}>
              <line x1={0} x2={14} y1={5} y2={5} stroke={s.color} strokeWidth={2} />
              <text x={18} y={9} fontSize={11} fill="var(--text-secondary)">
                {s.name}
              </text>
            </g>
          ))}
      </svg>
      {hoverI != null && (
        <div className="mono" style={{ color: 'var(--text-secondary)', minHeight: 18 }}>
          tick {x[hoverI]} ·{' '}
          {series
            .map((s) => `${s.name}: ${s.values[hoverI] == null ? '—' : fmt(s.values[hoverI] as number)}`)
            .join(' · ')}
        </div>
      )}
      {hoverI == null && <div style={{ minHeight: 18 }} />}
    </div>
  )
}
