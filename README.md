# Fcatbot3

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Fcatbot3 是一个基于 Python 的异步 Bot 框架，采用模块化插件架构，通过 WebSocket 与后端服务通信。内置事件总线、服务注册表和丰富的日志系统，旨在为 Bot 开发者提供高性能、可扩展、易维护的开发体验。

## 功能特性

- **异步核心** — 基于 `asyncio` 构建，支持高并发事件处理；同时提供同步包装器，兼容同步代码场景。
- **Plugkit 插件系统** — 声明式插件开发，支持事件监听、服务注册、依赖管理、配置持久化和开发期热重载。
- **事件总线** — 多 Worker 消费队列，支持优先级调度、全局拦截器、Handler 拦截器和一次性事件订阅。
- **WebSocket 连接层** — 异步/同步双形态客户端，监听器模式广播消息，自动重连（指数退避 + 抖动），完善的连接指标。
- **API 客户端** — 基于元类的声明式 API 定义，自动派发 `ApiRequest`，支持泛型返回类型。
- **丰富的日志系统** — 彩色终端输出、按级别差异化格式、JSON 格式支持、日志文件按日轮转。

## 安装

```bash
# 克隆仓库
git clone <repository-url>
cd Fcatbot3

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装项目及生产依赖
pip install -e .

# 安装开发依赖（测试）
pip install -e ".[dev]"
```

**依赖要求**：Python >= 3.10

**核心依赖**：`aiohttp`, `pyyaml`, `watchdog`, `pillow`, `packaging`

## 快速开始

### 1. 启动 Bot

```bash
# 基础启动
python -m fcatbot start -u "ws://localhost:8080/ws"

# 带鉴权 Token、指定插件目录、调试模式
python -m fcatbot start -u "ws://localhost:8080/ws" \
    -t "your-token" \
    -p ./plugins \
    --debug

# 开发模式（启用插件热重载和文件监视）
python -m fcatbot start -u "ws://localhost:8080/ws" \
    -p ./plugins \
    --dev --debug
```

### 2. 编写最小插件

在插件目录（如 `./plugins`）中创建 `echo_plugin.py`：

```python
from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.runtime.decorators import on_event
from fcatbot.plugkit.protocol.event import Event

class EchoPlugin(Plugin):
    name = "echo"
    version = "1.0.0"

    def on_load(self):
        print("EchoPlugin 已加载")

    @on_event("sdk.raw", priority=50)
    async def handle_raw(self, event: Event):
        print(f"收到原始消息: {event.data}")
```

启动 Bot 时指定 `-p ./plugins`，框架会自动发现并加载该插件。

## 项目结构

```text
Fcatbot3/
├── main.py                          # CLI 入口
├── pyproject.toml                   # 项目配置
├── src/
│   └── fcatbot/
│       ├── __main__.py              # Bot 主入口与生命周期
│       ├── api/
│       │   └── client.py            # 声明式 API 客户端（元类自动生成 invoke）
│       ├── connection/
│       │   └── websocket.py         # WebSocket 客户端（异步 + 同步双形态）
│       ├── plugkit/                 # 插件系统
│       │   ├── protocol/            # 协议层（接口与模型定义）
│       │   │   ├── bus.py           # EventBus Protocol
│       │   │   ├── data.py          # PluginData / PluginConfig / ConfigSection
│       │   │   ├── event.py         # Event 数据类
│       │   │   ├── exceptions.py    # 插件异常体系
│       │   │   ├── manager.py       # PluginManager Protocol
│       │   │   ├── plugin.py        # Plugin 抽象基类
│       │   │   ├── service.py       # ServiceRegistry Protocol
│       │   │   ├── state.py         # PluginState / PluginStatus
│       │   │   └── storage.py       # StorageBackend（YAML / JSON / Pickle）
│       │   └── runtime/             # 运行时层（具体实现）
│       │       ├── bus.py           # Bus 实现（多 Worker + 拦截器）
│       │       ├── decorators.py    # @on_event 装饰器
│       │       ├── lifecycle.py     # LifecycleManager（加载/启动/停止/重载）
│       │       ├── loader.py        # PluginLoader（支持 .py / package / .zip）
│       │       ├── registry.py      # PluginServiceRegistry 实现
│       │       ├── resolver.py      # 插件依赖拓扑排序
│       │       └── watcher.py       # PluginWatcher（开发期热重载）
│       └── utils/                   # 工具模块
│           ├── color.py             # 跨平台 ANSI 颜色（含 Windows VT 模式）
│           ├── logformat.py         # 消息日志风格模板
│           └── logger.py            # 日志初始化与格式化
└── plugins/                         # 插件目录
    ├── adapter/napcat/              # NapCat 协议适配器
    ├── History/                     # 消息历史记录插件
    ├── Luckperms/                   # 权限管理插件
    └── ...
```

