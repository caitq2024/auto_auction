"""First LLM prompt-only bidding baseline (doc §21.1 'Frontier LLM Prompt-only').

Drops an LLMBidAgent (Bedrock-backed) into the controlled slot of the
upstream 48-agent market, runs episodes, and reports score + trajectory stats
(fallback rate, latency, token usage). Trajectories are saved as JSONL for
future SFT (doc Phase 4).

Usage:
    python scripts/run_llm_baseline.py --model anthropic.claude-haiku-4-5-20251001-v1:0 \
        --pv-num 50000 --episodes 2 --out outputs/llm_baseline_haiku
"""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

from adsim.agents.llm import LLMAgentConfig, LLMBidAgent
from adsim.agents.llm_clients import BedrockClient
from adsim.core.runner import EpisodeRunner
from adsim.core.scenario import ScenarioConfig
from adsim.storage.event_writer import write_run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="us.anthropic.claude-haiku-4-5-20251001-v1:0")
    ap.add_argument("--pv-num", type=int, default=50000)
    ap.add_argument("--episodes", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--out", default="outputs/llm_baseline")
    ap.add_argument("--max-alpha", type=float, default=200.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    client = BedrockClient(model_id=args.model)
    agent = LLMBidAgent(client, LLMAgentConfig(max_alpha=args.max_alpha))

    scenario = ScenarioConfig.upstream_default_48(
        scenario_id=f"llm_baseline_{args.model.split('.')[-1].split(':')[0]}",
        seed=args.seed,
        pv_num=args.pv_num,
        num_episode=args.episodes,
        controlled={args.slot: ("pid", {})},  # placeholder, swapped below
    )
    runner = EpisodeRunner(scenario)
    runner.agents[args.slot] = agent  # inject the LLM agent directly
    # relabel AFTER runner construction (label is reporting-only; build_agent
    # must not see the "llm:" pseudo-strategy)
    scenario.advertisers[args.slot].strategy = f"llm:{args.model}"

    results = []
    for ep in range(args.episodes):
        res = runner.run_episode(ep)
        results.append(res)
        s = res.summaries[args.slot]
        traj = agent.trajectory
        fallbacks = sum(1 for t in traj if t.fallback)
        with open(out / f"trajectory_ep{ep}.jsonl", "w") as f:
            for t in traj:
                f.write(json.dumps(asdict(t)) + "\n")
        print(json.dumps({
            "episode": ep,
            "score": round(s.score, 4),
            "conversions": s.conversions,
            "cost": round(s.cost, 2),
            "actual_cpa": round(s.actual_cpa, 2),
            "target_cpa": s.target_cpa,
            "budget_utilization": round(s.budget_utilization, 4),
            "llm_calls": len(traj),
            "fallback_rate": round(fallbacks / max(len(traj), 1), 4),
            "mean_latency_sec": round(
                sum(t.latency_sec for t in traj) / max(len(traj), 1), 3),
            "alphas_head": [t.applied_alpha for t in traj[:6]],
        }))

    write_run(out, scenario, results, {
        "model_id": args.model,
        "total_input_tokens": client.total_input_tokens,
        "total_output_tokens": client.total_output_tokens,
        "total_llm_calls": client.calls,
    })
    print(f"tokens: in={client.total_input_tokens} out={client.total_output_tokens} "
          f"calls={client.calls}")
    print(f"outputs -> {out}")


if __name__ == "__main__":
    main()
