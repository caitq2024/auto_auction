# 实现细节记录（供复盘）

更新：2026-07-28（Phase 1 第一轮开发，约 5 小时窗口）
环境：conda `adsim_py311`（Python 3.11.15，torch 2.13.0+cpu）；upstream 复现环境仍为 `auctionnet_py39`。

## 1. 这一轮做了什么

`src/adsim/` 从零实现了内部模拟器核心（对应任务卡 T02–T09、T11），全部测试通过（22 单测/parity + 2 集成），并跑通了第一个 4 策略配对对比实验。upstream 两个仓库保持只读。

```
src/adsim/
├── core/
│   ├── types.py        # T02: TrafficBatch/AuctionResult/AgentObservation/EpisodeSummary
│   ├── rng.py          # T03: RngManager（strict/legacy 双模式）
│   ├── scenario.py     # T06: ScenarioConfig + upstream 48-agent 默认市场表
│   └── runner.py       # T08: EpisodeRunner（在线模拟主循环，多受控 agent）
├── auction/
│   ├── gsp.py          # T04: 三坑位 GSP core
│   └── budget_control.py  # T05: sequential_stop + random_drop_legacy
├── agents/registry.py  # T07: fixed/pid（内部实现）+ upstream:* adapter
├── traffic/parametric.py  # NeurIPSPvGen adapter（修 reset bug）
├── evaluation/
│   ├── metrics.py      # 竞赛评分 score = conv 或 conv*(tCPA/CPA)^2
│   ├── threshold_replay.py  # T09: clean-room 实现（AIGB 无 LICENSE，不抄码）
│   └── compare.py      # T11: 配对多策略对比 + bootstrap CI + markdown 报告
├── storage/event_writer.py  # T08: parquet 明细/summary + resolved config + git rev
└── cli/main.py         # adsim run / adsim compare
```

## 2. 关键设计决策（含理由）

### 2.1 RngManager 双模式（core/rng.py）
- **strict（默认）**：`SeedSequence(entropy=experiment_seed, spawn_key=(episode, tick, module_hash))` 派生独立流。module 名用固定 FNV-1a hash（Python 内置 str hash 有进程盐，不可复现）。
- **legacy**：复刻 upstream 三处固定 seed 行为——`default_rng(1)`（曝光/转化/truncnorm 值采样，每次调用重建）、`adjust_over_cost` 的 `default_rng(1)`、trunc bounds 的 `hash((adv,0,episode))+1019`。int tuple 的 `hash()` 不受 PYTHONHASHSEED 影响，跨进程稳定（已验证）。
- 后果（重要）：strict 模式下不同 experiment seed 的曝光/转化不同，但**流量仍只由 episode 编号决定**（upstream NeurIPSPvGen 的设计）。adapter 加了 `episode_offset` 供未来解耦；CRN 配对实验（GRPO 要用）天然成立——同 episode 同流量。

### 2.2 GSP core（auction/gsp.py）
逐条复刻 upstream 机制语义（这些是机制，不是 bug，两种模式都保留）：
- market price = 每 PV 第 2..4 高 bid，floor 到 reserve price；slot k 支付 market_prices[k-1]；
- 曝光概率 [1.0, 0.8, 0.6] 做 Bernoulli；**slot2 未曝光则同 PV 的 slot3 强制不曝光**（upstream 连续性规则）；
- **unsold 判定 quirk**：`cost == reserve_pv_price` 的 slot 被整个清零（xi/slot/cost/曝光/转化）。副作用：真实赢了但下一名 bid 恰好 ≤ reserve 的 slot 也会被取消。这是 upstream 原样行为，为 parity 保留，测试 `test_reserve_price_floor` 明确固化了这个语义；
- 转化 = truncnorm(pValue, sigma, 每广告主每 episode 抽一次的截断参数) 采样后 Bernoulli × 曝光。
- 新增：`expected_conversion = clip(pValue,0,1) × slot曝光系数`（文档 6.4 的双口径），upstream 没有这个输出。

### 2.3 Budget control（auction/budget_control.py）
结构与 upstream 一致：出价 → 清算 → 检测超支 → 改 bid → 重清算（循环，上限 50 轮）。
- `random_drop_legacy`：按 slot 列随机 drop 超支比例的获胜 PV（legacy 模式下每 agent 重建 `default_rng(1)`，与 upstream bitwise 同源）。
- `sequential_stop`（默认）：对每个超支 agent，按实际扣费的累计和找到预算耗尽点（`searchsorted`），之后的 bid 全部清零。语义 = "按 PV 到达顺序消费预算，花完即停"。注意它也要重清算，因为该 agent 退出后其他 agent 可能补位获胜。

