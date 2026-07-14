"""Minimal example: call POST /memory/register with a hardcoded JSON body."""

import requests

API_BASE_URL = 'http://127.0.0.1:18003'

payload = {
    'messages': [
        {
            'group_idx': 0,
            'group_id': 'demo_user_0',
            'session_idx': 1,
            'msg_idx': 0,
            'speaker': 'Alice',
            'text': 'I bought a shell necklace in Hawaii last week.',
            'episode_body': 'Alice: I bought a shell necklace in Hawaii last week.',
            'reference_time': '2024-01-15T10:00:00Z',
        },
        {
            'group_idx': 0,
            'group_id': 'demo_user_0',
            'session_idx': 1,
            'msg_idx': 1,
            'speaker': 'Bob',
            'text': 'That sounds lovely! Did you go alone?',
            'episode_body': 'Bob: That sounds lovely! Did you go alone?',
            'reference_time': '2024-01-15T10:00:00Z',
        },
    ],
    'source_description': 'demo message',
}

response = requests.post(f'{API_BASE_URL}/memory/register', json=payload, timeout=600)
response.raise_for_status()
print(response.json())
