# Graphiti Memory API 调用说明

本文档对应 `examples/locomo/main_server.py` 提供的本地接口服务。

## 服务地址

Docker Compose 启动后的默认调用地址（宿主机映射端口）：

```text
http://127.0.0.1:18003
```

如果远端机器要调用你的服务，需要把 `127.0.0.1` 换成你这台机器在局域网或服务器上的 IP，例如：

```text
http://你的机器IP:18003
```

Docker Compose 启动：

```powershell
docker compose -f examples/locomo/docker-compose.yaml up --build -d
```

如果不用 Docker、本机直接跑脚本，默认仍是 `8000`：

```powershell
uv sync --extra locomo
uv run python examples/locomo/main_server.py
```

也可以直接使用 Uvicorn 启动：

```powershell
uv run uvicorn examples.locomo.main_server:app --host 0.0.0.0 --port 8000
```


## 通用说明

- 请求体和响应体均为 JSON。
- OpenAI、embedding、FalkorDB 等连接参数不放在请求体里，统一从本机 `examples/locomo/.env` 读取。
- `LLM_MODEL` 用于写入抽取和最终回答；`CROSS_ENCODER_MODEL` 单独用于事实重排，
  推荐设为支持 `logit_bias` 和 `logprobs` 的 `gpt-4.1-nano`。
- 对外接口统一使用 `user_id`，必填且不能为空；服务内部将它映射为 Graphiti 的 `group_id`。
- 当前所有数据都写入 FalkorDB 的同一张 graph：`graphiti_memory`。
- 内部 `group_id` 不是数据库名，也不是 graph 名；它是节点和边上的属性。检索时服务会用它过滤。
- 建议请求超时时间设置为 `600` 秒，尤其是注册接口会触发 LLM 抽取。

## 1. 健康检查

### 请求

```http
GET /health
```

### 示例

```bash
curl http://127.0.0.1:18003/health
```

### 响应

```json
{
  "status": "ok"
}
```

## 2. 注册/写入消息

把一个用户的一批消息写入 Graphiti。

服务端会按 `messages` 数组顺序循环调用 `graphiti.add_episode(...)`，并在内部把外部字段转换为 Graphiti 参数。

### 请求

```http
POST /memory/add
Content-Type: application/json
```

### 请求体

```json
{
  "user_id": "locomo_experiment_user_0",
  "messages": [
    {
      "session_idx": 1,
      "msg_idx": 0,
      "speaker": "Caroline",
      "content": "Hey Mel! Good to see you! How have you been?",
      "timestamp": "2023-05-08T13:56:00Z"
    },
    {
      "session_idx": 1,
      "msg_idx": 1,
      "speaker": "Melanie",
      "content": "Hey Caroline! Good to see you! I'm swamped with work.",
      "timestamp": "2023-05-08T13:56:00Z"
    }
  ],
  "source_description": "LOCOMO message"
}
```

字段说明：

- `user_id`：string，必填。用户 ID；服务内部将其作为 Graphiti 的 `group_id`。
- `messages`：array，必填，至少 1 条。
- `messages[].session_idx`：integer，必填。session 序号，例如 `1` 对应 `session_1`。
- `messages[].msg_idx`：integer，必填。该 session 内消息序号，从 `0` 开始。
- `messages[].speaker`：string，必填。说话人。
- `messages[].content`：string，必填。原始消息文本。
- `messages[].timestamp`：datetime，必填。消息发生时间，建议传 ISO 8601 格式。
- `source_description`：string，必填。说明消息来源，例如 `LOCOMO message`。

服务端内部转换关系：

```text
episode_name   <- {user_id}_session_{session_idx}_msg_{msg_idx}
episode_body   <- "{speaker}: {content}"
reference_time <- timestamp
group_id       <- user_id
```

### Python 调用示例

```python
import requests

api_base_url = "http://127.0.0.1:18003"

payload = {
    "user_id": "locomo_experiment_user_0",
    "messages": [
        {
            "session_idx": 1,
            "msg_idx": 0,
            "speaker": "Caroline",
            "content": "Hey Mel! Good to see you! How have you been?",
            "timestamp": "2023-05-08T13:56:00Z",
        }
    ],
    "source_description": "LOCOMO message",
}

response = requests.post(f"{api_base_url}/memory/add", json=payload, timeout=600)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "user_id": "locomo_experiment_user_0",
  "ingested_count": "2/2",
  "duration_ms": 1234.5,
  "input_tokens": 1000,
  "output_tokens": 200,
  "total_tokens": 1200
}
```

字段说明：

