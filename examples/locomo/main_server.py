"""
Minimal LOCOMO API service backed by local Graphiti + Docker FalkorDB.
"""

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from copy import copy
from datetime import datetime
from pathlib import Path
from time import time
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Query, Request  # pyright: ignore[reportMissingImports]
from fastapi.responses import HTMLResponse  # pyright: ignore[reportMissingImports]
from openai import BadRequestError  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field

from examples.locomo.locomo_responses import (
    locomo_response,  # pyright: ignore[reportMissingImports]
)
from examples.locomo.locomo_utils import build_graphiti_client, load_environment
from graphiti_core import Graphiti
from graphiti_core.edges import EntityEdge
from graphiti_core.namespaces import EdgeNamespace, NodeNamespace
from graphiti_core.nodes import EntityNode, EpisodeType
from graphiti_core.request_usage import CURRENT_REQUEST_USAGE, RequestUsage
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_CROSS_ENCODER,
    NODE_HYBRID_SEARCH_RRF,
)
from graphiti_core.utils.maintenance.graph_data_operations import clear_data

EXAMPLE_DIR = Path(__file__).parent
ENV_PATH = EXAMPLE_DIR / '.env'
REGISTER_PROGRESS_DIR = EXAMPLE_DIR / 'data' / 'register_progress'
DEFAULT_SERVER_HOST = '0.0.0.0'
DEFAULT_SERVER_PORT = 8000
SEARCH_RESULT_LIMIT = 20
logger = logging.getLogger('uvicorn.error')

SEARCH_CONTEXT_TEMPLATE = """
FACTS and ENTITIES represent relevant context to the current conversation.

# These are the most relevant facts for the conversation along with the datetime of the event that the fact refers to.
If a fact mentions something happening a week ago, then the datetime will be the date time of last week and not the datetime
of when the fact was stated.
Timestamps in memories represent the actual time the event occurred, not the time the event was mentioned in a message.


{facts}


# These are the most relevant entities
# ENTITY_NAME: entity summary

{entities}

"""


class RegisterMessage(BaseModel):
    session_idx: int = Field(..., ge=0)
    msg_idx: int = Field(..., ge=0)
    speaker: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    timestamp: datetime


class RegisterRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    messages: list[RegisterMessage] = Field(..., min_length=1)
    source_description: str = Field(..., min_length=1)


class RegisterResponse(BaseModel):
    user_id: str
    ingested_count: str
    duration_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int


class RegisterProgressItem(BaseModel):
    episode_name: str
    duration_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    completed_at: datetime | None = None


class ClearMemoryRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class ClearMemoryResponse(BaseModel):
    user_id: str
    deleted: bool
    progress_deleted: bool


class GraphNodeView(BaseModel):
    uuid: str
    name: str
    summary: str = ''
    label: str = 'Entity'


class GraphEdgeView(BaseModel):
    uuid: str
    source: str
    target: str
    name: str = ''
    fact: str = ''
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    created_at: datetime | None = None
    expired_at: datetime | None = None


class GraphViewResponse(BaseModel):
    user_id: str
    nodes: list[GraphNodeView]
    edges: list[GraphEdgeView]


class SearchRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    queries: list[str] = Field(..., min_length=1)


class FactResult(BaseModel):
    uuid: str
    fact: str
    valid_at: datetime | None = None
    invalid_at: datetime | None = None


class NodeResult(BaseModel):
    uuid: str
    name: str
    summary: str


class SearchQueryResult(BaseModel):
    query: str
    context: str
    duration_ms: float
    facts: list[FactResult]
    nodes: list[NodeResult] = Field(default_factory=list)


class SearchResponse(BaseModel):
    user_id: str
    results: list[SearchQueryResult]
    duration_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int


class QAItem(BaseModel):
    question: str


class ResponseRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    qa: list[QAItem] = Field(..., min_length=1)


class ResponseItem(BaseModel):
    question: str
    answer: str
    duration_ms: float
    search_result: SearchQueryResult


