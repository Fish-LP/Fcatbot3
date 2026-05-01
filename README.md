# Fcatbot3

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Fcatbot3 是一个基于 Python 的异步 Bot 框架，采用模块化插件架构，通过 WebSocket 与后端服务通信。它内置了事件总线、服务注册表、RBAC 权限控制和丰富的日志系统，旨在为 Bot 开发者提供高性能、可扩展、易维护的开发体验。

## 功能特性

- **异步核心** — 基于 `asyncio` 构建，支持高并发事件处理；同时提供同步包装器，兼容同步代码场景。
- **Plugkit 插件系统** — 声明式插件开发，支持事件监听、服务注册、依赖管理、配置持久化和开发期热重载。
- **事件总线** — 多 Worker 消费队列，支持优先级调度、全局拦截器、Handler 拦截器和一次性事件订阅。
- **WebSocket 连接层** — 异步/同步双形态客户端，监听器模式广播消息，自动重连（指数退避 + 抖动），完善的连接指标。
- **RBAC 权限控制** — 角色继承、权限通配符匹配、上下文绑定、临时授权过期、轨道升降级机制。
- **API 客户端** — 基于元类的声明式 API 定义，自动派发 `ApiRequest`，支持泛型返回类型。
- **丰富的日志系统** — 彩色终端输出、按级别差异化格式、JSON 格式支持、日志文件按日轮转、tqdm 进度条集成。

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
python main.py start -u "ws://localhost:8080/ws"

# 带鉴权 Token、指定插件目录、调试模式
python main.py start -u "ws://localhost:8080/ws" \
    -t "your-token" \
    -p ./plugins \
    --debug

# 开发模式（启用插件热重载和文件监视）
python main.py start -u "ws://localhost:8080/ws" \
    -p ./plugins \
    --dev --debug
```

### 2. 作为模块启动

```bash
python -m fcatbot start -u "ws://localhost:8080/ws" -p ./plugins
```

### 3. 编写最小插件

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

```
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
│       ├── rbac/                    # 基于角色的访问控制
│       │   ├── engine.py            # 上下文、权限匹配、权限持有者
│       │   └── manager.py           # RBACManager、Role、Track
│       └── utils/                   # 工具模块
│           ├── color.py             # 跨平台 ANSI 颜色（含 Windows VT 模式）
│           ├── logformat.py         # 消息日志风格模板
│           └── logger.py            # 日志初始化与格式化
└── tests/                           # 测试套件
    ├── connection/
    │   └── test_ws_client.py
    └── rbac/
        └── test_rbac.py
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
- **Mixin 机制**（`runtime/lifecycle.py`）：支持通过 `on_mixin_load` / `on_mixin_unload` 在插件加载和卸载时注入横切逻辑，实现关注点复用。Mixin 类必须显式声明在 `Plugin.mixins` 中或出现在 MRO 中并定义了相关钩子。
- **服务注册**（`runtime/registry.py` + `protocol/service.py`）：插件通过类属性 `provides` 声明服务，加载时由 `LifecycleManager` 自动注册到 `PluginServiceRegistry`；其他插件通过 `self.registry.require(name)` 消费服务，支持版本约束检查。注册表提供 `add_listener()` 机制，允许插件等待依赖服务就绪后再初始化，解决启动时序问题。
- **数据持久化**（`protocol/data.py`）：`PluginConfig`（YAML 后端，用户可编辑）和 `PluginData`（通用存储）自动绑定到 `{data_dir}/{plugin_name}/` 下的路径，支持 `save()` / `reload()`。`ConfigSection` 使用**描述符协议**（`Value`）实现声明式配置，支持点号访问、懒加载和类型强制转换。
- **依赖管理**（`runtime/resolver.py`）：`Plugin.dependencies` 支持版本约束（PEP 440），`LifecycleManager.load_all()` 基于 DAG 拓扑排序自动批量加载，失败时完整回滚。
- **热重载**（`runtime/watcher.py` + `runtime/loader.py`）：开发模式下 `watchdog` 监视插件代码和配置文件变更；代码变更触发 `reload()`（保存状态 → 卸载 → 重新加载类 → 恢复状态 → 重新启动）；配置变更触发 `on_config_change()`。

