# auto_auction · 广告竞价多策略模拟实验平台

基于 [AuctionNet](https://github.com/alimama-tech/AuctionNet)（NeurIPS 2024, Apache-2.0）的广告竞价研究平台：48 个广告主对最多 50 万次展示机会实时竞价（3 坑位 GSP），把受控广告主的策略换成**传统算法 / 离线强化学习 / Decision Transformer / LLM** 同台对比，按 NeurIPS 竞赛口径（转化数 × CPA 超标平方惩罚）评分。

## 当前能力一览

| 模块 | 状态 |
|---|---|
| 内部模拟器核心（GSP、预算控制、RNG 管理、多受控 agent） | ✅ `src/adsim/`，32 个测试全过，与 upstream 锚点 parity 对齐 |
| 策略：PID / Fixed / IQL 等 upstream checkpoint / 自训 DT / LLM | ✅ `agents/registry.py`，统一接口 |
| LLM 竞价 agent（每时段一次结构化决策 + 校验 + 三级 fallback + 轨迹导出） | ✅ `agents/llm.py`，支持 Bedrock（含 BYO API key 的 BearerTokenClient，推理模型 120s 超时 + 重试加固） |
| Prompt 工程闭环（v1 基础 → v2 pacing 纪律，得分可量化对比） | ✅ Haiku 500k：5.74 → 6.55，预算利用 63% → 72% |
| 多策略配对比较（同市场同随机数、bootstrap CI、markdown 报告） | ✅ `adsim compare` CLI |
| DT 训练管道（自产/官方数据 → upstream DT 训练 → 接回评估） | ✅ `scripts/train_dt_baseline.py`；结论：官方数据版 1.51 < 自产版 2.23，瓶颈在模仿目标而非数据 |
| 官方数据集（21 period / 93GB，逐分片下载 + schema 校验） | ✅ `scripts/download_official_data.py`，全部就绪 |
| 官方分布交叉复核（alpha 序列 threshold replay） | ✅ `scripts/verify_on_official.py`，period-7 排序与模拟器榜一致：IQL 34.3 > Haiku 27.9 > Opus 14.0 > PID 5.4 > DT 2.8 |
| SFT 数据导出（教师轨迹 → chat JSONL） | ✅ `training/rollout.py`，首批 177 条 |
| Web demo（排行榜 / 48-tick 回放 / LLM 决策透视 / 自助实验 BYO-key + TLS） | ✅ `demo/`，已集成团队 aifl-dashboard `/tools/auction-bid`（PR #2） |

## 下一步：ReplayTrafficGenerator（进行中）

把官方 21 天预生成数据接成在线模拟的流量源——读官方 CSV 的 PV/pValue 序列，48 个对手照常实时竞价。等于在"复杂版生成器的 500k 流量"上跑完整多智能体模拟（复杂版生成器 checkpoint 上限 10.5 万 PV/episode，跑不了标准市场；官方数据没有这个限制），用于最终确认排行榜与训练数据生成。之后：教师扩样选型（≥10 ep）→ SFT/蒸馏（p5 GPU）→ GRPO。

### 500k PV 全规模排行榜（当前基线）

| # | 策略 | score | 实际 CPA（目标 100） |
|---|---|---|---|
| 1 | IQL (Implicit Q-Learning) | 17.78 | 100.5 ✓ |
| 2 | LLM Claude Opus 4.8 (prompt-only) | 7.63 | 109.1 |
| 3 | PID | 6.15 | 172.4 |
| 4 | LLM Claude Haiku 4.5 (prompt-only) | 5.74 | 145.9 |
| 5 | DT（自训 20k 步） | 2.23 | 248.6 |

> 所有数字为 simulated 结果（模拟器口径），未经真实平台数据校准。

## 快速开始

```bash
# 环境：Python 3.11
conda create -y -n adsim_py311 python=3.11
pip install -e . && pip install fastapi uvicorn boto3

# 跑一个 4 策略对比（20k PV × 4 episodes，几分钟）
adsim compare --candidates pid upstream:iql dt fixed_alpha:alpha=120 \
  --pv-num 20000 --episodes 4 --seed 1 --out outputs/my_compare

# LLM 竞价基线（需要 Bedrock 权限）
python scripts/run_llm_baseline.py --model us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --pv-num 50000 --episodes 2 --max-alpha 2000 --out outputs/my_llm_run

# Web demo（先导出数据，再起前后端）
python scripts/export_demo.py
cd demo/server && uvicorn api:app --port 8688 \
  --ssl-keyfile certs/adsim-key.pem --ssl-certfile certs/adsim-cert.pem &
cd .. && npm install && npm run dev
```

## 仓库结构

```
src/adsim/          # 模拟器核心：core/(runner,scenario,rng) auction/(gsp,budget)
                    # agents/(pid,dt,llm,upstream adapter) evaluation/ training/ storage/
demo/               # Web 实验台：React SPA + FastAPI 自助实验后端(demo/server/)
scripts/            # 复现脚本：smoke test / DT 训练 / LLM 基线 / demo 数据导出
tests/              # unit + parity(对齐 upstream 锚点) + integration(确定性)
docs/               # upstream 审计、parity 报告、实现细节(IMPLEMENTATION_DETAILS.md)
outputs/            # 实验产物（parquet 明细 + 轨迹 JSONL + 基线结果）
third_party/        # AuctionNet/AIGB（只读，commit 锁定于 UPSTREAM_LOCK.json，不入库）
```

## 复现与文档

- **实现细节与实验记录**（复盘入口）：`docs/IMPLEMENTATION_DETAILS.md`
- Phase 0 upstream 审计：`docs/upstream_audit.md` / `docs/upstream_parity.md`
- 进度与下一步：`IMPLEMENTATION_STATUS.md`
- Demo 设计：`docs/demo_design.md`

## 硬约束

- `third_party/` 只读（AIGB Baseline 无 LICENSE，仅作参考，不复制源码）；
- 不连接真实广告账户，不执行真实出价；
- 用户自带的 Bedrock API key 只存内存，不落盘、不回显、不入日志。
