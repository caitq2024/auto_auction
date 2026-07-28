"""Phase 0 smoke test: run AuctionNet online evaluation at small scale.

Does NOT modify upstream. Strategy:
- chdir into third_party/AuctionNet so upstream relative paths resolve;
- parse upstream config/test.gin, then apply extra gin bindings to shrink
  traffic (Controller.pv_num) and episodes (run_test.num_episode);
- monkeypatch run.run_test.initialize_player_agent to inject the player
  strategy we want (upstream default would sys.exit(1) because
  strategy_train_env/bidding_train_env/saved_model/ is missing);
- record runtime, memory, warnings and results as JSON.

Usage:
    python smoke_test_auctionnet_online.py --player pid --pv-num 20000 \
        --num-episode 1 --player-index 0 --out out.json
"""
import argparse
import json
import os
import platform
import resource
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
UPSTREAM = os.path.abspath(os.path.join(HERE, "..", "third_party", "AuctionNet"))


def build_player(name: str):
    import numpy as np
    if name == "pid":
        from simul_bidding_env.strategy.pid_bidding_strategy import PidBiddingStrategy
        agent = PidBiddingStrategy(exp_tempral_ratio=np.ones(48))
        agent.name += "_player"
        return agent
    if name == "iql":
        from simul_bidding_env.strategy.iql_bidding_strategy import IqlBiddingStrategy
        agent = IqlBiddingStrategy()
        agent.name += "_player"
        return agent
    if name == "fixed":
        from simul_bidding_env.strategy.base_bidding_strategy import BaseBiddingStrategy

        class FixedAlphaStrategy(BaseBiddingStrategy):
            def __init__(self, alpha=80.0):
                super().__init__(budget=100, name="FixedAlpha_player", cpa=2, category=1)
                self.alpha = alpha

            def reset(self):
                self.remaining_budget = self.budget

            def bidding(self, timeStepIndex, pValues, pValueSigmas, historyPValueInfo,
                        historyBid, historyAuctionResult, historyImpressionResult,
                        historyLeastWinningCost):
                return self.alpha * pValues

        return FixedAlphaStrategy()
    raise ValueError(f"unknown player: {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", default="pid", choices=["pid", "iql", "fixed"])
    ap.add_argument("--pv-num", type=int, default=20000)
    ap.add_argument("--num-episode", type=int, default=1)
    ap.add_argument("--player-index", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--generate-log", action="store_true",
                    help="write upstream train-data CSV to <AuctionNet>/data/log/")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.out:
        args.out = os.path.abspath(args.out)

    os.chdir(UPSTREAM)
    sys.path.insert(0, UPSTREAM)
    # NOTE: deliberately NOT adding strategy_train_env to sys.path — its
    # PlayerBiddingStrategy needs a missing saved_model dir; we inject
    # the player ourselves instead.

    import gin
    import numpy as np
    import torch

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    extra_bindings = [
        f"Controller.pv_num = {args.pv_num}",
        f"run_test.num_episode = {args.num_episode}",
        f"run_test.generate_log = {args.generate_log}",
    ]
    gin.parse_config_files_and_bindings(["./config/test.gin"], extra_bindings)

    # Upstream bug (documented in docs/upstream_audit.md): NeurIPSPvGen.reset()
    # calls self.__init__(episode=episode) without forwarding constructor args,
    # so pv_num silently reverts to the 500000 default on every episode reset.
    # Monkeypatch reset to preserve the configured sizes.
    from simul_bidding_env.PvGenerator.NeurIPSPvGen import NeurIPSPvGen

    def _reset_preserving_config(self, episode: int = 0):
        self.__init__(episode=episode, num_tick=self.NUM_TICK,
                      num_agent=self.NUM_AGENT,
                      num_agent_category=self.NUM_AGENT_CATEGORY,
                      num_category=self.NUM_CATEGORY, pv_num=self.PV_NUM)

    NeurIPSPvGen.reset = _reset_preserving_config

    import run.run_test as rt
    player = build_player(args.player)
    rt.initialize_player_agent = lambda: player

    record = {
        "player": args.player,
        "pv_num": args.pv_num,
        "num_episode": args.num_episode,
        "player_index": args.player_index,
        "seed": args.seed,
        "python": platform.python_version(),
        "extra_gin_bindings": extra_bindings,
    }
    t0 = time.time()
    try:
        result = rt.run_test(player_index=args.player_index)
        record["status"] = "ok"
        record["result"] = {k: (v.item() if hasattr(v, "item") else v)
                            for k, v in result.items()}
    except Exception:
        record["status"] = "error"
        record["traceback"] = traceback.format_exc()
    record["wall_time_sec"] = round(time.time() - t0, 2)
    record["max_rss_mb"] = round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)

    out = json.dumps(record, indent=2, default=str)
    print(out)
    if args.out:
        with open(args.out, "w") as f:
            f.write(out)


if __name__ == "__main__":
    main()
