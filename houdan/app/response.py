"""统一响应封装，独立模块以避免循环依赖"""
from flask import jsonify


def ok(data=None, msg="ok"):
    return jsonify(code=0, msg=msg, data=data)


def fail(code=1, msg="error", data=None):
    return jsonify(code=code, msg=msg, data=data)
