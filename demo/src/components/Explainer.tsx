import { useState } from 'react'

interface SampleRow {
  label: string
  note: string
  row: {
    timeStepIndex: number
    pValue: number
    bid: number
    leastWinningCost: number
    adSlot: number
    isExposed: number
    cost: number
    conversionAction: number
  }
}

const STRATEGY_INTRO: { name: string; what: string; how: string }[] = [
  {
    name: 'PID',
    what: '工业界最常用的预算 pacing 控制器，无学习、纯规则。',
    how: '把预算均匀分到 48 个时段：上个时段花得比计划慢就把 alpha ×1.2，花太快就 ×0.7。只管把钱花完，不看转化质量，所以转化多但 CPA 容易崩——它是所有智能策略应当超越的下界。',
  },
  {
    name: 'IQL (Implicit Q-Learning)',
    what: '离线强化学习算法，模型权重来自 AuctionNet 仓库自带的预训练 checkpoint。',
    how: '从 50 万 PV 规模的历史竞价日志学一个价值函数（估计"此状态下调 alpha 的长期收益"），对没见过的激进动作保持保守。它赢在会控 CPA：只花 65% 预算，但每个转化成本刚好压在约束线内，一分惩罚不吃。',
  },
  {
    name: 'DT (Decision Transformer)',
    what: '把强化学习当序列建模：用 Transformer 读"历史状态-动作-想要的回报"序列，预测下一个动作。',
    how: '我们用模拟器自产日志训练。它学会了数据里的行为模式（比如"把预算花完"），但数据由 PID 主导，所以也继承了 PID 不控 CPA 的毛病——训练数据质量决定它的上限。',
  },
  {
    name: 'LLM (Claude prompt-only)',
    what: '大语言模型直接当竞价 agent：每个时段把状态发给模型，它回一个 JSON 决策。',
    how: '模型没有任何针对这个市场的训练，纯靠 prompt 里的市场统计推理。当前特点是"纪律好但胆子小"——CPA 控制不错但预算只敢花不到 10%，赢得太少。这正是后续蒸馏/强化学习要补的短板。',
  },
]

