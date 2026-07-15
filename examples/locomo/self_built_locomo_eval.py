import json
import os
from datetime import datetime
from pathlib import Path

import requests


API_BASE_URL = os.getenv('GRAPHITI_API_BASE_URL', 'http://10.110.159.20:18003').strip().rstrip('/')
REQUEST_TIMEOUT = int(os.getenv('GRAPHITI_API_TIMEOUT', '1000000'))

DATASET_FILE = Path('self-bulid_data_locomo.json')
OUTPUT_DIR = Path('graphti')
RESULT_FILE = OUTPUT_DIR / 'self-bulid_data_all_loco_results.json'
USAGE_FILE = OUTPUT_DIR / 'self-bulid_data_run_usage_loco.json'

USER_ID = 'self-bulid_data_conv1'
QUERY_TIME = '2026-01-01'
QUERY_PREFIX = f'Current date: {QUERY_TIME}, '
SOURCE_DESCRIPTION = 'Self-built LoCoMo conversation'


def as_string(value):
    return '' if value is None else str(value)


def parse_session_timestamp(value):
    """将 LoCoMo 会话时间转换成 Graphiti 要求的 ISO 8601 格式。"""
    value = as_string(value).strip()
    if not value:
        raise ValueError('会话缺少 date_time')

    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).isoformat()
    except ValueError:
        pass

    formats = (
        '%I:%M %p on %d %B, %Y',
        '%I:%M %p on %d %B %Y',
        '%H:%M on %d %B, %Y',
        '%H:%M on %d %B %Y',
    )
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format).isoformat()
        except ValueError:
            continue
    raise ValueError(f'无法解析会话时间：{value!r}')


def session_number(session_key):
    try:
        return int(session_key.removeprefix('session_'))
    except ValueError:
        return 0


def process_conversation(conversation):
    session_keys = sorted(
        (
            key
            for key in conversation
            if key.startswith('session_') and not key.endswith('_date_time')
        ),
        key=session_number,
    )

    messages = []
    for session_idx, session_key in enumerate(session_keys):
        timestamp = parse_session_timestamp(conversation.get(f'{session_key}_date_time'))
        dialogs = conversation.get(session_key, [])
        if not isinstance(dialogs, list):
            raise ValueError(f'{session_key} 不是消息列表')

        for msg_idx, dialog in enumerate(dialogs):
            if not isinstance(dialog, dict):
                raise ValueError(f'{session_key} 的第 {msg_idx} 条消息不是对象')

            content = as_string(dialog.get('text')).strip()
            image_caption = as_string(dialog.get('blip_caption')).strip()
            if image_caption:
                content = f'{content} (image description: {image_caption})'.strip()
            if not content:
                continue

            messages.append(
                {
                    'session_idx': session_idx,
                    'msg_idx': msg_idx,
                    'speaker': as_string(dialog.get('speaker')).strip() or 'unknown',
                    'content': content,
                    'timestamp': timestamp,
                }
            )
    return messages


def build_request_qa(qa_pairs):
    request_qa = []
    for qa in qa_pairs:
        if not isinstance(qa, dict):
            raise ValueError('qa 中存在非对象数据')
        original_question = as_string(qa.get('question')).strip()
        if not original_question:
            raise ValueError('qa 中存在空问题')
        request_qa.append({'question': f'{QUERY_PREFIX}{original_question}'})
    return request_qa