class ResponseResult(BaseModel):
    user_id: str
    results: list[ResponseItem]
    duration_ms: float
    total_tokens: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_environment(ENV_PATH)
    logger.info('正在初始化 Graphiti Memory API')
    graphiti = build_graphiti_client()
    await graphiti.build_indices_and_constraints()
    app.state.graphiti = graphiti
    app.state.user_graphiti = {}
    app.state.user_locks = {}
    logger.info('Graphiti Memory API 初始化完成')
    try:
        yield
    finally:
        logger.info('正在关闭 Graphiti Memory API')
        await graphiti.close()


app = FastAPI(title='Graphiti Memory API', lifespan=lifespan)


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}


def get_graphiti(request: Request) -> Graphiti:
    graphiti = getattr(request.app.state, 'graphiti', None)
    if graphiti is None:
        raise HTTPException(status_code=503, detail='Graphiti client is not ready')
    return graphiti


def get_user_lock(request: Request, user_id: str) -> asyncio.Lock:
    locks: dict[str, asyncio.Lock] = request.app.state.user_locks
    return locks.setdefault(user_id, asyncio.Lock())


async def get_user_graphiti(request: Request, user_id: str) -> Graphiti:
    graphiti_by_user: dict[str, Graphiti] = request.app.state.user_graphiti
    if user_id in graphiti_by_user:
        return graphiti_by_user[user_id]

    base_graphiti = get_graphiti(request)
    driver = base_graphiti.driver.clone(database=user_id)
    graphiti = copy(base_graphiti)
    graphiti.driver = driver
    graphiti.clients = base_graphiti.clients.model_copy(update={'driver': driver})
    graphiti.nodes = NodeNamespace(driver, graphiti.embedder)
    graphiti.edges = EdgeNamespace(driver, graphiti.embedder)
    await graphiti.build_indices_and_constraints()
    graphiti_by_user[user_id] = graphiti
    return graphiti


def build_episode_name(user_id: str, message: RegisterMessage) -> str:
    return f'{user_id}_session_{message.session_idx}_msg_{message.msg_idx}'


def usage_fields(usage: RequestUsage) -> dict[str, int]:
    return {
        'input_tokens': usage.input_tokens,
        'output_tokens': usage.output_tokens,
        'total_tokens': usage.total_tokens,
    }


def is_content_filter_error(exc: BadRequestError) -> bool:
    error_text = f'{exc} {getattr(exc, "body", None)}'.lower()
    return 'content_filter' in error_text or 'responsibleaipolicyviolation' in error_text


def register_progress_path(group_id: str) -> Path:
    safe_group_id = re.sub(r'[^A-Za-z0-9_.-]+', '_', group_id)
    return REGISTER_PROGRESS_DIR / f'{safe_group_id}_register_progress.jsonl'


def legacy_register_progress_path(group_id: str) -> Path:
    safe_group_id = re.sub(r'[^A-Za-z0-9_.-]+', '_', group_id)
    return REGISTER_PROGRESS_DIR / f'{safe_group_id}_register_progress.json'


def parse_register_progress_item(item: object, path: Path) -> RegisterProgressItem:
    try:
        if isinstance(item, str):
            return RegisterProgressItem(episode_name=item)
        return RegisterProgressItem.model_validate(item)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail=f'Invalid register progress item in: {path}'
        ) from exc


def write_register_progress_jsonl(group_id: str, progress: list[RegisterProgressItem]) -> None:
    REGISTER_PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    path = register_progress_path(group_id)
    temp_path = path.with_suffix(f'{path.suffix}.tmp')
    with temp_path.open('w', encoding='utf-8') as file:
        for item in progress:
            file.write(json.dumps(item.model_dump(mode='json'), ensure_ascii=False) + '\n')
    temp_path.replace(path)


