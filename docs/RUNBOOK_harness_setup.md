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

手动建两个执行角色（claw 没有 iam:CreateRole/UpdateAssumeRolePolicy，必须控制台操作）：

**建角色路径（重要——第一步就要选对）**：IAM → Roles → Create role →
Trusted entity type 选 **AWS service** → Use case 下拉里：

- `adsim-task-role`：选 **Elastic Container Service → ECS Task**（⚠️ 不是默认的
  EC2！选错 ECS 起任务时报 unable to assume role）。附加策略：
  AmazonECSTaskExecutionRolePolicy + AmazonS3FullAccess + AmazonBedrockFullAccess +
  BedrockAgentCoreFullAccess
- `adsim-lambda-role`：选 **Lambda**。附加策略：AWSLambdaBasicExecutionRole +
  AWSStepFunctionsFullAccess + AmazonS3FullAccess
- `adsim-sfn-role`：选 **Step Functions**（Use case 搜 "Step Functions"）。附加策略：
  AmazonECS_FullAccess + CloudWatchEventsFullAccess（runTask.sync 需要 events 权限来
  监听任务结束）+ 上面同款 adsim-passrole inline policy（把 adsim-task-role 传给 ECS）

如果建时选错了 use case（例如默认 EC2），事后修复：角色页 → Trust relationships →
Edit trust policy，Principal.Service 改成 `ecs-tasks.amazonaws.com`（task role）/
`lambda.amazonaws.com`（lambda role）。首次搭建时我们就踩了这个坑。

验证（在 claw 机器上跑）：

```bash
aws ecr get-authorization-token --region us-west-2 --query 'authorizationData[0].expiresAt'
aws bedrock-agentcore-control list-agent-runtimes --region us-west-2 --max-results 1
python3 -c "
import boto3
iam = boto3.client('iam')
for r in ('adsim-task-role', 'adsim-lambda-role'):
    d = iam.get_role(RoleName=r)['Role']
    print(r, d['AssumeRolePolicyDocument']['Statement'][0]['Principal'])"
# 期望输出 Service 分别为 ecs-tasks.amazonaws.com / lambda.amazonaws.com
```

坑：
- `ecr:GetAuthorizationToken` 必须 Resource:*（AWS 规定）；
- PowerUser 版 ECR 策略缺 CreateRepository，agentcore 首次部署会失败——用 FullAccess；
- 建角色 use case 选错成 EC2 → trust policy 是 ec2.amazonaws.com，ECS/Lambda 无法
  assume，必须手动改 trust policy（见上）；
- claw 自身对 IAM 只有读权限（get/list），所有角色创建/修改都在控制台由账号 owner 做
  ——这是有意的权限收敛，claw 只能 PassRole 那些 adsim-* 前缀的角色。

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

## 第 3 步（H2）：模拟器容器化 + Step Functions 矩阵编排（已完成 2026-08-04）

1. **容器**：harness/simulator/Dockerfile（py311-slim + adsim + upstream simul_bidding_env
   只读拷贝 + torch CPU）；入口 harness/simulator/run_task.py——读环境变量 TASK_JSON
   （单个 MatrixTask），跑模拟，产物上传 s3://<bucket>/matrix/<matrix_id>/<task_id>/。
   本地验证：`docker build -f harness/simulator/Dockerfile -t adsim-simulator .` 后
   `docker run -e TASK_JSON='{...pid 5k pv...}'`（S3 上传在本地会因无凭证失败，属预期）。

2. **ECR**：
   ```bash
   aws ecr create-repository --repository-name adsim-simulator --region us-west-2
   aws ecr get-login-password --region us-west-2 | docker login --username AWS \
     --password-stdin <ACCOUNT>.dkr.ecr.us-west-2.amazonaws.com
   docker tag adsim-simulator:latest <ACCOUNT>.dkr.ecr.us-west-2.amazonaws.com/adsim-simulator:latest
   docker push <ACCOUNT>.dkr.ecr.us-west-2.amazonaws.com/adsim-simulator:latest
   ```

3. **ECS**：集群 `adsim-harness`；任务定义 `adsim-simulator`（FARGATE，4 vCPU/8GB，
   execution/taskRole 都是 adsim-task-role，awslogs → /ecs/adsim-simulator）；网络用
   默认 VPC 子网 + assignPublicIp=ENABLED（公网拉镜像/调 Bedrock）。
   单任务冒烟：ecs.run_task(...) → exit 0，S3 产物 6 个文件齐全。

