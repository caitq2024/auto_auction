"""Self-serve experiment backend for the AdSim demo.

Pattern follows agentic_advertising/app/api.py:
- BYO Bedrock API key: X-Bedrock-Key header -> held in the task object in
  memory only; never logged, persisted, or echoed in any response.
- X-User-Id header (frontend session id) isolates task ownership; swap to
  the dept-site BFF's X-AIFL-Alias later without changing this file.
- POST /api/experiments -> task_id; GET /api/experiments/{id} polls status
  (progress = completed LLM calls / total); result payload matches the
  demo_data.json candidate/llm_run shapes so the frontend reuses components.

Run: uvicorn api:app --host 0.0.0.0 --port 8687   (from demo/server/)
"""
from __future__ import annotations

import sys
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from adsim.agents.llm import LLMAgentConfig, LLMBidAgent, SYSTEM_PROMPT  # noqa: E402
from adsim.agents.llm_clients import SELF_SERVE_MODELS, BearerTokenClient  # noqa: E402
from adsim.core.runner import EpisodeRunner  # noqa: E402
from adsim.core.scenario import ScenarioConfig  # noqa: E402

app = FastAPI(title="adsim self-serve", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

MAX_PV = 500000          # full paper-scale market allowed (sim ~6 min/episode)
MAX_EPISODES = 2
MAX_PROMPT_CHARS = 4000
MAX_CONCURRENT_TASKS = 4
_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()


class ExperimentRequest(BaseModel):
    model: str = Field(description="key of SELF_SERVE_MODELS")
    pv_num: int = Field(default=50000, ge=5000, le=MAX_PV)
    episodes: int = Field(default=1, ge=1, le=MAX_EPISODES)
    seed: int = Field(default=1, ge=0, le=10**6)
    max_alpha: float = Field(default=2000.0, gt=0, le=10000)
    system_prompt: Optional[str] = Field(
        default=None, max_length=MAX_PROMPT_CHARS,
        description="custom instruction prompt; None = platform default")


@app.get("/api/models")
def list_models():
    return {
        "models": [
            {"key": k, "model_id": mid, "price_in_per_1m": pin, "price_out_per_1m": pout}
            for k, (mid, pin, pout) in SELF_SERVE_MODELS.items()
        ],
        "default_system_prompt": SYSTEM_PROMPT,
        "limits": {"max_pv": MAX_PV, "max_episodes": MAX_EPISODES,
                   "max_prompt_chars": MAX_PROMPT_CHARS},
    }


@app.post("/api/experiments")
def create_experiment(
    req: ExperimentRequest,
    x_bedrock_key: Optional[str] = Header(None),
    x_user_id: str = Header("anonymous"),
):
    key = (x_bedrock_key or "").strip()
    if not key:
        raise HTTPException(400, "缺少 X-Bedrock-Key（在页面设置区粘贴你的 Bedrock API key）")
    if req.model not in SELF_SERVE_MODELS:
        raise HTTPException(400, f"未知模型 {req.model}")
    with _TASKS_LOCK:
        running = sum(1 for t in _TASKS.values() if t["status"] == "running")
        if running >= MAX_CONCURRENT_TASKS:
            raise HTTPException(429, "当前实验队列已满，请稍后再试")
        task_id = uuid.uuid4().hex[:12]
        _TASKS[task_id] = {
            "status": "running", "user": x_user_id, "progress": 0.0,
            "detail": "启动中", "created_at": time.time(), "result": None,
            "error": None,
        }
    threading.Thread(
        target=_run_experiment, args=(task_id, req, key), daemon=True
    ).start()
    return {"task_id": task_id}


@app.get("/api/experiments/{task_id}")
def get_experiment(task_id: str, x_user_id: str = Header("anonymous")):
    t = _TASKS.get(task_id)
    if not t or t["user"] != x_user_id:
        raise HTTPException(404, "task not found")
    return {k: t[k] for k in ("status", "progress", "detail", "result", "error")}


def _run_experiment(task_id: str, req: ExperimentRequest, key: str) -> None:
    t = _TASKS[task_id]
    total_calls = 48 * req.episodes
    try:
        model_id = SELF_SERVE_MODELS[req.model][0]
        client = BearerTokenClient(model_id=model_id, api_key=key)

        # preflight: fail fast on bad key / missing model access, instead of
        # silently running the whole experiment on fallback
        t["detail"] = "校验 key 与模型权限"
        client("Reply with the word OK.")

        # progress hook: plain closure (assigning __call__ on the instance
        # would be ignored — special methods are looked up on the type)
        def counted(prompt: str) -> str:
            out = client(prompt)
            t["progress"] = round(client.calls / total_calls, 3)
            t["detail"] = f"LLM 决策 {client.calls}/{total_calls}"
            return out

        agent = LLMBidAgent(
            counted, LLMAgentConfig(max_alpha=req.max_alpha),
            system_prompt=req.system_prompt or None,
            prompt_version="self-serve" if req.system_prompt else "v1",
        )

        scenario = ScenarioConfig.upstream_default_48(
            scenario_id=f"selfserve_{req.model}", seed=req.seed,
            pv_num=req.pv_num, num_episode=req.episodes,
            controlled={0: ("pid", {})},
        )
        runner = EpisodeRunner(scenario)
        runner.agents[0] = agent

        episodes_out = []
        for ep in range(req.episodes):
            t["detail"] = f"episode {ep} 模拟中"
            res = runner.run_episode(ep)
            s = res.summaries[0]
            calls = [asdict(c) for c in agent.trajectory]
            for c in calls:
                c.pop("prompt", None)  # keep payload small; obs shown from raw output side
            episodes_out.append({
                "episode": ep,
                "score": round(s.score, 4),
                "conversions": s.conversions,
                "cost": round(s.cost, 2),
                "actual_cpa": round(s.actual_cpa, 2),
                "budget_utilization": round(s.budget_utilization, 4),
                "calls": calls,
                "fallback_rate": round(
                    sum(1 for c in calls if c["fallback"]) / max(len(calls), 1), 4),
            })
        scores = [e["score"] for e in episodes_out]
        t["result"] = {
            "model": req.model,
            "model_id": model_id,
            "pv_num": req.pv_num,
            "custom_prompt": bool(req.system_prompt),
            "score_mean": round(sum(scores) / len(scores), 4),
            "episodes": episodes_out,
            "total_input_tokens": client.total_input_tokens,
            "total_output_tokens": client.total_output_tokens,
        }
        t["status"] = "done"
        t["progress"] = 1.0
        t["detail"] = "完成"
    except PermissionError as e:
        t["status"] = "error"
        t["error"] = str(e)
    except Exception as e:  # never include the key in errors
        t["status"] = "error"
        t["error"] = f"{type(e).__name__}: {e}"[:300]