def load_register_progress(group_id: str) -> list[RegisterProgressItem]:
    path = register_progress_path(group_id)
    if path.exists():
        progress: list[RegisterProgressItem] = []
        with path.open(encoding='utf-8') as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise HTTPException(
                        status_code=500,
                        detail=f'Invalid register progress JSONL: {path}:{line_number}',
                    ) from exc
                progress.append(parse_register_progress_item(item, path))
        return progress

    legacy_path = legacy_register_progress_path(group_id)
    if not legacy_path.exists():
        return []

    with legacy_path.open(encoding='utf-8') as file:
        legacy_progress = json.load(file)
    if not isinstance(legacy_progress, list):
        raise HTTPException(
            status_code=500, detail=f'Invalid register progress file: {legacy_path}'
        )

    progress = [parse_register_progress_item(item, legacy_path) for item in legacy_progress]
    write_register_progress_jsonl(group_id, progress)
    legacy_path.unlink()
    logger.info('已迁移注册进度文件 JSON -> JSONL path=%s', path)
    return progress


def append_register_progress(group_id: str, item: RegisterProgressItem) -> None:
    REGISTER_PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    path = register_progress_path(group_id)
    with path.open('a', encoding='utf-8') as file:
        file.write(json.dumps(item.model_dump(mode='json'), ensure_ascii=False) + '\n')


def delete_register_progress(group_id: str) -> bool:
    deleted = False
    for path in (
        register_progress_path(group_id),
        legacy_register_progress_path(group_id),
    ):
        if path.exists():
            path.unlink()
            deleted = True
    return deleted


def fact_result_from_edge(edge) -> FactResult:
    return FactResult(
        uuid=edge.uuid,
        fact=edge.fact,
        valid_at=edge.valid_at,
        invalid_at=edge.invalid_at,
    )


def node_result_from_node(node) -> NodeResult:
    return NodeResult(
        uuid=node.uuid,
        name=node.name,
        summary=getattr(node, 'summary', '') or '',
    )


def compose_search_context(edges: list[EntityEdge], nodes: list[EntityNode]) -> str:
    facts = [f' - {edge.fact} (event_time: {edge.valid_at})' for edge in edges]
    entities = [f' - {node.name}: {node.summary}' for node in nodes]
    return SEARCH_CONTEXT_TEMPLATE.format(facts='\n'.join(facts), entities='\n'.join(entities))


async def search_context(
    graphiti: Graphiti,
    group_id: str,
    query: str,
    limit: int,
) -> SearchQueryResult:
    start = time()
    node_config = NODE_HYBRID_SEARCH_RRF.model_copy(update={'limit': limit})
    edge_config = EDGE_HYBRID_SEARCH_CROSS_ENCODER.model_copy(update={'limit': limit})
    node_results, edge_results = await asyncio.gather(
        graphiti.search_(query, config=node_config, group_ids=[group_id]),
        graphiti.search_(query, config=edge_config, group_ids=[group_id]),
    )
    duration_ms = (time() - start) * 1000

    return SearchQueryResult(
        query=query,
        context=compose_search_context(edge_results.edges, node_results.nodes),
        duration_ms=duration_ms,
        facts=[fact_result_from_edge(edge) for edge in edge_results.edges],
        nodes=[node_result_from_node(node) for node in node_results.nodes],
    )