### 2.4 Upstream 策略复用（agents/registry.py）
- **验证过的关键事实：TorchScript checkpoint（`torch.jit.load`）在 torch 2.13/py3.11 下可直接加载 upstream 3.9/torch1.12 存的模型**，且 `simul_bidding_env` 的策略模块本身兼容 3.11（只有 `run/run_test.py` 用了 3.9-only 的 `from collections import Iterable`，我们不 import 它）。所以 adapter 是轻量的：sys.path 注入 + 类实例化 + 每 tick 同步 `remaining_budget`。
- PID 在内部重新实现（`PidAgent`，纯 pacing 逻辑 30 行），因为它是后续 LLM fallback 链的一环，不应依赖 upstream。数值行为与 upstream 一致（parity 测试间接验证）。
- `ScalarAlphaAgent` 基类记录 `last_alpha` → 进 Event Ledger 和 observation，这是未来 LLM/DT 的动作接口（文档 8.3 的 ScalarAlphaAction）。

### 2.5 ScenarioConfig（core/scenario.py）
- upstream 的 48 元素预算表、CPA 表、每类目 8 策略组合表全部收编为**数据**（`UPSTREAM_BUDGETS/UPSTREAM_CPAS/UPSTREAM_STRATEGY_MIX`），`upstream_default_48()` 重建原市场，`controlled={slot: (strategy, kwargs)}` 换入候选策略。
- YAML 支持 `base: upstream_default_48` + 覆盖字段；每次运行 `resolved_scenario.yaml` 落盘。

### 2.6 Runner 与 upstream run_test 的行为差异（有意为之，都有开关或记录）
| 项 | upstream | 内部 | 说明 |
|---|---|---|---|
| 受控 agent 数 | 1 个 player_index | `controlled_agent_ids` 列表 | 文档 3.2 要求 |
| 超支处理 | random drop | sequential_stop 默认，legacy 可选 | 文档 7.5 |
| RNG | 固定 seed | RngManager，`legacy_rng` 可选 | 文档 7.4 |
| compete_pv 口径 | 所有 tick 计入 | 只计实际出价的 tick | 我认为 upstream 把预算耗尽后的 tick 也计入 compete 是口径问题；不影响 score |
| win_pv 口径 | isExposed 求和 | 同 upstream（exposed_pv） | 对齐 |
| observation | 无 | 每 tick 每受控 agent 结构化 observation | LLM/DT 准备 |

### 2.7 Threshold Replay（evaluation/threshold_replay.py）
- **Clean-room**：AIGB 仓库无 LICENSE，故按规则数学定义重写（win iff `bid ≥ leastWinningCost`，cost = lwc），没有复制其源码。接口不同（DataFrame + alpha_fn 回调 vs 它的类结构）。
- 双口径输出：expected（确定性，clip(pValue) 求和）与 sampled（truncnorm+Bernoulli）。两口径分别给 score。
- 超支同样支持 legacy 随机 drop 与 sequential 尾部截断。

## 3. Parity 结果（tests/parity/）

场景：PID @ slot0，5000 PV，episode 0，`legacy_rng=True` + `random_drop_legacy`，对齐 Phase 0 锚点 `outputs/phase0/online_pid_pv5000_ep1_seed1.json`：

| 指标 | upstream 锚点 | 内部 legacy 模式 | 判定 |
|---|---|---|---|
| conversions (reward) | 4 | 4（精确相等） | ✅ |
| cost | 2899.95 | 差 < 1.0 | ✅ |
| win_pv | 1227 | 相对差 < 2% | ✅ |

未做到 bitwise 全对齐的原因：upstream 在 run_test 循环里 while 重清算的迭代顺序与我们 clear_with_budget 的封装存在浮点求和顺序差异；conversions/cost/win_pv 已在容忍误差内，记录为已知差异。

## 4. 首个对比实验（outputs/compare_v1/）

`adsim compare --candidates pid fixed_alpha:alpha=120 upstream:iql upstream:td3_bc --pv-num 20000 --episodes 4 --seed 1`

| 排名 | 策略 | score_mean | conversions | budget_util |
|---|---|---|---|---|
| 1 | pid | 0.861 | 6.25 | 94% |
| 2-4 | fixed_alpha(120) / iql / td3_bc | 0.0 | 0 | <0.5% |

解读：与 Phase 0 审计结论一致——RL checkpoint 和 fixed alpha 是按 500k PV 市场校准的，20k PV 下市场价格结构完全不同，出价过低几乎不赢。**结论仅对 20k PV 场景成立**。产出：`comparison_report.md` + 每策略的 parquet 明细。