## 核心架构

### Bot 入口与生命周期

`Bot` 类（`src/fcatbot/__main__.py`）是整个框架的统一入口：

- **纯同步初始化，异步运行**：`__init__` 中完成 WebSocket 配置保存和 HTTP API 基地址推导，但不建立连接；`run()` 启动事件循环并调用 `run_async()`。
- **优雅退出**：`stop()` 设置停止事件，触发插件系统关闭、WebSocket 断开、资源清理。
- **原始事件透传**：`_cat()` 循环以最小开销从 WS 读取消息，包装为 `Event(name="sdk.raw", ...)` 后发布到总线，不解析、不过滤。

### Plugkit 插件系统

插件系统分为**协议层**（`protocol/`）和**运行时层**（`runtime/`）：

- **Plugin 基类**（`protocol/plugin.py`）：定义插件生命周期钩子（`on_load`、`on_start`、`on_stop`、`on_unload`、`run`）和热重载钩子（`on_before_reload`、`on_after_reload`、`on_config_change`）。
- **声明式事件监听**（`runtime/decorators.py`）：`@on_event(event_spec, priority=50, once=False, filter=...)` 装饰的方法会在插件启动时自动绑定到事件总线。
- **Mixin 机制**（`runtime/lifecycle.py`）：支持通过 `on_mixin_load` / `on_mixin_unload` 在插件加载和卸载时注入横切逻辑，实现关注点复用。
- **服务注册**（`runtime/registry.py` + `protocol/service.py`）：插件通过类属性 `provides` 声明服务，加载时由 `LifecycleManager` 自动注册到 `PluginServiceRegistry`；其他插件通过 `self.registry.require(name)` 消费服务，支持版本约束检查。
- **数据持久化**（`protocol/data.py`）：`PluginConfig`（YAML 后端，用户可编辑）和 `PluginData`（通用存储）自动绑定到 `{data_dir}/{plugin_name}/` 下的路径，支持 `save()` / `reload()`。`ConfigSection` 使用**描述符协议**（`Value`）实现声明式配置，支持点号访问、懒加载和类型强制转换。
- **依赖管理**（`runtime/resolver.py`）：`Plugin.dependencies` 支持版本约束（PEP 440），`LifecycleManager.load_all()` 基于 DAG 拓扑排序自动批量加载，失败时完整回滚。
- **热重载**（`runtime/watcher.py` + `runtime/loader.py`）：开发模式下 `watchdog` 监视插件代码和配置文件变更；代码变更触发 `reload()`（保存状态 → 卸载 → 重新加载类 → 恢复状态 → 重新启动）；配置变更触发 `on_config_change()`。

### 事件总线 (Bus)

`Bus`（`runtime/bus.py`）是框架的核心消息枢纽：

- **多 Worker 消费**：`workers` 参数控制并发处理协程数，默认 4；通过 `asyncio.Queue` 缓冲事件，支持背压保护（`BackpressureError`）。
- **优先级调度**：`priority` 数字越大越先执行（默认 50）；支持同一事件的多 Handler 按优先级顺序执行。
- **拦截器体系**：`GlobalInterceptor`（事件级，可全局阻断）和 `HandlerInterceptor`（Handler 级，可单个阻断）。
- **一次性订阅**：`once=True` 的 Handler 在执行后自动取消订阅。
- **事件取消**：`Event.cancel()` 可中断后续 Handler 执行。

### WebSocket 连接层

WebSocket 模块（`connection/websocket.py`）提供连接管理能力：

- **双形态客户端**：
  - `AsyncWebSocketClient` — 原生协程，性能高，支持异步上下文管理器。
  - `SyncWebSocketClient` — 后台线程运行事件循环，所有方法线程安全。
- **监听器模式**：任意协程可 `create_listener()` 获取独立的 `listener_id`，消息广播到所有监听器；每个监听器自带环形缓冲区，满时自动丢弃最旧数据。
- **自动重连**：指数退避 + 随机抖动，支持最大次数限制（`0` 表示无限）；网络闪断、服务端踢人、压缩协商失败均自动重试。
- **指标可观测**：`get_metrics()` 导出连接次数、收发字节、重连状态、监听器数量，方便接入外部监控系统。
- **压缩自动降级**：zlib 压缩协商失败时自动禁用压缩并重连，无需人工干预。

### API 客户端

API 客户端（`api/client.py`）基于元类实现声明式 API 定义：

- `APIClient[T]` 使用 `ApiMeta` 元类，自动扫描子类中的方法并包装为异步调用。
- 方法返回 `ApiRequest` / `str` / `tuple` 时，自动派发为 `invoke(ApiRequest(...))`。
- 支持 `__getattr__` 动态方法调用。

### 日志与终端输出

日志系统（`utils/logger.py`）提供生产级日志能力：

