# LOCOMO Self-Hosted Graphiti Example
# LOCOMO 自托管 Graphiti 示例

This directory contains scripts and docs for running the LOCOMO memory evaluation flow
with self-hosted Graphiti, Docker FalkorDB, and your own OpenAI-compatible
LLM/embedding endpoint.

本目录用于用自托管 Graphiti、Docker FalkorDB，以及你自己的 OpenAI-compatible
LLM/embedding 接口运行 LOCOMO 记忆评测流程。

## Files
## 文件

- `locomo_ingestion.py`: downloads LOCOMO and ingests each message into Graphiti.
- `locomo_search.py`: mirrors `zep_locomo_search.py` and writes search contexts.
- `locomo_responses.py`: mirrors `zep_locomo_responses.py` and writes generated answers.
- `locomo_retrieval_eval.py`: small manual retrieval smoke test.
- `locomo_utils.py`: shared dataset and Graphiti client helpers.
- `main_server.py`: local FastAPI service exposing register, search, and response APIs.
- `.env.example`: environment variable template.
- `API_USAGE.md`: API request and response examples for remote callers.
- `DEPLOYMENT.md`: full runbook for ingestion, retrieval, answering, grading, and future service packaging.

## Quick Start
## 快速开始

Run from the repository root:

在仓库根目录运行：

```powershell
uv sync --extra locomo
```

```powershell
Copy-Item examples\locomo\.env.example examples\locomo\.env
```

Start FalkorDB with Docker:

启动 Docker 版 FalkorDB：

```powershell
docker compose -f examples/locomo/docker-compose.yaml up --build
```

This starts both FalkorDB and the memory API. Host ports start from `18003`:
API `http://127.0.0.1:18003`, FalkorDB `18004`, FalkorDB Browser `18005`.
Data is bind-mounted to host folders under `/data/graphti/`.

这会同时启动 FalkorDB 和 memory API。宿主机端口从 `18003` 起：
API `http://127.0.0.1:18003`，FalkorDB `18004`，FalkorDB Browser `18005`。
数据会映射到宿主机目录 `/data/graphti/`。

Create the host directories first:

先创建宿主机目录：

```bash
sudo mkdir -p /data/graphti/falkordb /data/graphti/register_progress
sudo chmod -R 777 /data/graphti
```



If you want to start FalkorDB manually instead:

如果你想手动启动 FalkorDB：

```powershell
docker --version
```

```powershell
docker run `
  --name falkordb `
  -p 6379:6379 `
  -v falkordb-data:/data `
  falkordb/falkordb:latest
```

By default, `.env.example` uses `GRAPH_BACKEND=falkordb`. Docker will pull the
FalkorDB image automatically and store graph data in the `falkordb-data` volume.

默认配置使用 `GRAPH_BACKEND=falkordb`。Docker 会自动拉取 FalkorDB 镜像，并把图数据保存到 `falkordb-data` 卷里。

Edit `examples/locomo/.env`, then start the local API service:

编辑 `examples/locomo/.env` 后，启动本地接口服务：

```powershell
uv run python examples/locomo/main_server.py
```

Or start it with Uvicorn directly:

```powershell
uv run uvicorn examples.locomo.main_server:app --host 0.0.0.0 --port 8000
```

The service exposes these endpoints:

服务提供四个接口：

- `POST /memory/add`: write messages into Graphiti/FalkorDB.
- `POST /memory/delete`: delete all memories for one `user_id`.
- `POST /memory/search`: search memories by `user_id`.
- `POST /memory/response`: search memories and generate an answer.

The public API uses `user_id` and maps it to Graphiti's internal `group_id` partition key.
All data is stored in the same FalkorDB graph `graphiti_memory`, and each node/edge is
filtered by the internal `group_id`.

外部接口统一使用 `user_id`，服务内部将它映射为 Graphiti 的 `group_id` 分区键。所有数据写在同一个
FalkorDB graph：`graphiti_memory`，节点和边靠内部 `group_id` 过滤隔离。

To run the script pipeline that mirrors the Zep LOCOMO scripts:

运行和 Zep LOCOMO 脚本对应的本地脚本流程：

```powershell
uv run python -m examples.locomo.locomo_ingestion
uv run python -m examples.locomo.locomo_search
uv run python -m examples.locomo.locomo_responses
```

For the complete deployment and future interface-service design, read `DEPLOYMENT.md`.

完整部署流程和未来接口服务设计请阅读 `DEPLOYMENT.md`。
