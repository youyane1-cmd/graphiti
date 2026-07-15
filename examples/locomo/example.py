"""Call the add, search, and response endpoints with one demo user."""

import json

import requests

API_BASE_URL = 'http://10.110.159.20:18003'
USER_ID = 'demo_user_0'
TIMEOUT_SECONDS = 600


def post(path: str, payload: dict) -> dict:
    response = requests.post(f'{API_BASE_URL}{path}', json=payload, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def main() -> None:
    add_result = post(
        '/memory/add',
        {
            'user_id': USER_ID,
            'messages': [
                {
                    'session_idx': 1,
                    'msg_idx': 0,
                    'speaker': 'Alice',
                    'content': 'I bought a shell necklace in Hawaii last week.',
                    'timestamp': '2024-01-15T10:00:00Z',
                },
                {
                    'session_idx': 1,
                    'msg_idx': 1,
                    'speaker': 'Alice',
                    'content': 'I enjoy photography, especially city night scenes.',
                    'timestamp': '2024-01-15T10:01:00Z',
                },
            ],
            'source_description': 'demo message',
        },
    )
    print('POST /memory/add')
    print(json.dumps(add_result, ensure_ascii=False, indent=2))

    search_result = post(
        '/memory/search',
        {
            'user_id': USER_ID,
            'queries': ['Alice 喜欢什么？'],
        },
    )
    print('\nPOST /memory/search')
    print(json.dumps(search_result, ensure_ascii=False, indent=2))

    response_result = post(
        '/memory/response',
        {
            'user_id': USER_ID,
            'qa': [{'question': 'Alice 喜欢什么？'}],
        },
    )
    print('\nPOST /memory/response')
    print(json.dumps(response_result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