export function Explainer({ samples }: { samples: SampleRow[] }) {
  const [open, setOpen] = useState(true)

  return (
    <div className="card">
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer' }}
        onClick={() => setOpen(!open)}
      >
        <h2 style={{ margin: 0, fontSize: 16 }}>这是什么？—— 30 秒看懂本实验台</h2>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{open ? '收起 ▲' : '展开 ▼'}</span>
      </div>
      {open && (
        <div style={{ display: 'grid', gap: 18, marginTop: 14 }}>
          {/* 1. 场景与数据来源 */}
          <section>
            <h3 style={{ fontSize: 14, margin: '0 0 6px' }}>场景与数据来源</h3>
            <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
              这是一个<b>广告竞价市场模拟器</b>（基于阿里妈妈开源的 AuctionNet，NeurIPS 2024）。
              一天分成 48 个时段，48 个广告主对每一次广告展示机会（PV）竞价，出价最高的三名获得
              3 个广告位，按 GSP 规则付费（按下一名的出价扣钱）。我们控制其中{' '}
              <b>1 个广告主</b>（预算 2,900、目标 CPA 100），把它的策略换成不同算法同台比较——
              其余 47 个对手保持不变，流量与随机数完全配对，保证公平。
              页面上所有数据都来自模拟器运行日志（非真实平台数据）。
            </p>
          </section>

          {/* 2. alpha 机制 */}
          <section>
            <h3 style={{ fontSize: 14, margin: '0 0 6px' }}>策略只做一件事：每个时段定一个出价系数 alpha</h3>
            <p style={{ margin: '0 0 6px', color: 'var(--text-secondary)' }}>
              每次展示机会都带一个 <span className="mono">pValue</span>（预估转化概率，通常只有
              0.0003~0.002）。策略不逐条出价，而是每个时段给一个系数，出价 ={' '}
              <span className="mono">alpha × pValue</span>。这等于"我愿意为 1 个预期转化付 alpha 元"：
              alpha = 200 时，一个 pValue 0.001 的机会出价 0.2 元。
            </p>
            <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
              调 alpha 就是踩油门：<b>调高</b> → 赢更多展示、花钱更快、单个转化成本更高；
              <b>调低</b> → 省钱但可能什么都买不到。竞价的艺术是在 48 个时段里动态踩油门——
              早上流量便宜多买点？还是留钱等晚高峰？这正是回放图里各策略曲线形状不同的原因。
              这个设计也让 LLM 竞价变得可行：<b>无论市场是 5 万还是 50 万次展示机会，LLM 每个
              episode 只被调用 48 次</b>（每时段一次）。48 次决策如何变成 50 万条出价？
              流程是：某时段开始时，LLM 读取当前状态（剩余预算、CPA 进度、市场价统计等）
              输出一个系数（如 alpha = 120）；该时段内成千上万个展示机会陆续到来，<b>每一个都自带
              平台预估的转化概率 pValue</b>（每条不同，比如 0.0003 / 0.0011 / 0.0007…）；执行器
              对每条机会机械计算 <span className="mono">出价 = 120 × 该条的pValue</span>，得到
              0.036 / 0.132 / 0.084 元…——所以出价条条不同，但"愿意为单位转化概率付多少钱"
              这个决策整个时段一致。这正是真实广告平台的主流做法：出价系统（如自动竞价）持有
              人/策略设定的系数，逐次曝光实时乘上 pCVR 出价，<b>广告主侧完全可以复现同样的架构
              ——只需把"LLM 每半小时给一次系数"接到自家出价系统即可，无需 LLM 参与每一次竞价</b>。
              实测 500k 市场一轮实验（2 个 episode、96 次调用）约 5 万 input token、3 万
              output token、每次决策约 4 秒。
              另外，"48 个时段"（一天 24 小时 × 每半小时一段）与"48 个广告主"（6 个行业类目 ×
              每类 8 家）是两个无关的数字，恰好相同。
            </p>
          </section>

          {/* 3. 示例数据 */}
          {samples.length > 0 && (
            <section>
              <h3 style={{ fontSize: 14, margin: '0 0 6px' }}>三行真实日志，看懂一次竞价</h3>
              <table className="data" style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>情形</th>
                    <th>时段</th>
                    <th>pValue</th>
                    <th>我的出价</th>
                    <th>最低获胜价</th>
                    <th>坑位</th>
                    <th>曝光</th>
                    <th>花费</th>
                    <th>转化</th>
                  </tr>
                </thead>
                <tbody>
                  {samples.map((s) => (
                    <tr key={s.label}>
                      <td style={{ fontWeight: 600 }}>{s.label}</td>
                      <td>{s.row.timeStepIndex}</td>
                      <td className="mono">{s.row.pValue}</td>
                      <td className="mono">{s.row.bid}</td>
                      <td className="mono">{s.row.leastWinningCost}</td>
                      <td>{s.row.adSlot || '—'}</td>
                      <td>{s.row.isExposed ? '✓' : '✗'}</td>
                      <td className="mono">{s.row.cost}</td>
                      <td>{s.row.conversionAction ? '✓' : '✗'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: 'var(--text-secondary)', fontSize: 12 }}>
                {samples.map((s) => (
                  <li key={s.label}>
                    <b>{s.label}</b>：{s.note}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* 3.5 出价→转化的因果链 */}
          <section>
            <h3 style={{ fontSize: 14, margin: '0 0 6px' }}>出价和转化是什么关系？不是碰巧</h3>
            <p style={{ margin: '0 0 6px', color: 'var(--text-secondary)' }}>
              转化不是随机掉落的，而是一条明确的因果链，出价只影响其中的<b>前半段</b>：
            </p>
            <p className="mono" style={{ margin: '0 0 6px', fontSize: 12, color: 'var(--text-secondary)' }}>
              出价高低 → 是否进前三（赢坑位）→ 是否曝光（坑位1/2/3 曝光率 100%/80%/60%）→
              曝光后按 pValue 掷骰子 → 转化
            </p>
            <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
              前半段是<b>确定性</b>的：你的出价和 47 个对手排序，前三名拿坑位，付下一名的价（GSP）。
              后半段是<b>概率性</b>的：赢到曝光后，模拟器按该次机会的 pValue（如 0.0008）做一次
              伯努利抽样决定是否转化——这模拟了真实世界"用户看到广告后是否购买"的不确定性。
              所以出价影响的是"你买到了多少次掷骰子的机会、以及每次花多少钱"，而单次转化本身有运气成分。
              为了对冲这种运气，排行榜同时跑多个 episode 取平均，平台内部还记录"期望转化"
              （pValue × 曝光率的累加，无随机性）作为低方差口径交叉验证——两个口径结论一致才可信。
            </p>
          </section>

          {/* 4. CPA 约束 */}
          <section>
            <h3 style={{ fontSize: 14, margin: '0 0 6px' }}>CPA 约束是什么？</h3>
            <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
              CPA = 总花费 ÷ 转化数，即"买到一个转化平均花了多少钱"。广告主会设定目标 CPA
              （本实验为 100）：花 2,900 拿 29 个转化刚好达标。评分规则（NeurIPS 竞赛口径）：
              <b>CPA 达标时得分 = 转化数；超标时按 (目标/实际)² 打折</b>。比如 PID 拿了 17
              个转化但实际 CPA 172，得分 = 17 × (100/172)² ≈ 6.15。这个平方惩罚就是排行榜上
              "转化多的反而输给转化少但守约束的"的原因——花钱买量不难，难的是守着成本线买量。
            </p>
          </section>

          {/* 5. 策略介绍 */}
          <section>
            <h3 style={{ fontSize: 14, margin: '0 0 8px' }}>四类策略是什么？</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
              {STRATEGY_INTRO.map((s) => (
                <div
                  key={s.name}
                  style={{ border: '1px solid var(--grid)', borderRadius: 8, padding: '10px 12px' }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>{s.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>{s.what}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{s.how}</div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