### 事件总线 (Bus)

`Bus`（`runtime/bus.py`）是框架的核心消息枢纽：

- **多 Worker 消费**：`workers` 参数控制并发处理线程数，默认 4；通过 `asyncio.Queue` 缓冲事件，支持背压保护（`BackpressureError`）。
- **优先级调度**：`priority` 数字越大越先执行（默认 50）；支持同一事件的多 Handler 按优先级顺序执行。
- **拦截器体系**：`GlobalInterceptor`（事件级，可全局阻断）和 `HandlerInterceptor`（Handler 级，可单个阻断）。
- **一次性订阅**：`once=True` 的 Handler 在执行后自动取消订阅。
- **事件取消**：`Event.cancel()` 可中断后续 Handler 执行。

### WebSocket 连接层

WebSocket 模块（`connection/websocket.py`）提供企业级的连接管理能力：

- **双形态客户端**：
  - `AsyncWebSocketClient` — 原生协程，性能高，支持异步上下文管理器。
  - `SyncWebSocketClient` — 后台线程运行事件循环，所有方法线程安全。
- **监听器模式**：任意协程可 `create_listener()` 获取独立的 `listener_id`，消息广播到所有监听器；每个监听器自带环形缓冲区，满时自动丢弃最旧数据。
- **自动重连**：指数退避 + 随机抖动，支持最大次数限制（`0` 表示无限）；网络闪断、服务端踢人、压缩协商失败均自动重试。
- **指标可观测**：`get_metrics()` 导出连接次数、收发字节、重连状态、监听器数量，方便接入外部监控系统。
- **压缩自动降级**：zlib 压缩协商失败时自动禁用压缩并重连，无需人工干预。

### RBAC 权限控制

RBAC 模块（`rbac/`）提供细粒度的访问控制能力：

- **角色（Role）**：支持权限集合和父角色继承；权限匹配支持精确匹配和 `.*` 通配符后缀（如 `plugin.*` 匹配 `plugin.a`，但不匹配 `plugin` 本身）。
- **权限持有者（PermissionHolder）**：支持白名单/黑名单、角色绑定、上下文绑定和过期时间；检查顺序为：上下文黑名单 → 上下文白名单 → 全局黑名单 → 全局白名单 → 上下文角色 → 全局角色。
- **上下文（Context）**：可针对特定群聊、私聊等场景绑定临时权限或角色；空上下文表示全局生效。
- **轨道（Track）**：实现角色升降级体系（如用户等级），通过 `promote()` / `demote()` 按轨道路径切换角色。

### API 客户端

API 客户端（`api/client.py`）基于元类实现声明式 API 定义：

- `APIClient[T]` 使用 `ApiMeta` 元类，自动扫描子类中的方法并包装为异步调用。
- 方法返回 `ApiRequest` / `str` / `tuple` 时，自动派发为 `invoke(ApiRequest(...))`。
- 支持 `__getattr__` 动态方法调用，将未知属性名转为 `ApiRequest(name, **kwargs)` 调用。
- 泛型返回类型 `T` 通过 `__orig_bases__` 提取，确保类型安全。

### 日志与终端输出

日志系统（`utils/logger.py`）提供生产级日志能力：

- **彩色终端**：按日志级别差异化配色（DEBUG=青色、INFO=绿色、WARNING=黄色、ERROR=红色、CRITICAL=洋红+粗体）。
- **文件轮转**：`TimedRotatingFileHandler` 按午夜自动轮转，保留 `backup_count` 份历史（默认 7 天）。
- **JSON 模式**：通过环境变量 `LOG_JSON_FORMAT=true` 启用结构化 JSON 日志输出。
- **日志分流**：`LOG_REDIRECT_RULES` 支持将特定 logger 的输出重定向到独立文件。
- **上下文追踪**：支持 `request_id` 和 `trace_id` 的 ContextVar 传递。
- **tqdm 集成**：若安装了 `tqdm`，自动提供彩色进度条封装。

