# LOCOMO 自托管 Graphiti 全链路部署说明

本文档说明如何用当前 `graphiti` 项目、Docker 版 FalkorDB 或其他支持的图存储，以及你自己的 OpenAI 兼容接口跑通 LOCOMO 数据集评测流程。

这里的目标不是直接使用 Zep Cloud，而是把 Zep Cloud 的 LOCOMO 评测流程迁移成自托管 Graphiti 流程。你后续可以基于这套流程再封装成接口服务，供远程评测程序调用。

参考的原始 Zep Cloud 脚本：

- 摄入记忆：`[zep_locomo_ingestion.py](https://github.com/youyane1-cmd/zep-papers/blob/main/kg_architecture_agent_memory/locomo_eval/zep_locomo_ingestion.py)`
- 检索上下文：`[zep_locomo_search.py](https://github.com/youyane1-cmd/zep-papers/blob/main/kg_architecture_agent_memory/locomo_eval/zep_locomo_search.py)`
- 生成回答：`[zep_locomo_responses.py](https://github.com/youyane1-cmd/zep-papers/blob/main/kg_architecture_agent_memory/locomo_eval/zep_locomo_responses.py)`
- 评测打分：`[zep_locomo_eval.py](https://github.com/youyane1-cmd/zep-papers/blob/main/kg_architecture_agent_memory/locomo_eval/zep_locomo_eval.py)`



## 1. 整体架构

```mermaid
flowchart LR
  locomoJson["LOCOMO 原始数据"] --> ingestStep["摄入记忆"]
  ingestStep --> graphitiCore["Graphiti 核心库"]
  graphitiCore --> graphDb["Docker FalkorDB 图存储"]
  modelApi["自定义 OpenAI 兼容接口"] --> graphitiCore
  queryStep["检索上下文"] --> graphitiCore
  queryStep --> answerStep["生成回答"]
  answerStep --> gradeStep["评测打分"]
```



原来的 Zep Cloud 流程中，`group.add` 用来注册分组，`graph.add` 用来写入记忆。

迁移到自托管 Graphiti 后，不需要单独调用 `group.add`。只要写入 episode 时传入 `group_id`，Graphiti 就会按这个 `group_id` 隔离图谱数据。

可以理解成：

```text
LOCOMO 用户 0 -> group_id = locomo_experiment_user_0
LOCOMO 用户 1 -> group_id = locomo_experiment_user_1
LOCOMO 用户 2 -> group_id = locomo_experiment_user_2
```

检索时也带上对应的 `group_id`，就不会把不同用户或不同对话的数据混在一起。

## 2. 需要准备的组件

你需要准备这几部分：

- 图存储：Windows 本地默认推荐 Docker 版 `FalkorDB`，用来存储 Graphiti 抽取出的实体、关系、事实、时间信息和索引。
- `graphiti_core`：当前仓库里的 Graphiti 核心库。
- 自定义 LLM 接口：需要兼容 OpenAI 的 `/v1/chat/completions`。
- 自定义 embedding 接口：需要兼容 OpenAI 的 `/v1/embeddings`。
- LOCOMO 数据集：脚本会从 `snap-research/locomo` 下载 `locomo10.json`。



## 3. 启动 Docker FalkorDB

Graphiti 不是把记忆直接写进 JSON 文件，而是把 LOCOMO 对话解析成图结构，再写入 FalkorDB。

大概结构是：

```text
locomo.json
  -> Graphiti 读取原始对话
  -> LLM 抽取实体、关系、事实、时间
  -> embedding 模型生成向量
  -> FalkorDB 保存图谱和索引
  -> 后续检索、问答都查 FalkorDB
```

在仓库根目录安装接口服务依赖：

```powershell
uv sync --extra locomo
```

先确认 Docker Desktop 已安装并启动：

```powershell
docker --version
```

如果这里提示无法识别 `docker`，说明当前系统还没有可用的 Docker 命令。需要先安装 Docker Desktop，启动 Docker Desktop 后重新打开 PowerShell。

启动 FalkorDB：

```powershell
docker run `
  --name falkordb `
  -p 6379:6379 `
  -v falkordb-data:/data `
  falkordb/falkordb:latest
```

第一次运行时 Docker 会自动下载 `falkordb/falkordb` 镜像。你不需要去网页上手动下载安装包。

这里的 `-v falkordb-data:/data` 是持久化配置。数据会写进 Docker 的命名卷 `falkordb-data`，不是写进 `examples/locomo/data/locomo.json`。

`.env` 里使用：

```env
GRAPH_BACKEND=falkordb
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
FALKORDB_DATABASE=graphiti_memory
FALKORDB_USERNAME=
FALKORDB_PASSWORD=
```

