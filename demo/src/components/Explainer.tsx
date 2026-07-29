import { useState, type ReactNode } from 'react'

import type { SampleRow } from '../lib/types'

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
    how: '模型没有任何针对这个市场的训练，纯靠 prompt 里的市场统计推理。500k 标准市场上 Opus 4.8 已超过 PID（7.63 vs 6.15）；短板是偏保守、预算利用率低——prompt 工程和后续蒸馏/强化学习都在补这个方向（见下方 prompt 版本对比）。',
  },
]

// prompt 迭代对同一模型得分的影响（500k PV × 2ep，同 seed）
const PROMPT_VERSIONS = [
  {
    ver: 'v1 基础版',
    desc: '规则 + 尺度提示（pValue 量级、合理 alpha 范围、win_rate 反馈）',
    rows: [{ model: 'Haiku 4.5', score: '5.74', util: '63%' }, { model: 'Opus 4.8', score: '7.63', util: '35%' }],
  },
  {
    ver: 'v2 pacing 版',
    desc: 'v1 + 明确的花钱纪律："没花完的预算是纯损失；按 t/48 进度对表，落后就果断加价（×1.3-2）；剩余 >10% 即失败"',
    rows: [{ model: 'Haiku 4.5', score: '6.55', util: '72%' }, { model: 'Opus 4.8', score: '（重跑中）', util: '—' }],
  },
]

function Collapsible({ title, children, defaultOpen = false }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ border: '1px solid var(--grid)', borderRadius: 8 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: 'flex',
          width: '100%',
          alignItems: 'center',
          gap: 8,
          background: 'none',
          border: 'none',
          padding: '10px 14px',
          cursor: 'pointer',
          fontSize: 14,
          fontWeight: 600,
          color: 'var(--text-primary)',
          textAlign: 'left',
        }}
      >
        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{open ? '▼' : '▶'}</span>
        {title}
      </button>
      {open && <div style={{ padding: '0 14px 12px' }}>{children}</div>}
    </div>
  )
}

