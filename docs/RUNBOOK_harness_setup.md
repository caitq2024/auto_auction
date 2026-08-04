# Runbook：竞价评测 Harness 从零搭建（可复现操作手册）

> 目的：让同事能照着本文从零复现整套 harness。每步含：做什么、具体命令/控制台操作、
> 如何验证、踩过的坑。持续更新，与实际操作同步。
>
> 环境前提：一台 us-west-2 的 EC2（本文用 16 vCPU/62GB），挂 EFS，实例角色本文称
> `claw`；AWS 账号本文用 651433607849，替换成你自己的。

## 第 0 步：IAM 权限清单（控制台，一次配齐）

给 EC2 实例角色（claw）附加托管策略：

| 策略 | 用途 | 何时需要 |
|---|---|---|
| AmazonBedrockFullAccess | 调用模型 | 一开始 |
| BedrockAgentCoreFullAccess | 创建/调用 AgentCore Runtime | H1 |
| AmazonS3FullAccess | 实验产物桶 | H1/H3 |
| AmazonEC2ContainerRegistryFullAccess | 推模拟器镜像（注意：不是 ...RegistryPublic...，那是 Public Gallery，没用） | H2 |
| AmazonECS_FullAccess | Fargate 跑模拟器 | H2 |
| AWSStepFunctionsFullAccess | 实验矩阵编排 | H2 |
| AWSLambda_FullAccess | 产物聚合/提交入口 | H3 |

inline policy `adsim-passrole`（允许把 adsim-* 执行角色传给服务）：

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PassAdsimRoles",
    "Effect": "Allow",
    "Action": "iam:PassRole",
    "Resource": "arn:aws:iam::<ACCOUNT>:role/adsim-*",
    "Condition": {"StringEquals": {"iam:PassedToService": [
      "ecs-tasks.amazonaws.com", "lambda.amazonaws.com", "states.amazonaws.com"]}}
  }]
}
```

手动建两个执行角色（claw 没有 iam:CreateRole，控制台操作）：

- `adsim-task-role`：信任 ecs-tasks.amazonaws.com；附 AmazonS3FullAccess +
  AmazonBedrockFullAccess + BedrockAgentCoreFullAccess + AmazonECSTaskExecutionRolePolicy
- `adsim-lambda-role`：信任 lambda.amazonaws.com；附 AmazonS3FullAccess +
  AWSLambdaBasicExecutionRole + AWSStepFunctionsFullAccess

验证：

```bash
aws ecr get-authorization-token --region us-west-2 --query 'authorizationData[0].expiresAt'
aws bedrock-agentcore-control list-agent-runtimes --region us-west-2 --max-results 1
```

坑：
- `ecr:GetAuthorizationToken` 必须 Resource:*（AWS 规定）；
- PowerUser 版 ECR 策略缺 CreateRepository，agentcore 首次部署会失败——用 FullAccess。

## 第 1 步（H0）：与 infra 无关的三个接口（纯代码，本仓库已含）

1. **AgentEndpoint 契约**：`POST {observation, meta} -> {"action":"set_alpha","alpha":...}`
   —— src/adsim/agents/remote.py（RemoteAgent，模拟器侧客户端；安全层 clip/fallback 在这，不外移）
2. **ExperimentSpec**：一个 YAML = 完整实验矩阵。`adsim run-matrix spec.yaml` 本地串行执行。
   —— src/adsim/core/experiment_spec.py；示例 configs/experiments/matrix_smoke.yaml
3. **OTEL trace 字段**：LLMCallRecord 带 trace_id/span_id（每 episode 一条 trace）。

验证：`adsim run-matrix configs/experiments/matrix_smoke.yaml`（2 个本地任务，几分钟）。

## 第 2 步（H1）：竞价 agent 部署到 AgentCore Runtime

代码：harness/adsimbidagent/（脚手架来自 `agentcore create`）+ 关键文件
app/adsimbidagent/main.py（`BedrockAgentCoreApp` + `@app.entrypoint`，收 observation
回 set_alpha；模型/模板用环境变量 MODEL_ID / PROMPT_TEMPLATE 控制）。

```bash
# 工具链
npm install -g @aws/agentcore
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv，toolkit 依赖

# 脚手架（选 CodeZip 构建，不需要 docker/ECR）
agentcore create --name adsimbidagent --project-name adsimbidagent \
  --build CodeZip --language Python --framework Strands --model-provider Bedrock --memory none
