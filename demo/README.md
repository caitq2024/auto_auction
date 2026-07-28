# AdSim 竞价策略实验台 Demo（方案 A：静态快照 SPA）

零后端：`scripts/export_demo.py` 把实验产物（parquet / 轨迹 JSONL）聚合成
`public/demo_data.json`，前端纯静态渲染。未来放入 aifl-dashboard/tools/ 时
整个 `demo/` 目录可直接拷贝（与 agentic_advertising/web-tool 同栈：React 19 + Vite + TS）。

## 页面结构

1. **策略排行榜** — 竞赛得分排序，CPA 达标/超标标记，场景切换（500k / 50k PV）
2. **Episode 回放** — 48 tick 的 alpha / 累计花费 / 累计转化 / 赢得曝光曲线（hover 十字线）
3. **LLM 决策透视** — 每 tick 一格的条带（深浅=alpha，红=fallback），点击展开该 tick 的
   observation 明细 + 模型原始回答 + 实际执行 alpha

## 使用

```bash
# 1. 有新实验后重新导出数据（在仓库根目录）
python scripts/export_demo.py

# 2. 开发
cd demo && npm install && npm run dev

# 3. 构建（产物在 dist/，任意静态服务器可托管）
npm run build && npm run preview
```

## 数据来源配置

`scripts/export_demo.py` 顶部的 `COMPARISONS` / `LLM_RUNS` 字典声明纳入哪些
输出目录及显示名。新增实验后在那里登记一行即可。

所有指标为模拟器结果（simulated only），未经客户数据校准。
