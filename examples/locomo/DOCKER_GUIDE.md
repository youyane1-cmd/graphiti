# Dockerfile 与 Docker Compose 使用指南

本文面向 Docker 初学者，结合 `examples/locomo/Dockerfile` 和
`examples/locomo/docker-compose.yaml`，说明二者如何配合构建镜像、启动服务和连接
FalkorDB。

## 1. Docker 中的几个基本概念

- **Dockerfile**：描述“如何制作一个镜像”。
- **镜像（Image）**：包含程序、依赖和默认启动命令的只读模板。
- **容器（Container）**：镜像运行后产生的进程和运行环境。
- **Docker Compose**：描述“需要运行哪些容器，以及它们如何连接”。
- **构建上下文（Build Context）**：Docker 构建时能够读取的宿主机目录。

可以简单理解为：

```text
Dockerfile --docker build--> 镜像 --docker run--> 容器

docker-compose.yaml --docker compose up--> 构建/拉取镜像并启动多个容器
```

本项目包含两个服务：

```text
外部请求
   │
   │ 宿主机端口 18003
   ▼
memory-api 容器（容器端口 8000）
   │
   │ Docker 内部网络：falkordb:6379
   ▼
FalkorDB 容器（容器端口 6379）
```

## 2. Dockerfile 负责什么

Dockerfile 负责构建 `memory-api` 镜像，主要步骤如下：

```dockerfile
FROM docker.m.daocloud.io/library/python:3.12-slim
```

`FROM` 指定基础镜像。当前镜像提供 Python 3.12 和精简的 Debian 系统环境。普通
Dockerfile 必须以 `FROM` 为构建基础（少数特殊场景除外）。

```dockerfile
ENV PYTHONUNBUFFERED=1
```

`ENV` 设置镜像中的默认环境变量。容器运行时可以通过 Compose 的 `environment` 覆盖。

```dockerfile
RUN pip install --no-cache-dir uv
```

`RUN` 在**构建镜像时**执行命令。它不是容器每次启动时执行的命令。这里负责安装 uv。

```dockerfile
WORKDIR /app
```

`WORKDIR` 把镜像内的当前工作目录设置为 `/app`。后续相对路径默认以 `/app` 为起点。

```dockerfile
COPY . .
```

`COPY` 的格式为：

```text
COPY <构建上下文中的来源> <镜像中的目标>
```

当前第一个 `.` 是 Compose 指定的仓库根目录；第二个 `.` 是 `WORKDIR` 设置的 `/app`。
因此它表示把仓库文件复制到镜像的 `/app`。

建议通过仓库根目录的 `.dockerignore` 排除以下内容，尤其不要把密钥写入镜像：

```text
.git
.venv
__pycache__
.pytest_cache
**/.env
```

```dockerfile
RUN uv sync --frozen --extra locomo --no-dev
```

在构建阶段安装项目运行依赖：

- `--frozen`：严格使用锁文件，不自动修改依赖版本。
- `--extra locomo`：安装 Locomo 所需的额外依赖。
- `--no-dev`：不安装测试、格式化等开发依赖。

```dockerfile
EXPOSE 8000
```

`EXPOSE` 声明应用预计使用容器的 8000 端口，但**不会真正发布端口**。真正的宿主机端口
映射由 Compose 的 `ports` 完成，因此 `EXPOSE` 属于推荐说明，不是运行所必需。

```dockerfile
CMD ["uv", "run", "--no-sync", "python", "examples/locomo/main_server.py"]
```

`CMD` 是容器的默认启动命令，在容器启动时执行。该命令最终运行：

```python
uvicorn.run(app, host=host, port=port)
```

因此 `memory-api` 的启动链路是：

```text
启动容器
→ 执行 Dockerfile 的 CMD
→ 运行 main_server.py
→ 启动 Uvicorn
→ 监听容器中的 0.0.0.0:8000
```

### Dockerfile 常用必要字段

| 字段 | 作用 | 当前项目是否必要 |
| --- | --- | --- |
| `FROM` | 指定基础镜像 | 必要 |
| `WORKDIR` | 设置镜像内工作目录 | 建议保留，当前路径依赖它 |
| `COPY` | 复制项目文件 | 必要 |
| `RUN` | 构建时安装软件或依赖 | 必要 |
| `CMD` 或 `ENTRYPOINT` | 设置容器启动命令 | 必须至少有可用的启动命令 |
| `ENV` | 设置默认环境变量 | 按需使用 |
| `EXPOSE` | 声明容器端口 | 可选，不负责端口映射 |

`RUN` 和 `CMD` 最容易混淆：

```text
RUN：docker build 时执行，结果写入镜像
CMD：docker run / docker compose up 启动容器时执行
```

## 3. docker-compose.yaml 负责什么

Compose 文件负责运行 `falkordb` 和 `memory-api` 两个服务。

### 3.1 YAML 基本语法

- 使用缩进表示层级，只使用空格，不使用 Tab。
- `键: 值` 表示一个配置项。
- `- 值` 表示列表中的一项。
- `#` 后面是注释。
- 端口、布尔型外观的值建议加引号，避免 YAML 自动转换类型。