@app.post('/memory/add', response_model=RegisterResponse)
async def register(request: RegisterRequest, http_request: Request) -> RegisterResponse:
    group_id = request.user_id
    usage = RequestUsage()
    context_token = CURRENT_REQUEST_USAGE.set(usage)
    start = time()
    ingested_count = 0
    total_messages = len(request.messages)
    logger.info('开始注册记忆 user_id=%s messages=%d', group_id, total_messages)

    try:
        async with get_user_lock(http_request, request.user_id):
            graphiti = await get_user_graphiti(http_request, request.user_id)
            group_progress = load_register_progress(group_id)
            completed_episode_names = {item.episode_name for item in group_progress}
            for index, message in enumerate(request.messages, start=1):
                episode_name = build_episode_name(request.user_id, message)
                if episode_name in completed_episode_names:
                    logger.info(
                        '跳过已注册消息 user_id=%s progress=%d/%d episode=%s',
                        group_id,
                        index,
                        total_messages,
                        episode_name,
                    )
                    continue

                message_start = time()
                message_input_tokens = usage.input_tokens
                message_output_tokens = usage.output_tokens
                logger.info(
                    '开始注册消息 user_id=%s progress=%d/%d episode=%s',
                    group_id,
                    index,
                    total_messages,
                    episode_name,
                )
                content_filtered = False
                try:
                    await graphiti.add_episode(
                        name=episode_name,
                        episode_body=f'{message.speaker}: {message.content}',
                        source=EpisodeType.message,
                        source_description=request.source_description,
                        reference_time=message.timestamp,
                        group_id=group_id,
                    )
                except BadRequestError as exc:
                    if not is_content_filter_error(exc):
                        raise
                    content_filtered = True
                    logger.warning(
                        '消息触发 Azure 内容过滤，按已处理跳过 user_id=%s '
                        'progress=%d/%d episode=%s',
                        group_id,
                        index,
                        total_messages,
                        episode_name,
                    )
                duration_ms = (time() - message_start) * 1000
                input_tokens = usage.input_tokens - message_input_tokens
                output_tokens = usage.output_tokens - message_output_tokens
                progress_item = RegisterProgressItem(
                    episode_name=episode_name,
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    completed_at=datetime.now().astimezone(),
                )
                append_register_progress(group_id, progress_item)
                group_progress.append(progress_item)
                completed_episode_names.add(episode_name)
                ingested_count += 1
                if not content_filtered:
                    logger.info(
                        '完成注册消息 user_id=%s progress=%d/%d episode=%s '
                        'duration_ms=%.0f total_tokens=%d',
                        group_id,
                        index,
                        total_messages,
                        episode_name,
                        duration_ms,
                        input_tokens + output_tokens,
                    )

        result = RegisterResponse(
            user_id=request.user_id,
            ingested_count=f'{ingested_count}/{total_messages}',
            duration_ms=(time() - start) * 1000,
            **usage_fields(usage),
        )
        logger.info(
            '完成注册记忆 user_id=%s ingested=%s duration_ms=%.0f total_tokens=%d',
            group_id,
            result.ingested_count,
            result.duration_ms,
            result.total_tokens,
        )
        return result
    except Exception:
        logger.exception(
            '注册记忆失败 user_id=%s ingested=%d/%d duration_ms=%.0f',
            group_id,
            ingested_count,
            total_messages,
            (time() - start) * 1000,
        )
        raise
    finally:
        CURRENT_REQUEST_USAGE.reset(context_token)


@app.post('/memory/delete', response_model=ClearMemoryResponse)
async def clear_memory(request: ClearMemoryRequest, http_request: Request) -> ClearMemoryResponse:
    logger.info('开始清理记忆 user_id=%s', request.user_id)
    async with get_user_lock(http_request, request.user_id):
        graphiti = await get_user_graphiti(http_request, request.user_id)
        await clear_data(graphiti.driver, group_ids=[request.user_id])
        progress_deleted = delete_register_progress(request.user_id)

    logger.info(
        '完成清理记忆 user_id=%s progress_deleted=%s',
        request.user_id,
        progress_deleted,
    )
    return ClearMemoryResponse(
        user_id=request.user_id,
        deleted=True,
        progress_deleted=progress_deleted,
    )


