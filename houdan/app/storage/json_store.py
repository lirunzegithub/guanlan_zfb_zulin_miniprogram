"""基于 JSON 文件的 Repository 实现。

文件格式：
{
  "next_id": 13,
  "items": [ { "id": 1, ... }, ... ]
}

所有写操作走 _save -> 写临时文件 -> os.replace 实现原子替换，避免半写。
进程内加锁，跨进程不保证一致（生产环境换成 DB）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional

from .base import BaseRepository


class JsonRepository(BaseRepository):
    def __init__(self, file_path: str, default_fields: Optional[dict] = None):
        self.file_path = file_path
        self.default_fields = default_fields or {}
        self._lock = threading.RLock()
        if not os.path.exists(file_path):
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            self._save({"next_id": 1, "items": []})

    # ---------- 内部 IO ----------
    def _load(self) -> dict:
        with open(self.file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, payload: dict) -> None:
        tmp = self.file_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.file_path)

    # ---------- 过滤匹配 ----------
    @staticmethod
    def _match(item: dict, filters: dict) -> bool:
        for k, v in filters.items():
            if v is None:
                continue
            if k.endswith("__in"):
                key = k[:-4]
                if item.get(key) not in v:
                    return False
            elif k.endswith("__contains"):
                key = k[:-10]
                if str(v).lower() not in str(item.get(key, "")).lower():
                    return False
            else:
                if item.get(k) != v:
                    return False
        return True

    # ---------- 公共接口 ----------
    def get(self, oid: int) -> Optional[dict]:
        with self._lock:
            data = self._load()
            for item in data["items"]:
                if item.get("id") == oid:
                    return dict(item)
        return None

    def list(self, **filters: Any) -> list[dict]:
        with self._lock:
            data = self._load()
            items = [dict(x) for x in data["items"]]
        if filters:
            items = [x for x in items if self._match(x, filters)]
        items.sort(key=lambda x: (x.get("sort", 0), x.get("id", 0)))
        return items

    def find(self, **filters: Any) -> Optional[dict]:
        rows = self.list(**filters)
        return rows[0] if rows else None

    def count(self, **filters: Any) -> int:
        return len(self.list(**filters))

    def create(self, data: dict) -> dict:
        now = int(time.time())
        with self._lock:
            payload = self._load()
            nid = payload["next_id"]
            payload["next_id"] = nid + 1

            record = {**self.default_fields, **data}
            record["id"] = nid
            record.setdefault("enabled", True)
            record.setdefault("sort", 0)
            record["created_at"] = now
            record["updated_at"] = now

            payload["items"].append(record)
            self._save(payload)
            return dict(record)

    def update(self, oid: int, data: dict) -> Optional[dict]:
        with self._lock:
            payload = self._load()
            for i, item in enumerate(payload["items"]):
                if item.get("id") == oid:
                    updated = {**item, **data}
                    updated["id"] = oid                  # 防止被覆盖
                    updated["updated_at"] = int(time.time())
                    payload["items"][i] = updated
                    self._save(payload)
                    return dict(updated)
        return None

    def delete(self, oid: int) -> bool:
        """物理删除：从 items 中移除。不存在返回 False。"""
        with self._lock:
            payload = self._load()
            for i, item in enumerate(payload["items"]):
                if item.get("id") == oid:
                    payload["items"].pop(i)
                    self._save(payload)
                    return True
        return False

    # ---------- 工具 ----------
    def seed(self, items: list[dict]) -> None:
        """初始化种子数据（仅在文件为空时生效）。"""
        with self._lock:
            payload = self._load()
            if payload["items"]:
                return
            now = int(time.time())
            next_id = 1
            new_items = []
            for raw in items:
                rec = {**self.default_fields, **raw}
                if "id" not in rec:
                    rec["id"] = next_id
                next_id = max(next_id, rec["id"]) + 1
                rec.setdefault("enabled", True)
                rec.setdefault("sort", 0)
                rec.setdefault("created_at", now)
                rec.setdefault("updated_at", now)
                new_items.append(rec)
            self._save({"next_id": next_id, "items": new_items})
