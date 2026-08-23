#!/usr/bin/env python3
"""AppStore Discover 推荐包发布脚本。

用法：
  python3 build_release.py --repo owner/appstore-discover [--dry-run]

维护者改动内容后由 CI 调用，立即生成并发布三件套：
  full.zip         index.json（卡片数组，按 cards/ 文件名序号）+ assets/（articles/ + covers/）
  incremental.zip  结构化差异（新增/变更卡片完整条目 + 移除 slug）
  patch.json       解析清单（base/target/algorithm/校验和）
客户端 SyncEngine 以同一套机制处理 AppIndex 与 Discover 两个通道。
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PATCH_ALGO = "structured-json-v1"
CARDS_DIR = "cards"
ARTICLES_DIR = "articles"
COVERS_DIR = "covers"
TOKEN_ENV = "GH_TOKEN"


def gh_api(path, method="GET", body=None, token=None):
    import urllib.request
    import urllib.error
    token = token or os.environ.get(TOKEN_ENV)
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if "json" in resp.headers.get("Content-Type", "") else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_cards():
    """cards/*.json 按文件名排序 → 卡片列表；校验引用完整性。"""
    cards = []
    if not os.path.isdir(CARDS_DIR):
        return cards
    for name in sorted(os.listdir(CARDS_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(CARDS_DIR, name)
        card = load_json(path)
        if "slug" not in card:
            print(f"[warn] {name} 缺 slug 字段，跳过")
            continue
        if card.get("type") == "article":
            art = card.get("article")
            if art and not os.path.isfile(os.path.join(ARTICLES_DIR, art)):
                print(f"[warn] {name} 引用文章 {art} 不存在")
        bg = card.get("background") or {}
        cover = bg.get("cover")
        if cover and not os.path.isfile(os.path.join(COVERS_DIR, cover)):
            print(f"[warn] {name} 引用封面 {cover} 不存在")
        cards.append(card)
    return cards


def collect_assets():
    """assets/ 内容：{相对路径: bytes}。"""
    files = {}
    for base, prefix in ((ARTICLES_DIR, "articles/"), (COVERS_DIR, "covers/")):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    files[prefix + name] = f.read()
    return files


def pack_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            z.writestr(name, data)
    return buf.getvalue()


def diff_cards(prev_cards, cur_cards):
    prev = {c["slug"]: c for c in prev_cards}
    cur = {c["slug"]: c for c in cur_cards}
    changed = {slug: c for slug, c in cur.items() if slug not in prev or prev[slug] != c}
    removed = [slug for slug in prev if slug not in cur]
    return changed, removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    token = os.environ.get(TOKEN_ENV, "")

    cards = read_cards()
    if not cards:
        print("[appstore] 无卡片内容，不发布")
        sys.exit(0)

    assets = collect_assets()
    index_json = json.dumps(cards, ensure_ascii=False, indent=2).encode()
    full_files = {"index.json": index_json}
    full_files.update(assets)
    full_zip = pack_zip(full_files)

    prev_cards = []
    status, releases = gh_api(f"/repos/{args.repo}/releases?per_page=10")
    if status == 200:
        for rel in releases:
            full_asset = next((a for a in rel.get("assets", []) if a["name"] == "full.zip"), None)
            if full_asset:
                import base64
                status2, data = gh_api(full_asset["url"])
                if status2 == 200 and isinstance(data, dict):
                    raw = base64.b64decode(data["content"])
                    with zipfile.ZipFile(io.BytesIO(raw)) as z:
                        prev_cards = json.loads(z.read("index.json"))
                break

    changed, removed = diff_cards(prev_cards, cards)
    if prev_cards == cards:
        print("[appstore] 内容无变化，不发布")
        sys.exit(0)

    inc_files = {"incremental.json": json.dumps(
        {"addedOrChanged": changed, "removed": removed}, ensure_ascii=False, indent=2).encode()}
    for slug in changed:
        card = changed[slug]
        if card.get("type") == "article":
            art = card.get("article")
            if art and ("articles/" + art) in assets:
                inc_files["articles/" + art] = assets["articles/" + art]
        bg = card.get("background") or {}
        cover = bg.get("cover")
        if cover and ("covers/" + cover) in assets:
            inc_files["covers/" + cover] = assets["covers/" + cover]
    inc_zip = pack_zip(inc_files)

    patch = {
        "base": None,
        "target": None,
        "algorithm": PATCH_ALGO,
        "incrementalSha256": hashlib.sha256(inc_zip).hexdigest(),
        "fullSha256": hashlib.sha256(full_zip).hexdigest(),
        "fullSize": len(full_zip),
        "cardCount": len(cards),
    }
    status, rel = gh_api(f"/repos/{args.repo}/releases/latest")
    if status == 200:
        patch["base"] = rel.get("tag_name")

    if args.dry_run:
        os.makedirs("dist", exist_ok=True)
        for name, data in [("full.zip", full_zip), ("incremental.zip", inc_zip)]:
            with open(os.path.join("dist", name), "wb") as f:
                f.write(data)
        with open("dist/patch.json", "w", encoding="utf-8") as f:
            json.dump(patch, f, ensure_ascii=False, indent=2)
        print(f"[appstore] dry-run 完成：{len(cards)} 张卡，变更 {len(changed)}，移除 {len(removed)}（见 dist/）")
        return

    ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    tag = f"discover-{ts}"
    patch["target"] = tag
    status, rel = gh_api(f"/repos/{args.repo}/releases", method="POST", body={
        "tag_name": tag, "name": f"推荐包 {ts}", "body": "推荐页内容自动发布",
        "draft": False, "prerelease": False,
    })
    if status not in (200, 201):
        print(f"[appstore] 创建 Release 失败: {status} {rel}")
        sys.exit(2)
    base = f"https://uploads.github.com/repos/{args.repo}/releases/{rel['id']}/assets"
    import urllib.request
    for fname, data in [("full.zip", full_zip), ("incremental.zip", inc_zip),
                        ("patch.json", json.dumps(patch, ensure_ascii=False).encode())]:
        req = urllib.request.Request(f"{base}?name={fname}", data=data, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/octet-stream")
        req.add_header("Accept", "application/vnd.github+json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                print(f"[appstore] 上传 {fname}: HTTP {resp.status}")
        except Exception as e:
            print(f"[appstore] 上传 {fname} 失败: {e}")
            sys.exit(2)
    print(f"[appstore] 已发布 {tag}")


if __name__ == "__main__":
    main()
