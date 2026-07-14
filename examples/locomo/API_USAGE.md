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
- `group_id` 必填，不能为空。它是 Graphiti 的分区键，用来隔离不同用户或不同实验样本。
- 当前所有数据都写入 FalkorDB 的同一张 graph：`graphiti_memory`。
- `group_id` 不是数据库名，也不是 graph 名；它是节点和边上的属性。检索时服务会用 `group_id` 过滤。
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

把一批 `LocomoMessage` 写入 Graphiti。

服务端会按 `messages` 数组顺序循环调用 `graphiti.add_episode(...)`。这里的 `messages[]` 对应 `examples/locomo/locomo_utils.py` 里的 `LocomoMessage`，也就是 `iter_locomo_messages(...)` 产出的对象。

### 请求

```http
POST /memory/register
Content-Type: application/json
```

### 请求体

```json
{
  "messages": [
    {
      "group_idx": 0,
      "group_id": "locomo_experiment_user_0",
      "session_idx": 1,
      "msg_idx": 0,
      "speaker": "Caroline",
      "text": "Hey Mel! Good to see you! How have you been?",
      "episode_body": "Caroline: Hey Mel! Good to see you! How have you been?",
      "reference_time": "2023-05-08T13:56:00Z"
    },
    {
      "group_idx": 0,
      "group_id": "locomo_experiment_user_0",
      "session_idx": 1,
      "msg_idx": 1,
      "speaker": "Melanie",
      "text": "Hey Caroline! Good to see you! I'm swamped with work.",
      "episode_body": "Melanie: Hey Caroline! Good to see you! I'm swamped with work.",
      "reference_time": "2023-05-08T13:56:00Z"
    }
  ],
  "source_description": "LOCOMO message"
}
```

字段说明：

- `messages`：array，必填，至少 1 条。每个元素就是一个 `LocomoMessage`。
- `messages[].group_idx`：integer，必填。LOCOMO 用户在数据集中的序号。
- `messages[].group_id`：string，必填。Graphiti 分区 ID，例如 `locomo_experiment_user_0`。
- `messages[].session_idx`：integer，必填。session 序号，例如 `1` 对应 `session_1`。
- `messages[].msg_idx`：integer，必填。该 session 内消息序号，从 `0` 开始。
- `messages[].speaker`：string，必填。说话人。
- `messages[].text`：string，必填。原始消息文本。
- `messages[].episode_body`：string，必填。写入 Graphiti 的 episode 内容，通常是 `speaker: text`，如果有图片描述则拼接在后面。
- `messages[].reference_time`：datetime，必填。消息发生时间，建议传 ISO 8601 格式。
- `source_description`：string，可选。默认是 `LOCOMO message`。

当前 `locomo_ingestion.py` 写入时实际使用的是：

```text
episode_name   <- locomo_user_{group_idx}_session_{session_idx}_msg_{msg_idx}
episode_body   <- message.episode_body
reference_time <- message.reference_time
group_id       <- message.group_id
```

### Python 调用示例

```python
import requests

api_base_url = "http://127.0.0.1:18003"

payload = {
    "messages": [
        {
            "group_idx": 0,
            "group_id": "locomo_experiment_user_0",
            "session_idx": 1,
            "msg_idx": 0,
            "speaker": "Caroline",
            "text": "Hey Mel! Good to see you! How have you been?",
            "episode_body": "Caroline: Hey Mel! Good to see you! How have you been?",
            "reference_time": "2023-05-08T13:56:00Z",
        }
    ],
}

response = requests.post(f"{api_base_url}/memory/register", json=payload, timeout=600)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "group_ids": ["locomo_experiment_user_0"],
  "ingested_count": 2,
  "episode_names": [
    "locomo_user_0_session_1_msg_0",
    "locomo_user_0_session_1_msg_1"
  ]
}
```

字段说明：

- `group_ids`：本次写入涉及的分区 ID。
- `ingested_count`：本次写入的消息数量。
- `episode_names`：本次写入生成的 episode 名称列表。

## 3. 清理指定分区记忆

根据 `group_id` 删除这个分区下的全部 Graphiti 图谱数据，并删除本地注册进度文件。

### 请求

```http
POST /memory/clear
Content-Type: application/json
```

### 请求体

```json
{
  "group_id": "locomo_experiment_user_0"
}
```

字段说明：

- `group_id`：string，必填。只清理这个分区下的数据，不会删除其他 `group_id`。

### Python 调用示例

```python
import requests

api_base_url = "http://127.0.0.1:18003"

payload = {
    "group_id": "locomo_experiment_user_0",
}

response = requests.post(f"{api_base_url}/memory/clear", json=payload, timeout=600)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "group_id": "locomo_experiment_user_0",
  "deleted": true,
  "progress_deleted": true
}
```

字段说明：

