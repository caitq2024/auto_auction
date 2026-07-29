# 教学 Notebook：从看懂数据到亲手实现四种竞价策略

配套 [AdSim 竞价实验台](https://caitq2024.github.io/auto_auction/) 的动手教程。
数据自带（官方 period-7 的切片，仓库内 22MB），除 05 篇的可选真 LLM 调用外全程免费、CPU 可跑。

| # | Notebook | 内容 | 耗时 |
|---|---|---|---|
| 01 | [样本观察](01_样本观察.ipynb) | 读懂 18 列竞价日志：一天 48 时段、50 万次展示的市场结构 | 5 分钟 |
| 02 | [自己实现 PID](02_自己实现PID.ipynb) | 30 行实现工业 pacing 基线 + threshold replay 评估器 | 10 分钟 |
| 03 | [自己实现 IQL](03_自己实现IQL.ipynb) | 教学版离线 RL：expectile 回归 + AWR 策略提取，看懂榜首为什么是它 | 15 分钟（含训练） |
| 04 | [自己实现 DT](04_自己实现DT.ipynb) | 最小 Decision Transformer（含训练），理解"模仿学习的天花板" | 15 分钟（含训练） |
| 05 | [自己实现 LLM Agent](05_自己实现LLM_Agent.ipynb) | 每时段一次 LLM 决策 + JSON 解析 + fallback；含 mock 模式（无需权限） | 10 分钟 |

## 运行方式

```bash
pip install pandas numpy torch matplotlib jupyter
jupyter lab   # 或 vscode 直接打开
```

每篇末尾有练习题，终极练习是把你实现的四个策略在同一份数据上排名，
与平台排行榜（IQL > LLM > PID > DT）对照。

## 数据说明

`data/period7_adv0.csv.gz`：AuctionNet 官方预生成数据集 period-7 中 0 号广告主的完整日志（50 万行）。
`data/period7_tick0_adv0to7.csv.gz`：第 0 时段 8 个广告主的横截面（观察同一 PV 对不同广告主的 pValue 差异）。
来源与许可见主仓库 README；数据为模拟器产物，非真实平台数据。
