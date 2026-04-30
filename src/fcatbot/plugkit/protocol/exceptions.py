class PluginFatalError(Exception):
    def __init__(self, plugin_name: str, cause: Exception):
        self.plugin_name = plugin_name
        self.__cause__ = cause
        super().__init__(f"Plugin '{plugin_name}' fatal crash: {cause}")
