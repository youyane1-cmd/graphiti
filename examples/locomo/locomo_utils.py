"""
Shared helpers for the self-hosted Graphiti LOCOMO examples.
"""

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from urllib.request import urlopen

from dotenv import load_dotenv

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient, StructuredOutputMode

DEFAULT_LOCOMO_URL = (
    'https://raw.githubusercontent.com/snap-research/locomo/refs/heads/main/data/locomo10.json'
)
DEFAULT_DATE_FORMAT = '%I:%M %p on %d %B, %Y UTC'


@dataclass(frozen=True)
class LocomoMessage:
    group_idx: int
    group_id: str
    session_idx: int
    msg_idx: int
    speaker: str
    text: str
    episode_body: str
    reference_time: datetime


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise ValueError(f'{name} must be set')
    return value or ''


def load_environment(env_path: Path | None = None) -> None:
    if env_path is not None:
        load_dotenv(env_path)
    else:
        load_dotenv()


def normalize_locomo_records(data: object) -> list[dict]:
    if isinstance(data, list):
        return [record for record in data if isinstance(record, dict)]

    if isinstance(data, dict):
        for key in ('data', 'records', 'examples'):
            value = data.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]

        if isinstance(data.get('conversation'), dict):
            return [data]

    raise ValueError('Unsupported LOCOMO JSON structure')


def load_locomo_dataset(data_path: Path) -> list[dict]:
    with data_path.open(encoding='utf-8') as file:
        data = json.load(file)
    return normalize_locomo_records(data)


def download_locomo_dataset(url: str, data_path: Path, *, force: bool = False) -> list[dict]:
    if data_path.exists() and not force:
        return load_locomo_dataset(data_path)

    data_path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url) as response:
        data = json.loads(response.read().decode('utf-8'))

    with data_path.open('w', encoding='utf-8') as file:
        json.dump(data, file, indent=2, ensure_ascii=False)

    return normalize_locomo_records(data)


def parse_session_time(raw_session_time: str | None) -> datetime:
    if not raw_session_time:
        return datetime.now(timezone.utc)

    session_time = raw_session_time.strip()
    if not session_time.endswith('UTC'):
        session_time = f'{session_time} UTC'

    return datetime.strptime(session_time, DEFAULT_DATE_FORMAT).replace(tzinfo=timezone.utc)


def iter_locomo_messages(
    records: list[dict],
    *,
    num_users: int,
    max_session_count: int,
    group_prefix: str,
) -> Iterator[LocomoMessage]:
    for group_idx, record in enumerate(records[:num_users]):
        conversation = record.get('conversation')
        if not isinstance(conversation, dict):
            continue

        group_id = f'{group_prefix}_{group_idx}'

        for session_idx in range(max_session_count):
            session = conversation.get(f'session_{session_idx}')
            if not isinstance(session, list):
                continue

            reference_time = parse_session_time(
                conversation.get(f'session_{session_idx}_date_time')
            )

            for msg_idx, message in enumerate(session):
                if not isinstance(message, dict):
                    continue

                speaker = str(message.get('speaker') or 'Unknown').strip()
                text = str(message.get('text') or '').strip()
                if not text:
                    continue

                blip_caption = message.get('blip_captions')
                img_description = (
                    f' (description of attached image: {blip_caption})'
                    if blip_caption is not None
                    else ''
                )

                yield LocomoMessage(
                    group_idx=group_idx,
                    group_id=group_id,
                    session_idx=session_idx,
                    msg_idx=msg_idx,
                    speaker=speaker,
                    text=text,
                    episode_body=f'{speaker}: {text}{img_description}',
                    reference_time=reference_time,
                )


def build_graphiti_client() -> Graphiti:
    api_key = env('OPENAI_API_KEY', required=True)
    base_url = env('OPENAI_BASE_URL', required=True)
    llm_model = env('LLM_MODEL', required=True)
    small_llm_model = env('SMALL_LLM_MODEL', llm_model)
    cross_encoder_model = env('CROSS_ENCODER_MODEL', 'gpt-4.1-nano')
    embedding_model = env('EMBEDDING_MODEL', required=True)
    embedding_dim = int(env('EMBEDDING_DIM', '1024'))
    structured_output_mode_value = env('STRUCTURED_OUTPUT_MODE', 'json_schema')

    if structured_output_mode_value not in {'json_schema', 'json_object'}:
        raise ValueError('STRUCTURED_OUTPUT_MODE must be json_schema or json_object')
    structured_output_mode = cast(StructuredOutputMode, structured_output_mode_value)

    llm_config = LLMConfig(
        api_key=api_key,
        model=llm_model,
        small_model=small_llm_model,
        base_url=base_url,
        temperature=0,
    )
    llm_client = OpenAIGenericClient(
        config=llm_config,
        structured_output_mode=structured_output_mode,
    )
    cross_encoder_config = LLMConfig(
        api_key=api_key,
        model=cross_encoder_model,
        base_url=base_url,
        temperature=0,
    )
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=api_key,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            base_url=base_url,
        )
    )
    cross_encoder = OpenAIRerankerClient(
        config=cross_encoder_config,
        client=llm_client.client,
    )

    graph_driver = FalkorDriver(
        host=env('FALKORDB_HOST', 'localhost'),
        port=int(env('FALKORDB_PORT', '6379')),
        username=env('FALKORDB_USERNAME') or None,
        password=env('FALKORDB_PASSWORD') or None,
        database=env('FALKORDB_DATABASE', 'graphiti_memory'),
    )

    return Graphiti(
        graph_driver=graph_driver,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
    )