- `user_id`：本次写入的用户 ID。
- `ingested_count`：`本次新写入数量/本次提交消息数量`。已注册过的消息会跳过。
- `duration_ms`：本次注册接口总耗时，单位毫秒。
- `input_tokens` / `output_tokens` / `total_tokens`：本次注册中 LLM 的 Token 消耗。

## 3. 清理指定分区记忆

根据 `user_id` 删除该用户的全部 Graphiti 图谱数据，并删除本地注册进度文件。

### 请求

```http
POST /memory/delete
Content-Type: application/json
```

### 请求体

```json
{
  "user_id": "locomo_experiment_user_0"
}
```

字段说明：

- `user_id`：string，必填。只清理该用户的数据，不会删除其他用户的数据。

### Python 调用示例

```python
import requests

api_base_url = "http://127.0.0.1:18003"

payload = {
    "user_id": "locomo_experiment_user_0",
}

response = requests.post(f"{api_base_url}/memory/delete", json=payload, timeout=600)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "user_id": "locomo_experiment_user_0",
  "deleted": true,
  "progress_deleted": true
}
```

字段说明：

- `user_id`：本次清理的用户 ID。
- `deleted`：服务端已执行删除操作。即使该分区原本没有数据，也会返回 `true`。
- `progress_deleted`：是否删除了对应的本地注册进度文件；如果进度文件本来不存在，则为 `false`。

## 4. 检索记忆

根据 `user_id` 和 `queries` 数组，从 Graphiti/FalkorDB 中检索相关事实。

本地检索逻辑对齐原始 `zep_locomo_search.py` 的两路检索：

```python
zep.graph.search(query=query, group_id=group_id, scope='nodes', reranker='rrf', limit=20)
zep.graph.search(query=query, group_id=group_id, scope='edges', reranker='cross_encoder', limit=20)
```

在本地 Graphiti 里对应为：

```python
graphiti.search_(query, config=NODE_HYBRID_SEARCH_RRF, group_ids=[group_id])
graphiti.search_(query, config=EDGE_HYBRID_SEARCH_CROSS_ENCODER, group_ids=[group_id])
```

默认检索数量：

- nodes：`NODE_HYBRID_SEARCH_RRF`，取 top 20 个实体节点。
- edges/facts：`EDGE_HYBRID_SEARCH_CROSS_ENCODER`，取 top 20 条事实边。
- 最终返回的 `context` 由 facts 和 entities 拼接，格式对齐原始 `zep_locomo_search.py` 的 `compose_search_context(...)`。

### 请求

```http
POST /memory/search
Content-Type: application/json
```

### 请求体

```json
{
  "user_id": "locomo_experiment_user_0",
  "queries": [
    "What important personal preferences or facts are known about this user?",
    "What has this user talked about recently?"
  ]
}
```

字段说明：

- `user_id`：string，必填。只检索该用户的数据。
- `queries`：array，必填，至少 1 条。对应 `locomo_retrieval_eval.py` 里的 `QUERIES`。
- 服务端固定返回最多 20 条 facts 和 20 个 nodes，不需要传 `limit`。

### Python 调用示例

```python
import requests

api_base_url = "http://127.0.0.1:18003"

payload = {
    "user_id": "locomo_experiment_user_0",
    "queries": [
        "What important personal preferences or facts are known about this user?",
        "What has this user talked about recently?",
    ],
}

response = requests.post(f"{api_base_url}/memory/search", json=payload, timeout=600)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "user_id": "locomo_experiment_user_0",
  "duration_ms": 456.7,
  "input_tokens": 1000,
  "output_tokens": 20,
  "total_tokens": 1020,
  "results": [
    {
      "query": "What important personal preferences or facts are known about this user?",
      "context": "FACTS and ENTITIES represent relevant context to the current conversation.\n...",
      "duration_ms": 123.4,
      "facts": [
        {
          "uuid": "fact-uuid",
          "fact": "The user bought a shell necklace in Hawaii.",
          "valid_at": "2024-01-01T12:00:00Z",
          "invalid_at": null
        }
      ],
      "nodes": [
        {
          "uuid": "node-uuid",
          "name": "Caroline",
          "summary": "Caroline is one speaker in the conversation."
        }
      ]
    }
  ]
}
```

字段说明：