def request_json(method, path, payload):
    response = requests.request(
        method,
        f'{API_BASE_URL}{path}',
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if not response.ok:
        raise requests.HTTPError(
            f'{response.status_code} {response.reason} for {response.url}; '
            f'body={response.text}',
            response=response,
        )
    return response.json()


def call_clear_memory():
    return request_json('POST', '/memory/delete', {'user_id': USER_ID})


def call_add_memory(messages):
    return request_json(
        'POST',
        '/memory/add',
        {
            'user_id': USER_ID,
            'messages': messages,
            'source_description': SOURCE_DESCRIPTION,
        },
    )


def call_get_response(request_qa):
    return request_json(
        'POST',
        '/memory/response',
        {
            'user_id': USER_ID,
            'qa': request_qa,
        },
    )


def load_json_list(path):
    if not path.exists():
        return []
    try:
        with path.open('r', encoding='utf-8') as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except Exception as exc:
        print(f'读取 {path} 失败，将使用空列表：{exc}')
        return []


def atomic_write_json(path, data):
    temp_path = path.with_suffix(path.suffix + '.tmp')
    with temp_path.open('w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


def build_results(qa_pairs, request_qa, response_result):
    response_items = response_result.get('results', [])
    if not isinstance(response_items, list):
        raise ValueError('回答接口的 results 不是列表')
    if len(response_items) != len(qa_pairs):
        raise ValueError(
            f'回答数量不一致：请求 {len(qa_pairs)} 个，返回 {len(response_items)} 个'
        )

    results = []
    for qa, request_item, response_item in zip(qa_pairs, request_qa, response_items):
        if not isinstance(response_item, dict):
            raise ValueError('回答接口返回了非对象结果')

        search_result = response_item.get('search_result', {})
        if not isinstance(search_result, dict):
            raise ValueError('回答接口返回的 search_result 不是对象')

        results.append(
            {
                'user_id': USER_ID,
                'query_time': QUERY_TIME,
                'query': as_string(request_item.get('question')),
                'question_type': as_string(qa.get('category')),
                'original_answer': as_string(qa.get('answer')),
                'system_answer': as_string(response_item.get('answer')),
                'search_result': search_result,
            }
        )
    return results


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    existing_usage = load_json_list(USAGE_FILE)
    if any(
        isinstance(item, dict) and as_string(item.get('user_id')) == USER_ID
        for item in existing_usage
    ):
        print(f'{USER_ID} 已在 usage 文件中完成，跳过。')
        return

    try:
        with DATASET_FILE.open('r', encoding='utf-8') as file:
            dataset = json.load(file)
        if not isinstance(dataset, list) or len(dataset) != 1:
            raise ValueError('数据集必须是只包含一个样本的列表')

        sample = dataset[0]
        if not isinstance(sample, dict):
            raise ValueError('数据集样本不是对象')
        conversation = sample.get('conversation')
        qa_pairs = sample.get('qa')
        if not isinstance(conversation, dict):
            raise ValueError('样本缺少合法的 conversation')
        if not isinstance(qa_pairs, list) or not qa_pairs:
            raise ValueError('样本缺少合法的 qa')

        messages = process_conversation(conversation)
        if not messages:
            raise ValueError('没有可注册的消息')
        request_qa = build_request_qa(qa_pairs)

        # usage 没有完成记录时，可能存在上次中断的残留，先清理再注册。
        clear_result = call_clear_memory()
        print(
            f"已清理旧记忆：deleted={clear_result.get('deleted')}, "
            f"progress_deleted={clear_result.get('progress_deleted')}"
        )

        print(f'注册 {len(messages)} 条消息，user_id={USER_ID}')
        register_result = call_add_memory(messages)

        print(f'批量回答 {len(request_qa)} 个问题')
        response_result = call_get_response(request_qa)
        results = build_results(qa_pairs, request_qa, response_result)

        usage = [
            {
                'user_id': USER_ID,
                'register_total_tokens': register_result.get('total_tokens', 0),
                'register_duration_ms': register_result.get('duration_ms', 0),
                'response_total_tokens': response_result.get('total_tokens', 0),
                'response_duration_ms': response_result.get('duration_ms', 0),
            }
        ]

        # 先写结果，再写 usage；只有 usage 落盘后才会被视为完整断点。
        atomic_write_json(RESULT_FILE, results)
        atomic_write_json(USAGE_FILE, usage)
        print(f'处理完成。结果：{RESULT_FILE}；用量：{USAGE_FILE}')
    except Exception as exc:
        print(f'处理失败，等待下次重新清理并续跑：{exc}')


if __name__ == '__main__':
    main()
