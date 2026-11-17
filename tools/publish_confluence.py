# -*- coding: utf-8 -*-
"""把 docs/confluence-page.html 发布到 Confluence 页面。

前提：目标页面已存在，你拥有编辑权限。

用法一（推荐，Confluence 7.9+ 的个人访问令牌）：
    set CONFLUENCE_TOKEN=你的token
    python tools\\publish_confluence.py --page-id 104961904

用法二（用户名 + 密码）：
    python tools\\publish_confluence.py --page-id 104961904 --user 你的账号 --password 你的密码

常用参数：
    --base     Confluence 地址，默认 http://10.1.2.21:8090
    --file     要写入的 HTML（Confluence storage 格式），默认 docs/confluence-page.html
    --dry-run  只读取当前版本，不提交
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def request(method, url, headers, data=None):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def main():
    parser = argparse.ArgumentParser(description="发布页面到 Confluence")
    parser.add_argument("--page-id", required=True, help="Confluence 页面 ID，例如 104961904")
    parser.add_argument("--base", default="http://10.1.2.21:8090", help="Confluence 地址")
    parser.add_argument("--file", default=os.path.join("docs", "confluence-page.html"), help="HTML 文件")
    parser.add_argument("--token", default=os.environ.get("CONFLUENCE_TOKEN", ""), help="个人访问令牌")
    parser.add_argument("--user", default="", help="用户名")
    parser.add_argument("--password", default="", help="密码")
    parser.add_argument("--dry-run", action="store_true", help="只读取，不提交")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    page_id = args.page_id.strip()
    if not os.path.isfile(args.file):
        print("找不到文件：%s" % args.file)
        return 2
    with open(args.file, "r", encoding="utf-8") as fh:
        html = fh.read()

    headers = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"}
    if args.token:
        headers["Authorization"] = "Bearer %s" % args.token
    elif args.user and args.password:
        raw = ("%s:%s" % (args.user, args.password)).encode("utf-8")
        headers["Authorization"] = "Basic %s" % base64.b64encode(raw).decode("ascii")
    else:
        print("缺少凭据：请设置 CONFLUENCE_TOKEN，或提供 --user/--password。")
        return 2

    content_url = "%s/rest/api/content/%s?expand=version,space" % (base, urllib.parse.quote(page_id))
    status, text = request("GET", content_url, headers)
    if status != 200:
        print("读取页面失败：HTTP %s" % status)
        if status in (401, 403):
            print("认证失败或没有权限：检查 token 是否有效、账号是否有该页面编辑权限。")
        print(text[:500])
        return 1

    page = json.loads(text)
    title = page.get("title", "")
    space_key = (page.get("space") or {}).get("key", "")
    version = (page.get("version") or {}).get("number", 0)
    print("页面：%s（space=%s，当前版本 %s）" % (title, space_key, version))

    if args.dry_run:
        print("dry-run：未提交。待写入 %d 字节。" % len(html))
        return 0

    payload = {
        "id": page_id,
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "version": {"number": int(version) + 1, "message": "更新下载链接与使用说明"},
        "body": {"storage": {"value": html, "representation": "storage"}},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status, text = request("PUT", content_url.split("?")[0], headers, data)
    if status not in (200, 201):
        print("提交失败：HTTP %s" % status)
        print(text[:800])
        return 1

    result = json.loads(text)
    new_version = (result.get("version") or {}).get("number")
    print("提交成功，新版本 %s" % new_version)
    print("页面地址：%s/pages/viewpage.action?pageId=%s" % (base, page_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