如果以后再次启动同一个容器：

```powershell
docker start falkordb
```

脚本连接 FalkorDB 成功后，会自动创建 Graphiti 需要的索引和约束，并把 LOCOMO 数据写入图数据库。

## 4. 环境配置

在仓库根目录安装依赖：

```powershell
uv sync --extra locomo
```

`examples/locomo/.env.example` 是配置模板，`examples/locomo/.env` 是你本地真正使用的配置文件。如果 `.env` 不存在，可以从模板复制一份：

```powershell
Copy-Item examples\locomo\.env.example examples\locomo\.env
```

`Copy-Item` 是 PowerShell 的复制命令，作用是把 `.env.example` 复制成 `.env`。这样做是为了避免把真实 API key 写进模板文件。

默认推荐的 `.env` 应该类似这样：

```env
GRAPH_BACKEND=falkordb
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
FALKORDB_DATABASE=graphiti_memory
FALKORDB_USERNAME=
FALKORDB_PASSWORD=

OPENAI_API_KEY=dummy
OPENAI_BASE_URL=http://10.112.86.11:80/v1

LLM_MODEL=your-chat-model
SMALL_LLM_MODEL=your-chat-model
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_DIM=1024

STRUCTURED_OUTPUT_MODE=json_schema
```

你还需要确认这几个值：

- `GRAPH_BACKEND`：保持 `falkordb`。
- `FALKORDB_HOST`：保持 `localhost`。
- `FALKORDB_PORT`：保持 `6379`，要和 Docker 端口映射一致。
- `FALKORDB_DATABASE`：FalkorDB 里的 graph 名字，默认使用 `graphiti_memory`，可按环境覆盖。
- `LLM_MODEL`：你的接口支持的聊天模型名。
- `SMALL_LLM_MODEL`：小任务模型名，可以先和 `LLM_MODEL` 一样。
- `EMBEDDING_MODEL`：你的接口支持的 embedding 模型名。
- `EMBEDDING_DIM`：embedding 模型输出维度，必须填真实维度，比如 `768`、`1024`、`1536`。
- `STRUCTURED_OUTPUT_MODE`：如果你的模型不稳定支持 `json_schema`，可以改成 `json_object`。



## 5. 阶段一：摄入记忆

原始 Zep Cloud 写入逻辑是：

```python
await zep.group.add(group_id=group_id)
await zep.graph.add(
    data=msg.get('speaker') + ': ' + msg.get('text') + img_description,
    type='message',
    created_at=iso_date,
    group_id=group_id,
)
```

迁移到 Graphiti 后，对应逻辑是：

```python
await graphiti.add_episode(
    name=f'locomo_user_{group_idx}_session_{session_idx}_msg_{msg_idx}',
    episode_body=f'{speaker}: {text}{img_description}',
    source=EpisodeType.message,
    source_description='LOCOMO message',
    reference_time=date_string,
    group_id=group_id,
)
```

当前实现脚本是：

```text
examples/locomo/locomo_ingestion.py
```

运行前，直接修改脚本顶部常量：

```python
ENV_PATH = EXAMPLE_DIR / '.env'
DATA_URL = DEFAULT_LOCOMO_URL
DATA_PATH = EXAMPLE_DIR / 'data' / 'locomo.json'
NUM_USERS = 10
MAX_SESSION_COUNT = 35
GROUP_PREFIX = 'locomo_experiment_user'
FORCE_DOWNLOAD = False
BUILD_INDICES = True
```

如果只是先跑一个用户做测试：

```python
NUM_USERS = 1
```

运行摄入脚本：

```powershell
uv run python -m examples.locomo.locomo_ingestion
```

运行后会发生这些事：

- 下载 LOCOMO 数据到 `examples/locomo/data/locomo.json`。
- 每个 LOCOMO 用户生成一个 `group_id`。
- 每条对话消息写成一个 `EpisodeType.message`。
- Graphiti 调用你的 LLM 和 embedding 接口抽取图谱。
- 抽取后的节点、边、事实和向量写入 Docker FalkorDB 容器里的 `graphiti_memory` 这张 graph。
- `graphiti_memory` 里不是每个用户单独一张图，而是所有节点和边都带 `group_id` 属性；检索时用 `group_ids=[...]` 过滤。

注意：同一个 `group_id` 的消息必须顺序写入，不要并发写入。Graphiti 会参考最近的历史 episode 来抽取实体和关系，并发写入会影响上下文顺序。

## 6. 阶段二：检索上下文

原始 Zep Cloud 检索脚本会同时检索节点和边：

