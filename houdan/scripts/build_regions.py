#!/usr/bin/env python3
"""生成 data/regions.json —— 省市区三级行政区划码表，供小程序地址选择器使用。

用法（在 houdan/ 目录下执行）：
    python3 scripts/build_regions.py                 # 拉最新数据重新生成
    python3 scripts/build_regions.py --version 2.7.0 # 指定 china-division 版本
    python3 scripts/build_regions.py --check-only    # 只校验现有 regions.json，不重新生成

数据源：npm 包 china-division（MIT），其原始数据来自国家统计局
「统计用区划代码和城乡划分代码」。区划每年都有调整（撤县设区、合并改名），
上游包更新后重跑本脚本即可；生成结果会写入 version，小程序据此判断缓存是否过期。

只依赖标准库，不需要装 npm / node。
"""
from __future__ import annotations

import argparse
import io
import json
import tarfile
import urllib.request
from datetime import date
from pathlib import Path

REGISTRY = "https://registry.npmjs.org/china-division"
OUT = Path(__file__).resolve().parent.parent / "data" / "regions.json"

# 直辖市：统计局层级里它们下面挂的是「市辖区」「县」这种占位市级，
# 直接展示成「北京市 > 市辖区 > 朝阳区」很怪。统一压成「北京市 > 北京市 > 朝阳区」，
# 与支付宝 my.getAddress 返回的 prov/city/area 口径一致。
MUNICIPALITIES = {"11": "北京市", "12": "天津市", "31": "上海市", "50": "重庆市"}
MUNICIPALITY_PLACEHOLDERS = {"市辖区", "县"}

# 省直管县级行政区划：市级码以 90 结尾的占位层（河南 4190 / 湖北 4290 /
# 海南 4690 / 新疆 6590）。其下的仙桃、潜江、天门等本身就是县级市，没有区县层级，
# 把它们提升为市级、区级留空——这也正是 my.getAddress 对这类地址的返回形态。
PROVINCE_DIRECT_PLACEHOLDERS = {"省直辖县级行政区划", "自治区直辖县级行政区划"}

EXPECTED_PROVINCES = 31  # 大陆 31 个省级行政区；港澳台上游是独立文件且无区划码，不并入

# 不设区的地级市（东莞/中山/儋州/嘉峪关）下面直接挂镇、街道，统计局给的是 9 位码。
# 这批照原样保留作为区级——快递面单也需要精确到镇街，淘宝这类 app 同样是这么给的。
TOWN_LEVEL_CODE_LEN = 9


# ---------------------------------------------------------------- fetch


def fetch_pca(version: str | None) -> tuple[list, str]:
    """下载 china-division 包，返回 (pca-code.json 内容, 实际版本号)"""
    with urllib.request.urlopen(REGISTRY, timeout=60) as r:
        meta = json.load(r)
    version = version or meta["dist-tags"]["latest"]
    if version not in meta["versions"]:
        raise SystemExit(f"npm 上没有 china-division@{version}")
    tarball = meta["versions"][version]["dist"]["tarball"]
    print(f"下载 china-division@{version} …")
    with urllib.request.urlopen(tarball, timeout=300) as r:
        blob = r.read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        f = tf.extractfile("package/dist/pca-code.json")
        if f is None:
            raise SystemExit("包内缺少 dist/pca-code.json，上游结构可能变了")
        return json.load(f), version


# ---------------------------------------------------------------- normalize


def pad(code: str) -> str:
    """省 2 位 / 市 4 位 → 补齐成 6 位国标码"""
    return code.ljust(6, "0")


def normalize(raw: list) -> list:
    out = []
    for prov in raw:
        p_code = pad(prov["code"])
        cities: list[dict] = []
        merged_municipality: dict | None = None

        for city in prov["children"]:
            name, code = city["name"], city["code"]
            kids = city.get("children") or []

            if name in MUNICIPALITY_PLACEHOLDERS:
                if prov["code"] not in MUNICIPALITIES:
                    raise SystemExit(f"非直辖市 {prov['name']} 下出现占位市级「{name}」，上游数据变了")
                # 重庆有「市辖区」+「县」两个占位层，合并成一个「重庆市」
                if merged_municipality is None:
                    merged_municipality = {
                        "code": pad(prov["code"] + "01"),
                        "name": MUNICIPALITIES[prov["code"]],
                        "subList": [],
                    }
                    cities.append(merged_municipality)
                merged_municipality["subList"].extend(
                    {"code": k["code"], "name": k["name"]} for k in kids
                )
                continue

            if name in PROVINCE_DIRECT_PLACEHOLDERS:
                if not code.endswith("90"):
                    raise SystemExit(f"{prov['name']} 的「{name}」码 {code} 不以 90 结尾，上游数据变了")
                # 县级市提升为市级，不带 subList（区级为空）
                for k in kids:
                    cities.append({"code": k["code"], "name": k["name"]})
                continue

            cities.append({
                "code": pad(code),
                "name": name,
                "subList": [{"code": k["code"], "name": k["name"]} for k in kids],
            })

        out.append({"code": p_code, "name": prov["name"], "subList": cities})
    return out


# ---------------------------------------------------------------- validate