示例：

```yaml
services:
  app:
    ports:
      - "18003:8000"
```

### 3.2 定义 FalkorDB

```yaml
services:
  falkordb:
    image: docker.m.daocloud.io/falkordb/falkordb:latest
```

- `services`：所有服务的根节点。
- `falkordb`：服务名，也是 Compose 内部网络中的主机名。
- `image`：使用已有镜像；本地没有时，Compose 会自动拉取。

这里没有写启动命令，因为 FalkorDB 镜像内部已经定义了 `ENTRYPOINT` 或 `CMD`。
`docker compose up` 会使用镜像自带命令启动数据库。

生产环境建议把 `latest` 换成经过验证的固定版本，避免重新拉取后行为意外变化。

```yaml
ports:
  - "18004:6379"
```

端口格式为：

```text
"宿主机端口:容器端口"
```

宿主机通过 `localhost:18004` 访问 FalkorDB；其他 Compose 容器应通过
`falkordb:6379` 访问。数据库不需要对宿主机开放时，可以删除这项端口映射。

```yaml
environment:
  BROWSER: "1"
  ENCRYPTION_KEY: ${FALKORDB_ENCRYPTION_KEY:-graphiti-local-encryption-key}
```

`environment` 给容器设置环境变量。变量替换表达式：

```text
${变量名:-默认值}
```

表示优先使用外部变量；未设置或为空时使用默认值。生产部署应提供自己的
`FALKORDB_ENCRYPTION_KEY`，不要依赖公开默认值。

```yaml
volumes:
  - /data/graphti/falkordb:/data
```

目录挂载格式为：

```text
宿主机目录:容器目录
```

数据库写入容器 `/data` 的内容会保存在宿主机目录中，容器删除并重建后数据仍然存在。
当前 `/data/...` 是 Linux 宿主机路径。在 Windows Docker Desktop 中，更适合使用命名卷：

```yaml
services:
  falkordb:
    volumes:
      - falkordb_data:/data

volumes:
  falkordb_data:
```

当前路径中的 `graphti` 如果不是有意命名，应考虑修正为 `graphiti`。

```yaml
healthcheck:
  test: ["CMD", "redis-cli", "-p", "6379", "ping"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 10s
```

健康检查定期执行 `redis-cli -p 6379 ping`：

- `interval`：每 10 秒检查一次。
- `timeout`：单次检查最多等待 5 秒。
- `retries`：连续失败 5 次后标记为不健康。
- `start_period`：启动后的 10 秒宽限期。

### 3.3 构建 memory-api

```yaml
memory-api:
  build:
    context: ../..
    dockerfile: examples/locomo/Dockerfile
```

- `build`：表示这个服务需要根据 Dockerfile 构建镜像。
- `context: ../..`：从 Compose 文件所在的 `examples/locomo` 向上两级，到达仓库根目录。
- `dockerfile`：相对于构建上下文选择 Dockerfile。

路径关系如下：

```text
graphiti/
├── pyproject.toml
├── uv.lock
├── graphiti_core/
└── examples/
    └── locomo/
        ├── Dockerfile
        └── docker-compose.yaml
```

这里不能简单使用 `build: .`。否则构建上下文只有 `examples/locomo`，Docker 无法读取仓库
根目录的 `pyproject.toml`、`uv.lock` 和 `graphiti_core`。

当前配置大致等价于在仓库根目录执行：

```powershell
docker build -f examples/locomo/Dockerfile .
```

### 3.4 注入环境变量

```yaml
env_file:
  - .env
environment:
  FALKORDB_HOST: falkordb
  FALKORDB_PORT: "6379"
  MEMORY_API_HOST: 0.0.0.0
  MEMORY_API_PORT: "8000"
```

`env_file` 把 `.env` 中的模型、API Key 和数据库配置注入 `memory-api` 容器。
`environment` 则设置或覆盖指定变量。

当前配置的主要目的，是把 `.env` 中适合宿主机运行的：

```env
FALKORDB_HOST=localhost
```

覆盖为容器网络中的服务名：

```yaml
FALKORDB_HOST: falkordb
```

优先级为：

```text
Compose environment
> Compose env_file
> Dockerfile ENV
> Python 代码默认值
```

如果 `.env` 和 Python 默认值已经提供相同端口，那么
`FALKORDB_PORT`、`MEMORY_API_HOST`、`MEMORY_API_PORT` 可以省略；显式保留也有助于展示
容器的运行配置。

### 3.5 发布 API 端口

```yaml
ports:
  - "18003:8000"
```

表示：

```text
宿主机 18003 → memory-api 容器 8000
```

外部访问地址为：

```text
http://localhost:18003
```

如果把应用的容器监听端口改为 9000，映射右侧也必须同步修改：

```yaml
environment:
  MEMORY_API_PORT: "9000"
ports:
  - "18003:9000"
```

### 3.6 控制启动顺序

```yaml
depends_on:
  falkordb:
    condition: service_healthy
```

这表示只有 FalkorDB 通过健康检查后，Compose 才启动 `memory-api`。它依赖 FalkorDB
服务中定义的 `healthcheck`。