async def load_graph_view(graphiti: Graphiti, group_id: str, limit: int) -> GraphViewResponse:
    node_records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (n:Entity)
        WHERE n.group_id = $group_id
        RETURN n.uuid AS uuid, n.name AS name, n.summary AS summary
        LIMIT $limit
        """,
        group_id=group_id,
        limit=limit,
    )
    edge_records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
        WHERE r.group_id = $group_id
        RETURN r.uuid AS uuid,
               a.uuid AS source,
               b.uuid AS target,
               r.name AS name,
               r.fact AS fact,
               r.valid_at AS valid_at,
               r.invalid_at AS invalid_at,
               r.created_at AS created_at,
               r.expired_at AS expired_at
        LIMIT $limit
        """,
        group_id=group_id,
        limit=limit,
    )

    nodes = [
        GraphNodeView(
            uuid=str(row.get('uuid') or ''),
            name=str(row.get('name') or ''),
            summary=str(row.get('summary') or ''),
            label='Entity',
        )
        for row in (node_records or [])
        if row.get('uuid')
    ]
    edges = [
        GraphEdgeView(
            uuid=str(row.get('uuid') or ''),
            source=str(row.get('source') or ''),
            target=str(row.get('target') or ''),
            name=str(row.get('name') or ''),
            fact=str(row.get('fact') or ''),
            valid_at=row.get('valid_at'),
            invalid_at=row.get('invalid_at'),
            created_at=row.get('created_at'),
            expired_at=row.get('expired_at'),
        )
        for row in (edge_records or [])
        if row.get('uuid') and row.get('source') and row.get('target')
    ]
    return GraphViewResponse(user_id=group_id, nodes=nodes, edges=edges)


@app.get('/memory/graph', response_model=GraphViewResponse)
async def graph_view(
    http_request: Request,
    user_id: str = Query(..., min_length=1),
    limit: int = Query(default=200, ge=1, le=1000),
) -> GraphViewResponse:
    async with get_user_lock(http_request, user_id):
        graphiti = await get_user_graphiti(http_request, user_id)
        return await load_graph_view(graphiti, user_id, limit)


