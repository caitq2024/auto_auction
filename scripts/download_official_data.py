"""Download AuctionNet official pre-generated dataset periods.

The full dataset is 21 delivery periods / ~80GB. Per project constraints
(doc §18.3) we download period by period, verify schema on arrival, and
never auto-fetch the whole set — pass explicit --periods.

Data lands in data/official/ (gitignored; EFS has space). Each zip holds
period-N.csv files with the same 18-column schema our simulator logs use,
so ThresholdReplay and TrainDataGenerator consume them unchanged.

Usage:
    python scripts/download_official_data.py --periods 7-8          # one zip (~2GB)
    python scripts/download_official_data.py --periods 7-8 9-10 13  # several
    python scripts/download_official_data.py --list                 # show all
"""
import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "official"
BASE = "https://alimama-bidding-competition.oss-cn-beijing.aliyuncs.com/share/final"

# zip name suffixes as published (21 periods 7..27)
PERIOD_ZIPS = ["7-8", "9-10", "11-12", "13", "14-15", "16-17", "18-19",
               "20-21", "22-23", "24-25", "26-27"]

EXPECTED_COLUMNS = [
    "deliveryPeriodIndex", "advertiserNumber", "advertiserCategoryIndex",
    "budget", "CPAConstraint", "timeStepIndex", "remainingBudget", "pvIndex",
    "pValue", "pValueSigma", "bid", "xi", "adSlot", "cost", "isExposed",
    "conversionAction", "leastWinningCost", "isEnd",
]


def download_period(tag: str) -> list[Path]:
    if tag not in PERIOD_ZIPS:
        raise SystemExit(f"unknown period tag {tag!r}; valid: {PERIOD_ZIPS}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_name = f"autoBidding_general_track_final_data_period_{tag}.zip"
    zip_path = DATA_DIR / zip_name
    if not zip_path.exists():
        url = f"{BASE}/{zip_name}"
        print(f"downloading {url}")
        subprocess.run(
            ["curl", "-L", "--fail", "--retry", "3", "-o", str(zip_path) + ".part", url],
            check=True,
        )
        (DATA_DIR / (zip_name + ".part")).rename(zip_path)
    else:
        print(f"{zip_name} already present, skipping download")

    print(f"extracting {zip_name}")
    with zipfile.ZipFile(zip_path) as zf:
        # skip macOS resource-fork junk (__MACOSX/._*) the publishers zipped in
        members = [m for m in zf.namelist()
                   if m.endswith(".csv") and not m.startswith("__MACOSX")]
        zf.extractall(DATA_DIR, members=members)
    extracted = [DATA_DIR / m for m in members]
    for p in extracted:
        print(f"  -> {p} ({p.stat().st_size/1e9:.2f}GB)")
    return extracted


def verify_schema(csv_path: Path) -> None:
    import pandas as pd

    head = pd.read_csv(csv_path, nrows=1000)
    missing = [c for c in EXPECTED_COLUMNS if c not in head.columns]
    if missing:
        raise SystemExit(f"{csv_path.name}: MISSING COLUMNS {missing} — schema drift, stop")
    print(f"  schema OK ({len(head.columns)} cols); sample: "
          f"period={head.deliveryPeriodIndex.iloc[0]}, "
          f"advertisers={head.advertiserNumber.nunique()} (of first 1000 rows), "
          f"pValue mean={head.pValue.mean():.6f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periods", nargs="*", default=[])
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list or not args.periods:
        print("available period zips (each ~2-8GB):", ", ".join(PERIOD_ZIPS))
        print("full set ≈ 80GB; download only what you need")
        return
    for tag in args.periods:
        for csv_path in download_period(tag):
            verify_schema(csv_path)


if __name__ == "__main__":
    main()
