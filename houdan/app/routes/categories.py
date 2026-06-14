"""分类接口"""
from flask import Blueprint
from app.response import ok
from app.storage.repos import category_repo

bp = Blueprint("categories", __name__)


@bp.get("")
def list_categories():
    cats = category_repo.list()
    return ok([{"id": c["id"], "name": c["name"]} for c in cats])
