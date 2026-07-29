"""Train the upstream Decision Transformer on self-generated simulator logs.

Uses upstream AuctionNet strategy_train_env code (Apache-2.0) as a library;
all inputs/outputs live under the internal repo (upstream stays read-only):
- input:  third_party/AuctionNet/data/log/*.csv  (simulator GENERATE_LOG output)
- work:   outputs/dt_baseline/traffic/           (rlData conversion)
- model:  outputs/dt_baseline/saved_model/DTtest/{dt.pt, normalize_dict.pkl}

Run under the py39 env (upstream training code targets it):
    python scripts/train_dt_baseline.py --steps 5000
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TRAIN_ENV = ROOT / "third_party" / "AuctionNet" / "strategy_train_env"
OUT = ROOT / "outputs" / "dt_baseline"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=5000)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--log-dir", default=str(ROOT / "third_party/AuctionNet/data/log"))
    ap.add_argument("--skip-convert", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(TRAIN_ENV))
    import numpy as np
    import torch

    torch.manual_seed(1)
    np.random.seed(1)

    traffic_dir = OUT / "traffic"
    rl_data = traffic_dir / "training_data_rlData_folder" / "training_data_all-rlData.csv"

    if not args.skip_convert:
        traffic_dir.mkdir(parents=True, exist_ok=True)
        for f in Path(args.log_dir).resolve().glob("*.csv"):
            target = traffic_dir / f.name
            target.unlink(missing_ok=True)  # clear stale/broken links
            os.symlink(f, target)
        from bidding_train_env.train_data_generator.train_data_generator import (
            TrainDataGenerator,
        )

        t0 = time.time()
        TrainDataGenerator(file_folder_path=str(traffic_dir)).batch_generate_train_data()
        print(f"conversion took {time.time()-t0:.0f}s -> {rl_data}")

    from bidding_train_env.baseline.dt.dt import DecisionTransformer
    from bidding_train_env.baseline.dt.utils import EpisodeReplayBuffer
    from bidding_train_env.common.utils import save_normalize_dict
    from torch.utils.data import DataLoader, WeightedRandomSampler

    model_dir = OUT / "saved_model" / "DTtest"
    model_dir.mkdir(parents=True, exist_ok=True)

    buf = EpisodeReplayBuffer(16, 1, str(rl_data))
    save_normalize_dict(
        {"state_mean": buf.state_mean, "state_std": buf.state_std}, str(model_dir)
    )
    print(f"trajectories: {len(buf.trajectories)} episodes: {len(buf.states)}")

    model = DecisionTransformer(
        state_dim=16, act_dim=1, state_mean=buf.state_mean, state_std=buf.state_std
    )
    sampler = WeightedRandomSampler(
        buf.p_sample, num_samples=args.steps * args.batch_size, replacement=True
    )
    loader = DataLoader(buf, sampler=sampler, batch_size=args.batch_size)

    model.train()
    t0 = time.time()
    losses = []
    for i, (states, actions, rewards, dones, rtg, timesteps, mask) in enumerate(loader, 1):
        losses.append(np.mean(model.step(states, actions, rewards, dones, rtg, timesteps, mask)))
        model.scheduler.step()
        if i % 500 == 0:
            print(f"step {i}/{args.steps} loss={np.mean(losses[-500:]):.5f} "
                  f"({time.time()-t0:.0f}s)")
    model.save_net(str(model_dir))
    print(f"saved -> {model_dir}, total {time.time()-t0:.0f}s, final loss "
          f"{np.mean(losses[-200:]):.5f}")


if __name__ == "__main__":
    main()