```python
search_results = await asyncio.gather(
    zep.graph.search(query=query, group_id=group_id, scope='nodes', reranker='rrf', limit=20),
    zep.graph.search(query=query, group_id=group_id, scope='edges', reranker='cross_encoder', limit=20),
)
```

Graphiti 基础检索写法：

```python
facts = await graphiti.search(query, group_ids=[group_id], num_results=20)
```

Graphiti 高级检索写法：

```python
results = await graphiti.search_(
    query,
    config=COMBINED_HYBRID_SEARCH_RRF,
    group_ids=[group_id],
)
```

当前实现脚本是：

```text
examples/locomo/locomo_retrieval_eval.py
```

运行前，直接修改脚本顶部常量：

```python
ENV_PATH = EXAMPLE_DIR / '.env'
GROUP_ID = 'locomo_experiment_user_0'
QUERIES = [
    'What important facts are known about this user?',
]
TOP_K = 10
USE_ADVANCED_SEARCH = False
```

如果要查另一个用户，就改 `GROUP_ID`：

```python
GROUP_ID = 'locomo_experiment_user_1'
```

如果要使用高级检索，就改：

```python
USE_ADVANCED_SEARCH = True
```

运行检索脚本：

```powershell
uv run python -m examples.locomo.locomo_retrieval_eval
```

后续给回答模型的上下文建议组织成这种形式：

```text
相关事实：
- <fact> (event_time: <valid_at>)

相关实体：
- <entity_name>: <entity_summary>
```



## 7. 阶段三：生成回答

原始 `zep_locomo_responses.py` 的逻辑是：

1. 读取 LOCOMO 的问题。
2. 读取检索阶段保存的上下文。
3. 把上下文和问题一起发给 LLM。
4. 得到生成回答。
5. 保存问题、生成回答、标准答案和耗时。

后续迁移到 Graphiti 服务时，回答逻辑可以写成这样：

```python
async def answer_question(llm_client, context: str, question: str) -> str:
    system_prompt = '你是一个基于记忆上下文回答问题的助手。'

    prompt = f'''
    你可以使用下面的记忆上下文回答问题。

    要求：
    1. 只根据给定上下文回答。
    2. 注意时间戳。
    3. 如果记忆之间有冲突，优先使用较新的记忆。
    4. 如果问题涉及相对时间，要尽量转换成具体日期、月份或年份。
    5. 回答要具体，不要泛泛而谈。

    上下文：
    {context}

    问题：{question}
    回答：
    '''

    response = await llm_client.chat.completions.create(
        model='your-chat-model',
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt},
        ],
        temperature=0,
    )
    return response.choices[0].message.content or ''
```

当前接口服务已经把“检索 + 回答”合并成一个接口：

```text
POST /memory/response
```



## 8. 阶段四：评测打分

原始 `zep_locomo_eval.py` 的逻辑是：

1. 读取生成回答。
2. 读取 LOCOMO 标准答案。
3. 调用一个打分 LLM 判断生成回答是否正确。
4. 统计正确率。

打分逻辑可以写成这样：

```python
async def grade_answer(
    llm_client,
    question: str,
    golden_answer: str,
    generated_answer: str,
) -> bool:
    prompt = f'''
    你需要判断生成回答是否匹配标准答案。

    问题：{question}
    标准答案：{golden_answer}
    生成回答：{generated_answer}

    判断规则：
    1. 如果生成回答和标准答案表达的是同一件事，判为 CORRECT。
    2. 如果是时间问题，只要指向同一日期、月份或时间段，就判为 CORRECT。
    3. 如果明显答非所问，判为 WRONG。

    只返回 CORRECT 或 WRONG。
    '''

    response = await llm_client.chat.completions.create(
        model='your-chat-model',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0,
    )
    label = (response.choices[0].message.content or '').strip().lower()
    return label == 'correct'
```

建议先把打分作为离线脚本跑通。等摄入、检索、回答都稳定后，再封装成接口：

```text
POST /memory/evaluate
```



## 9. 本地接口服务

接口服务脚本：

```text
examples/locomo/main_server.py
```

启动命令：

```powershell
uv sync --extra locomo
uv run python examples/locomo/main_server.py
```

也可以直接使用 Uvicorn 启动：

```powershell
uv run uvicorn examples.locomo.main_server:app --host 0.0.0.0 --port 8000
```

远端请求体只需要传业务数据，不需要传 OpenAI、embedding、FalkorDB 连接参数。这些参数都从本机 `examples/locomo/.env` 读取。

详细接口字段说明见：

```text
examples/locomo/API_USAGE.md
```

### `POST /memory/register`

作用：注册并写入一批 `LocomoMessage`。服务端会按 `messages` 顺序循环调用 `graphiti.add_episode(...)`。

