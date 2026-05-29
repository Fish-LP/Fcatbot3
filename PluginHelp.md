# fcatbot 独立插件开发指南

## 1. 概述

fcatbot 采用 **插件化架构**：每个插件是一个独立的 Python 类，通过框架协议与核心及其他插件交互。插件之间不直接 import，而是通过**注册表（Registry）**进行服务发现与调用，实现松耦合。

### 核心设计原则

| 原则         | 说明                                                          |
| ------------ | ------------------------------------------------------------- |
| **自包含**   | 每个插件独立加载、独立配置、独立生命周期。                    |
| **显式依赖** | 通过`dependencies` 声明硬依赖，框架按拓扑排序加载。           |
| **服务抽象** | 业务逻辑封装为纯 Python 服务类，通过`provides` 向注册表暴露。 |
| **事件驱动** | 插件通过事件总线（Bus）通信，支持监听与广播。                 |

---

## 2. 最小插件结构

一个可运行的插件至少需要继承 `Plugin` 并实现生命周期钩子：

```python
from __future__ import annotations

import logging
from typing import ClassVar

from fcatbot.plugkit.protocol.plugin import Plugin


class MyPlugin(Plugin):
    """
    最小插件示例。
    """

    name: ClassVar[str] = "MyPlugin"
    version: ClassVar[str] = "1.0.0"

    def __init__(self):
        super().__init__()
        self.Log = logging.getLogger(self.name)

    def on_load(self) -> None:
        """插件加载钩子。

        Return:
            无。
        """
        self.Log.info(f"▸ {self.name} v{self.version} 已加载")

    def on_start(self) -> None:
        """插件启动钩子。

        Return:
            无。
        """
        self.Log.info("▸ 插件启动")

    def on_stop(self) -> None:
        """插件停止钩子。

        Return:
            无。
        """
        self.Log.info("▸ 插件停止")

    def on_unload(self) -> None:
        """插件卸载钩子。

        Return:
            无。
        """
        self.Log.info("▸ 插件卸载")
```

---

## 3. 服务提供（Provider 模式）

业务逻辑应剥离为**纯 Python 类**（无框架依赖），再通过 `provides` 向注册表声明。

### 3.1 纯业务服务层

```python
# services.py
import time
from typing import Any


class EchoService:
    """回显服务。纯 Python 类，无框架依赖。"""

    def __init__(self):
        self.__version__ = "2.1.0"
        self._History: list[dict[str, Any]] = []

    def Echo(self, message: str) -> str:
        """回显消息并记录历史。

        Args:
            message: 输入消息。

        Return:
            格式化后的回显字符串。
        """
        self._History.append({
            "Original": message,
            "Timestamp": time.time(),
        })
        return f"Echo: {message}"

    def Status(self) -> dict[str, Any]:
        """获取服务状态。

        Return:
            包含版本与历史记录数的状态字典。
        """
        return {
            "Service": "demo.echo",
            "Version": self.__version__,
            "HistoryCount": len(self._History),
        }
```

### 3.2 服务提供者插件

```python
# provider.py
from typing import ClassVar, Any

from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.protocol.data import PluginConfig, value

from .services import EchoService, TimeService


class ProviderConfig(PluginConfig):
    """提供者配置。

    Attributes:
        Prefix: 消息前缀。
    """

    Prefix = value(default="[Provider]")


class DemoProvider(Plugin):
    """
    服务提供者。
    无外部依赖，优先加载；向注册表注册 demo.echo 与 demo.time。
    """

    name: ClassVar[str] = "DemoProvider"
    version: ClassVar[str] = "2.1.0"
    # 声明本插件向注册表提供的服务：键为服务名，值为服务类
    provides: ClassVar[dict[str, Any]] = {
        "demo.echo": EchoService,
        "demo.time": TimeService,
    }

    def __init__(self):
        super().__init__()
        self.Log = logging.getLogger(self.name)
        self.Cfg = ProviderConfig("provider")
        # 实例化服务（短名 echo / time 供框架扫描注册）
        self.echo = EchoService()
        self.time = TimeService()

    def on_load(self) -> None:
        """加载阶段初始化服务实例。

        Return:
            无。
        """
        self.Log.info(f"▸ on_load | {self.name} v{self.version}")

    async def on_start(self) -> None:
        """启动阶段广播就绪事件。

        Return:
            无。
        """
        self.Log.info(f"▸ 服务就绪: {self.echo.Status()}")
        await self.bus.publish({
            "event": "demo.provider.ready",
            "provider": self.name,
            "services": list(self.provides.keys()),
        })
```

