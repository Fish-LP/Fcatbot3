from collections import deque

from fcatbot.plugkit.protocol.exceptions import PluginDependencyError


def resolve_load_order(graph: dict[str, set[str]]) -> list[str]:
    in_degree = {name: len(deps) for name, deps in graph.items()}
    queue = deque([name for name, deg in in_degree.items() if deg == 0])
    order = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for name, deps in graph.items():
            if node in deps:
                in_degree[name] -= 1
                if in_degree[name] == 0:
                    queue.append(name)

    if len(order) != len(graph):
        remaining = set(graph.keys()) - set(order)
        raise PluginDependencyError(f"Circular dependency detected among: {remaining}")

    return order