请求示例：

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
    }
  ],
  "source_description": "LOCOMO message"
}
```

字段对应源码：

```text
messages[] <- examples.locomo.locomo_utils.LocomoMessage
```

响应示例：

```json
{
  "group_ids": ["locomo_experiment_user_0"],
  "ingested_count": 1,
  "episode_names": [
    "locomo_user_0_session_1_msg_0"
  ]
}
```

### `POST /memory/clear`

作用：按 `group_id` 删除这个分区下的全部 Graphiti 图谱数据，并删除本地注册进度文件。适合重新导入同一个用户或同一批评测样本前使用。

请求示例：

```json
{
  "group_id": "locomo_experiment_user_0"
}
```

响应示例：

```json
{
  "group_id": "locomo_experiment_user_0",
  "deleted": true,
  "progress_deleted": true
}
```

### `POST /memory/search`

作用：给定 `group_id` 和 `queries` 数组，从 Graphiti 检索相关事实。

请求示例：

```json
{
  "group_id": "locomo_experiment_user_0",
  "queries": [
    "What important facts are known about this user?"
  ],
  "top_k": 20,
  "use_advanced_search": false
}
```

响应示例：

```json
{
  "group_id": "locomo_experiment_user_0",
  "results": [
    {
      "query": "What important facts are known about this user?",
      "facts": [],
      "nodes": [],
      "episodes": []
    }
  ]
}
```

### `POST /memory/response`

作用：先按 `group_id` 检索相关事实，再调用本地 `.env` 里配置的 LLM 生成回答。

请求示例：

```json
{
  "group_id": "locomo_experiment_user_0",
  "questions": [
    "What did the user buy in Hawaii?"
  ],
  "top_k": 10
}
```

响应示例：

```json
{
  "group_id": "locomo_experiment_user_0",
  "results": [
    {
      "question": "What did the user buy in Hawaii?",
      "answer": "A shell necklace",
      "facts": []
    }
  ]
}
```

`group_id` 是分区键。当前所有用户的数据都写在 FalkorDB 的同一张 graph：`graphiti_memory` 里，节点和边靠 `group_id` 属性隔离。检索时必须传同一个 `group_id`。



## 10. 建议执行顺序

完整跑通建议按这个顺序：

1. 运行 `uv sync --extra locomo` 安装 FalkorDB、FastAPI、Uvicorn 依赖。
2. 用 Docker 启动 `falkordb/falkordb` 容器。
3. 配置 `examples/locomo/.env`，默认保持 `GRAPH_BACKEND=falkordb` 即可。
4. 确认 `LLM_MODEL`、`EMBEDDING_MODEL`、`EMBEDDING_DIM` 都是真实可用值。
5. 如果跑脚本流程，依次运行 `locomo_ingestion.py`、`locomo_search.py`、`locomo_responses.py`。
6. 如果跑接口服务，运行 `uv run uvicorn examples.locomo.main_server:app --host 0.0.0.0 --port 8000`。
7. 接口模式下，远端先调 `POST /memory/register` 写入消息。
8. 接口模式下，远端调 `POST /memory/search` 做检索测试。
9. 接口模式下，远端调 `POST /memory/response` 生成回答。
10. 如果要重跑同一个 `group_id`，先调 `POST /memory/clear` 清理旧数据和注册进度。



## 11. 脚本映射关系


| 原 Zep Cloud 脚本            | 作用           | 本地脚本方式                                  | 接口方式                    |
| ------------------------- | ------------ | --------------------------------------- | ----------------------- |
| `zep_locomo_ingestion.py` | 注册分组并摄入消息    | `examples/locomo/locomo_ingestion.py`   | `POST /memory/register` |
| `zep_locomo_search.py`    | 检索节点和边，拼接上下文 | `examples/locomo/locomo_search.py`      | `POST /memory/search`   |
| `zep_locomo_responses.py` | 基于上下文生成回答    | `examples/locomo/locomo_responses.py`   | `POST /memory/response` |
| `zep_locomo_eval.py`      | 对生成回答打分      | 暂不封装                                    | 暂不封装                    |




## 12. 当前文档边界

当前文档只负责说明 Docker FalkorDB 和三接口服务的本地跑通方式。

当前已经有：

- 摄入脚本：`examples/locomo/locomo_ingestion.py`
- 检索脚本：`examples/locomo/locomo_search.py`
- 回答脚本：`examples/locomo/locomo_responses.py`
- 检索冒烟测试脚本：`examples/locomo/locomo_retrieval_eval.py`
- 接口服务：`examples/locomo/main_server.py`
- 公共工具：`examples/locomo/locomo_utils.py`
- 配置模板：`examples/locomo/.env.example`