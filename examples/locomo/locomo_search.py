"""
Generate LOCOMO search contexts with self-hosted Graphiti.

This mirrors zep_locomo_search.py, replacing Zep Cloud search with Graphiti search.
"""

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from time import time

from graphiti_core.edges import EntityEdge
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import (
    EDGE_HYBRID_SEARCH_CROSS_ENCODER,
    NODE_HYBRID_SEARCH_RRF,
)

from examples.locomo.locomo_utils import (
    DEFAULT_LOCOMO_URL,
    build_graphiti_client,
    download_locomo_dataset,
    load_environment,
)

TEMPLATE = """
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

EXAMPLE_DIR = Path(__file__).parent

# Edit these constants directly before running the script.
ENV_PATH = EXAMPLE_DIR / '.env'
DATA_URL = DEFAULT_LOCOMO_URL
DATA_PATH = EXAMPLE_DIR / 'data' / 'locomo.json'
OUTPUT_PATH = EXAMPLE_DIR / 'data' / 'locomo_search_results.json'
NUM_USERS = 10
GROUP_PREFIX = 'locomo_experiment_user'
LIMIT = 20
FORCE_DOWNLOAD = False


def compose_search_context(edges: list[EntityEdge], nodes: list[EntityNode]) -> str:
    facts = [f' - {edge.fact} (event_time: {edge.valid_at})' for edge in edges]
    entities = [f' - {node.name}: {node.summary}' for node in nodes]
    return TEMPLATE.format(facts='\n'.join(facts), entities='\n'.join(entities))


async def main() -> None:
    load_environment(ENV_PATH)

    records = download_locomo_dataset(DATA_URL, DATA_PATH, force=FORCE_DOWNLOAD)
    graphiti = build_graphiti_client()
    search_results: dict[str, list[dict]] = defaultdict(list)

    try:
        node_config = NODE_HYBRID_SEARCH_RRF.model_copy(update={'limit': LIMIT})
        edge_config = EDGE_HYBRID_SEARCH_CROSS_ENCODER.model_copy(update={'limit': LIMIT})

        for group_idx, record in enumerate(records[:NUM_USERS]):
            qa_set = record.get('qa')
            if not isinstance(qa_set, list):
                continue

            group_id = f'{GROUP_PREFIX}_{group_idx}'
            print(group_id)

            for qa in qa_set:
                if not isinstance(qa, dict):
                    continue
                if qa.get('category') == 5:
                    continue

                query = str(qa.get('question') or '').strip()
                if not query:
                    continue

                start = time()
                node_results, edge_results = await asyncio.gather(
                    graphiti.search_(query, config=node_config, group_ids=[group_id]),
                    graphiti.search_(query, config=edge_config, group_ids=[group_id]),
                )

                context = compose_search_context(edge_results.edges, node_results.nodes)
                duration_ms = (time() - start) * 1000

                search_results[group_id].append(
                    {
                        'context': context,
                        'duration_ms': duration_ms,
                    }
                )

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT_PATH.open('w', encoding='utf-8') as file:
            json.dump(dict(search_results), file, indent=2, ensure_ascii=False, default=str)
        print(f'Saved search results to {OUTPUT_PATH}')
    finally:
        await graphiti.close()


if __name__ == '__main__':
    asyncio.run(main())
