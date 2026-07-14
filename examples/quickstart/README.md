# Graphiti Quickstart Example
# Graphiti 快速开始示例

This example demonstrates the basic functionality of Graphiti, including:
本示例演示 Graphiti 的基础功能，包括：

1. Connecting to a Neo4j or FalkorDB database
   连接到 Neo4j 或 FalkorDB 数据库
2. Initializing Graphiti indices and constraints
   初始化 Graphiti 的索引和约束
3. Adding episodes to the graph
   向图中添加 episodes
4. Searching the graph with semantic and keyword matching
   使用语义匹配和关键词匹配搜索图
5. Exploring graph-based search with reranking using the top search result's source node UUID
   使用最高搜索结果的源节点 UUID 进行重排，探索基于图的搜索
6. Performing node search using predefined search recipes
   使用预定义的搜索配方执行节点搜索

## Prerequisites
## 前置条件

- Python 3.9+
  Python 3.9 或更高版本
- OpenAI API key (set as `OPENAI_API_KEY` environment variable)
  OpenAI API 密钥（设置为 `OPENAI_API_KEY` 环境变量）
- **For Neo4j**:
  **使用 Neo4j 时**：
  - Neo4j Desktop installed and running
    已安装并运行 Neo4j Desktop
  - A local DBMS created and started in Neo4j Desktop
    已在 Neo4j Desktop 中创建并启动本地 DBMS