@app.get('/memory/ui', response_class=HTMLResponse)
async def graph_ui() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Graphiti Memory Graph</title>
  <style>
    body { margin: 0; font-family: sans-serif; background: #0f1419; color: #e7ecf3; }
    .bar { display: flex; gap: 8px; padding: 12px; background: #1a2332; align-items: center; }
    input, button { padding: 8px 10px; border-radius: 6px; border: 1px solid #334155; background: #0f1419; color: #e7ecf3; }
    button { cursor: pointer; background: #2563eb; border-color: #2563eb; }
    #status { margin-left: auto; opacity: 0.8; font-size: 13px; }
    #canvas { width: 100vw; height: calc(100vh - 56px); display: block; background: #0b1016; }
    #panel { position: absolute; right: 12px; top: 68px; width: 320px; max-height: calc(100vh - 90px);
      overflow: auto; background: rgba(26,35,50,0.95); border: 1px solid #334155; border-radius: 8px; padding: 12px; display: none; }
  </style>
</head>
<body>
  <div class="bar">
    <label>user_id</label>
    <input id="userId" value="demo_user_0" style="min-width: 220px;" />
    <button id="loadBtn">加载图谱</button>
    <span id="status">FalkorDB 自带 UI 不可用时，用这个页面查看</span>
  </div>
  <canvas id="canvas"></canvas>
  <div id="panel"></div>
  <script>
    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');
    const panel = document.getElementById('panel');
    const status = document.getElementById('status');
    let nodes = [], edges = [], selected = null;

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight - 56;
    }
    window.addEventListener('resize', resize);
    resize();

    function layout() {
      const w = canvas.width, h = canvas.height;
      nodes.forEach((n, i) => {
        const angle = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
        const radius = Math.min(w, h) * 0.32;
        n.x = w / 2 + Math.cos(angle) * radius;
        n.y = h / 2 + Math.sin(angle) * radius;
        n.vx = 0; n.vy = 0;
      });
    }

    function tick() {
      const nodeMap = Object.fromEntries(nodes.map(n => [n.uuid, n]));
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          let dx = a.x - b.x, dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = 8000 / (dist * dist);
          dx /= dist; dy /= dist;
          a.vx += dx * force; a.vy += dy * force;
          b.vx -= dx * force; b.vy -= dy * force;
        }
      }
      edges.forEach(e => {
        const a = nodeMap[e.source], b = nodeMap[e.target];
        if (!a || !b) return;
        let dx = b.x - a.x, dy = b.y - a.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist - 140) * 0.01;
        dx /= dist; dy /= dist;
        a.vx += dx * force; a.vy += dy * force;
        b.vx -= dx * force; b.vy -= dy * force;
      });
      nodes.forEach(n => {
        n.vx *= 0.85; n.vy *= 0.85;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(30, Math.min(canvas.width - 30, n.x));
        n.y = Math.max(30, Math.min(canvas.height - 30, n.y));
      });
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const nodeMap = Object.fromEntries(nodes.map(n => [n.uuid, n]));
      ctx.strokeStyle = '#475569';
      ctx.lineWidth = 1.2;
      edges.forEach(e => {
        const a = nodeMap[e.source], b = nodeMap[e.target];
        if (!a || !b) return;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      });
      nodes.forEach(n => {
        ctx.beginPath();
        ctx.fillStyle = selected && selected.uuid === n.uuid ? '#60a5fa' : '#38bdf8';
        ctx.arc(n.x, n.y, 10, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#e2e8f0';
        ctx.font = '12px sans-serif';
        ctx.fillText(n.name || n.uuid.slice(0, 8), n.x + 12, n.y + 4);
      });
    }

    function loop() { tick(); draw(); requestAnimationFrame(loop); }
    loop();

    function formatTime(value) {
      return value ? new Date(value).toLocaleString() : '无';
    }

    canvas.addEventListener('click', (ev) => {
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
      selected = nodes.find(n => Math.hypot(n.x - x, n.y - y) < 14) || null;
      if (!selected) { panel.style.display = 'none'; return; }
      const nodeMap = Object.fromEntries(nodes.map(n => [n.uuid, n]));
      const related = edges.filter(e => e.source === selected.uuid || e.target === selected.uuid);
      panel.style.display = 'block';
      panel.innerHTML = `<h3>${selected.name || selected.uuid}</h3>
        <p>${selected.summary || '无摘要'}</p>
        <h4>相关边 (${related.length})</h4>
        ${related.map(e => {
          const sourceName = nodeMap[e.source]?.name || e.source;
          const targetName = nodeMap[e.target]?.name || e.target;
          return `<div style="border-top:1px solid #334155;padding:8px 0">
            <strong>${sourceName} → ${targetName}</strong>
            <div>关系：${e.name || '未命名'}</div>
            <div>事实：${e.fact || '无'}</div>
            <div>有效时间：${formatTime(e.valid_at)} ～ ${formatTime(e.invalid_at)}</div>
            <div>系统时间：${formatTime(e.created_at)} ～ ${formatTime(e.expired_at)}</div>
          </div>`;
        }).join('') || '<p>无</p>'}`;
    });

    document.getElementById('loadBtn').onclick = async () => {
      const userId = document.getElementById('userId').value.trim();
      if (!userId) return;
      status.textContent = '加载中...';
      try {
        const res = await fetch('/memory/graph?user_id=' + encodeURIComponent(userId) + '&limit=200');
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        nodes = data.nodes || [];
        edges = data.edges || [];
        layout();
        status.textContent = `节点 ${nodes.length} / 边 ${edges.length}`;
      } catch (err) {
        status.textContent = '加载失败: ' + err;
      }
    };
  </script>
</body>
</html>"""


@app.post('/memory/search', response_model=SearchResponse)
async def search(request: SearchRequest, http_request: Request) -> SearchResponse:
    usage = RequestUsage()
    context_token = CURRENT_REQUEST_USAGE.set(usage)
    start = time()
    total_queries = len(request.queries)
    logger.info('开始搜索记忆 user_id=%s queries=%d', request.user_id, total_queries)

    try:
        async with get_user_lock(http_request, request.user_id):
            graphiti = await get_user_graphiti(http_request, request.user_id)
            results: list[SearchQueryResult] = []
            for index, query in enumerate(request.queries, start=1):
                logger.info(
                    '开始搜索问题 user_id=%s progress=%d/%d',
                    request.user_id,
                    index,
                    total_queries,
                )
                query_result = await search_context(
                    graphiti, request.user_id, query, SEARCH_RESULT_LIMIT
                )
                results.append(query_result)
                logger.info(
                    '完成搜索问题 user_id=%s progress=%d/%d facts=%d nodes=%d duration_ms=%.0f',
                    request.user_id,
                    index,
                    total_queries,
                    len(query_result.facts),
                    len(query_result.nodes),
                    query_result.duration_ms,
                )

        result = SearchResponse(
            user_id=request.user_id,
            results=results,
            duration_ms=(time() - start) * 1000,
            **usage_fields(usage),
        )
        logger.info(
            '完成搜索记忆 user_id=%s queries=%d duration_ms=%.0f total_tokens=%d',
            request.user_id,
            total_queries,
            result.duration_ms,
            result.total_tokens,
        )
        return result
    except Exception:
        logger.exception(
            '搜索记忆失败 user_id=%s duration_ms=%.0f',
            request.user_id,
            (time() - start) * 1000,
        )
        raise
    finally:
        CURRENT_REQUEST_USAGE.reset(context_token)


@app.post('/memory/response', response_model=ResponseResult)
async def response(request: ResponseRequest, http_request: Request) -> ResponseResult:
    usage = RequestUsage()
    context_token = CURRENT_REQUEST_USAGE.set(usage)
    start = time()
    total_questions = len(request.qa)
    logger.info('开始生成回答 user_id=%s questions=%d', request.user_id, total_questions)

    try:
        async with get_user_lock(http_request, request.user_id):
            graphiti = await get_user_graphiti(http_request, request.user_id)
            results: list[ResponseItem] = []
            for index, qa in enumerate(request.qa, start=1):
                item_start = time()
                logger.info(
                    '开始回答问题 user_id=%s progress=%d/%d',
                    request.user_id,
                    index,
                    total_questions,
                )
                search_result = await search_context(
                    graphiti,
                    request.user_id,
                    qa.question,
                    SEARCH_RESULT_LIMIT,
                )

                llm_client = cast(Any, graphiti.llm_client)
                answer = await locomo_response(
                    llm_client.client,
                    graphiti.llm_client.model or 'gpt-4.1-mini',
                    search_result.context,
                    qa.question,
                )
                duration_ms = (time() - item_start) * 1000
                results.append(
                    ResponseItem(
                        question=qa.question,
                        answer=answer,
                        duration_ms=duration_ms,
                        search_result=search_result,
                    )
                )
                logger.info(
                    '完成回答问题 user_id=%s progress=%d/%d facts=%d nodes=%d duration_ms=%.0f',
                    request.user_id,
                    index,
                    total_questions,
                    len(search_result.facts),
                    len(search_result.nodes),
                    duration_ms,
                )

        result = ResponseResult(
            user_id=request.user_id,
            results=results,
            duration_ms=(time() - start) * 1000,
            total_tokens=usage.total_tokens,
        )
        logger.info(
            '完成生成回答 user_id=%s questions=%d duration_ms=%.0f total_tokens=%d',
            request.user_id,
            total_questions,
            result.duration_ms,
            result.total_tokens,
        )
        return result
    except Exception:
        logger.exception(
            '生成回答失败 user_id=%s duration_ms=%.0f',
            request.user_id,
            (time() - start) * 1000,
        )
        raise
    finally:
        CURRENT_REQUEST_USAGE.reset(context_token)


if __name__ == '__main__':
    import uvicorn  # pyright: ignore[reportMissingImports]

    load_environment(ENV_PATH)
    host = os.environ.get('MEMORY_API_HOST', DEFAULT_SERVER_HOST)
    port = int(os.environ.get('MEMORY_API_PORT', str(DEFAULT_SERVER_PORT)))
    uvicorn.run(app, host=host, port=port)
