# API 调用高密度笔记：HTTP 传输与 Chat 模型

核心先记住一句话：

> API 调用不是只给一个 URL，而是一次 HTTP 请求：`method + url + headers + body`。  
> 对 Chat 模型来说，大多数情况都是 `POST /chat/completions`，变化主要发生在 `body` 里。

## 1. 一次 HTTP 请求到底传了什么

一次请求通常由四部分组成：

```text
METHOD URL
Headers

Body
```

比如 Chat 模型调用大概是：

```http
POST https://api.example.com/v1/chat/completions
Authorization: Bearer sk-xxx
Content-Type: application/json

{
  "model": "gpt-4o-mini",
  "messages": [
    {"role": "user", "content": "你好"}
  ]
}
```

各部分含义：

- `POST`：请求方法，表示“把数据提交给服务端处理”。
- `url`：接口地址，告诉请求发到哪里。
- `headers`：请求头，常放鉴权和格式说明。
- `body`：请求体，真正要让服务处理的数据。

常见 headers：

```http
Authorization: Bearer 你的_API_KEY
Content-Type: application/json
```

其中：

- `Authorization`：告诉服务端你是谁，有没有权限。
- `Content-Type`：告诉服务端 body 是什么格式。

## 2. 请求头鉴权：api_key 放哪、谁决定、怎么取

先记住结论：

> `api_key` 通常不放在 JSON body 里，而是放在 HTTP 请求头 `Authorization` 里。  
> 字段名和格式是**服务端约定**的；客户端只是按约定去传。

### 2.1 服务端实际收到什么样的请求

OpenAI 兼容接口常见完整请求是：

```http
POST https://api.openai.com/v1/chat/completions
Authorization: Bearer sk-xxxxxx
Content-Type: application/json

{
  "model": "gpt-4o-mini",
  "messages": [
    {"role": "user", "content": "你好"}
  ]
}
```

注意拆分：

| 位置 | 放什么 | 例子 |
|---|---|---|
| Header | 鉴权、内容类型 | `Authorization`、`Content-Type` |
| Body | 业务参数 | `model`、`messages` |

所以：

- body 里只有 `model`、`messages` 这类业务数据
- `api_key` 在 header 的 `Authorization` 里
- `base_url` 只是客户端用来拼 URL，不会出现在 body 里

### 2.2 Bearer 是什么意思

常见写法：

```http
Authorization: Bearer sk-xxxxxx
```

可以拆成两段：

```text
Authorization: <鉴权方案> <凭证>
```

对 OpenAI 风格接口：

- 鉴权方案 = `Bearer`
- 凭证 = 你的 `api_key`

服务端通常会：

1. 读取请求头 `Authorization`
2. 检查是否以 `Bearer ` 开头
3. 取出后面的 key
4. 去自己的数据库 / 配置里校验这个 key 是否有效

### 2.3 谁规定必须用 Authorization？

是服务端规定的。

- OpenAI 官方约定：用 `Authorization: Bearer <api_key>`
- 兼容 OpenAI 的中转 / 自建网关：通常也按同样约定实现
- 如果你自己写服务端，也可以改成别的，例如：

```http
X-API-Key: sk-xxxxxx
```

但一旦改成自定义头，OpenAI SDK 默认就不会自动传这个头了，客户端要自己配。

所以工作里的原则是：

> 鉴权字段以接口文档为准。  
> 文档说 Bearer，就传 Bearer；文档说 `X-API-Key`，就传 `X-API-Key`。

### 2.4 OpenAI SDK：自动把 key 放进请求头

```python
from openai import OpenAI

api_key = "你的_API_KEY"

client = OpenAI(
    api_key=api_key,
    base_url="https://api.openai.com/v1",
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "你好"}],
)
```

你只传了 `api_key=...`，SDK 会自动变成：

```http
Authorization: Bearer 你的_API_KEY
```

也就是说：用 SDK 时，一般不用自己手写 headers。

### 2.5 requests：要自己把 key 写进请求头

`requests` 不会帮你做 OpenAI 鉴权封装，所以要自己写：

```python
import requests

api_key = "你的_API_KEY"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

body = {
    "model": "gpt-4o-mini",
    "messages": [
        {"role": "user", "content": "你好"}
    ],
}

resp = requests.post(
    "https://api.openai.com/v1/chat/completions",
    headers=headers,
    json=body,
)

print(resp.json())
```

核心就是这一句：

```python
"Authorization": f"Bearer {api_key}"
```

对比一下：

| 方式 | api_key 怎么处理 |
|---|---|
| OpenAI SDK | 传给 `OpenAI(api_key=...)`，SDK 自动放进 header |
| `requests` | 自己在 `headers` 里写 `Authorization: Bearer ...` |