**关键点**：

- `provides` 中声明的服务名（如 `demo.echo`）是全局唯一的注册表键。
- 服务实例作为插件属性（`self.echo`）存在，框架会自动将其注册到 Registry。
- 服务类应包含 `__version__` 属性，供版本匹配使用。

---

## 4. 服务消费（Consumer 模式）

消费者通过 `dependencies` 声明硬依赖，在 `on_load` 中通过 `registry` 获取服务实例。

### 4.1 严格依赖声明

```python
# consumer.py
from typing import ClassVar

from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.protocol.event import Event
from fcatbot.plugkit.runtime.decorators import on_event


class DemoConsumer(Plugin):
    """
    服务消费者。
    声明依赖 DemoProvider >=2.0.0，框架按拓扑排序确保其先加载。
    """

    name: ClassVar[str] = "DemoConsumer"
    version: ClassVar[str] = "1.0.0"
    # 硬依赖声明：键为插件名，值为版本约束
    dependencies: ClassVar[dict[str, str]] = {
        "DemoProvider": ">=2.0.0",
    }

    def __init__(self):
        super().__init__()
        self.Log = logging.getLogger(self.name)
        self.echo = None   # 严格服务引用
        self.time = None   # 可选服务引用

    def on_load(self) -> None:
        """加载阶段执行依赖预检与服务获取。

        Return:
            无；若依赖缺失或版本不符则抛出异常，阻止加载。
        """
        # 1. 批量检查服务存在性
        missing = self.registry.check("demo.echo", "demo.time")
        if missing:
            raise RuntimeError(f"依赖服务缺失: {missing}")

        # 2. 严格获取：不存在抛 ServiceNotFound，版本不符抛 VersionMismatch
        self.echo = self.registry.require("demo.echo", version=">=2.0.0")
        self.Log.info(f"  ✓ 严格获取 demo.echo: {self.echo.Status()}")

        # 3. 宽松获取：可选依赖，不存在返回 None
        self.time = self.registry.resolve("demo.time")
        if self.time:
            self.Log.info(f"  ✓ 宽松获取 demo.time: {self.time.Status()}")

    @on_event("demo.provider.ready", priority=60)
    async def OnProviderReady(self, event: Event) -> None:
        """监听提供者就绪事件。

        Args:
            event: 包含 provider / services 的数据事件。

        Return:
            无。
        """
        self.Log.info(
            f"  ◆ 收到就绪通知: {event.data.get('provider')} "
            f"提供 {event.data.get('services')}"
        )

    @on_event("sdk.raw", priority=50)
    async def OnRawMessage(self, event: Event) -> None:
        """监听原始消息并调用依赖服务。

        Args:
            event: 原始 SDK 事件。

        Return:
            无。
        """
        if self.echo is None:
            return

        raw = str(event.data)
        result = self.echo.Echo(raw)
        if self.time is not None:
            result = f"{self.time.Format()} {result}"

        self.Log.info(f"  ◆ 服务调用结果: {result}")

        # 发布衍生事件
        await self.bus.publish({
            "event": "demo.message.processed",
            "data": result,
        })
```

### 4.2 Registry API 对照

| 方法                                   | 行为           | 异常                                 |
| -------------------------------------- | -------------- | ------------------------------------ |
| `registry.require(name, version=None)` | 严格获取服务   | `ServiceNotFound`、`VersionMismatch` |
| `registry.resolve(name)`               | 宽松获取服务   | 不存在返回`None`                     |
| `registry.check(*names)`               | 批量检查存在性 | 返回缺失名称列表                     |
| `registry.add_listener(callback)`      | 订阅注册表变化 | —                                   |
| `registry.remove_listener(token)`      | 取消订阅       | —                                   |

---

## 5. 服务发现（Observer 模式）

不声明硬依赖，通过监听注册表事件实现松耦合的服务发现。

