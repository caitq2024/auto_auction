# Upstream 审计报告（Phase 0）

日期：2026-07-28
环境：AWS EC2，16 vCPU（Xeon 8259CL）、62GB RAM、**无 GPU**（nvidia-smi 无驱动）、EFS 存储充足。
Python：conda env `auctionnet_py39`（Python 3.9.12），torch 1.12.0+cpu，依赖锁定于 `requirements-upstream-py39.lock.txt`。

## 1. Commit lock 与许可

见 `third_party/UPSTREAM_LOCK.json`：

| 仓库 | commit | 许可 |
|---|---|---|
| AuctionNet | `c20de63` (2025-04-25) | Apache-2.0，LICENSE.txt 存在 |
| AIGB_Baseline | `550f0b1` (2024-08-21) | **无 LICENSE 文件** — 只作阅读/算法参考，不复制源码进内部代码 |

两个目录均按只读处理；所有必要变更以 monkeypatch（`scripts/`）或 adapter（未来 `src/adsim/`）实现。

## 2. 能否运行

**能。** 两条路径均已在最小规模下跑通并可同 seed bitwise 复现：

- AuctionNet 在线评测（`run/run_test.py`，48 agent、48 tick、GSP 三坑位），PID 与 IQL 两种受控策略。
- AIGB threshold 离线评测（`run/run_evaluate.py` 逻辑），使用模拟器 `GENERATE_LOG` 自产的小样本 CSV，未下载任何官方数据。

结果 JSON 存于 `outputs/phase0/`。

## 3. 缺失文件

1. **`strategy_train_env/bidding_train_env/saved_model/` 整个目录缺失**（AuctionNet）。
   `main_test.py` 的默认路径依赖 `PlayerBiddingStrategy = IqlBiddingStrategy`，其构造函数从 `saved_model/IQLtest/` 加载 checkpoint → `ImportError` 后 runner 会静默 fallback 到 PID。README 指引从预生成数据自行训练得到这些模型。
   规避：smoke 脚本直接注入 player agent，不走 `strategy_train_env` 导入链；环境侧 47 个对手用的 checkpoint 在 `simul_bidding_env/strategy/official_agent/` 内齐全（154MB，随 git 分发）。
2. **AIGB_Baseline 无任何数据文件**，`run_evaluate.py` 硬编码 `./data/traffic/period-7.csv`。规避：用 AuctionNet 模拟器生成的 log CSV（schema 与官方数据集 readme 的 18 列一致）。
3. AIGB_Baseline 无 LICENSE（见上）。

## 4. 依赖问题

- `requirements.txt` 里的 `gin==0.1.006` 是 PyPI 上一个无关包，真正需要的是 `gin_config==0.5.0`；只装后者即可。
- `torch==1.12.0` 官方 index 无 cp39 CPU wheel 名称冲突问题，用 `--index-url https://download.pytorch.org/whl/cpu` 装 `1.12.0+cpu` 成功。本机无 GPU，所有 checkpoint（TorchScript `torch.jit.load`）在 CPU 上可正常推理。
- `run/run_test.py` 使用 `from collections import Iterable`（Python 3.10+ 移除），确认了 upstream 必须跑在 3.9；内部平台（3.11）必须走 adapter 层。
- Python 3.9.12 通过 conda 创建成功；系统自带 3.9.21 未使用（保持与 upstream 推荐版本一致）。

## 5. 已验证的文档第 7 节问题 + 新发现

