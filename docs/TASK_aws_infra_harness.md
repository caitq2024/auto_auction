# 任务：与 AWS Infra 结合——竞价实验平台的 Harness 化

状态：Proposal（2026-07-30）· 负责人：caitq · 讨论稿，实施前逐项确认

## 1. 问题：现在的"实验"还不是"harness"

当前跑一个 LLM 竞价实验 = 在一台 EC2 上顺序执行 48 次模型调用 + 模拟器 tick 循环，
产物落 EFS。够做研究，但有四个结构性缺口：

| 缺口 | 现状 | harness 化目标 |
|---|---|---|
| 编排 | 手工脚本 + nohup 后台进程，断了要人管 | 声明式任务定义，失败自动重试/续跑 |
| 并发 | 单机顺序跑，教师扩样（10 ep × 多模型 × 多 seed）要排队数小时 | 并行 fan-out，一次提交全矩阵 |
| 可观测 | run_meta.json + 手动 grep 日志 | 每次调用的 trace（prompt/输出/延迟/token）自动上报 |
| Agent 运行时 | LLMBidAgent 进程内嵌在模拟器里 | agent 独立部署，模拟器与 agent 解耦，可热替换 |

## 2. AWS 组件映射（按引入顺序排序）

### 2.1 Bedrock AgentCore（核心候选）

AgentCore 提供托管的 agent 运行时（Runtime）、记忆（Memory）、可观测性
（Observability，OTEL 兼容 trace）、网关（Gateway，工具/MCP 接入）。与我们的映射：

```
现在                                  AgentCore 化
─────────────────────────────────    ─────────────────────────────────────
LLMBidAgent（进程内 Python 类）   →   AgentCore Runtime 上的独立 agent 服务
  ._decide(obs) 直调 Bedrock      →     模拟器通过 InvokeAgentRuntime 调用
  trajectory 列表存内存           →   AgentCore Observability 自动记录每次
                                        调用的 trace/token/延迟
  observation dict 手工拼          →   保持不变（我们的 schema 已稳定）
  fallback 链（prev→PID→fixed）   →   保留在模拟器侧（安全边界不外移！）
48 时段的"记忆"= 重发全量状态     →   AgentCore Memory 存 episode 内决策
                                        历史，prompt 只发增量（省 token）
```

**先做验证（PoC，1-2 天）**：把 LLMBidAgent 的决策部分包成一个 AgentCore Runtime
agent（`set_alpha` 单工具），模拟器改为远程调用；跑 1 个 500k episode，对比：
延迟开销、trace 质量、成本。**判定标准**：每决策延迟增量 < 1s 且 trace 能替代
我们手工的 trajectory JSONL，才继续迁移。

风险：AgentCore 按 session 计费的模型下，48 决策/episode × 大批量实验的成本
要先算清；如果贵过自管，退回"仅用 Observability（OTEL 直报）"的轻量方案。

### 2.2 批量实验编排：Step Functions + Batch/ECS

教师扩样、多 seed 矩阵、GRPO rollout 都是"同一模拟器、不同参数"的 fan-out：

```
实验矩阵 YAML ──→ Step Functions Map state（并发 N）
                    └─ 每个分支：ECS Fargate task 运行
                       adsim run --scenario s --seed k --model m
                       产物写 S3://adsim-experiments/{run_id}/
```

- 模拟器容器化（Dockerfile 已有雏形：py311 + adsim + upstream 只读拷贝）；
- EFS 官方数据集挂进 task（或首跑同步到 S3，Fargate 拉 S3 更快）；
- 单 episode 500k PV 约 6 分钟 CPU → Fargate 4vCPU spot，一次教师选型
  （2 模型 × 10 ep）约 $2 计算费 + LLM token 费，全程无人值守。

### 2.3 产物与追踪：S3 + （可选）MLflow on ECS

- outputs/ 从 EFS 迁 S3（版本化 bucket），run_meta.json 记 git SHA + 数据 SHA；
- demo 数据管道改为读 S3 → export_demo.py 可以跑在 Lambda 上定时聚合；
- 若实验量到百级，起一个轻量 MLflow 存 run 指标（也可继续用 parquet+榜单，够用）。

### 2.4 GPU 训练（SFT/GRPO 阶段）：SageMaker Training Job 或直接 p5

- 已有 p5en.48xlarge 可 SSH（EFS 共享），短期直接用它跑 SFT/GRPO；
- 量大后再考虑 SageMaker Training Job（spot + 断点续训），非当前瓶颈。

## 3. Harness 化的接口设计（与 infra 无关的部分，先做）

无论上不上 AgentCore，先把这三个接口稳定下来，任何 runtime 都能接：

1. **AgentEndpoint 协议**：`decide(observation: dict) -> {"alpha": float, ...}`
   ——HTTP 版的 LLMBidAgent 接口。模拟器新增 `RemoteAgent(endpoint_url)`，
   本地类 / AgentCore / vLLM 服务一律通过它接入；
2. **ExperimentSpec**：一个 YAML 定义完整实验矩阵（scenario × strategy ×
   seeds × episodes），`adsim run-matrix spec.yaml` 本地串行可跑，之后
   Step Functions 只是换个执行器；
3. **Trace 标准化**：LLMCallRecord 增加 OTEL 兼容字段（trace_id/span_id），
   本地写 JSONL，接 AgentCore/OTEL collector 时零改动。

## 4. 分阶段计划

| 阶段 | 内容 | 依赖 | 预估 |
|---|---|---|---|
| H0 | 接口稳定：AgentEndpoint 协议 + RemoteAgent + ExperimentSpec/run-matrix | 无 | 1 天 |
| H1 | AgentCore PoC：单 agent 迁 Runtime，跑 1 episode 对比延迟/trace/成本 | H0、账号开通 AgentCore | 1-2 天 |
| H2 | 容器化 + Step Functions 批量编排，教师扩样矩阵作为首个用例 | H0 | 2 天 |
| H3 | 产物迁 S3 + demo 数据管道自动化（Lambda 定时聚合） | H2 | 1 天 |
| H4 | （视 H1 结论）全量 AgentCore 化 or 仅 Observability 接入 | H1 | 2 天 |
| H5 | SFT/GRPO 训练接 p5/SageMaker | 教师数据就绪 | 后续任务 |

## 5. 判定与止损

- H1 的 PoC 不达标（延迟 >1s/决策 或 成本高于自管 2 倍）→ AgentCore 只用
  Observability，Runtime 不迁；
- Step Functions 编排若批量需求不足（实验矩阵 < 20 任务/周）→ 推迟 H2，
  本地 run-matrix 串行够用；
- 所有阶段保持"本地可跑"：EC2 单机路径永远是 fallback，harness 是加速器
  不是依赖。

## 6. 待确认问题（开工前问 caitq）

1. AgentCore 当前账号是否已开通/在哪个 region 可用？
2. 实验产物迁 S3 的 bucket 命名/权限规范（个人 or 团队账号）？
3. 教师扩样的规模预期（决定 H2 优先级）：多少模型 × 多少 episodes？
4. Fargate/Step Functions 的成本上限？