```python
# observer.py
from typing import ClassVar

from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.protocol.service import ServiceInfo


class DemoObserver(Plugin):
    """
    注册表观察者。
    不声明 dependencies，通过监听注册表事件感知服务上线/下线。
    """

    name: ClassVar[str] = "DemoObserver"
    version: ClassVar[str] = "1.0.0"

    def __init__(self):
        super().__init__()
        self.Log = logging.getLogger(self.name)

    def on_load(self) -> None:
        """加载阶段订阅注册表变化。

        Return:
            无。
        """
        self.Log.info(f"▸ on_load | {self.name} v{self.version}")
        self._token = self.registry.add_listener(self._OnServiceChange)
        self.Log.info("  ✓ 已订阅注册表变化")

    def on_unload(self) -> None:
        """卸载阶段取消订阅。

        Return:
            无。
        """
        if hasattr(self, "_token"):
            self.registry.remove_listener(self._token)
        self.Log.info("▸ on_unload | 观察者卸载")

    def _OnServiceChange(self, event: str, info: ServiceInfo) -> None:
        """注册表变更回调。

        Args:
            event: "register" 或 "unregister"。
            info: 服务元数据。

        Return:
            无。
        """
        if info.name in ("demo.echo", "demo.time"):
            self.Log.info(
                f"  ◆ [Observer] {info.name}@{info.version} {event.upper()} "
                f"by {info.provider}"
            )
```

**适用场景**：

- 可选依赖（服务存在时增强功能，不存在时降级运行）。
- 监控面板、服务治理、动态路由等旁路功能。

---

## 6. 配置与数据

### 6.1 静态配置（PluginConfig）

配置在插件目录的 `config/` 下持久化，重启后保留：

```python
from fcatbot.plugkit.protocol.data import PluginConfig, value


class MyConfig(PluginConfig):
    """插件静态配置。

    Attributes:
        Timeout: 请求超时秒数。
        Prefix: 消息前缀。
    """

    Timeout = value(default=5)
    Prefix = value(default="[Bot]")


class MyPlugin(Plugin):
    cfg: MyConfig = MyConfig("myplugin")

    def on_load(self) -> None:
        self.Log.info(f"当前前缀: {self.cfg.Prefix}")
```

### 6.2 动态数据（PluginData）

数据在插件目录的 `data/` 下持久化，运行时读写。框架通过 `_coerce` 钩子**自动完成类型强制转换**，无需手动逐个字段构建：

```python
from fcatbot.plugkit.protocol.data import PluginData, ConfigSection, Value, section


class GroupData(ConfigSection):
    """单个群组的动态数据。"""

    enabled = Value(default=False)
    count = Value(default=0)


class GroupsHolder(ConfigSection):
    """群号 -> GroupData 容器。

    当从 YAML/JSON 加载原始 dict 时，框架自动调用 _coerce
    将嵌套字典转为 GroupData 实例，无需手动 build。
    """

    @classmethod
    def _coerce(cls, name: str, value: Any) -> Any:
        """强制转换原始 dict 为 GroupData。

        Args:
            name: 群号字符串。
            value: 原始值。

        Return:
            转换后的值。
        """
        if isinstance(value, dict) and not isinstance(value, ConfigSection):
            return GroupData.from_dict(value)
        return super()._coerce(name, value)


class MyData(PluginData):
    """插件动态数据。"""

    groups = section(default_factory=GroupsHolder)


class MyPlugin(Plugin):
    data: MyData = MyData("myplugin")

    def _ensure_group(self, group_id: str) -> GroupData:
        """确保群组数据已初始化。

        Args:
            group_id: 群号字符串。

        Return:
            该群的 GroupData 实例。
        """
        if group_id not in self.data.groups:
            self.data.groups[group_id] = GroupData()
        return self.data.groups[group_id]
```

**自动构建说明**：

- `ConfigSection.from_dict()` 由框架在反序列化时自动调用。
- 自定义 `_coerce` 钩子后，向 `self.data.groups[group_id] = {...}` 赋值一个原始 `dict` 时，框架会自动将其包装为 `GroupData`。
- 多层嵌套结构同理，开发者**不需要**在业务代码中手动调用 `build()` 或 `from_dict()`。

---

## 7. 事件系统

### 7.1 监听事件