### 2.6 服务端怎么从请求头取 key

客户端怎么传，服务端就怎么取。约定是双方对齐的。

FastAPI 示例：

```python
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    authorization = request.headers.get("authorization")
    # 例如：Bearer sk-xxxxxx

    if not authorization:
        return {"error": "missing api key"}

    if not authorization.startswith("Bearer "):
        return {"error": "invalid authorization format"}

    api_key = authorization.removeprefix("Bearer ").strip()
    # 得到：sk-xxxxxx

    # 这里再去校验 api_key 是否有效
    return {"ok": True, "api_key_prefix": api_key[:8]}
```

Flask 示例：

```python
from flask import Flask, request

app = Flask(__name__)

@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    authorization = request.headers.get("Authorization")

    if not authorization:
        return {"error": "missing api key"}, 401

    api_key = authorization.replace("Bearer ", "", 1).strip()

    # 校验 api_key ...
    return {"ok": True}
```

流程可以记成：

```text
客户端：api_key -> Header Authorization: Bearer xxx
服务端：读 Authorization -> 去掉 Bearer -> 得到 api_key -> 校验权限
```

### 2.7 常见踩坑

1. 把 `api_key` 塞进 JSON body  
   OpenAI 兼容接口通常不认 body 里的 `api_key`，认的是 header。

2. 忘了 `Bearer ` 前面的空格  
   正确是 `Bearer sk-xxx`，不是 `Bearersk-xxx`。

3. 以为 SDK 的 `base_url` 会带鉴权信息  
   `base_url` 只决定请求发到哪；鉴权靠 header。

4. 自建服务改了鉴权头，却还用官方 SDK 默认行为  
   如果服务端改成 `X-API-Key`，客户端也要跟着改。

### 2.8 这一节记忆版

```text
api_key 放哪？
通常放 Header：Authorization: Bearer <api_key>

谁规定的？
服务端 / 接口文档规定

SDK 怎么做？
OpenAI(api_key=...) 自动写入 Authorization

requests 怎么做？
自己写 headers = {"Authorization": f"Bearer {api_key}"}

服务端怎么取？
request.headers.get("Authorization")
再去掉前面的 "Bearer "
```

## 3. 文本、图片、文件、URL 本质上怎么传

这些东西不是“特殊魔法”，都是按某种格式放进 HTTP 请求里。

| 内容类型 | 请求里传的是什么 | 常见位置 | 服务端怎么得到内容 |
|---|---|---|---|
| 普通文本 | 字符串 | JSON body | 直接读取字符串 |
| 图片 URL | 图片地址字符串 | JSON body | 服务端自己去 URL 下载图片 |
| base64 图片 | 图片二进制转成的文本 | JSON body | 服务端把 base64 解码回图片 bytes |
| 文件上传 | 文件二进制 bytes | `multipart/form-data` body | 服务端直接接收文件 bytes |
| 视频 URL | 视频地址字符串 | JSON body | 服务端自己去 URL 下载视频 |

所以要分清楚：

- `base64`：我把文件内容变成字符串发给你。
- `multipart file`：我把文件二进制直接发给你。
- `url`：我只告诉你文件在哪，你自己去下载。

不是所有接口都同时支持这三种方式。接口文档说支持 `url`，你才能传 URL；文档说支持 `file`，你才能传文件；文档说支持 `base64`，你才能传 base64。

## 4. Chat 模型里 body 怎么变化

Chat 模型通常走：

```text
POST /chat/completions
```

变的主要是 `messages[*].content`。

### 纯文本

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "user",
      "content": "你好，请介绍你自己。"
    }
  ]
}
```

### 文本 + 图片 URL

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "请描述这张图片。"},
        {
          "type": "image_url",
          "image_url": {
            "url": "https://example.com/cat.png"
          }
        }
      ]
    }
  ]
}
```

这里传的是图片地址，不是图片内容。服务端要能访问这个 URL。

### 文本 + base64 图片

```json
{
  "model": "gpt-4o-mini",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "请描述这张图片。"},
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/png;base64,这里是图片base64内容"
          }
        }
      ]
    }
  ]
}
```

这里完整图片内容已经在 JSON 里了。

格式里的：

```text
data:image/png;base64,
```

是在告诉服务端：后面这串文本是 PNG 图片的 base64。

JPG/JPEG 通常写：

```text
data:image/jpeg;base64,
```

### 文本 + 视频 URL

如果某个 Chat 接口支持视频 URL，body 通常也是 JSON。

常见思路是：