### 4.1 500k PV 全规模对比（outputs/compare_fullscale_v1/）

`adsim compare --candidates pid upstream:iql --pv-num 500000 --episodes 2 --seed 1`（单 episode 单策略约 5–6 分钟，16 核 CPU）：

| 策略 | score_mean | conversions | actual CPA | CPA violation | budget_util | paired win vs pid |
|---|---|---|---|---|---|---|
| upstream:iql | **17.78** | 18.5 | 100.5 | +1.3% | 64.8% | 2/2 |
| pid | 6.15 | 17.0 | 172.4 | +72.4% | 99.6% | — |

结论：全规模下排序反转——IQL 用 65% 预算拿到相近转化并把 CPA 压在约束线上（score 不被惩罚），PID 烧完预算但 CPA 超标 72%（score 被 (100/172)² ≈ 0.34 惩罚）。这与竞赛的预期行为一致，验证了：(a) 平台机制正确；(b) **任何策略对比结论必须声明 PV 规模**；(c) 竞赛评分对 CPA 违约的平方惩罚是排序的主导项。

## 4.2 Decision Transformer 基线（第二段开发）

数据→训练→评估全链路已打通，全部使用自产数据（零下载）：

1. **数据**：`smoke_test_auctionnet_online.py --generate-log`，50k PV × 4 episodes → 4 × ~380MB 原始 log CSV。
2. **转换**：upstream `TrainDataGenerator`（log → 16 维状态的 tick 级轨迹，每个 (episode, advertiser) 一条 48 步轨迹，共 192 条）。
3. **训练**：`scripts/train_dt_baseline.py`（py39 env，upstream DT 代码作库使用，Apache-2.0）。5000 步 × batch 32，CPU 上 179 秒。模型/normalize_dict 存 `outputs/dt_baseline/saved_model/DTtest/`（不写入 upstream 目录）。
4. **推理接入**：`src/adsim/agents/dt.py`（`DtAgent`，registry 名 `"dt"`）。16 维状态构造逐项复刻 upstream `DtBiddingStrategy`；upstream dt.py 可直接在 py311/torch2.13 下 import。
   - 踩坑 1：`load_net` 收文件路径不是目录（与 `save_net` 不对称）；
   - 踩坑 2：`take_actions` 返回 shape (1,) 数组，numpy≥2 禁止对其 `float()`，需 `.reshape(-1)[0]`。
5. **对比**（50k PV × 4 ep，seed 1，`outputs/compare_dt_v1/`）：

| 策略 | score_mean | conversions | budget_util |
|---|---|---|---|
| pid | 3.23 | 10.75 | 95% |
| **dt（自训 5k 步）** | **1.59** | **9.5** | **100%** |
| upstream:iql | 1.00 | 1.0 | 2% |

解读：DT 在与训练数据同规模（50k PV）的市场上行为合理（转化量接近 PID、预算用满），5000 步 CPU 快训还打不过 PID 但显著好于分布不匹配的 IQL checkpoint。这是"能训练、能接入、能评估"的验证，不是调优后的结论；正式 DT 基线要用 500k PV 数据 + 更多 episodes + p5 GPU 训练。

## 4.3 LLM Bid Agent（第二段开发）

`src/adsim/agents/llm.py`，按文档 §11 实现，8 个单测覆盖安全管道：

- **协议**：每 tick 一次调用，输入 = SYSTEM_PROMPT + AgentObservation JSON（runner 通过 `observe()` hook 在出价前注入，见 runner.py），要求输出 `{"action":"set_alpha","alpha":...,"confidence":...,"reason_code":...}`。
- **安全管道**（全部在 agent 层，绝不进 auction core）：JSON 解析（容忍 markdown 代码块）→ schema/类型校验 → NaN/Inf 拒绝 → clip 到 [min_alpha, max_alpha]（默认 [0,200]）→ 失败时 fallback 链 **previous valid alpha → 内部 PID → safe fixed alpha(15)**。
- **轨迹**：每次调用记录 prompt、原始输出、解析结果、实际执行 alpha、fallback 原因、延迟——`LLMCallRecord` 列表即 SFT/GRPO 导出的原料。
- **client 可插拔**：任何 `(prompt: str) -> str` callable。测试用 `MockLLMClient`；接真模型时（Claude API 或 p5 上的 vLLM）只需实现同签名，无需改 agent。

## 4.4 LLM prompt-only 基线（Bedrock，第一个真实 LLM 竞价实验）

模型：`us.anthropic.claude-haiku-4-5`（Bedrock Converse API，注意必须用 `us.` inference profile 前缀，裸 model id 会报 on-demand 不支持）。50k PV × 2 episodes，LLM 占 slot 0（budget 2900 / tCPA 100），48 次调用/episode。