```python
from fcatbot.plugkit.runtime.decorators import on_event
from fcatbot.plugkit.protocol.event import Event

class MyPlugin(Plugin):
    @on_event("napcat.message.group", priority=50)
    async def on_group_message(self, event: Event) -> None:
        """监听群消息。

        Args:
            event: 群消息事件。

        Return:
            无。
        """
        msg = event.data
        text = msg.extract_plain_text() if hasattr(msg, "extract_plain_text") else str(msg)
        self.Log.info(f"收到群消息: {text}")
```

### 7.2 发布事件

```python
await self.bus.publish({
    "event": "myplugin.task.done",
    "data": {"result": "success"},
})
```

### 7.3 事件优先级

`priority` 数值越大优先级越高（越早执行）。建议：

- `10-30`：前置拦截（权限检查、过滤器）。
- `50-70`：业务处理。
- `90-100`：后置监听（日志、统计）。

---

## 8. 命令系统（ConsoleMixin）

通过 `ConsoleMixin` 与 `@on_command` 注册控制台命令，支持命令树与自动挂载。

```python
from typing import ClassVar

from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.console import ConsoleMixin
from fcatbot.utils.cmdparse import on_command, CommandContext


class MyPlugin(Plugin, ConsoleMixin):
    name: ClassVar[str] = "MyPlugin"
    version: ClassVar[str] = "1.0.0"

    # 定义命令组
    cmd = on_command.group("my", description="我的插件命令")

    @cmd(description="回声测试")
    async def echo(self, ctx: CommandContext, raw: str = "") -> str:
        """回声消息。

        Args:
            ctx: 命令上下文。
            raw: 原始参数。

        Return:
            回声结果。
        """
        return f"echo: {raw or 'world'}"

    @cmd.command(description="查看状态")
    def status(self, ctx: CommandContext, raw: str = "") -> str:
        """查看插件状态。

        Return:
            状态文本。
        """
        return f"{self.name} v{self.version} 运行中"
```

**要点**：

- 继承 `ConsoleMixin` 后，命令会被自动挂载到全局控制台。
- `on_command.group()` 创建命令前缀组，`@cmd` 注册子命令。
- 方法参数中的 `raw` 接收剩余参数字符串。

---

## 9. 消息链构造（NapcatMixin）

通过 `NapcatMixin` 获取 API，使用 `MsgChain` 或 `BuildMessage` 构造富媒体消息。

```python
from typing import ClassVar

from fcatbot.plugkit.protocol.plugin import Plugin
from plugins.adapter import NapcatMixin
from plugins.adapter.napcat.building import BuildMessage, MsgChain


class MyPlugin(Plugin, NapcatMixin):
    name: ClassVar[str] = "MyPlugin"
    version: ClassVar[str] = "1.0.0"
    dependencies: ClassVar[dict[str, str]] = {"NapcatAdapter": ">=1.0.0"}

    async def on_start(self) -> None:
        # 发送组合消息：@某人 + 文本 + 图片
        chain = (
            BuildMessage("你好，")
            .at(123456789)
            .text("这是测试消息")
            .image(file="https://example.com/pic.png")
        )
        await self.api.group.send_group_message(987654321, chain.to_api())
```

**常用链式方法**：

| 方法                     | 说明                          |
| ------------------------ | ----------------------------- |
| `.text(str)`             | 纯文本                        |
| `.at(qq)`                | @某人，`"all"` 表示 @全体成员 |
| `.image(file, url, ...)` | 图片段                        |
| `.reply(message_id)`     | 回复段                        |
| `.face(id)`              | QQ 表情                       |
| `.markdown(content)`     | Markdown 段                   |
| `.to_api()`              | 输出为标准消息段数组          |

---

## 10. 权限检查（LuckPermsMixin）

通过 `LuckPermsMixin` 在消息事件中执行 LuckPerms-Mirai 风格权限检查。

