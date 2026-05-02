"""
RBAC 权限管理层
"""

from fcatbot.rbac.manager import (
    RBACManager,
    Role,
    Track,
    is_role,
    is_track,
)

__all__ = [
    "RBACManager",
    "Role",
    "Track",
    "is_role",
    "is_track",
]