```json
{
  "model": "some-video-chat-model",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "请总结这个视频的内容。"},
        {
          "type": "video_url",
          "video_url": {
            "url": "https://example.com/demo.mp4"
          }
        }
      ]
    }
  ]
}
```

这里传的不是视频文件本身，而是视频地址字符串。

流程是：

```text
客户端把视频 URL 放进 JSON body
服务端收到 URL
服务端自己去下载视频
服务端分析视频
服务端返回文本结果
```

注意：

- 不是所有 OpenAI-compatible Chat 接口都支持 `video_url`。
- `type: "video_url"` 只是常见表达方式示例，具体字段名必须看接口文档。
- 视频 URL 的核心要求是：模型服务端能访问到它。公网服务通常需要公网 URL；公司内网模型服务可能能访问内网 URL。
- 本地路径例如 `C:\Users\xxx\video.mp4` 对远程服务端通常没用。

如果视频在本地或内网机器上，可以用 FastAPI 临时把视频目录挂成 HTTP 地址：

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI()

app.mount(
    "/videos",
    StaticFiles(directory="D:/videos"),
    name="videos",
)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )
```

这句 `app.mount("/videos", StaticFiles(directory="D:/videos"), name="videos")` 的意思是：把本地 `D:/videos` 文件夹发布成 HTTP 路径 `/videos/...`，`name="videos"` 只是 FastAPI 内部给这个挂载点起的名字。

假设目录里有：

```text
D:/videos/demo.mp4
```

启动后，同一内网里其他机器通常访问：

```text
http://你的内网IP:8000/videos/demo.mp4
```

然后 Chat body 里就可以传这个 URL：

```json
{
  "type": "video_url",
  "video_url": {
    "url": "http://你的内网IP:8000/videos/demo.mp4"
  }
}
```

关键点：

- `0.0.0.0` 是监听所有网卡，不是给别人访问的真实地址。
- 传给模型服务时，要用真实内网 IP，例如 `http://192.168.1.23:8000/videos/demo.mp4`。
- 能不能访问成功，取决于模型服务所在机器能不能连到这个 IP 和端口。
- 同一个 Wi-Fi 或同一个公司内网经常可以访问，但如果有防火墙、网段隔离、端口限制，也可能不行。

### 文件和视频

文件、PDF、视频不一定能直接塞进 Chat 接口。

常见有三种情况：

1. 接口支持 `multipart/form-data` 文件上传：直接传文件 bytes。
2. 接口支持文件 URL：body 里只传文件地址，服务端自己下载。
3. 接口要求先上传文件到专门的 files 接口，再在 Chat 请求里引用文件 ID。

所以不能默认认为一个 Chat 接口同时支持：

```text
base64 + file + url + video
```

必须看接口文档。

## 5. OpenAI SDK：完整 Chat 调用

SDK 写法里，你传的是 `base_url`，不是完整接口。

```python
from openai import OpenAI

api_url = "https://api.openai.com/v1"
api_key = "你的_API_KEY"

client = OpenAI(
    api_key=api_key,
    base_url=api_url,
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "user", "content": "你好，请介绍你自己。"}
    ],
)

reply = response.choices[0].message.content
print(reply)
```

这句：

```python
client.chat.completions.create(...)
```

实际做的是：

```text
POST https://api.openai.com/v1/chat/completions
```

也就是：

```text
base_url + /chat/completions
```

SDK 还会自动做这些事：

- 把 `api_key` 放进 `Authorization: Bearer ...`
- 设置 JSON 请求格式
- 把 `model/messages` 变成 JSON body
- 把返回 JSON 封装成对象

所以 SDK 取回复用点号：

```python
reply = response.choices[0].message.content
```

## 6. OpenAI SDK：Chat 传 base64 图片

```python
import base64
from openai import OpenAI

api_url = "https://api.openai.com/v1"
api_key = "你的_API_KEY"
image_path = "test.png"

with open(image_path, "rb") as f:
    image_base64 = base64.b64encode(f.read()).decode("utf-8")

client = OpenAI(
    api_key=api_key,
    base_url=api_url,
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请描述这张图片。"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_base64}"
                    },
                },
            ],
        }
    ],
)

reply = response.choices[0].message.content
print(reply)
```

关键点：

- 图片文件本来就是 bytes。
- `open(image_path, "rb")` 是用二进制方式读取文件。
- `base64.b64encode(...)` 把 bytes 转成可放进 JSON 的字符串。
- `data:image/png;base64,...` 告诉服务端这是 PNG base64 图片。

## 7. requests.post：完整 Chat 调用

`requests` 不会帮你拼接口，也不会自动封装 OpenAI 格式。