4. **Step Functions**：状态机 `adsim-matrix`（STANDARD，role=adsim-sfn-role）——
   输入 {"tasks":[MatrixTask…]}，Map 状态 MaxConcurrency=12，每项
   `ecs:runTask.sync` 拉一个 Fargate 任务，TASK_JSON 用
   `States.JsonToString($)` 注入容器环境变量；TaskFailed 重试 1 次。

5. **首个用例**：teacher_matrix_v1（configs/experiments/teacher_matrix_v1.yaml，
   6 模型 × 2ep × 500k PV × v2 prompt）。提交方式：本地读 spec → tasks JSON →
   `sfn.start_execution`。执行名 teacher-matrix-v1-run1。

坑：
- Step Functions 需要独立执行角色 adsim-sfn-role（trust=states.amazonaws.com；
  AmazonECS_FullAccess + CloudWatchEventsFullAccess——runTask.sync 靠 EventBridge
  感知任务结束；inline PassRole 只需点名 adsim-task-role）；
- 容器 overrides 传参用 States.JsonToString($) 把 Map 项整体注入 TASK_JSON，
  避免逐字段映射；
- ECR 策略必须 FullAccess（PowerUser 缺 CreateRepository，本次又踩了一遍：策略
  曾被换回 PowerUser，建仓失败后换回 FullAccess）。

## 第 3.5 步：官方数据流量 + GPT-5.6 接入（2026-08-04 完成）

**官方数据 replay**：period CSV 上传 s3://<bucket>/data/official/；run_task.py 按
base.replay_period_csvs 从 S3 按需下载（约 1-2 分钟/3.8GB）。episode i → 列表第 i 个 period。

**GPT-5.6（sol/terra/luna）**：Bedrock 上不支持 InvokeModel/Converse，只能走
Mantle endpoint 的 OpenAI Responses API（详见 EFS bedrock_gpt/call-bedrock-gpt skill）。
MantleGptClient（llm_clients.py）处理：base_url = bedrock-mantle.<region>.api.aws/openai/v1、
sol 自动选 us-east-1、瞬时 auth 失败重试、输出预算 2500（reasoning 花销）。
experiment_spec 按 model_id 前缀 `openai.` 自动路由到 Mantle 客户端。
API key 通过任务的 env_extra 传入容器（注意：会出现在 SFN 执行历史里——claw 无
secretsmanager 权限的当前折衷，后续可让账号 owner 建 secret + task role 读取）。

**教师矩阵·官方数据版最终榜（token 修复后，9 模型 × 2ep × 500k PV × v2 prompt）**：
haiku-4.5 11.91（0% fallback）> sonnet-5 7.83 > deepseek-r1 5.94 >
gpt-5.6-sol 5.78 > gpt-5.6-terra 5.10 > gpt-5.6-luna 4.44 > nova-2-lite 2.08 >
opus-5 1.22 > sonnet-4.6 1.03。

**重要教训（trace 浏览器立功）**：初版榜单的"sonnet-4.6 第一（13.05）"是假的——
它 48/48 决策全部 fallback（推理正确但 300 token 预算把 JSON 截断在末尾），
分数实际是 fallback 链交出来的。修复分两轮：① 默认输出下限 300→1500（普通模型
的 prose+JSON 需要）；② sonnet-5 也在 v2 prompt 下输出 reasoningContent，
reasoning 名单扩为 fable-5/deepseek/opus-5/sonnet-5，预算 2500→4000。
修复后全场 fallback 接近 0（deepseek 剩 12/30 属模型自身稳定性）。
**榜单必须与 fallback 率一起读**——分数好可能只是兜底策略好。

坑：
- opus-5 在复杂 prompt 下会输出 reasoningContent 块（简单探测不会）——300 token
  输出预算饿死 text 块 → 48/48 fallback 得 0 分。已加入 _REASONING_MARKERS
  （≥2500 token + 120s 超时）后重跑正常（5.36）；
- 判断"模型是否 reasoning"必须用真实 prompt 探测，简单 probe 会误判。

## 第 4 步（H3）：S3 产物 + Lambda 聚合（2026-08-04 完成）