def validate(tree: list) -> dict:
    """校验通过返回统计信息；不通过直接抛错退出。"""
    errors: list[str] = []
    codes: dict[str, str] = {}
    town_level: list[str] = []
    n_city = n_dist = 0

    def check_code(code: str, name: str, where: str, allow_town: bool = False) -> None:
        ok_len = (6, TOWN_LEVEL_CODE_LEN) if allow_town else (6,)
        if not (isinstance(code, str) and len(code) in ok_len and code.isdigit()):
            errors.append(f"{where} 码不合法: {code!r} ({name})")
        elif code in codes:
            errors.append(f"码重复: {code} 同时属于「{codes[code]}」和「{name}」")
        else:
            codes[code] = name

    if len(tree) != EXPECTED_PROVINCES:
        errors.append(f"省级数量 {len(tree)} != 预期 {EXPECTED_PROVINCES}")

    bad_names = MUNICIPALITY_PLACEHOLDERS | PROVINCE_DIRECT_PLACEHOLDERS
    for prov in tree:
        check_code(prov["code"], prov["name"], "省")
        if not prov["subList"]:
            errors.append(f"省「{prov['name']}」下没有市级")
        for city in prov["subList"]:
            n_city += 1
            check_code(city["code"], city["name"], "市")
            if city["name"] in bad_names:
                errors.append(f"占位层未清理: {prov['name']} > {city['name']}")
            if city["code"][:2] != prov["code"][:2]:
                errors.append(f"市码前缀不匹配: {prov['name']}({prov['code']}) > {city['name']}({city['code']})")
            sub = city.get("subList") or []
            if any(len(d.get("code") or "") == TOWN_LEVEL_CODE_LEN for d in sub):
                town_level.append(f"{prov['name']} > {city['name']}（{len(sub)} 个镇街）")
            for dist in sub:
                n_dist += 1
                check_code(dist["code"], dist["name"], "区", allow_town=True)
                if dist["code"][:2] != prov["code"][:2]:
                    errors.append(f"区码省前缀不匹配: {prov['name']} > {city['name']} > {dist['name']}({dist['code']})")
                # 区码前 4 位应与市码一致；重庆「县」被并进「重庆市」，这批是已知例外
                if dist["code"][:4] != city["code"][:4] and prov["code"][:2] != "50":
                    errors.append(f"区码市前缀不匹配: {city['name']}({city['code']}) > {dist['name']}({dist['code']})")

    # 抽查几个最容易被规范化搞坏的样本
    def find(path: list[str]) -> dict | None:
        cur, nodes = None, tree
        for seg in path:
            cur = next((n for n in nodes if n["name"] == seg), None)
            if cur is None:
                return None
            nodes = cur.get("subList") or []
        return cur

    hubei_xiantao = find(["湖北省", "仙桃市"])
    if hubei_xiantao is None:
        errors.append("抽查失败: 湖北省 > 仙桃市 不存在（省直管县级市未提升为市级）")
    elif hubei_xiantao.get("subList"):
        errors.append("抽查失败: 仙桃市 不应有区级下级")
    elif hubei_xiantao["code"] != "429004":
        errors.append(f"抽查失败: 仙桃市码应为 429004，实际 {hubei_xiantao['code']}")

    for path in (["北京市", "北京市", "朝阳区"], ["上海市", "上海市", "浦东新区"],
                 ["重庆市", "重庆市", "渝中区"], ["重庆市", "重庆市", "云阳县"],
                 ["海南省", "琼海市"], ["广东省", "深圳市", "南山区"]):
        if find(path) is None:
            errors.append("抽查失败: " + " > ".join(path) + " 不存在")

    if not 2500 <= n_dist <= 3200:
        errors.append(f"区县总数 {n_dist} 超出合理区间 2500~3200")

    if errors:
        print(f"\n校验未通过，{len(errors)} 个问题：")
        for e in errors[:40]:
            print("  -", e)
        raise SystemExit(1)

    if town_level:
        print("不设区的地级市（区级位置是镇/街道，属正常）：")
        for t in town_level:
            print("  -", t)

    return {"province": len(tree), "city": n_city, "district": n_dist}


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="china-division 版本，默认取 npm latest")
    ap.add_argument("--check-only", action="store_true", help="只校验现有 regions.json")
    args = ap.parse_args()

    if args.check_only:
        if not OUT.exists():
            raise SystemExit(f"{OUT} 不存在，先不带 --check-only 跑一次")
        doc = json.loads(OUT.read_text("utf-8"))
        stat = validate(doc["list"])
        print(f"校验通过 {OUT.name}（version={doc.get('version')}）：{stat}")
        return

    raw, version = fetch_pca(args.version)
    tree = normalize(raw)
    stat = validate(tree)

    doc = {
        "version": f"{version}+{date.today():%Y%m%d}",
        "source": f"npm china-division@{version}（原始数据：国家统计局统计用区划代码）",
        "generated_at": f"{date.today():%Y-%m-%d}",
        "note": "港澳台未包含；直辖市压成「省=市」两同名层；省直管县级市（仙桃/潜江/天门等）区级为空",
        "count": stat,
        "list": tree,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"已写入 {OUT}（{OUT.stat().st_size / 1024:.0f} KB）：{stat}")
    print(f"version = {doc['version']}")


if __name__ == "__main__":
    main()
