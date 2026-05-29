# AGENTS

`AGENTS.md` 记录本仓库中 Copilot / VS Code 自定义 Agent 的用途、范围与使用规范，作为架构理解与生成的统一入口。

`Fcatbot3` 是一个基于 Python 的异步 Bot 框架，采用 WebSocket 连接后端，Plugkit 插件系统实现模块化扩展。Agent 配置围绕核心层、协议层、运行时层、连接层、权限层五个维度展开。

## 目录

1. [概述](#概述)
2. [Agent 列表](#agent-列表)
3. [定义规范](#定义规范)
4. [Agent 详情](#agent-详情)
5. [维护建议](#维护建议)

## 概述

本文档用于：

- 记录项目内自定义 Agent 的用途、范围与约定。
- 说明如何在仓库中新增、修改或清理 Agent 配置。
- 为开发者与维护者提供统一的 Agent 文档入口。
- 加速 Copilot / VS Code 理解 Fcatbot3 的架构分层。

## Agent 列表

| Agent 名称         | 目标                 | 对应文件    | 触发场景                               |
| ------------------ | -------------------- | ----------- | -------------------------------------- |
| `FcatbotCore`      | 核心架构与生命周期   | `AGENTS.md` | 查询启动流程、事件总线、插件生命周期   |
| `PlugkitDeveloper` | 插件开发与调试       | `AGENTS.md` | 编写插件、装饰器、服务注册、数据持久化 |
| `WebSocketExpert`  | WebSocket 连接与通信 | `AGENTS.md` | 连接管理、监听器、重连策略、指标观测   |

## 定义规范

Agent 配置采用以下文件组织：

- `AGENTS.md`：仓库层面的 Agent 文档索引。
- `*.instructions.md`：Agent 的行为指令与设计说明。
- `*.prompt.md`：交互式 prompt 文本。

## Agent 详情

### Agent: FcatbotCore

**目标**：理解 `Fcatbot3` 核心入口、事件总线、插件生命周期与整体架构决策。

**触发场景**：

- 查询 `Bot` 类的启动流程（`run()` / `run_async()`）和优雅退出（`stop()`）。
- 理解 `Bus` 的订阅/发布机制、优先级调度、拦截器体系。
- 理解 `LifecycleManager` 如何管理插件的加载、启动、停止、卸载、热重载。
- 了解 WebSocket 原始事件如何被包装为 `Event` 并发布到总线。

**关键指令**：

- `Bot` 是纯同步初始化、异步运行的统一入口；`_cat()` 循环将 WS 消息以最小开销发布为 `sdk.raw` 事件。
- `Bus` 使用多 worker 消费队列，支持全局拦截器和 Handler 拦截器；事件优先级数字越大越先执行。
- `LifecycleManager` 自动处理插件依赖拓扑排序（`resolver.py`）、Mixin 收集、服务自动注册、数据路径绑定。
- 开发模式下（`--dev`），`PluginWatcher` 通过 `watchdog` 监视插件代码和配置变更，实现热重载。

**对应文件**：

- `src/fcatbot/__main__.py` — `Bot` 主入口
- `src/fcatbot/plugkit/runtime/bus.py` — `Bus` 实现
- `src/fcatbot/plugkit/runtime/lifecycle.py` — `LifecycleManager`
- `src/fcatbot/plugkit/runtime/resolver.py` — 依赖解析
- `src/fcatbot/plugkit/runtime/watcher.py` — 热重载监视器

---

### Agent: PlugkitDeveloper

**目标**：指导开发者编写、调试和维护插件，掌握声明式事件监听、服务注册与数据持久化。

**触发场景**：

- 创建 `Plugin` 子类并声明事件处理器。
- 使用 `@on_event` 装饰器绑定事件，设置优先级和过滤条件。
- 插件需要暴露服务（`provides`）或消费其他插件注册的服务。
- 插件需要持久化配置（`PluginConfig`）或数据（`PluginData`）。
- 插件需要处理热重载前后状态保存与恢复。

**关键指令**：

- 插件必须继承 `Plugin` 抽象基类，声明 `name`、`version`、`dependencies`、`provides` 等类属性。
- 使用 `@on_event(event_spec, priority=50, once=False, filter=...)` 装饰方法即可自动订阅事件；事件总线会在插件启动时统一绑定。
- `provides` 字典中的服务名会在插件加载后自动注册到 `PluginServiceRegistry`；其他插件通过 `self.registry.require("svc.name")` 消费。
- `PluginConfig` 使用 YAML 后端，默认自动绑定到 `{data_dir}/{plugin_name}/config/{name}.yml`。
- 热重载钩子：`on_before_reload`（保存状态）、`on_after_reload`（恢复状态）；`on_config_change` 响应外部配置修改。

**对应文件**：

- `src/fcatbot/plugkit/protocol/plugin.py` — `Plugin` 基类
- `src/fcatbot/plugkit/protocol/data.py` — `PluginData`、`PluginConfig`、`ConfigSection`
- `src/fcatbot/plugkit/protocol/service.py` — `ServiceRegistry` 协议
- `src/fcatbot/plugkit/runtime/decorators.py` — `@on_event`
- `src/fcatbot/plugkit/runtime/registry.py` — `PluginServiceRegistry` 实现
- `src/fcatbot/plugkit/runtime/loader.py` — `PluginLoader`

---

### Agent: WebSocketExpert

**目标**：正确使用 WebSocket 连接层，包括异步/同步双形态客户端、监听器模式、自动重连与指标观测。

**触发场景**：

- 建立或管理 Bot 与后端的 WebSocket 连接。
- 创建监听器来消费 WS 消息，或理解消息广播机制。
- 遇到连接断开、重连失败、压缩协商错误等问题。
- 需要导出连接指标（连接次数、收发字节、队列长度、监听器数量）。

**关键指令**：

- `AsyncWebSocketClient` 是原生协程实现；`SyncWebSocketClient` 在后台线程运行事件循环，供同步代码使用。
- 使用 `create_listener()` 获取独立的消息队列（自带缓冲区，满时丢弃最旧数据）；通过 `get_message()` 阻塞读取或异步迭代。
- 自动重连采用指数退避 + 随机抖动；`reconnect_attempts=0` 表示无限重连；压缩协商失败会自动禁用压缩并重试。
- 指标通过 `get_metrics()` 获取，包含 `connection`、`reconnection`、`listeners` 三个维度。
- 发送队列满时抛出 `WebSocketError`；监听器用完务必 `remove_listener`，否则一直占内存。

**对应文件**：

- `src/fcatbot/connection/websocket.py` — `AsyncWebSocketClient`、`SyncWebSocketClient`、`WebSocketListener`

# 维护建议

- 新增或变更 Agent 时，务必在本文档同步更新说明。
- 本仓库以 `AGENTS.md` 作为索引，各模块详细指令可拆分到对应目录的 `.instructions.md`。
- 定期检查并移除过时 Agent 配置。
- 新增 Agent 优先覆盖 Fcatbot3 的核心分层（核心层、协议层、运行时层、连接层、权限层），避免过度细分。
