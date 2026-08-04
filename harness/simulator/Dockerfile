# adsim simulator for Fargate matrix tasks.
# Build context = repo root:  docker build -f harness/simulator/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

# runtime deps only (no dev/test extras); torch CPU wheel for upstream agents
RUN pip install --no-cache-dir numpy pandas pyarrow pyyaml scipy gin-config \
    boto3 einops \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml README.md ./
COPY src ./src
# upstream is read-only inside the image; only the pieces the simulator uses
COPY third_party/AuctionNet/simul_bidding_env ./third_party/AuctionNet/simul_bidding_env
COPY third_party/AuctionNet/LICENSE.txt ./third_party/AuctionNet/LICENSE.txt
COPY harness/simulator/run_task.py ./harness/simulator/run_task.py

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["python", "harness/simulator/run_task.py"]