- `user_id`：本次检索的用户 ID。
- `duration_ms`：整个检索接口耗时，单位毫秒。
- `input_tokens` / `output_tokens` / `total_tokens`：本次检索中 LLM 重排的 Token 消耗。
- `results`：每个 query 对应一个结果对象。
- `results[].query`：本次检索问题。
- `results[].context`：拼接后的上下文，供 response 阶段使用。
- `results[].duration_ms`：本条 query 的检索耗时，单位毫秒。
- `results[].facts`：检索到的事实数组。
- `results[].nodes`：检索到的实体节点数组。
- `results[].facts[].uuid`：事实边的唯一 ID。
- `results[].facts[].fact`：事实文本。
- `results[].facts[].valid_at`：事实生效时间，可能为 `null`。
- `results[].facts[].invalid_at`：事实失效时间，可能为 `null`。

## 5. 生成回答

基于指定 `user_id` 的记忆生成回答。

端到端评测时，调用方只需要传 `qa`。接口内部会自动执行和 `/memory/search` 相同的两路检索：

- nodes：`NODE_HYBRID_SEARCH_RRF`，默认 top 20。
- edges/facts：`EDGE_HYBRID_SEARCH_CROSS_ENCODER`，默认 top 20。

然后把拼好的 `context` 放进回答 prompt，再调用本地 `.env` 中配置的 LLM。

### 请求

```http
POST /memory/response
Content-Type: application/json
```

### 请求体

```json
{
  "user_id": "locomo_experiment_user_0",
  "qa": [
    {
      "question": "What did the user buy in Hawaii?"
    }
  ]
}
```

字段说明：

- `user_id`：string，必填。只使用该用户的数据生成回答。
- `qa`：array，必填，至少 1 条。对应 LOCOMO 原始数据里的 `qa` 数组。
- `qa[].question`：string，必填。要回答的问题。
- 服务端固定检索最多 20 条 facts 和 20 个 nodes，不需要传 `limit`。

### Python 调用示例

```python
import requests

api_base_url = "http://127.0.0.1:18003"

payload = {
    "user_id": "locomo_experiment_user_0",
    "qa": [
        {
            "question": "What did the user buy in Hawaii?",
        }
    ],
}

response = requests.post(f"{api_base_url}/memory/response", json=payload, timeout=600)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "user_id": "locomo_experiment_user_0",
  "duration_ms": 2345.6,
  "total_tokens": 1280,
  "results": [
    {
      "question": "What did the user buy in Hawaii?",
      "answer": "A shell necklace.",
      "duration_ms": 2340.1
    }
  ]
}
```

字段说明：

- `user_id`：本次问答使用的用户 ID。
- `duration_ms`：整个问答接口耗时，单位毫秒。
- `total_tokens`：本次检索重排和回答生成的 LLM Token 总消耗。
- `results`：每个 `qa` 对应一个回答结果。
- `results[].question`：本次问题。
- `results[].answer`：服务生成的回答。
- `results[].duration_ms`：本条问题的端到端耗时，包含内部 search 和 LLM answer。

## 6. 查看图谱 JSON

按 `user_id` 拉取 Entity 节点和 RELATES_TO 边。磁盘上的 FalkorDB 数据是二进制库文件；这个接口是查库后返回可读 JSON。

### 请求

```http
GET /memory/graph?user_id=demo_user_0&limit=200
```

### Python 调用示例

```python
import requests

api_base_url = "http://10.110.159.20:18003"
response = requests.get(
    f"{api_base_url}/memory/graph",
    params={"user_id": "demo_user_0", "limit": 200},
    timeout=60,
)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "user_id": "demo_user_0",
  "nodes": [
    {
      "uuid": "node-uuid",
      "name": "Alice",
      "summary": "Alice bought a shell necklace.",
      "label": "Entity"
    }
  ],
  "edges": [
    {
      "uuid": "edge-uuid",
      "source": "alice-uuid",
      "target": "necklace-uuid",
      "name": "BOUGHT",
      "fact": "Alice bought a shell necklace.",
      "valid_at": "2024-01-08T10:00:00Z",
      "invalid_at": null,
      "created_at": "2026-07-15T06:40:00Z",
      "expired_at": null
    }
  ]
}
```

事实边同时返回事件时间线（`valid_at` / `invalid_at`）和系统时间线
（`created_at` / `expired_at`）。图形页面点击实体节点后，会显示相关边的方向、关系类型、
事实内容和这两组时间。

## 7. 浏览器可视化页面

FalkorDB 自带 Browser 在当前国内镜像里可能不可用。服务内置了一个简单可视化页：

```text
http://服务器IP:18003/memory/ui
```

打开后输入 `user_id`，点击「加载图谱」。页面会请求 `/memory/graph` 并画出节点和边。

## 调用地址配置

本机调用：

```python
API_BASE_URL = "http://127.0.0.1:18003"
```

远端调用时，把 IP 改成运行服务的机器 IP：

```python
API_BASE_URL = "http://你的机器IP:18003"
```
