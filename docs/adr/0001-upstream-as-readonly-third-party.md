# ADR 0001: Upstream 仓库以只读 third_party 形式引入

日期：2026-07-28 · 状态：Accepted

## 决策

AuctionNet（`c20de63`）与 AIGB_Baseline（`550f0b1`）克隆到 `third_party/`，锁定 commit，不做任何 in-place 修改。必要的行为变更以两种形式表达：

1. Phase 0：`scripts/` 中的 monkeypatch（如 `NeurIPSPvGen.reset` 参数透传修复），在脚本内注释并在 `docs/upstream_audit.md` 记录；
2. Phase 1+：`src/adsim/` 中的独立实现 + adapter，用 `tests/parity/` 以 Phase 0 锚点做 golden-file 对齐。

`third_party/` 加入 `.gitignore`，内部 git 只追踪 `UPSTREAM_LOCK.json`（含 URL + commit），复现靠脚本重新克隆并 checkout 锁定 commit。

## 理由

- AIGB_Baseline 无 LICENSE，不能把其源码纳入内部代码库分发；
- upstream 依赖 Python 3.9-only API（`from collections import Iterable`），与内部 3.11 目标不兼容，隔离比迁移安全；
- 锁 commit 避免结果漂移（主文档 2.3 工程决策）。