所以要自己写：

- 完整 URL
- headers
- body
- 解析返回 JSON

```python
import requests

api_url = "https://api.openai.com/v1/chat/completions"
api_key = "你的_API_KEY"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

body = {
    "model": "gpt-4o-mini",
    "messages": [
        {"role": "user", "content": "你好，请介绍你自己。"}
    ],
}

response = requests.post(
    api_url,
    headers=headers,
    json=body,
)

data = response.json()
reply = data["choices"][0]["message"]["content"]
print(reply)
```

返回的 `data` 大概长这样：

```json
{
  "id": "chatcmpl_xxx",
  "object": "chat.completion",
  "model": "gpt-4o-mini",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！我是一个 AI 助手。"
      },
      "finish_reason": "stop"
    }
  ]
}
```

所以取回复：

```python
reply = data["choices"][0]["message"]["content"]
```

## 8. requests.post：Chat 传 base64 图片

```python
import base64
import requests

api_url = "https://api.openai.com/v1/chat/completions"
api_key = "你的_API_KEY"
image_path = "test.png"

with open(image_path, "rb") as f:
    image_base64 = base64.b64encode(f.read()).decode("utf-8")

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

body = {
    "model": "gpt-4o-mini",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请描述这张图片。"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_base64}"
                    },
                },
            ],
        }
    ],
}

response = requests.post(
    api_url,
    headers=headers,
    json=body,
)

data = response.json()
reply = data["choices"][0]["message"]["content"]
print(reply)
```

对比纯文本 Chat，只有 `body["messages"][0]["content"]` 变了：

```python
# 纯文本
"content": "你好"

# 图文
"content": [
    {"type": "text", "text": "请描述这张图片。"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
]
```

## 9. requests.post：文件上传的通用写法

如果接口要求上传文件，通常不是 `application/json`，而是：

```http
Content-Type: multipart/form-data
```

`requests` 写法通常是：

```python
import requests

api_url = "https://api.example.com/upload"
api_key = "你的_API_KEY"
file_path = "document.pdf"

headers = {
    "Authorization": f"Bearer {api_key}",
}

files = {
    "file": open(file_path, "rb")
}

data = {
    "purpose": "analysis"
}

response = requests.post(
    api_url,
    headers=headers,
    files=files,
    data=data,
)

result = response.json()
print(result)
```

注意：

- `file` 一般是单个文件，不是文件夹。
- PDF、图片、视频、压缩包都可以作为文件 bytes 上传。
- 但服务端是否接受和解析，要看接口文档。
- 文件夹要先压缩成 `.zip`，或者拆成多个文件上传。
- `files=...` 会让 `requests` 自动生成 `multipart/form-data`，一般不要自己手写 `Content-Type`。

## 10. POST 方法怎么理解

`POST` 的核心含义是：

> 我把一份数据提交给服务端，请你处理，然后返回结果。

Chat 场景：

```text
POST /chat/completions
body = model + messages
返回 = assistant 回复
```

Embedding 场景：

```text
POST /embeddings
body = model + input
返回 = embedding 向量
```

文件上传场景：

```text
POST /upload
body = multipart file bytes
返回 = 文件 ID 或处理结果
```

所以 `POST` 不等于“只传 JSON”。  
`POST` 只是方法，body 可以是 JSON，也可以是文件表单，也可以是别的格式。

## 11. 最终记忆版

OpenAI SDK：

```text
base_url = https://api.openai.com/v1
client.chat.completions.create(...)
实际访问 = POST base_url + /chat/completions
返回对象取值 = response.choices[0].message.content
```

requests：

```text
完整 url = https://api.openai.com/v1/chat/completions
headers = 鉴权 + body格式
body = model + messages
返回 dict 取值 = data["choices"][0]["message"]["content"]
```

鉴权：

```text
api_key 通常在 Header，不在 JSON body
格式：Authorization: Bearer <api_key>
SDK：OpenAI(api_key=...) 自动写入
requests：自己写 headers["Authorization"]
服务端：读 Authorization，去掉 Bearer 后校验
约定由接口文档 / 服务端决定
```

传输方式：

```text
文本：直接放 JSON
图片 URL：JSON 里放 URL，服务端自己下载
base64 图片：图片 bytes 转字符串，放 JSON
文件上传：multipart/form-data 直接传 bytes
视频 URL：JSON 里放 URL，服务端自己下载
```

最重要的一点：

> 支持什么传法不是客户端决定的，而是服务端接口决定的。  
> 工作里一定要看接口文档：字段要的是 `text`、`url`、`base64`、`file`，还是 `file_id`。