## 架构成熟度与改进空间

Fcatbot3 的架构设计遵循**协议-实现分离**原则，核心逻辑高度可测试、可替换。以下是外部架构评审识别的亮点与已知注意事项：

### 设计亮点

| 维度 | 说明 |
|------|------|
| **协议层零依赖** | `plugkit/protocol/` 仅定义契约（`EventBus`、`PluginManager`、`ServiceRegistry` 等），对运行时零依赖，便于 Mock 测试和自定义实现。 |
| **六阶段生命周期** | 插件完整经历 `on_load` → `on_start` → `run` → `on_stop` → `on_unload`，外加热重载的 `on_before_reload` / `on_after_reload`，状态机严谨。 |
| **DAG 依赖解析** | `resolver.py` 基于拓扑排序批量加载，失败时完整回滚已加载的插件，避免半初始化状态。 |
| **服务注册表** | 支持版本约束（PEP 440）、监听机制（`add_listener`）和严格的 `require()` / 宽松的 `resolve()` 双模式，具备微服务化思维。 |
| **背压控制** | `Bus` 通过 `max_queue` + `QueueFull` 防止内存无限增长，`Semaphore` 限制并发数。 |

### 已知注意事项

| 方面 | 现状 | 建议 |
|------|------|------|
| **RBAC 异步锁** | `_PermissionHolder` 使用 `threading.RLock`，但框架运行在 `asyncio` 事件循环中 | 高频并发场景下建议提供 `asyncio.Lock` 的异步版本，或明确文档说明其线程安全边界（当前以协程单线程执行为主，`RLock` 主要保护跨线程回调） |
| **事件总线类型精度** | `Bus.publish()` 参数类型为 `Any`，丢失了事件类型信息 | 可引入 `TypeVar` 或 `@overload` 增强静态检查，但不影响运行时行为 |
| **插件主协程恢复** | `run()` 未捕获异常会导致插件进入 `Failed` 状态并触发 `_on_fatal`，框架目前不提供自动恢复策略 | 当前由 LifecycleManager 统一处理故障传播；如需自动恢复，可在插件层自行实现 Exponential Backoff 重试 |
| **WebSocket 生产验证** | 从测试用例看接口设计合理，但生产环境下需关注重连风暴和心跳机制 | 已内置指数退避 + 抖动、压缩自动降级，建议根据实际网络环境调整 `reconnect_attempts` 和 `backoff_max` |
| **测试解耦** | 部分测试可能依赖外部插件适配器 | 建议测试优先使用本地 Mock 对象，避免外部插件耦合 |

## CLI 使用

```bash
python main.py start -h
```

| 参数 | 说明 |
|---|---|
| `-u, --url` | **必填** WebSocket 服务器地址 |
| `-t, --token` | 鉴权 Token（写入 `Authorization` 请求头） |
| `-p, --plugin-dir` | 额外插件目录（除内置 `sys_plugin` 外） |
| `--data-dir` | 数据目录，默认 `./data` |
| `--debug` | 调试模式（详细日志 + 异常透传） |
| `--dev` | 开发模式（插件热重载 + 文件监视） |

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
- **ZIP 包**：`{plugin_dir}/{name}.zip`（内部含 `__init__.py`）
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
python main.py start -u "ws://localhost:8080/ws" -p ./plugins --dev
```

- 修改插件 `.py` 文件后自动热重载（保留 `on_before_reload` / `on_after_reload` 状态）。
- 修改插件配置 `.yml` 文件后触发 `on_config_change()`。

### 5. 实战示例：协议适配器

以下是一个真实场景下的 **NapCat 协议适配器** 简化示例，展示了如何从原始 WebSocket 事件解析协议、自检测、并重新发布结构化事件：

```python
import json
from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.protocol.event import Event
from fcatbot.plugkit.runtime.decorators import on_event

