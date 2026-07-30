# H1: AgentCore PoC

竞价 agent 作为独立服务（AgentCore Runtime 的 `/invocations` + `/ping` 契约），
模拟器通过 `RemoteAgent(endpoint)` 连接。本地和 AgentCore 之间切换只改 URL。

## 本地验证（无需任何 AWS 权限之外的东西）

```bash
# 终端 1：起 agent 服务
cd harness/agentcore
MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0 PROMPT_TEMPLATE=v2 \
  uvicorn bidding_agent:app --port 9000

# 终端 2：模拟器通过 RemoteAgent 连它跑一个 episode
python harness/agentcore/poc_run.py --endpoint http://localhost:9000/invocations
```

## 部署到 AgentCore（需要 IAM 权限，见下）

```bash
pip install bedrock-agentcore-starter-toolkit
cd harness/agentcore
agentcore configure -e bidding_agent.py     # 生成 Dockerfile + 配置
agentcore launch                             # 构建并部署 Runtime
# 然后 poc_run.py --endpoint <InvokeAgentRuntime URL> --agentcore
```

## PoC 判定门槛（TASK_aws_infra_harness.md H1）

- 每决策延迟增量 < 1s（对比本地直调 BedrockClient）
- AgentCore Observability 的 trace 覆盖 prompt/输出/延迟/token（能替代手工 JSONL）
- 成本核算：session 计费 × 48 决策/episode，对比自管 EC2

不达标 → 只用 Observability（OTEL 直报），Runtime 不迁。

## 当前 IAM 阻塞（2026-07-30）

本机角色 `claw` 缺以下权限（AccessDenied 实测）：
- `bedrock-agentcore:*`（或至少 control-plane 的 list/create + data-plane invoke）
- `s3:CreateBucket` / `s3:ListAllMyBuckets`（H3 产物迁移用）
- `ecr:*`（agentcore launch 要推容器镜像）

需要账号管理员给 `claw` 角色附加，或提供单独的部署凭证。