# 然后把 main.py 换成我们的实现、pyproject 依赖精简为
# bedrock-agentcore + boto3（删 strands/mcp），uv lock 刷新

# 打包（产出 agentcore/adsimbidagent.zip）
agentcore package

# 部署：不用 `agentcore deploy`（它走 CDK/CloudFormation，claw 无 cfn 权限），
# 直接 control-plane API：
python - <<'PY'
import boto3
s3 = boto3.client('s3', region_name='us-west-2')
s3.upload_file('agentcore/adsimbidagent.zip', '<BUCKET>', 'agentcore/adsimbidagent.zip')
c = boto3.client('bedrock-agentcore-control', region_name='us-west-2')
r = c.create_agent_runtime(
    agentRuntimeName='adsim_bidding_agent',
    agentRuntimeArtifact={'codeConfiguration': {
        'code': {'s3': {'bucket': '<BUCKET>', 'prefix': 'agentcore/adsimbidagent.zip'}},
        'runtime': 'PYTHON_3_14',          # zip 内二进制是 aarch64/py314
        'entryPoint': ['main.py']}},        # zip 根相对路径！带子目录会 CREATE_FAILED
    networkConfiguration={'networkMode': 'PUBLIC'},
    roleArn='arn:aws:iam::<ACCOUNT>:role/<runtime执行角色>',  # trust 需含 bedrock-agentcore
    environmentVariables={'MODEL_ID': 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
                          'PROMPT_TEMPLATE': 'v2'})
print(r['agentRuntimeId'])
PY
```

验证（smoke + 全 episode）：

```bash
# 单次调用
python -c "…invoke_agent_runtime(payload={'observation': …})…"   # 见 harness/agentcore/README.md
# 完整 48 决策 episode + 判定指标
python harness/agentcore/poc_run_agentcore.py --runtime-arn <ARN> --pv-num 50000
```

实测判定（2026-07-30）：延迟 +0.4s/决策（门槛 <1s）、fallback 0%、行为与本地一致 → 通过。

坑：
- entryPoint 是 zip 根相对路径；
- CodeZip 选 PYTHON_3_14（toolkit 用本机 uv 装的依赖是 py314/aarch64）；
- `agentcore deploy`（CDK 路线）需要 cloudformation:*，没有就走上面的直接 API 路线。

## 第 3 步（H2）：模拟器容器化 + Step Functions 矩阵编排

（进行中，边做边记）

计划：
1. Dockerfile：py311 + adsim + upstream 只读拷贝；入口 `python -m adsim.harness.run_task`
   （读单个 MatrixTask JSON：跑模拟 → 产物上传 S3）；
2. 推 ECR：`aws ecr create-repository --repository-name adsim-simulator` + docker push；
3. ECS 集群（Fargate）+ 任务定义（4 vCPU / 8GB，taskRole=adsim-task-role）；
4. Step Functions 状态机：输入 ExperimentSpec → Map 状态并发跑任务（ecs:runTask.sync）；
5. 首个用例：教师扩样 6 模型 × 2 episodes（haiku-4.5 / sonnet-4.6 / sonnet-5 /
   opus-5 / deepseek-r1 / nova-2-lite）。

## 第 4 步（H3）：S3 产物 + Lambda 聚合

（待做）计划：S3 事件触发 adsim-lambda-role 的 Lambda → 重新聚合 demo_data.json →
写回 S3/前端数据位置。

## 第 5 步（H4）：Observability / AgentCore evals 接入

（待做）

## 附录 A：当前云上资产清单

| 资产 | 值 |
|---|---|
| S3 bucket | adsim-experiments-651433607849 (us-west-2) |
| AgentCore Runtime | adsim_bidding_agent-keyeetGBSF（haiku4.5+v2，READY） |
| ECR | （H2 建） |
| ECS/StepFunctions/Lambda | （H2/H3 建） |

## 附录 B：教师扩样确认参数（2026-08-04）

6 模型：haiku-4.5、sonnet-4.6、sonnet-5、opus-5、deepseek-r1、nova-2-lite；
每模型 2 episodes、同 seed 配对、500k PV、v2 prompt。官方榜全矩阵；
自助实验允许自选子集。成本上限 $3000（全程实际预计 <$100 infra + token）。