1. **Lambda**：`adsim-aggregator`（python3.12，512MB/120s，role=adsim-lambda-role，
   代码 harness/aggregator/lambda_function.py，纯 stdlib 直接 zip 上传）。
   逻辑：对触发到的 matrix_id，列出 matrix/<id>/*/task_result.json → 合并排名 →
   写 leaderboards/<id>.json + 维护 leaderboards/index.json。
2. **S3 事件触发**：bucket 通知（prefix=matrix/ suffix=task_result.json →
   ObjectCreated → Lambda）；先 lambda add-permission（Principal s3.amazonaws.com、
   SourceArn 限定本桶）再 put_bucket_notification_configuration。
3. **前端接入**：export_demo.py 读 S3 leaderboards/ 拼进 demo_data.json 的
   harness_leaderboards 字段；前端 TeacherMatrix 组件渲染（demo + Pages 自动更新）。

验证：put 一个假 task_result.json → ~15s 后 leaderboards/ 出现对应 json（记得清理
测试产物 + index）。

坑：
- put_bucket_notification 在 add-permission 后立即调用可能 InvalidArgument
  （权限传播），等 1-2 分钟重试即好；
- 排查触发问题看 filter_log_events（describe_log_streams 取"最新流"可能拿到旧流）。

## 第 5 步（H4）：Observability + 竞技场提交入口（2026-08-04 完成）

**决策 trace → CloudWatch**（src/adsim/storage/trace_export.py）：
- 每个 LLM/remote/agentcore 任务跑完，把逐决策记录以 **EMF**（Embedded Metric
  Format）写入 log group `/adsim/decisions`（stream 为 matrix/task/ep）；
- EMF 自动生成指标：namespace `adsim` 下 decision_latency_sec / fallback /
  applied_alpha（维度 matrix_id × model_id）——CloudWatch 里直接出图，可设告警
  （如 fallback 突增）；
- trace_id/span_id（H0 字段）把三处记录连起来：S3 JSONL（训练/复盘的事实源）↔
  CloudWatch EMF（运维观测）↔ AgentCore Runtime 自身日志。

**竞技场提交入口**（harness/aggregator/submit_agent_lambda.py → Lambda
`adsim-submit-agent` + Function URL，AWS_IAM 鉴权）：
- POST {"name", "runtime_arn"|"endpoint_url"} → 校验（ARN 格式/HTTPS）→ 每名字
  每小时限一次（S3 marker）→ 固定服务端场景（official period-7/8 × 500k × 2ep，
  arena_v1 矩阵）→ 起 adsim-matrix 执行 → 结果经聚合器自动进
  leaderboards/arena_v1.json；
- experiment_spec 新增 `agentcore` 策略（runtime_arn → AgentCoreAgent 传输层）。
- 首个参赛者：我们的 H1 haiku runtime，score 15.85（官方流量口径）。

坑：
- remote/agentcore 策略也要走 placeholder controlled slot（首跑 KeyError）；
- Fargate task role 能 put 日志但 log group 需预先存在（create_log_group 的
  异常被吞导致静默跳过）——用 claw 预建 `/adsim/decisions` 一次即可；
- claw 无 logs:DescribeLogStreams（读日志用 filter_log_events 或控制台）。

## 云上资产（H4 后完整清单）

| 资产 | 值 |
|---|---|
| S3 bucket | adsim-experiments-651433607849（matrix/ data/ leaderboards/ arena/） |
| AgentCore Runtime | adsim_bidding_agent-keyeetGBSF |
| ECR | adsim-simulator |
| ECS | 集群 adsim-harness · 任务定义 adsim-simulator |
| Step Functions | adsim-matrix |
| Lambda | adsim-aggregator（S3 触发）· adsim-submit-agent（Function URL） |
| CloudWatch | /adsim/decisions（EMF）· namespace adsim 三个指标 |

## 附录 A：当前云上资产清单

| 资产 | 值 |
|---|---|
| S3 bucket | adsim-experiments-651433607849 (us-west-2) |
| AgentCore Runtime | adsim_bidding_agent-keyeetGBSF（haiku4.5+v2，READY） |
| ECR | adsim-simulator |
| ECS/StepFunctions/Lambda | 见 H4 后完整清单 |

## 附录 B：教师扩样确认参数（2026-08-04）

6 模型：haiku-4.5、sonnet-4.6、sonnet-5、opus-5、deepseek-r1、nova-2-lite；
每模型 2 episodes、同 seed 配对、500k PV、v2 prompt。官方榜全矩阵；
自助实验允许自选子集。成本上限 $3000（全程实际预计 <$100 infra + token）。