- `group_id`：本次清理的分区 ID。
- `deleted`：服务端已执行删除操作。即使该分区原本没有数据，也会返回 `true`。
- `progress_deleted`：是否删除了对应的本地注册进度文件；如果进度文件本来不存在，则为 `false`。

## 4. 检索记忆

根据 `group_id` 和 `queries` 数组，从 Graphiti/FalkorDB 中检索相关事实。

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
  "group_id": "locomo_experiment_user_0",
  "queries": [
    "What important personal preferences or facts are known about this user?",
    "What has this user talked about recently?"
  ],
  "limit": 20
}
```

字段说明：

- `group_id`：string，必填。只检索这个分区下的数据。
- `queries`：array，必填，至少 1 条。对应 `locomo_retrieval_eval.py` 里的 `QUERIES`。
- `limit`：integer，可选，默认 `20`。分别控制 nodes 和 edges/facts 两路检索的 top 数，范围是 `1` 到 `100`。

### Python 调用示例

```python
import requests

api_base_url = "http://127.0.0.1:18003"

payload = {
    "group_id": "locomo_experiment_user_0",
    "queries": [
        "What important personal preferences or facts are known about this user?",
        "What has this user talked about recently?",
    ],
    "limit": 20,
}

response = requests.post(f"{api_base_url}/memory/search", json=payload, timeout=600)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "group_id": "locomo_experiment_user_0",
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

- `group_id`：本次检索的分区 ID。
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

基于指定 `group_id` 的记忆生成回答。

端到端评测时，调用方只需要传 `qa`。接口内部会自动执行和 `/memory/search` 相同的两路检索：

- nodes：`NODE_HYBRID_SEARCH_RRF`，默认 top 20。
- edges/facts：`EDGE_HYBRID_SEARCH_CROSS_ENCODER`，默认 top 20。

然后把拼好的 `context` 放进回答 prompt，再调用本地 `.env` 中配置的 LLM。

如果你已经提前调用 `/memory/search` 并保存了 context，也可以传 `search_results`。传 `search_results` 时，服务会直接使用这些 context，不再重复检索。

### 请求

```http
POST /memory/response
Content-Type: application/json
```

### 请求体

```json
{
  "group_id": "locomo_experiment_user_0",
  "qa": [
    {
      "question": "What did the user buy in Hawaii?",
      "answer": "A shell necklace"
    }
  ],
  "limit": 20
}
```

字段说明：

- `group_id`：string，必填。只使用这个分区下的数据生成回答。
- `qa`：array，必填，至少 1 条。对应 LOCOMO 原始数据里的 `qa` 数组。
- `qa[].question`：string，必填。要回答的问题。
- `qa[].answer`：string，可选。标准答案；服务不会用它生成回答，只会原样放到响应的 `golden_answer` 字段中，方便后续评测。
- `search_results`：array，可选。如果提供，长度必须和 `qa` 一致，每个元素至少包含 `context` 字段。
- `limit`：integer，可选，默认 `20`。未传 `search_results` 时，分别控制 nodes 和 edges/facts 两路检索的 top 数，范围是 `1` 到 `100`。

### Python 调用示例

```python
import requests

api_base_url = "http://127.0.0.1:18003"

payload = {
    "group_id": "locomo_experiment_user_0",
    "qa": [
        {
            "question": "What did the user buy in Hawaii?",
            "answer": "A shell necklace",
        }
    ],
    "limit": 20,
}

response = requests.post(f"{api_base_url}/memory/response", json=payload, timeout=600)
response.raise_for_status()
print(response.json())
```

### 响应体

```json
{
  "group_id": "locomo_experiment_user_0",
  "results": [
    {
      "question": "What did the user buy in Hawaii?",
      "answer": "A shell necklace.",
      "golden_answer": "A shell necklace",
      "duration_ms": 2345.6,
      "facts": [
        {
          "uuid": "fact-uuid",
          "fact": "The user bought a shell necklace in Hawaii.",
          "valid_at": "2024-01-01T12:00:00Z",
          "invalid_at": null
        }
      ]
    }
  ]
}
```

字段说明：

- `group_id`：本次问答使用的分区 ID。
- `results`：每个 `qa` 对应一个回答结果。
- `results[].question`：本次问题。
- `results[].answer`：服务生成的回答。
- `results[].golden_answer`：请求体中 `qa[].answer` 的原样返回值；没有传则为 `null`。
- `results[].duration_ms`：本条问题的端到端耗时，包含内部 search 和 LLM answer。
- `results[].facts`：生成回答前检索到的事实数组，格式同 `/memory/search`。如果请求体传了 `search_results`，这里为空数组。

## 调用地址配置

本机调用：

```python
API_BASE_URL = "http://127.0.0.1:18003"
```

远端调用时，把 IP 改成运行服务的机器 IP：

```python
API_BASE_URL = "http://你的机器IP:18003"
```
