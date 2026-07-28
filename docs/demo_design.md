# Bid 平台前端 Demo 设计草案

日期：2026-07-28 · 状态：Proposal（待用户选型）

## 目标

把 auction-sim-platform 的实验结果做成可展示的 demo，未来落位 `aifl-dashboard/tools/` 下（与预算分配平台平级）。核心受众：团队内部演示"多策略竞价对比 + LLM agent 决策过程"。

## 已有的数据基础（demo 只需要读这些，零后端计算）

每次 `adsim run/compare` 已产出：

| 文件 | 内容 | demo 用途 |
|---|---|---|
| `episode_summary.parquet/csv` | 每 (episode, advertiser) 的 score/转化/CPA/预算利用 | 排行榜、策略卡片 |
| `tick_events.parquet` | 每 tick 每广告主的 alpha/出价/胜出/花费/转化 + observation JSON | 时序曲线、tick 回放 |
| `trajectory_ep*.jsonl`（LLM） | 每次 LLM 调用的 prompt/原始输出/解析动作/fallback/延迟 | **决策过程透视**（最有演示价值） |
| `comparison_report.md` | 排名 + 置信区间 | 直接渲染 |
| `resolved_scenario.yaml` / `run_meta.json` | 完整配置与元数据 | 可复现性展示 |

## 三个候选形态

### A. 静态快照 SPA（推荐起步）
- 一个 `export_demo.py` 把上述 parquet/JSONL 聚合成单个 `demo_data.json`；前端纯静态（React/Vite，与 aifl-dashboard 同栈），读 JSON 渲染。
- 页面结构：
  1. **策略排行榜**：score/转化/CPA/预算利用率 + CI，按场景切换（50k/500k PV）；
  2. **Episode 回放**：48 tick 时间轴，多策略 alpha/花费/转化曲线叠加（配对 seed 下可直接对比）；
  3. **LLM 决策透视**：逐 tick 展示 observation → 模型 JSON 输出 → reason_code → 实际效果，fallback 高亮；
  4. 场景/配置元数据页。
- 优点：与 aifl-dashboard 的"snapshot.json + 只读 SPA"模式完全同构，将来并入 tools/ 几乎零改造；无服务、无权限问题。
- 成本：1-2 天。

### B. 轻后端交互版
- FastAPI 包一层：浏览器里选策略/预算/tCPA/seed → 触发 `adsim run` → 轮询结果。
- 优点：演示"现场发起实验"；缺点：要管运行队列/超时（500k PV 一次 6 分钟、LLM episode 3-8 分钟），demo 现场风险高。
- 建议作为 A 之后的增量，且现场演示用 50k PV + 缓存兜底。

### C. Jupyter/报告式
- 最省事但"平台感"弱，不建议作为对外形态，可作内部分析补充。

## 推荐路径

A 先行（静态快照，数据管道即 `export_demo.py`），跑顺后按需加 B 的"发起实验"按钮。快照 schema 设计时直接对齐 aifl-dashboard 的 versioning 约定，未来入驻 tools/ 时不换格式。

## 待用户确认

1. 形态选 A / A+B？
2. demo 第一版放本仓库 `demo/` 自包含开发，还是直接开在 aifl-dashboard/tools/（涉及那边 scope 变更，见 CLAUDE.md 边界声明）？
