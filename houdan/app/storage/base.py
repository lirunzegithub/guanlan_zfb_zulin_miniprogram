"""存储抽象层。所有 Repository 实现都需符合此接口，业务路由只依赖此接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Any


class BaseRepository(ABC):
    """通用 Repository 接口"""

    @abstractmethod
    def get(self, oid: int) -> Optional[dict]:
        """按主键取一条；不存在返回 None。"""

    @abstractmethod
    def list(self, **filters: Any) -> list[dict]:
        """按过滤条件取列表；不传过滤条件返回全部。"""

    @abstractmethod
    def find(self, **filters: Any) -> Optional[dict]:
        """按过滤条件取首条。"""

    @abstractmethod
    def create(self, data: dict) -> dict:
        """新增；自动注入 id / created_at / updated_at；返回入库后的记录。"""

    @abstractmethod
    def update(self, oid: int, data: dict) -> Optional[dict]:
        """更新部分字段；自动刷新 updated_at；不存在返回 None。"""

    @abstractmethod
    def delete(self, oid: int) -> bool:
        """物理删除。不存在返回 False。需要"禁用"语义请用 update(oid, {"enabled": False})。"""

    @abstractmethod
    def count(self, **filters: Any) -> int:
        """计数。"""