export function Explainer({ samples }: { samples: SampleRow[] }) {
  return (
    <div className="card">
      <h2 style={{ margin: '0 0 12px', fontSize: 16 }}>实验平台介绍</h2>
      <div style={{ display: 'grid', gap: 8 }}>
        <Collapsible title="场景与数据来源" defaultOpen>
          <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
            这是一个<b>广告竞价市场模拟器</b>（基于阿里妈妈开源的 AuctionNet，NeurIPS 2024）。
            一天分成 48 个时段，48 个广告主对每一次广告展示机会（PV）竞价，出价最高的三名获得
            3 个广告位，按 GSP 规则付费（按下一名的出价扣钱）。我们控制其中{' '}
            <b>1 个广告主</b>（预算 2,900、目标 CPA 100），把它的策略换成不同算法同台比较——
            其余 47 个对手保持不变，流量与随机数完全配对，保证公平。
            页面上所有数据都来自模拟器运行日志（非真实平台数据）。
            "48 个时段"（一天 24 小时 × 每半小时一段）与"48 个广告主"（6 个行业类目 ×
            每类 8 家）是两个无关的数字，恰好相同。
          </p>
        </Collapsible>

        <Collapsible title="Bidding 场景业务名词解释">
          <div style={{ display: 'grid', gap: 8, color: 'var(--text-secondary)' }}>
            <p style={{ margin: 0 }}>
              <b>PV（展示机会）</b>：一次"用户刷到广告位"的机会，是竞价的最小单位。50 万 PV
              即一天有 50 万次机会可以竞。
            </p>
            <p style={{ margin: 0 }}>
              <b>pValue（预估转化概率）</b>：平台对"这次展示如果给你，用户会转化（购买/下载）
              的概率"的预估，通常只有 0.0003~0.002。每条 PV 各不相同。
            </p>
            <p style={{ margin: 0 }}>
              <b>alpha（出价系数）</b>：策略每个时段唯一要定的数。每条 PV 的出价 ={' '}
              <span className="mono">alpha × 该条的 pValue</span>，含义是"我愿意为 1 个预期转化付
              alpha 元"。调高 alpha → 赢更多、花更快、单转化更贵；调低 → 省钱但可能什么都买不到。
            </p>
            <p style={{ margin: 0 }}>
              <b>GSP（广义第二价格）</b>：赢家不按自己的出价付费，而是按下一名的出价付费。出价
              最高的三名分获坑位 1/2/3，曝光率分别 100%/80%/60%。
            </p>
            <p style={{ margin: 0 }}>
              <b>CPA 与目标 CPA</b>：CPA = 总花费 ÷ 转化数，"买到一个转化平均花多少钱"。本实验目标
              CPA 为 100：花 2,900 拿 29 个转化刚好达标。
            </p>
            <p style={{ margin: 0 }}>
              <b>竞赛得分</b>（NeurIPS 口径）：CPA 达标时得分 = 转化数；超标时按 (目标/实际)²
              打折。比如 PID 拿 17 个转化但 CPA 172，得分 = 17 × (100/172)² ≈ 6.15。平方惩罚就是
              排行榜上"转化多的反而输给守约束的"的原因——花钱买量不难，难的是守着成本线买量。
            </p>
            <p style={{ margin: 0 }}>
              <b>出价 → 转化的因果链</b>（不是碰巧）：出价高低 → 是否进前三（确定性：和 47
              个对手排序）→ 是否曝光（按坑位曝光率）→ 曝光后按该条 pValue 掷骰子 → 转化。前半段
              确定、后半段概率——出价买到的是"掷骰子的机会和单价"。为对冲运气，排行榜取多
              episode 平均，平台内部还记录无随机性的"期望转化"（pValue × 曝光率累加）交叉验证。
            </p>
          </div>
        </Collapsible>

        <Collapsible title="广告主如何使用 LLM 完成竞价">
          <p style={{ margin: '0 0 6px', color: 'var(--text-secondary)' }}>
            <b>无论市场是 5 万还是 50 万次展示机会，LLM 每个 episode 只被调用 48 次</b>
            （每时段一次）。流程：时段开始时，LLM 读取当前状态（剩余预算、CPA 进度、市场价统计等）
            输出一个系数（如 alpha = 120）；该时段内成千上万条展示机会陆续到来，每条自带各自的
            pValue；执行器逐条机械计算 <span className="mono">出价 = 120 × 该条的 pValue</span>，
            得到 0.036 / 0.132 / 0.084 元…——出价条条不同，但"愿意为单位转化付多少钱"整个时段一致。
          </p>
          <p style={{ margin: '0 0 6px', color: 'var(--text-secondary)' }}>
            <b>广告主侧完全可以复现同样的架构</b>：真实平台的自动竞价本来就是"系统持有系数、逐次曝光
            实时乘 pCVR 出价"，把"LLM 每半小时给一次系数"接到自家出价系统即可，无需 LLM 参与每一次
            竞价。成本实测：500k 市场一轮实验（2 episode、96 次调用）约 5 万 input + 3 万 output
            token，每次决策约 4 秒。若模型输出不合法，平台自动 fallback（沿用前一系数 → PID →
            安全固定值），竞价不中断。
          </p>
          <p style={{ margin: '0 0 10px', color: 'var(--text-secondary)' }}>
            <b>广告主能拿到 pValue 么？</b>分两种情况。① 用平台的<b>自动竞价产品</b>（Google
            tCPA、Meta 成本上限、亚马逊自动竞价等）：pCVR（即 pValue）由平台内部预估并在竞价时刻
            使用，广告主拿不到逐次曝光的原始值——但广告主设置的"目标 CPA / 出价上限"实质上就是在设
            alpha，平台替你完成"× pValue"那一步，所以本架构对应的落地形式是<b>用 LLM 动态调
            tCPA/出价倍率</b>。② 用<b>开放竞价接口</b>（RTB/DSP、手动竞价 API）：广告主或其 DSP
            自建 pCVR 模型逐次预估（大广告主和代理商的普遍做法），此时"LLM 出 alpha × 自有
            pCVR"可原样复制。关键是：<b>拿不拿得到 pValue 不影响本平台结论的迁移性</b>——我们比较的
            是"系数怎么调"这一层的策略优劣；pValue 由谁算、算得准不准是另一层问题，真实迁移前需用
            客户数据校准 pCVR 分布。
          </p>
          {samples.length > 0 && (
            <>
              <div style={{ fontSize: 13, fontWeight: 600, margin: '0 0 6px' }}>
                三行真实日志，看懂一次竞价
              </div>
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
            </>
          )}
        </Collapsible>

        <Collapsible title="47 个对手是谁？市场如何互相影响">
          <div style={{ display: 'grid', gap: 8, color: 'var(--text-secondary)' }}>
            <p style={{ margin: 0 }}>
              模拟平台里实际部署着 <b>48 套独立运行的决策程序</b>：1 个受控位（被换成待测策略）+
              47 个对手。对手构成：<b>12 个 PID</b>（纯规则 pacing）、<b>约 23
              个预训练神经网络模型</b>（IQL、BCQ、TD3+BC、CQL、BC、两种基于模型的 RL 变体——
              AuctionNet 作者在其数据上训练好、随代码仓库分发的 checkpoint）、<b>12 个
              OnlineLP</b>（线性规划优化器）。
            </p>
            <p style={{ margin: 0 }}>
              <b>信息结构</b>：每个时段，48 个广告主收到同构但不同值的信息——各自的 pValue
              数组（同一条展示机会对不同广告主的预估转化概率不同）、各自的剩余预算、各自的历史
              战绩，然后各自跑自己的程序出价。平台把每条展示机会上的 48 个出价排序，前三名获得
              坑位、按 GSP 定价、抽样曝光与转化、扣减预算——不只是统计，是完整执行竞价机制。
            </p>
            <p style={{ margin: 0 }}>
              <b>你的出价会改变对手的行为</b>（多智能体反馈循环）：你出价变高 → 把原本第 3
              名的对手挤出坑位 → 该对手本时段花费和转化减少 → 它的模型看到"花钱太慢" →
              下个时段它调高自己的出价系数 → 市场价格被推高 → 反过来又影响你。这正是"在线模拟"
              与"离线回放"（对手出价冻结）的本质区别，也是正式结论必须用在线模拟的原因。
            </p>
            <p style={{ margin: 0 }}>
              <b>诚实的边界</b>：对手不会"察觉你的存在"并针对你——它们只是各自对市场结果做反应，
              没有对手建模（opponent modeling）。
            </p>
          </div>
        </Collapsible>

        <Collapsible title="四个实验策略简介">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
            {STRATEGY_INTRO.map((s) => (
              <div key={s.name} style={{ border: '1px solid var(--grid)', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>{s.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>{s.what}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{s.how}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
              Prompt 迭代的直接影响（同模型同市场同 seed，500k PV × 2 episodes）
            </div>
            <table className="data" style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  <th>Prompt 版本</th>
                  <th>改动</th>
                  <th>模型</th>
                  <th>score</th>
                  <th>预算利用</th>
                </tr>
              </thead>
              <tbody>
                {PROMPT_VERSIONS.flatMap((v) =>
                  v.rows.map((r, i) => (
                    <tr key={v.ver + r.model}>
                      {i === 0 && (
                        <>
                          <td rowSpan={v.rows.length} style={{ fontWeight: 600 }}>{v.ver}</td>
                          <td rowSpan={v.rows.length} style={{ color: 'var(--text-muted)' }}>{v.desc}</td>
                        </>
                      )}
                      <td>{r.model}</td>
                      <td style={{ fontWeight: 600 }}>{r.score}</td>
                      <td>{r.util}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '6px 0 0' }}>
              一句"没花完的预算是纯损失 + 按 t/48 对表"的 pacing 纪律让 Haiku 提升 14%（5.74→6.55，
              预算利用 63%→72%）。自助实验区可以查看/修改当前 prompt 亲自验证。
            </p>
          </div>
        </Collapsible>

        <Collapsible title="流量从哪来：简易版 vs 复杂版生成器，以及三处数据口径">
          <p style={{ margin: '0 0 6px', color: 'var(--text-secondary)' }}>
            AuctionNet 提供两种流量（PV + pValue）生成器，本平台目前使用<b>简易版</b>：
          </p>
          <table className="data" style={{ fontSize: 12 }}>
            <thead>
              <tr>
                <th></th>
                <th>简易版（本平台在用）</th>
                <th>复杂版（ModelPvGen）</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ fontWeight: 600 }}>原理</td>
                <td>参数化公式：写死的时段流量曲线 + 正态扰动生成 pValue</td>
                <td>深度生成模型：预训练神经网络 checkpoint，生成带特征结构的流量</td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>保真度</td>
                <td>统计形状近似真实</td>
                <td>更接近真实分布（pValue 均值约为简易版 3 倍，市场更"便宜"）</td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>速度</td>
                <td>毫秒级</td>
                <td>CPU 约 2 分钟/episode</td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>硬限制</td>
                <td>PV 数量任意（500k 无压力）</td>
                <td>checkpoint 内置上限 10.5 万 PV/episode，跑不了 500k 标准市场</td>
              </tr>
            </tbody>
          </table>
          <p style={{ margin: '8px 0 6px', color: 'var(--text-secondary)' }}>
            <b>为什么用简易版</b>：① AuctionNet 官方评测入口就用它，保持与官方基准的可比性；
            ② 复杂版撑不起 500k 规模。<b>更好的替代已在路上</b>：官方发布的 21 天预生成数据
            （93GB，即复杂版生成器在 500k 规模的产物）已全部下载并校验，下一步接入
            ReplayTrafficGenerator——在线模拟直接使用官方流量，对手照常实时竞价，等于免费获得
            "复杂版 500k 流量"。
          </p>
          <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
            <b>三处数据口径</b>，看表时请注意：① <b>策略排行榜与 Episode 回放</b> = 简易版流量 +
            48 广告主<b>在线模拟</b>（对手实时反应）；② <b>自助实验</b> = 同口径①（你的 LLM
            进同一个市场）；③ 交叉复核（见 GitHub 仓库 scripts/verify_on_official.py）= 官方
            period-7 数据的<b>离线回放</b>（对手出价冻结、期望转化口径）——分数与①不可直接比大小，
            只用于验证相对排序。period-7 复核结果与排行榜排序一致：IQL 34.3 &gt; LLM Haiku 27.9
            &gt; LLM Opus 14.0 &gt; PID 5.4 &gt; DT 2.8。
          </p>
        </Collapsible>
      </div>
    </div>
  )
}