- **彩色终端**：按日志级别差异化配色。
- **文件轮转**：`TimedRotatingFileHandler` 按午夜自动轮转，保留 `backup_count` 份历史（默认 7 天）。
- **JSON 模式**：通过环境变量 `LOG_JSON_FORMAT=true` 启用结构化 JSON 日志输出。
- **日志分流**：`LOG_REDIRECT_RULES` 支持将特定 logger 的输出重定向到独立文件。
- **上下文追踪**：支持 `request_id` 和 `trace_id` 的 ContextVar 传递。

## CLI 使用

```bash
python -m fcatbot start -h
```

| 参数               | 说明                                     |
| ------------------ | ---------------------------------------- |
| `-u, --url`        | **必填** WebSocket 服务器地址            |
| `-t, --token`      | 鉴权 Token（写入`Authorization` 请求头） |
| `-p, --plugin-dir` | 额外插件目录（除内置`sys_plugin` 外）    |
| `--data-dir`       | 数据目录，默认`./data`                   |
| `--debug`          | 调试模式（详细日志 + 异常透传）          |
| `--dev`            | 开发模式（插件热重载 + 文件监视）        |

## 插件开发快速指南

### 1. 最小插件结构

```python
from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.runtime.decorators import on_event
from fcatbot.plugkit.protocol.event import Event
from fcatbot.plugkit.protocol.data import PluginConfig, value

class MyPlugin(Plugin):
    name = "my_plugin"
    version = "1.0.0"
    dependencies = {}          # 依赖的其他插件名: 版本约束
    provides = {}              # 暴露的服务名: 契约类

    # 声明式配置（自动绑定到 data/my_plugin/config/settings.yml）
    settings = PluginConfig("settings")
    api_key = value(default="")
    max_retries = value(default=3)

    def on_load(self):
        # 插件加载时调用（bus / data_root 已注入）
        print(f"API Key: {self.settings.api_key}")

    def on_start(self):
        # 插件启动时调用（进入事件循环）
        pass

    @on_event("sdk.raw", priority=50)
    async def on_message(self, event: Event):
        # 处理事件
        pass

    def on_stop(self):
        # 插件停止时调用
        pass

    def on_unload(self):
        # 插件卸载时调用（bus 即将解绑）
        pass
```

### 2. 服务注册与消费

```python
class DataService:
    def fetch(self, key: str) -> dict:
        return {"key": key}

class ProviderPlugin(Plugin):
    name = "data_provider"
    version = "1.0.0"
    provides = {"data.service": DataService}

    def on_load(self):
        self.data_svc = DataService()

class ConsumerPlugin(Plugin):
    name = "data_consumer"
    version = "1.0.0"
    dependencies = {"data_provider": "~1.0"}

    @on_event("some.event")
    async def handle(self, event: Event):
        svc = self.registry.require("data.service", version="~1.0")
        result = svc.fetch("test")
```

### 3. 插件加载格式支持

`PluginLoader` 支持三种插件格式，以及**显式导出机制**：

- **单文件**：`{plugin_dir}/{name}.py`
- **包目录**：`{plugin_dir}/{name}/__init__.py`
- **ZIP 包**：`{plugin_dir}/{name}.zip`（内部含 `__init__.py`）(不推荐)
- **显式导出**（推荐）：包目录的 `__init__.py` 中声明 `__plugins__ = [PluginA, PluginB]`，可精确控制加载的插件类，避免误加载辅助模块。

```python
# plugins/my_suite/__init__.py
from .provider import ProviderPlugin
from .consumer import ConsumerPlugin

__plugins__ = [ProviderPlugin, ConsumerPlugin]
```

### 4. 开发模式热重载

启动时添加 `--dev` 标志：

```bash
python -m fcatbot start -u "ws://localhost:8080/ws" -p ./plugins --dev
```

- 修改插件 `.py` 文件后自动热重载（保留 `on_before_reload` / `on_after_reload` 状态）。
- 修改插件配置 `.yml` 文件后触发 `on_config_change()`。

## 测试

```bash
# 运行全部测试
pytest

# 运行指定模块
pytest tests/connection/

# 查看覆盖率
pytest --cov=src/fcatbot --cov-report=term-missing
```

测试配置已写入 `pyproject.toml`：

- `asyncio_mode = auto`
- 测试路径：`tests/`
- 测试文件模式：`test_*.py`

## 依赖

| 依赖        | 用途                       |
| ----------- | -------------------------- |
| `aiohttp`   | WebSocket 客户端底层连接   |
| `pyyaml`    | 插件配置 YAML 持久化       |
| `watchdog`  | 开发期文件监视与热重载     |
| `pillow`    | 图像处理（Bot 功能相关）   |
| `packaging` | PEP 440 版本解析与约束检查 |

开发依赖：`pytest`, `pytest-cov`, `pytest-asyncio`

## 许可证

MIT License
