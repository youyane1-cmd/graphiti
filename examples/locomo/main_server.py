"""
Minimal LOCOMO API service backed by local Graphiti + Docker FalkorDB.
"""

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from time import time
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request  # pyright: ignore[reportMissingImports]
from graphiti_core import Graphiti
from graphiti_core.edges import EntityEdge
from graphiti_core.nodes import EntityNode, EpisodeType
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_CROSS_ENCODER,
    NODE_HYBRID_SEARCH_RRF,
)
from graphiti_core.utils.maintenance.graph_data_operations import clear_data
from pydantic import BaseModel, Field

from examples.locomo.locomo_responses import locomo_response  # pyright: ignore[reportMissingImports]
from examples.locomo.locomo_utils import build_graphiti_client, load_environment

EXAMPLE_DIR = Path(__file__).parent
ENV_PATH = EXAMPLE_DIR / '.env'
REGISTER_PROGRESS_DIR = EXAMPLE_DIR / 'data' / 'register_progress'
DEFAULT_SERVER_HOST = '0.0.0.0'
DEFAULT_SERVER_PORT = 8000

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
    group_idx: int
    group_id: str
    session_idx: int
    msg_idx: int
    speaker: str
    text: str
    episode_body: str
    reference_time: datetime


class RegisterRequest(BaseModel):
    messages: list[RegisterMessage] = Field(..., min_length=1)
    source_description: str = 'LOCOMO message'


class RegisterResponse(BaseModel):
    group_ids: list[str]
    ingested_count: int
    episode_names: list[str]


class ClearMemoryRequest(BaseModel):
    group_id: str = Field(..., min_length=1)


class ClearMemoryResponse(BaseModel):
    group_id: str
    deleted: bool
    progress_deleted: bool


class SearchRequest(BaseModel):
    group_id: str
    queries: list[str] = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


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
    group_id: str
    results: list[SearchQueryResult]


class QAItem(BaseModel):
    question: str
    answer: str | None = None


class ResponseRequest(BaseModel):
    group_id: str
    qa: list[QAItem] = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class ResponseItem(BaseModel):
    question: str
    answer: str
    golden_answer: str | None = None
    duration_ms: float
    facts: list[FactResult]


class ResponseResult(BaseModel):
    group_id: str
    results: list[ResponseItem]


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_environment(ENV_PATH)
    graphiti = build_graphiti_client()
    await graphiti.build_indices_and_constraints()
    app.state.graphiti = graphiti
    try:
        yield
    finally:
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


def build_episode_name(message: RegisterMessage) -> str:
    return (
        f'locomo_user_{message.group_idx}_'
        f'session_{message.session_idx}_msg_{message.msg_idx}'
    )


def register_progress_path(group_id: str) -> Path:
    safe_group_id = re.sub(r'[^A-Za-z0-9_.-]+', '_', group_id)
    return REGISTER_PROGRESS_DIR / f'{safe_group_id}_register_progress.json'


def load_register_progress(group_id: str) -> list[str]:
    path = register_progress_path(group_id)
    if not path.exists():
        return []

    with path.open(encoding='utf-8') as file:
        progress = json.load(file)

    if not isinstance(progress, list) or not all(isinstance(item, str) for item in progress):
        raise HTTPException(status_code=500, detail=f'Invalid register progress file: {path}')

    return progress


def save_register_progress(group_id: str, episode_names: list[str]) -> None:
    REGISTER_PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    path = register_progress_path(group_id)
    with path.open('w', encoding='utf-8') as file:
        json.dump(episode_names, file, indent=2, ensure_ascii=False)


def delete_register_progress(group_id: str) -> bool:
    path = register_progress_path(group_id)
    if not path.exists():
        return False

    path.unlink()
    return True


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


@app.post('/memory/register', response_model=RegisterResponse)
async def register(request: RegisterRequest, http_request: Request) -> RegisterResponse:
    graphiti = get_graphiti(http_request)
    group_ids = sorted({message.group_id for message in request.messages})

    for message in request.messages:
        episode_name = build_episode_name(message)
        group_progress = load_register_progress(message.group_id)
        if episode_name in group_progress:
            continue

        await graphiti.add_episode(
            name=episode_name,
            episode_body=message.episode_body,
            source=EpisodeType.message,
            source_description=request.source_description,
            reference_time=message.reference_time,
            group_id=message.group_id,
        )
        group_progress.append(episode_name)
        save_register_progress(message.group_id, group_progress)

    episode_names = [
        episode_name
        for group_id in group_ids
        for episode_name in load_register_progress(group_id)
    ]

    return RegisterResponse(
        group_ids=group_ids,
        ingested_count=len(episode_names),
        episode_names=episode_names,
    )


@app.post('/memory/clear', response_model=ClearMemoryResponse)
async def clear_memory(request: ClearMemoryRequest, http_request: Request) -> ClearMemoryResponse:
    graphiti = get_graphiti(http_request)
    await clear_data(graphiti.driver, group_ids=[request.group_id])
    progress_deleted = delete_register_progress(request.group_id)

    return ClearMemoryResponse(
        group_id=request.group_id,
        deleted=True,
        progress_deleted=progress_deleted,
    )


@app.post('/memory/search', response_model=SearchResponse)
async def search(request: SearchRequest, http_request: Request) -> SearchResponse:
    graphiti = get_graphiti(http_request)
    results: list[SearchQueryResult] = []

    for query in request.queries:
        results.append(await search_context(graphiti, request.group_id, query, request.limit))

    return SearchResponse(
        group_id=request.group_id,
        results=results,
    )


@app.post('/memory/response', response_model=ResponseResult)
async def response(request: ResponseRequest, http_request: Request) -> ResponseResult:
    graphiti = get_graphiti(http_request)
    results: list[ResponseItem] = []

    for qa in request.qa:
        start = time()
        search_result = await search_context(
            graphiti,
            request.group_id,
            qa.question,
            request.limit,
        )

        llm_client = cast(Any, graphiti.llm_client)
        answer = await locomo_response(
            llm_client.client,
            graphiti.llm_client.model,
            search_result.context,
            qa.question,
        )
        duration_ms = (time() - start) * 1000
        results.append(
            ResponseItem(
                question=qa.question,
                answer=answer,
                golden_answer=qa.answer,
                duration_ms=duration_ms,
                facts=search_result.facts,
            )
        )

    return ResponseResult(
        group_id=request.group_id,
        results=results,
    )


if __name__ == '__main__':
    import uvicorn  # pyright: ignore[reportMissingImports]

    load_environment(ENV_PATH)
    host = os.environ.get('MEMORY_API_HOST', DEFAULT_SERVER_HOST)
    port = int(os.environ.get('MEMORY_API_PORT', str(DEFAULT_SERVER_PORT)))
    uvicorn.run(app, host=host, port=port)
