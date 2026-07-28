"""Phase 0 smoke test: AIGB Baseline threshold offline evaluation.

Mirrors third_party/AIGB_Baseline/run/run_evaluate.py::run_test verbatim,
with two deviations (documented in docs/upstream_audit.md):
- the traffic CSV path is a CLI arg instead of the hardcoded
  './data/traffic/period-7.csv' (we use a small simulator-generated sample
  rather than downloading the full dataset);
- budget / CPA / seed are recorded, and results are dumped to JSON.

Upstream code is imported unmodified from third_party/AIGB_Baseline.

Usage:
    python smoke_test_aigb_offline.py --traffic <csv> --advertiser 0 \
        --budget 2900 --cpa 100 --seed 1 --out out.json
"""
import argparse
import json
import math
import os
import platform
import resource
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
UPSTREAM = os.path.abspath(os.path.join(HERE, "..", "third_party", "AIGB_Baseline"))


def getScore_nips(reward, cpa, cpa_constraint):
    beta = 2
    penalty = 1
    if cpa > cpa_constraint:
        coef = cpa_constraint / (cpa + 1e-10)
        penalty = pow(coef, beta)
    return penalty * reward


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traffic", required=True, help="path to traffic CSV")
    ap.add_argument("--advertiser", type=int, default=0)
    ap.add_argument("--period", type=int, default=0)
    ap.add_argument("--budget", type=float, default=None,
                    help="override agent budget (default: upstream default 100)")
    ap.add_argument("--cpa", type=float, default=None,
                    help="override agent CPA constraint (default: upstream default 40)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    traffic_path = os.path.abspath(args.traffic)
    out_path = os.path.abspath(args.out) if args.out else None

    sys.path.insert(0, UPSTREAM)
    import numpy as np

    np.random.seed(args.seed)

    from bidding_train_env.strategy import PlayerBiddingStrategy
    from bidding_train_env.dataloader.test_dataloader import TestDataLoader
    from bidding_train_env.environment.offline_env import OfflineEnv

    record = {
        "traffic": traffic_path,
        "advertiser": args.advertiser,
        "period": args.period,
        "seed": args.seed,
        "python": platform.python_version(),
    }
    t0 = time.time()
    try:
        data_loader = TestDataLoader(file_path=traffic_path)
        env = OfflineEnv()
        agent = PlayerBiddingStrategy()
        if args.budget is not None:
            agent.budget = args.budget
        if args.cpa is not None:
            agent.cpa = args.cpa
        agent.reset()
        record["agent"] = {"name": agent.name, "budget": agent.budget,
                           "cpa": agent.cpa}

        key = (float(args.period), float(args.advertiser))
        if key not in data_loader.test_dict:
            key = data_loader.keys[0]
        record["key_used"] = list(key)

        num_timeStepIndex, pValues, pValueSigmas, leastWinningCosts = \
            data_loader.mock_data(key)
        rewards = np.zeros(num_timeStepIndex)
        history = {k: [] for k in
                   ["historyBids", "historyAuctionResult",
                    "historyImpressionResult", "historyLeastWinningCost",
                    "historyPValueInfo"]}

        # --- verbatim upstream loop (run/run_evaluate.py) ---
        for timeStep_index in range(num_timeStepIndex):
            pValue = pValues[timeStep_index]
            pValueSigma = pValueSigmas[timeStep_index]
            leastWinningCost = leastWinningCosts[timeStep_index]

            if agent.remaining_budget < env.min_remaining_budget:
                bid = np.zeros(pValue.shape[0])
            else:
                bid = agent.bidding(timeStep_index, pValue, pValueSigma,
                                    history["historyPValueInfo"],
                                    history["historyBids"],
                                    history["historyAuctionResult"],
                                    history["historyImpressionResult"],
                                    history["historyLeastWinningCost"])

            tick_value, tick_cost, tick_status, tick_conversion = \
                env.simulate_ad_bidding(pValue, pValueSigma, bid, leastWinningCost)

            over_cost_ratio = max(
                (np.sum(tick_cost) - agent.remaining_budget) /
                (np.sum(tick_cost) + 1e-4), 0)
            while over_cost_ratio > 0:
                pv_index = np.where(tick_status == 1)[0]
                dropped_pv_index = np.random.choice(
                    pv_index,
                    int(math.ceil(pv_index.shape[0] * over_cost_ratio)),
                    replace=False)
                bid[dropped_pv_index] = 0
                tick_value, tick_cost, tick_status, tick_conversion = \
                    env.simulate_ad_bidding(pValue, pValueSigma, bid,
                                            leastWinningCost)
                over_cost_ratio = max(
                    (np.sum(tick_cost) - agent.remaining_budget) /
                    (np.sum(tick_cost) + 1e-4), 0)

            agent.remaining_budget -= np.sum(tick_cost)
            rewards[timeStep_index] = np.sum(tick_conversion)
            history["historyPValueInfo"].append(
                np.array([(pValue[i], pValueSigma[i])
                          for i in range(pValue.shape[0])]))
            history["historyBids"].append(bid)
            history["historyLeastWinningCost"].append(leastWinningCost)
            history["historyAuctionResult"].append(
                np.array([(tick_status[i], tick_status[i], tick_cost[i])
                          for i in range(tick_status.shape[0])]))
            history["historyImpressionResult"].append(
                np.array([(tick_conversion[i], tick_conversion[i])
                          for i in range(pValue.shape[0])]))
        # --- end upstream loop ---

        all_reward = float(np.sum(rewards))
        all_cost = float(agent.budget - agent.remaining_budget)
        cpa_real = all_cost / (all_reward + 1e-10)
        score = getScore_nips(all_reward, cpa_real, agent.cpa)
        record["status"] = "ok"
        record["result"] = {
            "num_timeStepIndex": num_timeStepIndex,
            "total_pv": int(sum(p.shape[0] for p in pValues)),
            "reward_conversions": all_reward,
            "cost": all_cost,
            "cpa_real": cpa_real,
            "cpa_constraint": agent.cpa,
            "score": score,
        }
    except Exception:
        record["status"] = "error"
        record["traceback"] = traceback.format_exc()

    record["wall_time_sec"] = round(time.time() - t0, 2)
    record["max_rss_mb"] = round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out = json.dumps(record, indent=2, default=str)
    print(out)
    if out_path:
        with open(out_path, "w") as f:
            f.write(out)


if __name__ == "__main__":
    main()
