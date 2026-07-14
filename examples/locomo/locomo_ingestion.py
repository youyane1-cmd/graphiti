"""
Ingest LOCOMO conversations into a self-hosted Graphiti + FalkorDB graph.
"""

import asyncio
from pathlib import Path

from graphiti_core.nodes import EpisodeType

from examples.locomo.locomo_utils import (
    DEFAULT_LOCOMO_URL,
    build_graphiti_client,
    download_locomo_dataset,
    iter_locomo_messages,
    load_environment,
)

EXAMPLE_DIR = Path(__file__).parent

# Edit these constants directly before running the script.
ENV_PATH = EXAMPLE_DIR / '.env'
DATA_URL = DEFAULT_LOCOMO_URL
DATA_PATH = EXAMPLE_DIR / 'data' / 'locomo.json'
NUM_USERS = 10
MAX_SESSION_COUNT = 35
GROUP_PREFIX = 'locomo_experiment_user'
FORCE_DOWNLOAD = False
BUILD_INDICES = True


async def main() -> None:
    load_environment(ENV_PATH)

    records = download_locomo_dataset(DATA_URL, DATA_PATH, force=FORCE_DOWNLOAD)
    print(f'Loaded {len(records)} LOCOMO records from {DATA_PATH}')

    graphiti = build_graphiti_client()
    ingested_count = 0

    try:
        if BUILD_INDICES:
            print('Building Graphiti indices and constraints...')
            await graphiti.build_indices_and_constraints()

        for message in iter_locomo_messages(
            records,
            num_users=NUM_USERS,
            max_session_count=MAX_SESSION_COUNT,
            group_prefix=GROUP_PREFIX,
        ):
            episode_name = (
                f'locomo_user_{message.group_idx}_'
                f'session_{message.session_idx}_msg_{message.msg_idx}'
            )

            await graphiti.add_episode(
                name=episode_name,
                episode_body=message.episode_body,
                source=EpisodeType.message,
                source_description='LOCOMO message',
                reference_time=message.reference_time,
                group_id=message.group_id,
            )

            ingested_count += 1
            print(
                f'[{ingested_count}] {message.group_id} '
                f'session_{message.session_idx} msg_{message.msg_idx}'
            )

        print(f'Finished ingesting {ingested_count} LOCOMO messages into Graphiti.')
    finally:
        await graphiti.close()


if __name__ == '__main__':
    asyncio.run(main())
