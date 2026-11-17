# -*- coding: utf-8 -*-
"""通过已登录的 Chrome（CDP）更新 Confluence 页面。

思路：浏览器里已经登录了 Confluence，直接在该页面上下文里 fetch REST 接口，
浏览器会自动带上会话 Cookie，不需要 token / 密码。

用法：
    python tools\\confluence_cdp_publish.py --page-id 104961904 --wait 1200

前提：Chrome 以 --remote-debugging-port=9222 启动（脚本 tools\\open_confluence.py 会做这件事）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

import websocket

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        msg_id = self._id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data

    def evaluate(self, expression, await_promise=True):
        data = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        })
        result = data.get("result", {})
        if "exceptionDetails" in result:
            raise RuntimeError(json.dumps(result["exceptionDetails"], ensure_ascii=False)[:800])
        return result.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def find_target(port, host_hint):
    for _ in range(10):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json" % port, timeout=5) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
            pages = [t for t in targets if t.get("type") == "page" and host_hint in (t.get("url") or "")]
            if pages:
                return pages[0]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return None


def build_js(page_id, section_html):
    section = json.dumps(section_html, ensure_ascii=True)
    return """(async () => {
  const pageId = %s;
  const section = %s;
  const opts = { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' };
  const getR = await fetch('/rest/api/content/' + pageId + '?expand=version,space,body.storage', opts);
  if (!getR.ok) { return { ok: false, step: 'get', status: getR.status, url: location.href }; }
  const page = await getR.json();
  let body = (page.body && page.body.storage && page.body.storage.value) || '';
  // Confluence 会丢掉 HTML 注释，所以用正文特征判断是不是我们写的段落：
  // 本页内容已包含“FIX 下单助手”和“一、下载”，就整段替换；否则追加到末尾。
  const ours = body.indexOf('FIX 下单助手') >= 0 && body.indexOf('一、下载') >= 0;
  if (ours) {
    body = section;
  } else {
    body = body + (body.trim() ? '<p>&nbsp;</p>' : '') + section;
  }
  const payload = {
    id: page.id,
    type: 'page',
    title: page.title,
    space: { key: page.space.key },
    version: { number: page.version.number + 1, message: '更新 FIX 下单助手下载与使用说明' },
    body: { storage: { value: body, representation: 'storage' } }
  };
  const putR = await fetch('/rest/api/content/' + pageId, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(payload)
  });
  const text = await putR.text();
  return { ok: putR.ok, status: putR.status, title: page.title,
           oldVersion: page.version.number, newVersion: page.version.number + 1,
           resp: text.slice(0, 300) };
})()""" % (json.dumps(page_id), section)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-id", default="104961904")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--host", default="10.1.2.21")
    parser.add_argument("--file", default=os.path.join(ROOT, "docs", "confluence-page.html"))
    parser.add_argument("--wait", type=int, default=900, help="等待登录的最长秒数")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print("找不到内容文件：%s" % args.file)
        return 2
    with open(args.file, "r", encoding="utf-8") as fh:
        html = fh.read()

    target = find_target(args.port, args.host)
    if not target:
        print("没有找到目标标签页，请确认 Chrome 已用 --remote-debugging-port 打开该页面。")
        return 1
    print("已连接标签页：%s" % target.get("title"))

    cdp = CDP(target["webSocketDebuggerUrl"])
    js = build_js(args.page_id, html)

    deadline = time.time() + args.wait
    last_state = None
    while time.time() < deadline:
        try:
            state = cdp.evaluate("({url: location.href, title: document.title})", await_promise=False)
        except Exception as exc:  # noqa: BLE001
            print("页面状态读取失败（可能正在跳转）：%s" % exc)
            time.sleep(3)
            continue

        url = (state or {}).get("url", "")
        title = (state or {}).get("title", "")
        if "login.action" in url:
            if last_state != "login":
                print("等待登录…（请在浏览器里完成登录）")
                last_state = "login"
            time.sleep(3)
            continue

        # 已离开登录页，尝试用页面会话调用接口
        try:
            result = cdp.evaluate(js)
        except Exception as exc:  # noqa: BLE001
            print("提交异常：%s" % exc)
            time.sleep(3)
            continue

        if isinstance(result, dict) and result.get("ok"):
            print("更新成功：%s，版本 %s → %s"
                  % (result.get("title"), result.get("oldVersion"), result.get("newVersion")))
            print("页面地址：http://%s:8090/pages/viewpage.action?pageId=%s" % (args.host, args.page_id))
            cdp.close()
            return 0

        if isinstance(result, dict) and result.get("status") in (401, 403, 404):
            if last_state != "waiting-auth":
                print("还没拿到权限（HTTP %s），继续等待登录…" % result.get("status"))
                last_state = "waiting-auth"
            time.sleep(3)
            continue

        print("提交失败：%s" % json.dumps(result, ensure_ascii=False)[:500])
        cdp.close()
        return 1

    print("等待超时（%d 秒），未完成更新。" % args.wait)
    cdp.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
