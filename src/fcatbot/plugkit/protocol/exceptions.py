class PluginError(Exception):
    """PlugKit 插件相关错误基类。"""


class PluginFatalError(PluginError):
    def __init__(self, plugin_name: str, cause: Exception):
        self.plugin_name = plugin_name
        self.__cause__ = cause
        super().__init__(f"Plugin '{plugin_name}' fatal crash: {cause}")


class PluginLoadError(PluginError):
    """插件加载失败时抛出的异常。"""

    def __init__(self, plugin_name: str, message: str):
        self.plugin_name = plugin_name
        super().__init__(f"Plugin '{plugin_name}' load error: {message}")


class PluginNotLoadedError(PluginError):
    """当插件尚未完成加载或绑定时抛出。"""

    def __init__(self, plugin_name: str, message: str = "not loaded"):
        self.plugin_name = plugin_name
        super().__init__(f"Plugin '{plugin_name}' not loaded: {message}")


class PluginStateError(PluginError):
    """无效的插件状态或生命周期操作时抛出。"""

    def __init__(self, message: str):
        super().__init__(message)


class PluginDependencyError(PluginError):
    """插件依赖关系错误时抛出。"""

    def __init__(self, message: str):
        super().__init__(message)


class PluginDataError(PluginError):
    """插件数据绑定/存储错误。"""

    def __init__(self, message: str):
        super().__init__(message)


class PluginEventLoopError(PluginError):
    """插件内部事件循环不可用时抛出。"""

    def __init__(self, message: str):
        super().__init__(message)


class BusClosedError(PluginError):
    """事件总线已关闭时抛出。"""

    def __init__(self, message: str = "Bus closed"):
        super().__init__(message)