单纯的容器“已启动”不代表数据库“已经可以连接”，所以健康检查比只指定启动先后顺序
更可靠。

### Compose 服务常用必要字段

| 字段 | 作用 | 是否必需 |
| --- | --- | --- |
| `services` | 定义所有服务 | 必要 |
| 服务名 | 标识服务并提供内部 DNS 名称 | 必要 |
| `image` 或 `build` | 指定镜像来源 | 通常至少需要一个 |
| `ports` | 发布端口到宿主机 | 仅外部需要访问时必要 |
| `environment` / `env_file` | 注入配置 | 按应用需求使用 |
| `volumes` | 持久化数据或挂载文件 | 数据需要保留时必要 |
| `depends_on` | 控制服务启动依赖 | 多服务存在依赖时建议使用 |
| `healthcheck` | 判断服务是否真正可用 | 建议用于数据库和 API |
| `command` | 覆盖镜像默认启动命令 | 可选 |

## 4. Dockerfile 与 Compose 如何配合

执行 Compose 启动命令后，完整过程如下：

```text
1. Compose 读取 docker-compose.yaml
2. 发现 falkordb 使用 image
3. 本地没有该镜像时拉取镜像
4. 发现 memory-api 使用 build
5. 以仓库根目录为构建上下文读取 Dockerfile
6. Dockerfile 安装 Python、uv 和项目依赖，生成 API 镜像
7. Compose 创建内部网络
8. Compose 创建并启动 FalkorDB 容器
9. FalkorDB 健康检查通过
10. Compose 创建并启动 memory-api 容器
11. memory-api 执行 Dockerfile 的 CMD
12. main_server.py 启动 Uvicorn
13. 宿主机通过 18003 端口访问 API
```

Compose 中没有为 `memory-api` 配置 `command`，因此它继承 Dockerfile 的 `CMD`。如果
Compose 增加 `command`，就会覆盖 Dockerfile 的默认 `CMD`。

## 5. 启动和管理服务

建议在仓库根目录执行以下命令。

首次启动或代码修改后重新构建：

```powershell
docker compose -f examples/locomo/docker-compose.yaml up --build
```

后台启动：

```powershell
docker compose -f examples/locomo/docker-compose.yaml up -d --build
```

查看服务状态：

```powershell
docker compose -f examples/locomo/docker-compose.yaml ps
```

查看所有日志：

```powershell
docker compose -f examples/locomo/docker-compose.yaml logs -f
```

只查看 API 日志：

```powershell
docker compose -f examples/locomo/docker-compose.yaml logs -f memory-api
```

只查看数据库日志：

```powershell
docker compose -f examples/locomo/docker-compose.yaml logs -f falkordb
```

停止并删除容器和网络：

```powershell
docker compose -f examples/locomo/docker-compose.yaml down
```

重新构建单个服务：

```powershell
docker compose -f examples/locomo/docker-compose.yaml build memory-api
```

重启单个服务：

```powershell
docker compose -f examples/locomo/docker-compose.yaml restart memory-api
```

## 6. 常见问题

### 修改代码后为什么没有生效

当前 Dockerfile 通过 `COPY . .` 把代码写入镜像，没有把源码目录实时挂载到容器。修改
源码后需要重新构建：

```powershell
docker compose -f examples/locomo/docker-compose.yaml up -d --build
```

### 为什么容器内不能使用 localhost 连接 FalkorDB

每个容器都有独立网络空间。`memory-api` 容器中的 `localhost` 代表 API 容器自己。
访问数据库应使用 Compose 服务名：

```text
falkordb:6379
```

### EXPOSE 8000 后为什么还要 ports

`EXPOSE 8000` 只声明容器使用 8000；`ports: "18003:8000"` 才会让宿主机能够访问它。

### 为什么 FalkorDB 没有 command 也能启动

FalkorDB 镜像内部已经定义了默认 `ENTRYPOINT` 或 `CMD`。Compose 创建容器时自动使用
该命令。

### env_file 和 environment 为什么同时存在

`env_file` 提供通用变量，`environment` 覆盖容器环境特有的变量。例如宿主机直接运行时
数据库地址是 `localhost`，容器运行时必须覆盖为服务名 `falkordb`。

### 删除容器会不会删除数据库

只要宿主机挂载目录或命名卷仍然存在，执行 `docker compose down` 不会删除其中的数据。
如果使用命名卷并执行 `docker compose down -v`，则会连同命名卷一起删除，应谨慎使用。

## 7. 部署前检查

启动前至少确认：

1. `examples/locomo/.env` 已配置真实的模型和 API Key。
2. `.env` 没有提交到 Git，也没有被 `COPY . .` 写入镜像。
3. 生产环境已设置安全的 `FALKORDB_ENCRYPTION_KEY`。
4. 宿主机的 18003 端口没有被其他程序占用。
5. 数据目录存在且 Docker 有读写权限，或改用命名卷。
6. 如果不需要从宿主机连接数据库，删除 `18004:6379` 映射以减少暴露面。
7. 生产环境尽量固定 FalkorDB 镜像版本，不长期使用 `latest`。