```python
from typing import ClassVar

from fcatbot.plugkit.protocol.plugin import Plugin
from plugins.adapter import NapcatMixin
from plugins.Luckperms.mixin import LuckPermsMixin
from fcatbot.plugkit.runtime.decorators import on_event


class MyPlugin(Plugin, NapcatMixin, LuckPermsMixin):
    name: ClassVar[str] = "MyPlugin"
    version: ClassVar[str] = "1.0.0"
    dependencies: ClassVar[dict[str, str]] = {
        "NapcatAdapter": ">=1.0.0",
        "LuckPerms": ">=1.0.0",
    }

    @on_event("napcat.message.group")
    async def on_group_message(self, event) -> None:
        msg = event.data
        user_id = msg.user_id
        group_id = str(msg.group_id)

        # 检查特定权限节点（自动注入群上下文）
        if not self.has_permission(user_id, "myplugin.use", group=group_id):
            await msg.reply("你没有权限使用此功能")
            return

        # 严格检查：无权限直接抛异常中断执行
        self.ensure_permission(user_id, "myplugin.admin", group=group_id)
```

**上下文自动注入**：

- `check_message(msg, node)` 会根据消息事件自动提取 `group`、`level`、`admin`、`contact`、`type`、`user` 等上下文。
- `has_permission()` 支持手动传入 `**context` 键值对。

---

## 11. 事件分流（EventTap）

通过 `NapcatMixin` 创建事件分流器，在 `async with` 块内捕获满足条件的事件。

```python
async with self.tap(group_id=123456, block=True) as tap:
    async for event in tap:
        msg = event.data
        # 处理事件...
        break
```

**参数说明**：

| 参数         | 说明                                      |
| ------------ | ----------------------------------------- |
| `predicate`  | 自定义过滤函数`Event -> bool`             |
| `event_name` | 事件名前缀匹配                            |
| `group_id`   | 群号过滤                                  |
| `user_id`    | 发送者 QQ 过滤                            |
| `block`      | `False`（透传，默认）/ `True`（阻断总线） |
| `maxsize`    | 内部队列最大长度，`0` 为无限制            |

---

## 12. 生命周期顺序

框架按以下顺序调用插件方法：

```
1. 拓扑排序（根据 dependencies）
2. 对每个插件：
   ├─ __init__()
   ├─ on_load()      ← 初始化配置、预检依赖、注册服务
   ├─ on_start()     ← 启动后台任务、广播就绪
   ├─ 运行期（处理事件、调用服务）
   ├─ on_stop()      ← 停止后台任务、释放资源
   └─ on_unload()    ← 保存数据、注销监听
```

**注意**：

- `on_load()` 中若抛出异常，插件加载失败，依赖它的插件也会被阻止。
- `on_start()` 可以是 `async`，用于启动协程任务。
- `on_unload()` 中务必保存 `PluginData` 并清理 `registry` 监听器。

---

## 13. 版本约束与依赖管理

### 13.1 版本声明

```python
dependencies: ClassVar[dict[str, str]] = {
    "DemoProvider": ">=2.0.0",      # 大于等于 2.0.0
    "LuckPerms": ">=1.0.0",         # 权限插件
    "NapcatAdapter": ">=1.0.0",     # 适配器
}
```

### 13.2 服务版本匹配

```python
# 要求 demo.echo 服务版本 >=2.0.0
self.echo = self.registry.require("demo.echo", version=">=2.0.0")
```

### 13.3 服务类版本标记

```python
class EchoService:
    def __init__(self):
        self.__version__ = "2.1.0"   # 供 registry 匹配
```

---

## 14. 开发模式与热重载

启动时添加 `--dev` 标志启用开发模式：

```bash
python -m fcatbot start -u "ws://localhost:8080/ws" -p ./plugins --dev
```

- 修改插件 `.py` 文件后自动热重载（保留 `on_before_reload` / `on_after_reload` 状态）。
- 修改插件配置 `.yml` 文件后触发 `on_config_change()`。
- 生产环境**不要**启用 `--dev`，避免文件监视器开销。

---

## 15. 调试与日志规范

### 15.1 日志命名

```python
import logging

class MyPlugin(Plugin):
    def __init__(self):
        super().__init__()
        self.Log = logging.getLogger(self.name)  # 使用插件名作为 logger 名
```

### 15.2 异常隔离

事件处理方法内务必捕获异常，避免单个插件错误导致事件总线中断：

```python
@on_event("napcat.message.group")
async def on_group_message(self, event: Event) -> None:
    try:
        await self._process(event.data)
    except Exception as e:
        self.Log.exception("处理群消息时出错")
        # 可选：向用户反馈错误
```

---

## 16. 完整示例：计数器插件

