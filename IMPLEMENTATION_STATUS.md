# IMPLEMENTATION_STATUS

更新：2026-07-28

## 已完成

- [x] Phase 0 / Step 1 环境检查：16 vCPU、62GB RAM、EFS 存储充足、**无 GPU**；conda 26.3.2、git 2.47.1、git-lfs 3.7.1；无 uv。
- [x] Phase 0 / Step 2 内部仓库骨架（本目录），git 已初始化。
- [x] Phase 0 / Step 3 upstream 克隆并锁定：AuctionNet `c20de63`（Apache-2.0）、AIGB_Baseline `550f0b1`（**无 LICENSE**）。见 `third_party/UPSTREAM_LOCK.json`。
- [x] Phase 0 / Step 4 smoke test：
  - 在线：PID（fixed 亦可用）与 IQL（官方 checkpoint）在 5k/50k PV 下跑通，同 seed bitwise 复现；
  - 离线：AIGB threshold 评估在自产 36MB 样本 CSV 上跑通并复现；
  - 未下载任何官方数据。
- [x] Phase 0 / Step 5 审计与 parity 报告：`docs/upstream_audit.md`、`docs/upstream_parity.md`、baseline JSON 在 `outputs/phase0/`。

## 当前 blocker

1. **无 GPU**：Phase 0–3（环境重构、评估、经典基线推理）纯 CPU 足够；Phase 4+ 的 LLM 推理/蒸馏/GRPO 训练需要外部推理端点或 GPU 机器，需在进入 Phase 4 前决定。
2. **AIGB_Baseline 无 LICENSE**：只读参考。Threshold Replay 将按公式重写（阈值规则一行数学，无抄码必要），不复制其源码。
3. **`saved_model/` 缺失**导致 upstream 官方入口 `main_test.py` 的 player IQL 路径不可用（fallback 到 PID）。不阻塞：环境侧 47 个对手 checkpoint 齐全；需要 player 侧 learned 模型时可自训或改用 `simul_bidding_env` 侧 checkpoint（smoke 脚本已这样做）。
4. 正式 500k PV 锚点未跑（现有 500k 数字来自单次运行），列入 Phase 1 验收项。

## 与设计文档不同的决策

- smoke 入口不使用 upstream `main_test.py`（其硬编码 range(0,2) 循环且依赖缺失的 saved_model），改为 `scripts/smoke_test_auctionnet_online.py` 等价复刻 `run_test` 单 player 路径并注入 player agent。
- 发现两个文档未列出的 upstream bug（audit 新发现 A/B）：`NeurIPSPvGen.reset()` 参数回退、`Controller` 默认参数与 gin 不一致。

## Phase 1 patch 计划（下一步，待确认后执行）

原则：不改 upstream；`src/adsim/` 全新实现 + parity 测试对齐 `legacy_mode`。

1. **T02 核心数据结构**（`core/types.py`）：TrafficBatch、BidMatrix、AuctionResult、AdvertiserState、EventBatch；mypy 严格模式。
2. **T03 RNG manager**（`core/rng.py`）：`SeedSequence` 按 experiment/episode/tick/module 派生；提供 `legacy_mode` 复刻 upstream 固定 seed 行为（BiddingEnv 的 hash+MAGIC 派生、adjust_over_cost 的 seed=1、PvGen 的 SEED=1019），使 parity 测试可 bitwise 对齐。
3. **T04 GSP core**（`auction/gsp.py`）：三坑位 GSP + reserve price + slot 曝光系数 [1.0,0.8,0.6]；手算单测（文档 15.1 的 bids=[0.9,0.8,0.6,0.4,0.2]）+ property tests（单调性、支付上界、slot∈{0..3}）。
4. **T05 budget control**（`auction/budget_control.py`）：`sequential_stop`（默认）与 `random_drop_legacy`（复刻 while 重算循环，含 seed=1）。
5. **T06 ScenarioConfig**（`core/scenario.py`）：YAML → resolved config 落盘；把 Controller 的 48 元素预算/CPA 硬编码表收编为默认 scenario `auctionnet_default_48.yaml`；agent 数量/类目/策略组合全部配置化。
6. **T07 upstream strategy adapter**（`agents/upstream_adapter.py`）：在 3.11 进程中隔离加载 upstream 策略 checkpoint（TorchScript 可直接 `torch.jit.load`，绕开 upstream 的 3.9-only import 链；PID/OnlineLP 纯逻辑可直接按接口包装）；支持 `controlled_agent_ids: list[int]`。
7. **T08 Event Ledger**（`storage/event_writer.py`）：文档 8.5 字段 → parquet 明细 + episode summary。
8. **T09 Threshold Replay**（`evaluation/threshold_replay.py`）：按公式重写（不抄 AIGB 源码），与 `outputs/phase0/aigb_offline_*.json` 锚点同 seed 对齐。
9. **parity gate**：`tests/parity/` 里以 Phase 0 锚点为 golden file；`legacy_mode=true` 下在线 5k PV PID episode 与 upstream 结果对齐后才关闭 Phase 1。

预计顺序：T02→T03→T04→T05 可并行于 T06；T07/T08 随后；T09 最后（依赖 T02/T03）。

## 未开始（按文档要求暂停）

LLM Agent（Phase 4）、GRPO（Phase 5）、BudgetAllocator/Mattel（Phase 6）、UI（Phase 7）。
