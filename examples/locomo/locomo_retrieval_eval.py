"""
Run simple LOCOMO retrieval checks against a self-hosted Graphiti graph.
"""

import asyncio
from pathlib import Path

from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF

from examples.locomo.locomo_utils import build_graphiti_client, load_environment

EXAMPLE_DIR = Path(__file__).parent

# Edit these constants directly before running the script.
ENV_PATH = EXAMPLE_DIR / '.env'
GROUP_ID = 'locomo_experiment_user_0'
QUERIES = [
    'What important personal preferences or facts are known about this user?',
    'What has this user talked about recently?',
]
TOP_K = 10
USE_ADVANCED_SEARCH = False


async def run_basic_search(group_id: str, queries: list[str], top_k: int) -> None:
    graphiti = build_graphiti_client()
    try:
        for query in queries:
            print('=' * 80)
            print(f'Query: {query}')
            print(f'Group: {group_id}')

            facts = await graphiti.search(query, group_ids=[group_id], num_results=top_k)
            if not facts:
                print('No facts found.')
                continue

            for idx, fact in enumerate(facts, start=1):
                print(f'\n[{idx}] {fact.fact}')
                print(f'    uuid: {fact.uuid}')
                print(f'    valid_at: {fact.valid_at}')
                print(f'    invalid_at: {fact.invalid_at}')
    finally:
        await graphiti.close()


async def run_advanced_search(group_id: str, queries: list[str]) -> None:
    graphiti = build_graphiti_client()
    try:
        for query in queries:
            print('=' * 80)
            print(f'Query: {query}')
            print(f'Group: {group_id}')

            results = await graphiti.search_(
                query,
                config=COMBINED_HYBRID_SEARCH_RRF,
                group_ids=[group_id],
            )
            print(f'Edges: {len(results.edges)}')
            for idx, edge in enumerate(results.edges, start=1):
                print(f'\n[edge {idx}] {edge.fact}')

            print(f'\nNodes: {len(results.nodes)}')
            for idx, node in enumerate(results.nodes, start=1):
                print(f'[node {idx}] {node.name}: {node.summary}')

            print(f'\nEpisodes: {len(results.episodes)}')
            for idx, episode in enumerate(results.episodes, start=1):
                print(f'[episode {idx}] {episode.name}: {episode.content[:200]}')
    finally:
        await graphiti.close()


async def main() -> None:
    load_environment(ENV_PATH)

    if USE_ADVANCED_SEARCH:
        await run_advanced_search(GROUP_ID, QUERIES)
    else:
        await run_basic_search(GROUP_ID, QUERIES, TOP_K)


if __name__ == '__main__':
    asyncio.run(main())
