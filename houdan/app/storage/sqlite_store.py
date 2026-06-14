"""基于 SQLite 的 Repository 实现。

设计要点：
1. **单一 .db 文件**：所有 repo 共享一个数据库，方便备份/迁移
2. **payload JSON blob**：每张表只有 `id / payload / enabled / sort_key / created_at / updated_at`，
   完整字典存进 payload，业务字段不强约束 schema 演进，对 JsonRepository 行为 100% 兼容
3. **过滤兼容**：list/find 拉全表 → Python `_match` 过滤，与 JsonRepository 逻辑一致
4. **id 类型**：默认 `int` AUTOINCREMENT；orders / users 用 `str` PRIMARY KEY（保留原业务 id 格式）
5. **并发**：SQLite 自带文件锁 + 事务，单进程多线程 + 多进程都安全
6. **每次都开短连接**：避免跨线程共享 Connection 的坑（Flask + gunicorn worker 友好）

切回 Json 只需把 repos.py 的实现换回去，业务路由零改动。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional

from .base import BaseRepository


class SqliteRepository(BaseRepository):

    def __init__(
        self,
        db_path: str,
        table: str,
        default_fields: Optional[dict] = None,
        id_type: str = "int",  # "int" | "str"
    ):
        self.db_path = db_path
        self.table = table
        self.default_fields = default_fields or {}
        self.id_type = id_type
        self._lock = threading.Lock()  # 进程内 INSERT 串行化（防 next_id 竞争对 str id 类型无所谓）
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_table()

    # -------------------- 内部 --------------------
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        # WAL 提升并发读性能；同步 NORMAL 在掉电时可能丢最后一条事务，业务能接受
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_table(self) -> None:
        id_col = (
            "INTEGER PRIMARY KEY AUTOINCREMENT"
            if self.id_type == "int"
            else "TEXT PRIMARY KEY"
        )
        with self._conn() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    id {id_col},
                    payload TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_key INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table}_enabled ON {self.table}(enabled)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table}_updated ON {self.table}(updated_at)")
            conn.commit()

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

    def _all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT payload FROM {self.table} ORDER BY sort_key ASC, id ASC"
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    # -------------------- BaseRepository 公共接口 --------------------
    def get(self, oid: Any) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT payload FROM {self.table} WHERE id = ?", (oid,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, **filters: Any) -> list[dict]:
        items = self._all()
        if filters:
            items = [x for x in items if self._match(x, filters)]
        return items

    def find(self, **filters: Any) -> Optional[dict]:
        rows = self.list(**filters)
        return rows[0] if rows else None

    def count(self, **filters: Any) -> int:
        return len(self.list(**filters))

    def create(self, data: dict) -> dict:
        now = int(time.time())
        record = {**self.default_fields, **data}
        record.setdefault("enabled", True)
        record.setdefault("sort", 0)
        record["created_at"] = now
        record["updated_at"] = now

        with self._lock, self._conn() as conn:
            if self.id_type == "str":
                if "id" not in record:
                    raise ValueError(f"{self.table}: str id 类型必须由调用方提供 'id'")
                conn.execute(
                    f"INSERT INTO {self.table} (id, payload, enabled, sort_key, created_at, updated_at) "
                    f"VALUES (?,?,?,?,?,?)",
                    (
                        record["id"],
                        json.dumps(record, ensure_ascii=False),
                        1 if record.get("enabled") else 0,
                        int(record.get("sort", 0)),
                        now, now,
                    ),
                )
            else:
                cur = conn.execute(
                    f"INSERT INTO {self.table} (payload, enabled, sort_key, created_at, updated_at) "
                    f"VALUES (?,?,?,?,?)",
                    (
                        json.dumps(record, ensure_ascii=False),
                        1 if record.get("enabled") else 0,
                        int(record.get("sort", 0)),
                        now, now,
                    ),
                )
                new_id = cur.lastrowid
                record["id"] = new_id
                conn.execute(
                    f"UPDATE {self.table} SET payload = ? WHERE id = ?",
                    (json.dumps(record, ensure_ascii=False), new_id),
                )
            conn.commit()
        return dict(record)

    def update(self, oid: Any, data: dict) -> Optional[dict]:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                f"SELECT payload FROM {self.table} WHERE id = ?", (oid,)
            ).fetchone()
            if not row:
                return None
            item = json.loads(row[0])
            item.update(data)
            item["id"] = oid                              # 防止被覆盖
            item["updated_at"] = int(time.time())
            conn.execute(
                f"UPDATE {self.table} SET payload = ?, enabled = ?, sort_key = ?, updated_at = ? "
                f"WHERE id = ?",
                (
                    json.dumps(item, ensure_ascii=False),
                    1 if item.get("enabled", True) else 0,
                    int(item.get("sort", 0)),
                    item["updated_at"],
                    oid,
                ),
            )
            conn.commit()
        return dict(item)

    def try_decrement(self, oid: Any, field: str, by: int = 1, floor: int = 0) -> Optional[int]:
        """原子扣减 payload 里的某个整数字段（如库存 stock）。

        仅当"扣减后的值 >= floor"时才执行，单条 UPDATE + 进程锁，
        从根本上杜绝并发下的超卖 / 扣成负数。

        返回：
          - 扣减成功 → 扣减后的新值（int）
          - 余量不足 / 记录不存在 → None（未做任何修改）

        注：field 必须是代码内写死的字段名（非用户输入），此处会拼进 SQL。
        """
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                f"UPDATE {self.table} "
                f"SET payload = json_set(payload, '$.{field}', "
                f"        CAST(json_extract(payload, '$.{field}') AS INTEGER) - ?), "
                f"    updated_at = ? "
                f"WHERE id = ? "
                f"  AND CAST(json_extract(payload, '$.{field}') AS INTEGER) - ? >= ?",
                (by, int(time.time()), oid, by, floor),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                f"SELECT CAST(json_extract(payload, '$.{field}') AS INTEGER) "
                f"FROM {self.table} WHERE id = ?",
                (oid,),
            ).fetchone()
        return int(row[0]) if row else None

    def delete(self, oid: Any) -> bool:
        """物理删除：DELETE FROM。记录不存在返回 False。

        如果需要"禁用而非删除"的语义，直接 update(oid, {"enabled": False})。
        """
        with self._lock, self._conn() as conn:
            cur = conn.execute(f"DELETE FROM {self.table} WHERE id = ?", (oid,))
            conn.commit()
            return cur.rowcount > 0

    def clear(self) -> None:
        """清空整张表，主要给 notify_log / 测试用。"""
        with self._lock, self._conn() as conn:
            conn.execute(f"DELETE FROM {self.table}")
            conn.commit()

    def seed(self, items: list[dict]) -> None:
        """种子数据：仅在表为空时写入。"""
        with self._conn() as conn:
            (n,) = conn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()
        if n > 0:
            return
        for raw in items:
            self.create(raw)
