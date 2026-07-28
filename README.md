# auction-sim-platform

内部广告竞价与预算分配研究平台。基于 [AuctionNet](https://github.com/alimama-tech/AuctionNet)（upstream primary，Apache-2.0）与 AIGB Track Baseline（upstream reference，无 LICENSE，只读参考）。总体设计见 `../AuctionNet_内部广告竞价模拟平台_设计与实施计划.md`。

## 当前状态

Phase 0（upstream 复现与审计）已完成，详见：

- `docs/upstream_audit.md` — 环境、缺失文件、依赖问题、已验证的 upstream bug；
- `docs/upstream_parity.md` — 锚点数字与 threshold vs online 差异量化；
- `third_party/UPSTREAM_LOCK.json` — commit lock 与许可结论；
- `IMPLEMENTATION_STATUS.md` — 进度、blocker、Phase 1 patch 计划。

## 快速开始（复现 Phase 0）

```bash
# 环境：conda env auctionnet_py39 (Python 3.9.12)
conda create -y -n auctionnet_py39 python=3.9.12
~/miniconda3/envs/auctionnet_py39/bin/pip install -r requirements-upstream-py39.lock.txt

# 在线 smoke test（小流量，PID 受控玩家）
python scripts/smoke_test_auctionnet_online.py --player pid --pv-num 5000 --num-episode 1 \
  --out outputs/phase0/online_pid.json

# 生成小样本 log 后运行 AIGB threshold 离线评估
python scripts/smoke_test_auctionnet_online.py --player pid --pv-num 5000 --num-episode 1 --generate-log
python scripts/smoke_test_aigb_offline.py --traffic third_party/AuctionNet/data/log/0.csv \
  --advertiser 0 --budget 2900 --cpa 100 --out outputs/phase0/aigb_offline.json
```

## 约束

- `third_party/` 只读，不做任何 in-place 修改（必要变更以 monkeypatch/adapter 形式并文档化）；
- 不自动下载完整 80GB 数据；
- 内部代码进 `src/adsim/`（目标 Python 3.11），upstream 兼容层隔离在 adapter。
