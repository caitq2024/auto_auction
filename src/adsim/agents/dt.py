"""Decision Transformer bid agent.

Wraps the upstream DT model (third_party/AuctionNet strategy_train_env,
Apache-2.0) trained by scripts/train_dt_baseline.py. State construction
mirrors upstream DtBiddingStrategy's 16-dim feature vector, computed from the
same history structures our runner maintains.

The upstream dt.py module imports cleanly under py311/torch2.x; the model is
a plain nn.Module checkpoint (torch.save/load of state_dict via save_net).
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np

from adsim.core.types import AdvertiserConfig

_TRAIN_ENV = Path(__file__).resolve().parents[3] / "third_party" / "AuctionNet" / "strategy_train_env"
_DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[3] / "outputs" / "dt_baseline" / "saved_model" / "DTtest"


class DtAgent:
    def __init__(self, model_dir: str | None = None, target_return: float | None = None):
        if str(_TRAIN_ENV) not in sys.path:
            sys.path.insert(0, str(_TRAIN_ENV))
        from bidding_train_env.baseline.dt.dt import DecisionTransformer

        model_dir_path = Path(model_dir) if model_dir else _DEFAULT_MODEL_DIR
        with open(model_dir_path / "normalize_dict.pkl", "rb") as f:
            norm = pickle.load(f)
        self.model = DecisionTransformer(
            state_dim=16, act_dim=1,
            state_mean=norm["state_mean"], state_std=norm["state_std"],
        )
        self.model.load_net(str(model_dir_path / "dt.pt"))
        if target_return is not None:
            self.model.target_return = target_return
        self.last_alpha: float | None = None
        self.advertiser: AdvertiserConfig | None = None

    def reset(self, advertiser: AdvertiserConfig, episode: int) -> None:
        self.advertiser = advertiser
        self.last_alpha = None

    def bidding(
        self, tick, pv_values, pvalue_sigmas, history_pvalue_infos, history_bids,
        history_auction_results, history_impression_results,
        history_least_winning_costs, remaining_budget,
    ) -> np.ndarray:
        assert self.advertiser is not None
        state = self._build_state(
            tick, pv_values, remaining_budget, history_pvalue_infos, history_bids,
            history_auction_results, history_impression_results,
            history_least_winning_costs,
        )
        if tick == 0:
            self.model.init_eval()
        history_conversion = [r[:, 1] for r in history_impression_results]
        pre_reward = float(np.sum(history_conversion[-1])) if history_conversion else None
        # take_actions returns a (act_dim,) ndarray; numpy>=2 forbids float()
        # on size-1 non-0d arrays.
        alpha = float(np.asarray(self.model.take_actions(state, pre_reward=pre_reward)).reshape(-1)[0])
        self.last_alpha = alpha
        return alpha * pv_values

    def _build_state(
        self, tick, pv_values, remaining_budget, history_pvalue_infos, history_bids,
        history_auction_results, history_impression_results, history_least_winning_costs,
    ) -> np.ndarray:
        # Mirrors upstream DtBiddingStrategy 16-dim state exactly.
        adv = self.advertiser
        time_left = (48 - tick) / 48
        budget_left = remaining_budget / adv.budget if adv.budget > 0 else 0
        hist_xi = [r[:, 0] for r in history_auction_results]
        hist_pv = [r[:, 0] for r in history_pvalue_infos]
        hist_conv = [r[:, 1] for r in history_impression_results]

        def hist_mean(xs):
            return float(np.mean([np.mean(x) for x in xs])) if xs else 0.0

        def last3_mean(xs, n):
            tail = xs[max(0, n - 3):n]
            return float(np.mean([np.mean(x) for x in tail])) if tail else 0.0

        n = len(history_bids)
        return np.array([
            time_left, budget_left,
            hist_mean(history_bids), last3_mean(history_bids, n),
            hist_mean(history_least_winning_costs), hist_mean(hist_pv),
            hist_mean(hist_conv), hist_mean(hist_xi),
            last3_mean(history_least_winning_costs, n), last3_mean(hist_pv, n),
            last3_mean(hist_conv, n), last3_mean(hist_xi, n),
            float(np.mean(pv_values)), float(len(pv_values)),
            float(sum(len(b) for b in history_bids[max(0, n - 3):n])),
            float(sum(len(b) for b in history_bids)),
        ])
