# Graphiti / Zep 设计思想与代码实现解读

> 依据材料：
> - 论文《Zep: A Temporal Knowledge Graph Architecture for Agent Memory》(arXiv 2501.13956)
> - 开源仓库 [getzep/graphiti](https://github.com/getzep/graphiti)（核心代码 `graphiti_core/`）
> - Zep 官方 LOCOMO 评测代码 [getzep/zep-papers](https://github.com/getzep/zep-papers/tree/main/kg_architecture_agent_memory/locomo_eval)
>
> 本文与《MemoryOS设计思想与代码实现解读.md》互为姊妹篇，最后一节会做两者的对照。

---

## 一、先回答你最困惑的问题：为什么又有 Zep 又有 Graphiti？

一句话：**Graphiti 是开源的"发动机"，Zep 是围绕这台发动机造的"整车"（商业云服务）。**

| 维度 | Graphiti | Zep |
|---|---|---|
| 是什么 | 开源 Python 框架（`pip install graphiti-core`） | 闭源托管平台（SaaS / 私有云） |
| 核心能力 | 时序知识图谱的构建 + 混合检索 | 用户/会话/消息管理、上下文组装 API、Dashboard、SDK |
| 数据库 | 你自己搭 Neo4j / FalkorDB / Kuzu / Neptune | 平台托管，宣称大规模下 <200ms 检索 |
| 检索 | 提供全套搜索原语，参数策略你自己配 | 预配置好的生产级检索管线 |
| 关系 | 被 Zep 内嵌为图引擎 | "Powered by Graphiti" |

所以你说的"Zep 是对 Graphiti 内部逻辑做了封装"基本正确，但方向要理顺：**先有 Zep 这个产品，团队把其中的图谱引擎抽出来开源，取名 Graphiti**。Zep 在 Graphiti 之上加的是产品层的东西：多租户用户体系（user / thread / group_id）、消息存储、REST/SDK 接口、检索参数的默认调优、运维和权限。论文标题挂的是 Zep，但第 2、3 章讲的图谱构建和检索机制，实现全部在 Graphiti 里。

一个直接的证据：Zep 官方跑 LOCOMO 的脚本里，调用的是 `zep_cloud` SDK 的 `zep.graph.add(...)` 和 `zep.graph.search(...)`——即云端 API；而这两个 API 背后执行的，就是开源仓库里 `graphiti_core/graphiti.py::add_episode()` 和 `graphiti_core/search/search.py::search()` 这两条代码路径。

---

## 二、设计思想：从"分层摘要"换成"时序知识图谱"

### 2.1 出发点

与 MemoryOS 一样，Graphiti 也认为 flat RAG（把对话切块进向量库）不适合做 Agent 记忆。但两家开出的药方完全不同：

- **MemoryOS**：模仿操作系统的存储层级，短/中/长期三层，靠"热度"驱动信息升级，用 LLM 摘要来压缩信息。
- **Graphiti**：模仿人的**情景记忆 + 语义记忆**双通道，把对话无损保留为"情景（episode）"，同时用 LLM 抽取出"实体（entity）"和"事实（fact）"构成图，靠**图结构 + 时间维度**来组织信息，不做有损压缩。

论文里明确说这是心理学记忆模型的映射：episodic memory 记具体事件，semantic memory 记概念之间的关联。

### 2.2 图的三层结构

知识图谱 G 分三个子图，自底向上：

1. **情景子图（Episode Subgraph）**：每条原始消息/文本/JSON 存为一个 episode 节点，**原文无损保留**。episode 通过 `MENTIONS` 类边连到它提到的实体。这保证任何抽取出来的事实都能回溯到原文（引用/取证）。
2. **语义实体子图（Semantic Entity Subgraph）**：实体节点（人、地点、概念……）+ 实体间的事实边。每条边携带一条自然语言写的 `fact`（如 "Kendra loves Adidas shoes"）和关系类型（`LOVES`）。同一事实可以在多对实体间重复出现，等效实现了超边（hyper-edge），表达多元关系。
3. **社区子图（Community Subgraph）**：对实体做社区发现（标签传播算法），每个社区节点带一份 LLM 生成的成员摘要和一个含关键词的社区名。这层提供"全局视野"，思路承自 GraphRAG，但用标签传播替代 Leiden 算法——因为标签传播有个很便宜的增量更新方式：新实体入图时看邻居们多数属于哪个社区，就跟着进哪个社区，不必全图重算。

这个"episode → 事实 → 实体 → 社区"的层级，本质上也是一种分层记忆，但与 MemoryOS 的"时间/热度分层"不同，它是**按抽象程度分层**：原文 → 原子事实 → 对象 → 主题簇。

### 2.3 双时间线（bi-temporal model）——最核心的差异化设计

每条事实边上维护四个时间戳，分属两条时间线：

- **事件时间线 T**：`valid_at` / `invalid_at` —— 这条事实**在现实世界里**何时开始成立、何时不再成立。
- **系统时间线 T'**：`created_at` / `expired_at` —— 这条边**在数据库里**何时被写入、何时被作废。

举例：用户 3 月说"我上周开始新工作了"，系统会结合消息的参考时间戳把 `valid_at` 解析成具体日期（相对时间 → 绝对时间）；6 月用户说"我离职了"，新事实入图时会触发**边失效（edge invalidation）**：LLM 判断新旧事实矛盾，把旧边的 `invalid_at` 设为新边的 `valid_at`。旧边不删除，只是打上"已失效"标记。

这样图里同时保存"当前世界状态"和"历史演变轨迹"，天然支持两类难题：

- **knowledge-update**（信息被更新后问最新状态）：取 `invalid_at` 为空的边即可；
- **temporal-reasoning**（"X 是什么时候发生的"）：直接读 `valid_at`，且已经是绝对日期。

对照你之前分析 MemoryOS 时的发现——MemoryOS 的 eval 管线连 query 时间都没传，时间题基本靠 LLM 硬猜——就能理解为什么 Zep 在时间类问题上分数高：**时间是它数据模型里的一等公民，从写入时就被解析、规范化并存了下来**。

---

## 三、写入（提取）管线：`add_episode` 逐步拆解

代码入口：`graphiti_core/graphiti.py::Graphiti.add_episode()`。每来一条消息（episode）执行一遍，全程无固定 schema，实体和关系都由 LLM 从文本里自主发现。步骤如下：

### 3.1 取上下文

先取最近 n 条历史 episode（论文中 n=4，即两轮完整对话）作为上下文一并交给 LLM。这解决指代消解问题——"她昨天去了那家店"里的"她"和"那家店"需要前文才能落到具体实体上。

### 3.2 实体抽取 + 消歧（extract_nodes → resolve_extracted_nodes）

1. **抽取**：LLM 从当前消息中抽实体。提示词规则很有讲究（论文附录 6.1.1）：说话人永远作为第一个实体抽出；**不为关系/动作建节点；不为日期时间建节点**（时间只放在边上）——这保证图的本体干净。抽完后还有一个受 Reflexion 启发的自省步骤，让 LLM 检查有没有漏抽/幻觉。
2. **消歧（去重）**：对每个新实体，(a) 用实体名 embedding 做余弦相似度找相近的既有节点；(b) 再用全文检索（BM25）在既有实体的名字和摘要里找候选。两路候选连同对话上下文一起交给 LLM 判断"这是不是同一个实体"（`dedupe_nodes` 提示词）。判定重复则合并，并让 LLM 生成更完整的名字和摘要。

这一步等价于 MemoryOS 里"相似 session 合并"的角色，但粒度细得多：MemoryOS 合并的是"话题段落"，Graphiti 合并的是"实体"，天然避免了 MemoryOS 那种"session 摘要不更新导致入口漂移"的问题——因为实体名/摘要在每次合并时都会被 LLM 重写。

### 3.3 事实（边）抽取 + 去重（extract_edges → resolve_extracted_edges）

1. **抽取**：把消息 + 已识别实体列表交给 LLM，抽出实体对之间的事实。每条边包含：全大写的 `relation_type`（如 `WORKS_FOR`）+ 一句完整的自然语言 `fact`。**检索时被 embedding 和 BM25 索引的是这句 fact**，这是 Graphiti 和传统三元组 KG 的重要区别——三元组丢信息，整句 fact 不丢。
2. **去重**：对每条新边，在**同一对实体之间**的既有边中做混合检索找候选（代码 `resolve_extracted_edge()`，用 `EdgeDuplicate` 结构化输出让 LLM 指认哪些是重复）。把搜索空间限制在同一实体对之间，既防止不同实体间的相似事实被误合并，也把去重的计算量从"全图"降到"一对节点"。

### 3.4 时间抽取 + 边失效（这段是精华）

对每条新边：

1. **时间抽取**：LLM 拿着 `fact` + episode 的参考时间戳 `reference_time`，解析出 `valid_at` / `invalid_at`。提示词（论文附录 6.1.5）规则严格：相对时间必须换算成绝对 ISO 8601 时间；只有当日期直接关系到这条关系的建立/终止时才填；现在时态的事实用参考时间做 `valid_at`；不允许从相关事件推测日期。
2. **矛盾检测**：除了同实体对的去重候选，还做一轮范围更广的混合检索找"失效候选"（语义相关但端点不同的边也算）。LLM 判断新边与哪些既有边矛盾（`contradicted_facts`）。
3. **时序失效逻辑**（纯代码，`resolve_edge_contradictions()`）：对每个矛盾候选——若两者有效期本就不重叠，跳过；若旧边 `valid_at` 早于新边 `valid_at`，则旧边 `invalid_at` = 新边 `valid_at`，同时打上系统时间线的 `expired_at`。反过来，如果矛盾候选比新边**更新**，则新边自己刚入图就被标记失效（历史信息补录的场景）。原则是沿事务时间线 T' 信任更新的信息。

### 3.5 社区更新（可选）

`update_communities=True` 时，新实体按邻居多数决入社区，社区摘要增量更新。社区会渐渐偏离全量重算的结果，所以需要周期性全量刷新——典型的"用精度换延迟"的工程折中。

### 3.6 成本特征

注意这条管线每条消息要跑 4~6 次 LLM 调用（实体抽取、实体消歧、事实抽取、事实去重、时间抽取、可能的社区摘要），**写入是重的、检索是轻的**。这是刻意为之：Agent 记忆场景里读远多于写，把智力开销前置到写入期，检索期就可以不调用 LLM（除了可选的 cross-encoder 重排），从而把检索延迟压到亚秒级。对比 GraphRAG 检索时要跑 map-reduce 摘要（几十秒），这是它延迟数量级优势的来源。

---

## 四、检索管线：`search()` 的"搜索 → 重排 → 组装"三段式

论文用一个复合函数概括：**f(α) = χ(ρ(φ(α)))** —— 搜索 φ、重排 ρ、构造 χ。代码在 `graphiti_core/search/search.py`。

### 4.1 四个检索对象（scope）并行搜

一次 `search()` 会并行对四类对象各跑一套子搜索：

| scope | 被索引的字段 | 说明 |
|---|---|---|
| edges（事实） | `fact` 一句话 | 最主要的信息来源 |
| nodes（实体） | 实体 `name`（返回时带 summary） | 提供"这个人/物是什么"的背景 |
| episodes（原文） | 消息原文 | 仅 BM25，需要原话时用 |
| communities（社区） | 社区名（关键词串） | 全局性/主题性问题 |

### 4.2 三种搜索方法（φ）

每个 scope 内可组合三种方法，每种先取 `2 × limit` 个候选：

1. **BM25 全文检索**（Neo4j Lucene）：抓字面词匹配；
2. **余弦相似度**（embedding）：抓语义匹配；
3. **广度优先搜索 BFS**：从种子节点沿图 n 跳扩散，抓"图上下文相关"——图上距离近的节点出现在相似的对话语境里。特别地，可以拿**最近几条 episode 当 BFS 种子**，等效于"最近聊到的东西优先浮现"，这是向量检索给不了的能力。代码里若没显式给种子，会用前两路搜索结果的源节点自动做一轮 BFS 扩展。

论文的说法：全文搜抓词面相似，向量搜抓语义相似，BFS 抓上下文相似，三路互补拉高召回。

### 4.3 五种重排器（ρ）

召回求全，重排求准。`search_config.py` 里定义了五种：

1. **RRF**（Reciprocal Rank Fusion）：多路排名倒数融合，最便宜的默认选择；
2. **MMR**：在相关性和多样性之间折中，避免 top-k 全是同义结果；
3. **cross_encoder**：LLM 交叉编码器对 (query, fact) 逐对打分，最准也最贵。开源版默认实现很巧：让 gpt-4o-mini 做"这段话与问题相关吗"的布尔分类，**取 logprob 作为连续分数**，一次分类调用替代专用重排模型；
4. **node_distance**：按候选与指定中心节点的图距离排序——把结果"锚定"在某个实体附近（比如以当前用户节点为中心）；
5. **episode_mentions**：按实体/事实在对话中被提及的次数排序——**被反复聊到的信息更容易被想起来**。

注意后两种是图结构专属的重排信号。episode_mentions 在功能上对应 MemoryOS 的"热度"，但实现干净得多：MemoryOS 要维护 `N_visit`、`L_interaction`、时间衰减再算加权和；Graphiti 里"提及次数"就是边上 `episodes` 列表的长度，天然随写入累积，不需要额外状态机。node_distance 则对应 MemoryOS 完全没有的能力。

预置配方（`search_config_recipes.py`）把方法×重排器的常用组合都封装好了，如 `EDGE_HYBRID_SEARCH_RRF`、`COMBINED_HYBRID_SEARCH_CROSS_ENCODER`（BM25+向量+BFS 三路、cross-encoder 重排、四个 scope 全开）。

### 4.4 上下文组装（χ）

把重排后的结果拼成给 LLM 的 context string：事实边取 `fact` + 有效期（`valid_at`~`invalid_at`），实体取 `name` + `summary`，社区取 `summary`。论文里的模板：

```text
FACTS and ENTITIES represent relevant context to the current conversation.
These are the most relevant facts and their valid date ranges.
format: FACT (Date range: from - to)
{facts}
These are the most relevant entities
ENTITY_NAME: entity summary
{entities}
```

**每条事实都自带时间范围**——回答模型不需要检索系统做任何时间推理，只要会读日期。

---

## 五、LOCOMO 评测：代码怎么跑的、分数到底是多少

### 5.1 先厘清三个基准，别混淆

| 基准 | Zep 成绩 | 备注 |
|---|---|---|
| DMR（MemGPT 提出） | 94.8%（gpt-4-turbo）/ 98.2%（gpt-4o-mini） | 你记忆里的"90 多分"是这个。但全文塞上下文的 baseline 就有 94.4%/98.0%，论文自己都说这基准太弱没区分度 |
| LongMemEval | 71.2%（gpt-4o），比全文 baseline 高 18.5%，延迟降 90%（2.58s vs 28.9s，1.6k vs 115k tokens） | 论文主推的结果，含金量最高 |
| **LOCOMO** | **75.14% ± 0.17** | 不在论文里，是后来跟 Mem0 打架时补测的 |

### 5.2 LOCOMO 分数的"罗生门"

时间线值得记录，因为它是记忆系统评测乱象的典型样本：

1. Mem0 发论文称自己 SOTA，报 Zep 在 LOCOMO 上分数很低；
2. Zep 发博客《Lies, Damn Lies, Statistics》反击，指出 Mem0 的实现三处错误：**(a)** 用了单用户模型却把两个说话人都当 user，导致 Zep 内部把两人当成一个身份反复变化的用户；**(b)** 时间戳拼在消息文本里而不是用 `created_at` 字段，直接废掉了 Zep 的时间推理；**(c)** 两个检索请求串行发而不是并行，延迟数据翻倍。Zep 自测报 84%；
3. Mem0 CTO 在 [getzep/zep-papers#5](https://github.com/getzep/zep-papers/issues/5) 反查出 Zep 的算分 bug：**category 5（对抗性问题）的答案被算进了分子，却没算进分母**，虚增了分数；
4. Zep 承认错误，修正为 **75.14% ± 0.17**（10 次运行），分项：单跳 79.79%、多跳 74.11%、开放域 66.04%、时间类 67.71%。

教训和你评 MemoryOS 时的结论一致：这个领域的横向对比表，**每一个别人家系统的分数都可能是被错误配置跑出来的**，只有系统作者自己调优过的分数才有下限保证。

### 5.3 评测代码逐个看（zep-papers 仓库，共三个脚本 + 一个评分脚本）

**① `zep_locomo_ingestion.py` —— 写入**

```python
await zep.graph.add(
    data=msg.get('speaker') + ': ' + msg.get('text') + img_description,
    type='message',
    created_at=iso_date,     # 会话时间戳走专用字段！
    group_id=group_id,       # 每个 LOCOMO 对话一个图分区
)
```

要点：
- 每个 LOCOMO 对话（两个说话人、多个 session）建一个 `group_id`，图彼此隔离；
- 每条消息单独 `graph.add`，格式为 `"说话人: 内容"`，图片只用 blip caption 文本代替；
- **session 的日期时间解析成 ISO 格式走 `created_at` 字段传入**——这就是 Zep 指责 Mem0 没做对的地方。这个时间戳成为 3.4 节里时间抽取的 `reference_time`，所有"上周""去年夏天"都据此换算成绝对日期。

对照 MemoryOS 的 eval：`main_loco_parse.py` 压根没把 session 时间传进检索和提示词，时间题裸考；Zep 的管线里时间从入口就贯穿到底。**这一项设计差异大概能解释两者时间类分数的大部分差距。**

**② `zep_locomo_search.py` —— 检索**

```python
search_results = await asyncio.gather(
    zep.graph.search(query=query, group_id=group_id, scope='nodes', reranker='rrf',           limit=20),
    zep.graph.search(query=query, group_id=group_id, scope='edges', reranker='cross_encoder', limit=20))
```

要点：
- 只用了 nodes 和 edges 两个 scope（没用 communities / episodes），并行发出；
- 实体用便宜的 RRF 重排，事实用最贵的 cross-encoder 重排——钱花在信息量最大的 fact 上；
- 各取 top 20，拼成 context：

```text
- {fact} (event_time: {valid_at})     ← 20 条事实，每条带事件时间
- {entity_name}: {entity_summary}     ← 20 个实体摘要
```

- category 5（对抗性问题，正确答案是"没有此信息"）直接跳过——这是当时的常见做法，也是后来算分踩坑的根源。

**③ `zep_locomo_responses.py` —— 回答**

用 gpt-4o-mini、temperature 0。提示词值得细看，它花了大量篇幅教模型**怎么用时间戳**：

> - 时间戳代表**事件实际发生的时间**，不是提到这件事的时间；
> - 例：Memory: `(2023-03-15T16:33:00Z) I went to the vet yesterday.` 问去看兽医是哪天 → 正确答案是 3 月 15 日（以时间戳为准，无视"yesterday"字面）；
> - 相对时间引用必须换算成具体日期/月份/年份；
> - 记忆互相矛盾时，以最新的记忆为准。

注意那个例子实际上在教模型"字面相对时间和 event_time 冲突时信 event_time"——因为 Graphiti 抽取时已经把"yesterday"解析过了，`valid_at` 才是权威。整条链路的时间处理是**写入端解析、检索端携带、回答端信任**的三段接力。

**④ `zep_locomo_eval.py` —— LLM as Judge 评分**，标准的对答案打分脚本，不赘述。

### 5.4 所以"分高"的机制归因

结合代码，Zep 在 LOCOMO/LongMemEval 上的优势不是"用了图"三个字能概括的，拆开是四层叠加：

1. **写入期做重活**：实体消歧 + 事实原子化，把对话打碎成互相独立、可单独命中的 fact，多跳问题的证据不会被埋在一大段摘要里；
2. **时间一等公民**：相对时间在写入期就换算为绝对时间存在边上，时间题变成读字段而非推理题；
3. **三路混合召回 + cross-encoder 精排**：BM25 抓词、向量抓义、BFS 抓图邻域，最后用 LLM logprob 精排，检索质量本身就高；
4. **矛盾失效机制**：knowledge-update 类问题里旧信息带着 `invalid_at`，模型不会被过期事实带偏。

---

## 六、与 MemoryOS 的对照总结

| 维度 | MemoryOS | Graphiti/Zep |
|---|---|---|
| 记忆的基本单元 | QA 对（page）+ 会话段（session） | 原子事实（fact 边）+ 实体节点 + 原文 episode |
| 组织原则 | 时间/热度分层（短→中→长期） | 抽象程度分层（原文→事实→实体→社区） |
| 信息压缩 | 有损（多主题摘要、滚动摘要、画像提炼） | 无损（原文保留，抽取是"增维"不是"压缩"） |
| 冲突/更新处理 | 无（新旧信息并存，靠 LLM 在 prompt 里自行分辨） | 显式边失效，双时间线记录演变 |
| 时间处理 | eval 管线未传时间，靠模型猜 | 写入期解析为绝对时间，随 fact 一路带到 prompt |
| 检索 | 两阶段（session→page）向量检索 | BM25+向量+BFS 三路混合 + 五种重排器 |
| "重要性"信号 | 热度 H（访问数、页数、时间衰减的加权和） | episode_mentions（边被提及次数）+ node_distance |
| 写入成本 | 中（摘要、连续性判断、画像分析） | 高（每条消息 4~6 次 LLM 调用） |
| 检索成本 | 低（纯向量，但实现上重复算 embedding） | 低到中（无 LLM，除非开 cross-encoder） |
| 工程成熟度 | 学术原型（硬编码模型名、参数未调优、机制做半截） | 生产系统（可插拔驱动、并发控制、遥测、benchmark 公开可复现） |

两个体系其实回答的是同一个问题的两个极端：**记忆应该"越存越少"还是"越存越结构化"**。MemoryOS 赌的是分层压缩——像人一样遗忘细节、保留印象；Graphiti 赌的是无损结构化——原文全留，靠图和时间轴把检索做准。从基准分看后者目前占优，但代价是每条消息几美分级的写入成本和一套图数据库运维——这也是它必须做成 Zep 这个商业产品的原因。

---

## 七、值得借鉴的点与可挑剔的点

**值得学的：**
1. 双时间线设计。用两组时间戳分开"世界何时如此"与"系统何时得知"，一次性解决了时间推理、知识更新、历史审计三个问题，是全文最漂亮的抽象。
2. fact 用整句自然语言存而不是三元组，检索索引直接建在 fact 句上——保信息量又好检索。
3. 去重搜索空间限制在同一实体对之间——精度和复杂度双赢的小设计。
4. cross-encoder 用"布尔分类 + logprob 当分数"实现，不需要专门的重排模型。
5. 评测代码全部开源且被对手复核过，75.14% 这个数的可信度比大多数论文自报分数高。

**可挑剔的：**
1. 写入成本高且串行敏感：文档明确要求 episode 逐条 await，长对话灌入很慢（默认 `SEMAPHORE_LIMIT=10` 还是为了防 429 限流）。
2. 整条管线深度依赖 LLM 的结构化输出质量，README 自己承认小模型经常产出坏 schema 导致灌入失败。
3. 实体消歧错误会累积：一旦两个实体被错误合并，后续所有 fact 都挂错节点，且无自动纠错机制。
4. 社区的增量更新会漂移，需要周期性全量重算，这部分成本在论文里没有量化。
5. LongMemEval 的 single-session-assistant 类反而比全文 baseline 掉了 17.7%——抽取式记忆对"助手自己说过什么"这类需要原话的问题有系统性劣势（信息在抽取时被改写了）。
6. LOCOMO 84%→75.14% 的算分事故说明：自家 benchmark 也得给别人留复核通道，这点它做到了，但第一版就错了。
