# Upstream Parity 报告（Phase 0 初版）

日期：2026-07-28。本文件在 Phase 1/2 每实现一个对应组件后更新。

## 1. Parity 基线的定义

- **在线基线**：`third_party/AuctionNet` @ `c20de63`，Python 3.9.12，`config/test.gin` + 显式 `Controller.pv_num` 绑定 + `NeurIPSPvGen.reset` monkeypatch（见 audit 新发现 A），入口 `scripts/smoke_test_auctionnet_online.py`。
- **离线基线**：`third_party/AIGB_Baseline` @ `550f0b1` 的 `run_evaluate.py` 循环逐行复刻（`scripts/smoke_test_aigb_offline.py`），仅参数化了数据路径与 budget/CPA。

所有基线结果 JSON 存于 `outputs/phase0/`，均验证同 seed bitwise 复现。

## 2. 当前锚点数字

场景：`neuripsPvGen`，48 agents，48 ticks，seed=1，player_index=0（budget 2900，tCPA 100，category 0）。

| ID | 配置 | score | reward | cost | CPA | budget_util |
|---|---|---|---|---|---|---|
| ON-PID-5k | 在线 PID, 5000 PV × 1 ep | 4.84e-6 | 4 | ~2900 | 642.5 | ~100% |
| ON-PID-50k | 在线 PID, 50000 PV × 2 ep | 8.25e-6 | 7 | — | 1001.1 | 98.4% |
| ON-IQL-50k | 在线 IQL, 50000 PV × 2 ep | 0.0 | 0 | ~6 | ~5.9e10 | 0.2% |
| ON-PID-500k | 在线 PID, 500000 PV × 1 ep（意外全量运行，可作全规模锚点） | 2.44e-4 | 16 | 2900 | 181.2 | ~100% |
| OFF-THR-adv0 | 离线 threshold, adv0, bid=100·pValue, 4973 PV | 0.0 | 0 conv | 2.21 | — | — |

## 3. Threshold Replay vs 在线 ground truth（同一份历史 bid）

用 5000 PV 在线运行产出的 log（`data/log/0.csv`），把**历史 bid 原样**送入 threshold 规则 `win = bid ≥ leastWinningCost`，与在线日志中的真实结果对比：

| adv | 在线 win | threshold win | 在线 cost | threshold cost | 在线 conv | threshold E[conv] |
|---|---|---|---|---|---|---|
| 0 | 1227 | 1692 (+38%) | 2570 | 2975 (+16%) | 4 | 1.31 |
| 1 | 1 | 2 | 0.1 | 0.1 | 0 | 0.00 |
| 7 | 1 | 2 | 0.1 | 0.1 | 0 | 0.00 |
| 20 | 0 | 0 | 0.0 | 0.0 | 0 | 0.00 |

结论（与主文档第 6 节预期一致，现有量化证据）：

1. threshold 规则**系统性高估 win 数**（+38%）：`bid ≥ leastWinningCost` 忽略了曝光采样（slot 系数 1.0/0.8/0.6）——在线上赢了 slot 但未曝光的 PV 不产生 cost/win 记账。
2. threshold 的 `cost = leastWinningCost` 忽略 GSP 分坑位定价，成本口径也偏高（+16%）。
3. 转化口径完全不同：在线是 Bernoulli 采样整数，threshold 侧这里报 expected conversion。两口径必须分开报告（主文档 6.4）。

因此 threshold replay 只可用于接口验证与粗排——这是 Phase 2 需要 Exact Fixed-Opponent Re-auction 的直接证据。

## 4. legacy 行为清单（内部实现必须以 legacy_mode 复刻的项）

| 行为 | upstream 位置 | strict 模式替代 |
|---|---|---|
| overspend 随机 drop（seed=1）后整轮重算 | `run/run_test.py::adjust_over_cost` | `sequential_stop` |
| PvGen reset 回退到 500k PV | `NeurIPSPvGen.reset` | reset 保持配置 |
| 曝光/转化 RNG：`hash((adv,tick,episode))+MAGIC` 派生 | `BiddingEnv` | SeedSequence 派生树 |
| 模块级 `SEED=1019` 影响 import 顺序敏感的随机流 | `NeurIPSPvGen` 模块顶部 | 无全局 seed 副作用 |
| bid<0 截为 0；`min_remaining_budget=0.1` 停竞价 | `run_test` / gin | 保留（行为合理） |

## 5. 待办

- [ ] Phase 1 GSP core 与 `legacy_mode` 下的在线锚点（本文件第 2 节）对齐到容忍误差内。
- [ ] Phase 2 ThresholdReplayEvaluator 与 OFF-THR 锚点严格对齐（同 seed 同结果）。
- [ ] 在 500k PV 下补一组正式锚点（PID + IQL，≥2 seeds），当前 500k 数字来自单次运行。
- [ ] Exact Re-auction 实现后，把第 3 节表格扩展成 threshold vs exact vs online 三方对比。