三轮迭代（完整轨迹 JSONL 在各输出目录）：

| 版本 | 问题/改动 | 结果 |
|---|---|---|
| v1 | JSON 解析只剥 markdown 围栏，模型在 JSON 后附加分析文字 → `Extra data` 解析全败 | fallback 100%，全程 PID 保底 alpha=15，0 转化 |
| v2 | 解析器改为提取首个平衡 `{...}` 块；prompt 加尺度提示（pValue ~1e-4、市场价 ~0.1-1、合理 alpha 数十到数百） | fallback 0%；ep0 拿到 1 转化 / score 0.36，但 alpha 顶到 200 clip 上限，预算只花 6% |
| v3 | `max_alpha` 200 → 2000（同市场 PID 的 alpha 会到 ~1200，200 的 clip 是人为瓶颈） | **ep0: 2 转化, CPA 108.6 vs 目标 100, score 1.70**；ep1: 1 转化, score 0.13 |

成本/延迟（haiku）：约 4s/决策、每 episode 48 调用 ≈ 530 input + 300 output tokens/调用；2 episodes 总计约 51k in / 29k out tokens。

结论：管道验证完成——结构化输出、校验、fallback、轨迹导出全部工作。haiku prompt-only 还远弱于 PID（3.23）/DT（1.59）同场景均值，但这在预期内：它没有历史数据可学，靠 prompt 里的市场统计冷启动。下一步研究议题（非工程）：更强教师模型（sonnet/opus）、few-shot 市场先验、observation 里加多 tick 趋势、蒸馏。

**给复盘的关键教训**：(1) LLM 输出解析必须按"首个平衡 JSON 块"提取，不能假设 clean JSON；(2) action bounds 是实验参数不是安全常数——clip 上限低于市场竞争水平会静默阉割策略；(3) 尺度提示（pValue/市场价的量级）对 LLM 在这种非常识数值环境里的表现是决定性的。

## 5. 测试清单（32 个，全过）

- `tests/unit/test_gsp.py`（8）：文档 15.1 手算例、reserve floor、无赢不扣费、未曝光无转化、提价不降名次、GSP 价 ≤ 自身 bid、slot ∈ {0..3}
- `tests/unit/test_rng_and_budget.py`（7）：同/异 seed、tick/module/episode 流独立、legacy 复刻、两种超支模式不超预算
- `tests/unit/test_threshold_replay.py`（5）：零 alpha、全赢成本、预算约束、同 seed 确定、expected < wins
- `tests/unit/test_llm_agent.py`（8）：合法 JSON 执行、markdown 包裹容忍、clip、NaN/Inf 拒绝→PID fallback、垃圾输出→previous fallback、client 异常处理、轨迹完整性、错误 action 类型拒绝
- `tests/parity/test_upstream_parity.py`（3）：见第 3 节
- `tests/integration/test_runner_determinism.py`（2）：同 seed 端到端一致、异 seed 变化

## 6. 已知问题与下一步

1. ~~500k PV 正式对比未跑~~ 已完成（4.1 节）。upstream 侧同规模 legacy parity 锚点仍待补（需 upstream 跑 500k 约 45 分钟）。
2. strict 模式的流量仍由 episode 决定（见 2.1），多样化流量要靠 episode_offset 或未来 Replay/Learned generator。
3. `upstream:onlinelp` 依赖 `official_agent/onlineLpTest/episode-{i}.csv`，episode 大于文件数时会退化，adapter 未特殊处理（upstream 同样问题）。
4. Event Ledger 目前是 tick 级 + observation JSON，PV 级明细（文档 8.5 全字段）留给 Exact Re-auction 需要时再加，避免 500k PV × 48 agent 的明细爆盘。
5. 下一轮按既定顺序：**DT 基线（用 GENERATE_LOG 自产数据在 CPU/p5 训练）→ LLM agent adapter（observation 已就绪，只差 model client + JSON schema 校验 + fallback 链）**。
6. GPU：p5en.48xlarge（i-0e33ab29bb6ceb8ff，us-west-2，running）可用 EFS 上同一代码库直接跑，密钥在 EFS。

## 7. 如何复现本轮所有结果

```bash
conda activate adsim_py311   # 或直接用绝对路径的 python
cd /home/ec2-user/efs/agentic_bidding/auction-sim-platform
pip install -e .
pytest tests -q                       # 24 passed
adsim compare --candidates pid fixed_alpha:alpha=120 upstream:iql upstream:td3_bc \
  --pv-num 20000 --episodes 4 --seed 1 --out outputs/compare_v1
```