- **For FalkorDB**:
  **使用 FalkorDB 时**：
  - FalkorDB server running (see [FalkorDB documentation](https://docs.falkordb.com) for setup)
    FalkorDB 服务正在运行（安装配置请参阅 [FalkorDB 文档](https://docs.falkordb.com)）
- **For Amazon Neptune**:
  **使用 Amazon Neptune 时**：
  - Amazon server running (see [Amazon Neptune documentation](https://aws.amazon.com/neptune/developer-resources/) for setup)
    Amazon 服务正在运行（安装配置请参阅 [Amazon Neptune 文档](https://aws.amazon.com/neptune/developer-resources/)）

## Setup Instructions
## 设置说明

1. Install the required dependencies:
   安装所需依赖：

```bash
pip install graphiti-core
```

2. Set up environment variables:
   设置环境变量：

```bash
# Required for LLM and embedding
# LLM 和嵌入模型所必需
export OPENAI_API_KEY=your_openai_api_key

# Optional Neo4j connection parameters (defaults shown)
# 可选的 Neo4j 连接参数（以下为默认值）
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password

# Optional FalkorDB connection parameters (defaults shown)
# 可选的 FalkorDB 连接参数（以下为默认值）
export FALKORDB_URI=falkor://localhost:6379

# Optional Amazon Neptune connection parameters
# 可选的 Amazon Neptune 连接参数
NEPTUNE_HOST=your_neptune_host
NEPTUNE_PORT=your_port_or_8182
AOSS_HOST=your_aoss_host
AOSS_PORT=your_port_or_443

# To use a different database, modify the driver constructor in the script
# 如需使用其他数据库，请修改脚本中的驱动构造函数
```

TIP: For Amazon Neptune host string please use the following formats
提示：Amazon Neptune 的 host 字符串请使用以下格式

* For Neptune Database: `neptune-db://<cluster endpoint>`
  Neptune Database 使用：`neptune-db://<cluster endpoint>`
* For Neptune Analytics: `neptune-graph://<graph identifier>`
  Neptune Analytics 使用：`neptune-graph://<graph identifier>`

3. Run the example:
   运行示例：

```bash
python quickstart_neo4j.py

# For FalkorDB
# 使用 FalkorDB
python quickstart_falkordb.py

# For Amazon Neptune
# 使用 Amazon Neptune
python quickstart_neptune.py
```

## What This Example Demonstrates
## 本示例演示的内容

- **Graph Initialization**: Setting up the Graphiti indices and constraints in Neo4j, Amazon Neptune, or FalkorDB
  **图初始化**：在 Neo4j、Amazon Neptune 或 FalkorDB 中设置 Graphiti 的索引和约束
- **Adding Episodes**: Adding text content that will be analyzed and converted into knowledge graph nodes and edges
  **添加 Episodes**：添加文本内容，这些内容会被分析并转换为知识图谱中的节点和边
- **Edge Search Functionality**: Performing hybrid searches that combine semantic similarity and BM25 retrieval to find relationships (edges)
  **边搜索功能**：执行结合语义相似度和 BM25 检索的混合搜索，以查找关系（边）
- **Graph-Aware Search**: Using the source node UUID from the top search result to rerank additional search results based on graph distance
  **图感知搜索**：使用最高搜索结果的源节点 UUID，根据图距离对更多搜索结果进行重排
- **Node Search Using Recipes**: Using predefined search configurations like NODE_HYBRID_SEARCH_RRF to directly search for nodes rather than edges
  **使用配方进行节点搜索**：使用 `NODE_HYBRID_SEARCH_RRF` 等预定义搜索配置，直接搜索节点而不是边
- **Result Processing**: Understanding the structure of search results including facts, nodes, and temporal metadata
  **结果处理**：理解搜索结果的结构，包括事实、节点和时间元数据

## Next Steps
## 后续步骤

After running this example, you can:
运行本示例后，你可以：

1. Modify the episode content to add your own information
   修改 episode 内容，添加你自己的信息
2. Try different search queries to explore the knowledge extraction
   尝试不同的搜索查询，探索知识抽取效果
3. Experiment with different center nodes for graph-distance-based reranking
   尝试使用不同的中心节点进行基于图距离的重排
4. Try other predefined search recipes from `graphiti_core.search.search_config_recipes`
   尝试 `graphiti_core.search.search_config_recipes` 中的其他预定义搜索配方
5. Explore the more advanced examples in the other directories
   探索其他目录中的高级示例

## Troubleshooting
## 故障排查

### "Graph not found: default_db" Error
### “Graph not found: default_db” 错误

If you encounter the error `Neo.ClientError.Database.DatabaseNotFound: Graph not found: default_db`, this occurs when the driver is trying to connect to a database that doesn't exist.
如果遇到错误 `Neo.ClientError.Database.DatabaseNotFound: Graph not found: default_db`，说明驱动正在尝试连接一个不存在的数据库。

**Solution:**
**解决方案：**

The Neo4j driver defaults to using `neo4j` as the database name. If you need to use a different database, modify the driver constructor in the script:
Neo4j 驱动默认使用 `neo4j` 作为数据库名称。如果需要使用其他数据库，请修改脚本中的驱动构造函数：

```python
# In quickstart_neo4j.py, change:
# 在 quickstart_neo4j.py 中，将：
driver = Neo4jDriver(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)

# To specify a different database:
# 改为指定其他数据库：
driver = Neo4jDriver(uri=neo4j_uri, user=neo4j_user, password=neo4j_password, database="your_db_name")
```

## Understanding the Output
## 理解输出

### Edge Search Results
### 边搜索结果

The edge search results include EntityEdge objects with:
边搜索结果包含 `EntityEdge` 对象，其中包括：

- UUID: Unique identifier for the edge
  UUID：边的唯一标识符
- Fact: The extracted fact from the episode
  Fact：从 episode 中抽取出的事实
- Valid at/invalid at: Time period during which the fact was true (if available)
  Valid at/invalid at：该事实为真的时间段（如果可用）
- Source/target node UUIDs: Connections between entities in the knowledge graph
  Source/target node UUIDs：知识图谱中实体之间连接关系的源节点和目标节点 UUID

### Node Search Results
### 节点搜索结果

The node search results include EntityNode objects with:
节点搜索结果包含 `EntityNode` 对象，其中包括：

- UUID: Unique identifier for the node
  UUID：节点的唯一标识符
- Name: The name of the entity
  Name：实体名称
- Content Summary: A summary of the node's content
  Content Summary：节点内容摘要
- Node Labels: The types of the node (e.g., Person, Organization)
  Node Labels：节点类型（例如 Person、Organization）
- Created At: When the node was created
  Created At：节点创建时间
- Attributes: Additional properties associated with the node
  Attributes：与节点关联的其他属性
