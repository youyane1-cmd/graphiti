"""
Generate LOCOMO answers from saved Graphiti search contexts.

This mirrors zep_locomo_responses.py, replacing the hardcoded OpenAI client setup with
the local OpenAI-compatible settings from examples/locomo/.env.
"""

import asyncio
import json
from pathlib import Path
from time import time

from openai import AsyncOpenAI

from examples.locomo.locomo_utils import (
    env,
    load_environment,
    load_locomo_dataset,
)

EXAMPLE_DIR = Path(__file__).parent

# Edit these constants directly before running the script.
ENV_PATH = EXAMPLE_DIR / '.env'
DATA_PATH = EXAMPLE_DIR / 'data' / 'locomo.json'
SEARCH_RESULTS_PATH = EXAMPLE_DIR / 'data' / 'locomo_search_results.json'
OUTPUT_PATH = EXAMPLE_DIR / 'data' / 'locomo_responses.json'
NUM_USERS = 10
GROUP_PREFIX = 'locomo_experiment_user'


async def locomo_response(llm_client: AsyncOpenAI, model: str, context: str, question: str) -> str:
    system_prompt = """
 You are a helpful expert assistant answering questions from lme_experiment users based on the provided context.
 """

    prompt = f"""
 # CONTEXT:
 You have access to facts and entities from a conversation.

 # INSTRUCTIONS:
 1. Carefully analyze all provided memories
 2. Pay special attention to the timestamps to determine the answer
 3. If the question asks about a specific event or fact, look for direct evidence in the memories
 4. If the memories contain contradictory information, prioritize the most recent memory
 5. Always convert relative time references to specific dates, months, or years.
 6. Be as specific as possible when talking about people, places, and events
 7. Timestamps in memories represent the actual time the event occurred, not the time the event was mentioned in a message.

 Clarification:
 When interpreting memories, use the timestamp to determine when the described event happened, not when someone talked about the event.

 Example:

 Memory: (2023-03-15T16:33:00Z) I went to the vet yesterday.
 Question: What day did I go to the vet?
 Correct Answer: March 15, 2023
 Explanation:
 Even though the phrase says "yesterday," the timestamp shows the event was recorded as happening on March 15th. Therefore, the actual vet visit happened on that date, regardless of the word "yesterday" in the text.

 # APPROACH (Think step by step):
 1. First, examine all memories that contain information related to the question
 2. Examine the timestamps and content of these memories carefully
 3. Look for explicit mentions of dates, times, locations, or events that answer the question
 4. If the answer requires calculation (e.g., converting relative time references), show your work
 5. Formulate a precise, concise answer based solely on the evidence in the memories
 6. Double-check that your answer directly addresses the question asked
 7. Ensure your final answer is specific and avoids vague time references

 Context:

 {context}

 Question: {question}
 Answer:
 """

    response = await llm_client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt},
        ],
        temperature=0,
    )
    return response.choices[0].message.content or ''


async def process_qa(
    qa: dict,
    search_result: dict,
    llm_client: AsyncOpenAI,
    model: str,
) -> dict:
    start = time()
    query = str(qa.get('question') or '')
    golden_answer = qa.get('answer')

    answer = await locomo_response(llm_client, model, search_result.get('context', ''), query)
    duration_ms = (time() - start) * 1000

    return {
        'question': query,
        'answer': answer,
        'golden_answer': golden_answer,
        'duration_ms': duration_ms,
    }


async def main() -> None:
    load_environment(ENV_PATH)

    records = load_locomo_dataset(DATA_PATH)
    with SEARCH_RESULTS_PATH.open(encoding='utf-8') as file:
        search_results = json.load(file)

    llm_client = AsyncOpenAI(
        api_key=env('OPENAI_API_KEY', required=True),
        base_url=env('OPENAI_BASE_URL') or None,
    )
    model = env('LLM_MODEL', required=True)

    responses: dict[str, list[dict]] = {}
    for group_idx, record in enumerate(records[:NUM_USERS]):
        qa_set = record.get('qa')
        if not isinstance(qa_set, list):
            continue

        qa_set_filtered = [
            qa for qa in qa_set if isinstance(qa, dict) and qa.get('category') != 5
        ]
        group_id = f'{GROUP_PREFIX}_{group_idx}'
        group_search_results = search_results.get(group_id, [])

        tasks = [
            process_qa(qa, search_result, llm_client, model)
            for qa, search_result in zip(qa_set_filtered, group_search_results, strict=True)
        ]

        responses[group_id] = await asyncio.gather(*tasks)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open('w', encoding='utf-8') as file:
        json.dump(responses, file, indent=2, ensure_ascii=False, default=str)
    print(f'Saved responses to {OUTPUT_PATH}')


if __name__ == '__main__':
    asyncio.run(main())