| 问题 | 验证结果 |
|---|---|
| 7.1 48-agent 硬编码 | 确认。`Controller.calculate_budget()` / `get_cpa_constraints()` 为 48 元素硬编码数组；`initialize_agents()` 按 category 奇偶写死 8 种策略组合。改 `num_category` 会与数组长度不一致。 |
| 7.2 默认非 learned generator | 确认。`test.gin` 用 `neuripsPvGen`（参数化）；`ModelPvGenerator` 才加载 `PV_model/Pv_latest.pth`。 |
| 7.3 配置未绑定 | **确认且比文档更糟**：`test.gin` 定义 `PVNUM = 500000` 但从未绑定到 `Controller.pv_num`（gin 宏定义了却没被引用）。需显式传 `Controller.pv_num = N`。 |
| 7.4 固定 seed 滥用 | 确认多处：`NeurIPSPvGen` 模块级 `SEED=1019`；`BiddingEnv` 内 `default_rng(seed=DEFAULT_SEED)` 每 tick 重建；`run_test.adjust_over_cost` 每次 `default_rng(seed=1)`；`main_test.py` 全局 seed(1)。同 seed bitwise 复现已验证成立，但 episode 间随机性来源仅是 `episode` 编号。 |
| 7.5 overspend 随机删除 | 确认。在线：`adjust_over_cost` 按比例随机将已赢 bid 置 0 后整轮重算（while 循环）；离线：`run_evaluate.py` 同样随机 drop。 |
| **新发现 A** | **`NeurIPSPvGen.reset()` 调 `self.__init__(episode=episode)` 不透传构造参数** → 每次 episode reset 后 `pv_num` 静默回到 500000。这就是为什么第一次 smoke test 配了 5000 PV 却跑了 499980 PV。smoke 脚本已 monkeypatch 修复并记录。Phase 1 必须在 adapter 中处理。 |
| **新发现 B** | `Controller.__init__` 默认值（`num_tick=24, num_category=5`）与 gin 配置（48/6）不一致——不用 gin 直接实例化会得到不同市场。内部平台一切参数必须显式来自 ScenarioConfig。 |
| **新发现 C** | AIGB 离线循环里 `historyAuctionResult` 用 `(status, status, cost)` 占位（status 重复充当 slot），与在线环境 `(xi, slot, cost)` 语义不一致；依赖 slot 的策略在离线评估下会拿到错误输入。 |

## 6. 数据需求

- **本轮零下载**。用 `GENERATE_LOG=True` 在 5000 PV × 1 episode 下自产 36MB 训练格式 CSV（18 列，schema 与 `pre_generated_dataset/readme_dataset.md` 一致），足够驱动 AIGB 离线评测与后续 Threshold Replay parity 测试。
- 完整数据 80GB（另有分 period 文件）。何时需要：训练 IQL/DT 等 player 模型、或做官方数据分布上的 replay 评估时。建议届时先下载单个 period（约 2GB 量级）并校验字段，需事先报告存储/时间预算。

## 7. Smoke test 结果摘要

硬件：16 vCPU CPU-only。所有运行同 seed 两次 bitwise 一致（result JSON 逐字段相等）。

| 运行 | 规模 | 结果 | 耗时 / 峰值内存 |
|---|---|---|---|
| 在线 PID (player_index=0, budget 2900, tCPA 100) | 5000 PV × 1 ep | reward=4, CPA=642, score≈4.8e-6 | 6.8s / 730MB |
| 在线 PID | 50000 PV × 2 ep | reward=7, budget_util≈98%, CPA 超约束严重 | 15.3s / 912MB |
| 在线 IQL（官方 checkpoint） | 50000 PV × 2 ep | reward=0, budget_util≈0.4%（bid 极低，几乎不赢） | 16.1s / 913MB |
| 在线 PID + generate_log | 5000 PV × 1 ep | 产出 36MB CSV | 9.9s |
| AIGB 离线 threshold（bid=cpa·pValue） | adv0, 48 tick, 4973 PV | conv=0, cost=2.2, score=0 | 0.8s / 184MB |

解读（重要）：小流量下预算/tCPA 与流量规模严重失配——48 个 agent 的预算表是按 500k PV 设计的，5k–50k PV 时市场价被抬高、转化稀少，所以 reward 个位数、CPA 超约束是**预期现象**，不代表跑错。IQL reward=0 同理：checkpoint 是在 500k PV 分布上训练的，小流量下其学到的 alpha 太低。全量 500k PV 的一次意外运行（第一次 smoke，pv_num 未生效）给出 PID reward=16、win_pv 26473、budget_util≈100%，量级合理，可作全规模锚点。

## 8. 结果是否可复现

- 同 config + 同 seed：**bitwise 可复现**（在线与离线均验证）。
- 代价：复现性来自大量硬编码 seed（7.4），episode 间/实验间的"随机性"实际非常受限——这正是 Phase 1 RNG manager 要替换的行为，替换后需以 `legacy_mode` 保留现行为供 parity。

## 9. 与主文档的差异

1. 文档 3.3 说 slot 曝光系数 `[1.0, 0.8, 0.6]`——已确认（`BiddingEnv.slot_coefficients`）。
2. 文档 7.3 怀疑 PVNUM 未绑定——确认属实，且叠加新发现 A（reset 回退），两个 bug 叠加使"改小流量"在原始入口 `main_test.py` 下不可能生效。
3. 文档建议 smoke 用 1000–20000 PV——可行，但注意上面第 7 节的预算失配解读；正式 parity 数字应在 500k PV 下取。
4. `main_test.py` 只循环 `player_index in range(0, 2)` 且写死 `NUM_EPISODE=2`，并非完整 48-agent 评测入口；我们的 smoke 脚本等价复刻其单 player 路径。