class NapcatAdapter(Plugin):
    """NapCat 协议适配器 —— 零配置，依赖第一个 sdk.raw 事件自检测。"""

    name = "NapcatAdapter"
    version = "1.0.0"
    provides = {"napcat.api": None, "napcat.rbac": None}

    def __init__(self):
        super().__init__()
        self._detected = False
        self.enabled = False

    @on_event("sdk.raw", priority=90)  # 高优先级，尽早消费
    async def on_raw(self, event: Event):
        raw = event.data
        if not isinstance(raw, str):
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        # 第一层：协议检测（仅未激活时执行）
        if not self._detected:
            if not self._is_onebot11(data):
                return  # 不是 OneBot11，静默丢弃，让其他适配器尝试
            self._detected = True
            self.enabled = True
            await self.bus.publish(Event(
                name="napcat.adapter.ready",
                data={"version": self.version, "bot_id": data.get("self_id")},
                source=self.name,
            ))

        # 第二层：echo 过滤（API 响应）
        if "echo" in data and "post_type" not in data:
            return

        # 第三层：事件解析与重发布
        if "post_type" not in data:
            return

        post_type = data.get("post_type")
        if post_type == "message":
            event_name = f"napcat.message.{data.get('message_type', 'unknown')}"
        elif post_type == "notice":
            event_name = f"napcat.notice.{data.get('notice_type', 'unknown')}"
        elif post_type == "meta_event":
            event_name = f"napcat.meta.{data.get('meta_event_type', 'unknown')}"
        else:
            return

        await self.bus.publish(Event(
            name=event_name,
            data=data,
            source="napcat",
            metadata=data,
        ))

    @staticmethod
    def _is_onebot11(data: dict) -> bool:
        return (
            "post_type" in data
            and "time" in data
            and "self_id" in data
            and isinstance(data.get("time"), int)
        )
```

适配器设计要点：
- **高优先级消费** `sdk.raw`（`priority=90`），在其他业务插件之前完成协议识别。
- **自检测机制**：首个合法 OneBot11 事件触发激活，避免硬编码协议类型。
- **命名空间隔离**：所有重发布事件使用 `napcat.*` 前缀，防止与其他适配器冲突。
- **echo 过滤**：过滤 API 响应消息，仅上报真实业务事件。

### 6. 实战示例：API 客户端

框架的 `APIClient` 采用**元类自动派发**：子类的方法返回 `tuple` 或 `ApiRequest` 时，`ApiMeta` 会自动将其转换为异步调用。以下是 NapCat 群组 API 的简化示例：

```python
from fcatbot.api.client import APIClient
from typing import Any, List, Union

class NCAPIGroup(APIClient):
    """napcat API 群组类 —— 方法返回 tuple，由元类自动包装为 ApiRequest"""

    async def invoke(self, request): ...  # 实际通信由基类/注入层实现

    async def send_group_message(
        self,
        group_id: Union[str, int],
        message: List[dict],
    ) -> Any:
        """发送群组消息"""
        return (
            "send_group_msg",
            {"group_id": group_id, "message": message},
        )

    async def get_group_list(self) -> Any:
        """获取群组列表"""
        return ("get_group_list", {})

    async def set_group_ban(
        self,
        group_id: Union[int, str],
        user_id: Union[int, str],
        duration: int,
    ) -> Any:
        """群组禁言"""
        return (
            "set_group_ban",
            {"group_id": group_id, "user_id": user_id, "duration": duration},
        )
```

使用方式：
- 方法返回 `(str, dict)` 元组时，`ApiMeta` 自动包装为 `ApiRequest(name=action, **params)` 并调用 `invoke()`。
- 支持 `__getattr__` 动态调用：`client.some_method(**kwargs)` 会自动转为 `ApiRequest("some_method", **kwargs)`。
- 泛型返回类型 `APIClient[T]` 中的 `T` 通过 `__orig_bases__` 提取，可供类型检查器使用。

### 7. 实战示例：服务提供者与消费者

以下演示 `demo_suite` 模式，展示如何通过 `provides` / `dependencies` / `registry` 实现插件间松耦合协作。

**服务层**（纯 Python 类，零框架依赖）：

```python
import time
from dataclasses import dataclass

@dataclass
class EchoResult:
    Original: str
    Timestamp: float
    Length: int