以下是一个兼具 **Provider** 与 **Consumer** 特征的完整插件：

```python
from __future__ import annotations

import logging
from typing import ClassVar, Any

from fcatbot.plugkit.protocol.plugin import Plugin
from fcatbot.plugkit.protocol.event import Event
from fcatbot.plugkit.protocol.data import PluginConfig, PluginData, Value
from fcatbot.plugkit.runtime.decorators import on_event


# ---------- 纯业务服务 ----------
class CounterService:
    """计数器服务。"""

    def __init__(self):
        self.__version__ = "1.0.0"
        self._count = 0

    def Increment(self) -> int:
        """计数加一并返回当前值。

        Return:
            当前计数值。
        """
        self._count += 1
        return self._count

    def Reset(self) -> None:
        """重置计数器。

        Return:
            无。
        """
        self._count = 0


# ---------- 配置与数据 ----------
class CounterConfig(PluginConfig):
    """计数器配置。"""

    step = Value(default=1)


class CounterData(PluginData):
    """计数器持久化数据。"""

    total = Value(default=0)


# ---------- 插件主体 ----------
class CounterPlugin(Plugin):
    """
    计数器插件。
    提供 demo.counter 服务，同时消费 napcat 消息事件。
    """

    name: ClassVar[str] = "CounterPlugin"
    version: ClassVar[str] = "1.0.0"
    provides: ClassVar[dict[str, Any]] = {
        "demo.counter": CounterService,
    }

    def __init__(self):
        super().__init__()
        self.Log = logging.getLogger(self.name)
        self.Cfg = CounterConfig("counter")
        self.Data = CounterData("counter")
        self.counter = CounterService()

    def on_load(self) -> None:
        """加载阶段绑定配置与数据路径。

        Return:
            无。
        """
        self.Log.info(f"▸ 计数器已加载，当前总计: {self.Data.total}")

    async def on_start(self) -> None:
        """启动阶段广播服务就绪。

        Return:
            无。
        """
        await self.bus.publish({
            "event": "demo.counter.ready",
            "provider": self.name,
        })

    def on_unload(self) -> None:
        """卸载阶段保存数据。

        Return:
            无。
        """
        self.Data.save()
        self.Log.info("▸ 计数器数据已保存")

    @on_event("napcat.message.group", priority=70)
    async def on_group_message(self, event: Event) -> None:
        """监听群消息，触发计数。

        Args:
            event: 群消息事件。

        Return:
            无。
        """
        msg = event.data
        text = msg.extract_plain_text() if hasattr(msg, "extract_plain_text") else str(msg)

        if text.strip() == "+1":
            current = self.counter.Increment()
            self.Data.total += self.Cfg.step
            self.Data.save()

            await self.bus.publish({
                "event": "demo.counter.incremented",
                "data": {"current": current, "total": self.Data.total},
            })
```

---

## 17. 最佳实践

| 实践                 | 说明                                                                                |
| -------------------- | ----------------------------------------------------------------------------------- |
| **业务与框架解耦**   | 核心逻辑写在纯 Python 类（如`services.py`），不依赖 `fcatbot` 包。                  |
| **显式优于隐式**     | 依赖必须写入`dependencies`，服务必须写入 `provides`，避免运行时找不到。             |
| **防御式获取**       | 对可选服务使用`registry.resolve()`，对强依赖使用 `registry.require()`。             |
| **及时保存数据**     | `PluginData` 修改后显式调用 `.save()`，或在 `on_unload()` 中统一保存。              |
| **清理监听器**       | `on_unload()` 中务必 `remove_listener`，防止插件热重载后回调残留。                  |
| **版本语义化**       | 遵循`MAJOR.MINOR.PATCH`，服务类通过 `__version__` 暴露版本号。                      |
| **异常隔离**         | 事件处理方法内捕获异常，避免单个插件错误导致事件总线中断。                          |
| **数据自动构建**     | 利用`ConfigSection._coerce` 实现嵌套结构的自动类型转换，无需手动 `build()`。        |
| **权限最小化**       | 使用 LuckPerms 细粒度节点控制功能访问，避免硬编码管理员 QQ 列表。                   |
| **事件分流慎用阻断** | `EventTap(block=True)` 会阻止事件进入总线，确保在 with 块内消费完毕，避免事件丢失。 |
