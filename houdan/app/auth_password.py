"""密码哈希：PBKDF2-HMAC-SHA256（Python 标准库，无外部依赖）

存储格式：`pbkdf2$<iterations>$<salt_hex>$<hash_hex>`
- 默认 200_000 轮（OWASP 2025 推荐 ≥ 600_000，本地后台够用，加大改本文件常量即可）
- 16 字节随机盐
- 32 字节派生 key
"""
from __future__ import annotations

import hashlib
import hmac
import os

_ITERATIONS = 200_000
_SALT_LEN = 16
_KEY_LEN = 32


def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    if not password or len(password) < 6:
        raise ValueError("密码至少 6 位")
    salt = os.urandom(_SALT_LEN)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=_KEY_LEN)
    return f"pbkdf2${iterations}${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    if not password or not encoded:
        return False
    try:
        algo, iterations_s, salt_hex, hash_hex = encoded.split("$")
        if algo != "pbkdf2":
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError):
        return False