class EchoService:
    def __init__(self):
        self.__version__ = "2.1.0"
        self._history = []

    def Echo(self, message: str) -> str:
        result = EchoResult(
            Original=message,
            Timestamp=time.time(),
            Length=len(message),
        )
        self._history.append(result)
        return f"Echo: {message}"

class TimeService:
    def __init__(self):
        self.__version__ = "1.0.0"

    def Format(self, timestamp=None) -> str:
        ts = timestamp or time.time()
        return time.strftime("%H:%M:%S", time.localtime(ts))
```

**提供者插件**：

```python
from fcatbot.plugkit.protocol.plugin import Plugin

class DemoProvider(Plugin):
    name = "DemoProvider"
    version = "2.1.0"
    provides = {
        "demo.echo": EchoService,
        "demo.time": TimeService,
    }

    def __init__(self):
        super().__init__()
        self.echo = EchoService()
        self.time = TimeService()

    async def on_start(self):
        # 广播就绪事件，供消费者监听
        await self.bus.publish({
            "event": "demo.provider.ready",
            "provider": self.name,
            "services": list(self.provides.keys()),
        })
```

**消费者插件**：

```python
from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.protocol.event import Event
from fcatbot.plugkit.runtime.decorators import on_event

class DemoConsumer(Plugin):
    name = "DemoConsumer"
    version = "1.0.0"
    dependencies = {"DemoProvider": ">=2.0.0"}

    def __init__(self):
        super().__init__()
        self.echo = None
        self.time = None

    def on_load(self):
        # 1. 批量检查服务存在性
        missing = self.registry.check("demo.echo", "demo.time")
        if missing:
            raise RuntimeError(f"依赖服务缺失: {missing}")

        # 2. 严格获取：不存在/版本不符时抛异常
        self.echo = self.registry.require("demo.echo", version=">=2.0.0")

        # 3. 宽松获取：可选依赖，不存在返回 None
        self.time = self.registry.resolve("demo.time")

    @on_event("demo.provider.ready")
    async def on_ready(self, event: Event):
        print(f"提供者就绪: {event.data}")

    @on_event("sdk.raw")
    async def on_raw(self, event: Event):
        if self.echo is None:
            return
        result = self.echo.Echo(str(event.data))
        if self.time is not None:
            result = f"{self.time.Format()} {result}"
        print(f"处理结果: {result}")
```

协作模式要点：
- **拓扑排序加载**：`LifecycleManager` 根据 `dependencies` 自动确保 `DemoProvider` 先于 `DemoConsumer` 加载。
- **严格 vs 宽松**：`require()` 用于强依赖（缺失即抛异常），`resolve()` 用于可选依赖（缺失返回 `None`）。
- **就绪通知**：提供者通过事件总线广播就绪状态，消费者可通过 `@on_event` 订阅，实现启动时序解耦。
- **注册表监听**：`registry.add_listener()` 允许插件动态等待依赖服务上线，无需在 `on_load` 时全部就绪。

## 测试

```bash
# 运行全部测试
pytest

# 运行指定模块
pytest tests/connection/
pytest tests/rbac/

# 查看覆盖率
pytest --cov=src/fcatbot --cov-report=term-missing
```

测试配置已写入 `pyproject.toml`：
- `asyncio_mode = auto`
- 测试路径：`tests/`
- 测试文件模式：`test_*.py`

## 依赖

| 依赖 | 用途 |
|---|---|
| `aiohttp` | WebSocket 客户端底层连接 |
| `pyyaml` | 插件配置 YAML 持久化 |
| `watchdog` | 开发期文件监视与热重载 |
| `pillow` | 图像处理（Bot 功能相关） |
| `packaging` | PEP 440 版本解析与约束检查 |

开发依赖：`pytest`, `pytest-cov`, `pytest-asyncio`

## 许可证

MIT License

---

> **提示**：若你使用 VS Code 或 GitHub Copilot，本仓库的 `AGENTS.md` 已预定义了 4 个领域 Agent（`FcatbotCore`、`PlugkitDeveloper`、`WebSocketExpert`、`RBACDesigner`），可在对应场景中加速代码理解和生成。
