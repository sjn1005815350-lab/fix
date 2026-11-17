# -*- coding: utf-8 -*-
"""端到端自测：在本机起一个极简 FIX 网关，验证连接/登录/下单/回报解析。

只连接 127.0.0.1，不会触碰真实交易网关。
"""
import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

SOH = "\x01"
BEGIN = "FIX.4.2"


def build_fix(msg_type, fields, seq, sender="TESTSRV", target="TESTCLI"):
    header = [
        "35=%s" % msg_type,
        "34=%d" % seq,
        "49=%s" % sender,
        "56=%s" % target,
        "52=%s" % time.strftime("%Y%m%d-%H:%M:%S", time.gmtime()),
    ]
    body = SOH.join(header + list(fields))
    raw = "8=%s" % BEGIN + SOH + "9=%d" % (len(body) + 1) + SOH + body + SOH
    checksum = sum(raw.encode("latin-1")) % 256
    return (raw + "10=%03d" % checksum + SOH).encode("latin-1")


def field_of(text, tag):
    for part in text.split("|"):
        if part.startswith(tag + "="):
            return part.split("=", 1)[1]
    return ""


class MockGateway(threading.Thread):
    def __init__(self):
        super(MockGateway, self).__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(2)
        self.messages = []
        self.ready = threading.Event()
        self.sent_exec = threading.Event()

    def run(self):
        self.ready.set()
        conn, _addr = self.sock.accept()
        buffer = b""
        seq = 1
        while True:
            try:
                data = conn.recv(65536)
            except OSError:
                break
            if not data:
                break
            buffer += data
            while True:
                index = buffer.find(b"10=")
                if index < 0:
                    break
                end = buffer.find(b"\x01", index)
                if end < 0:
                    break
                raw = buffer[: end + 1]
                buffer = buffer[end + 1:]
                text = raw.decode("latin-1").replace(SOH, "|")
                self.messages.append(text)
                print("  [server] <-", text)
                msg_type = field_of(text, "35")
                if msg_type == "A":
                    reply = build_fix("A", ["98=0", "108=30"], seq)
                    print("  [server] ->", reply.decode("latin-1").replace(SOH, "|"))
                    conn.sendall(reply)
                    seq += 1
                elif msg_type == "D":
                    clordid = field_of(text, "11") or "UNKNOWN"
                    fields = [
                        "37=GATEWAY-0001", "11=%s" % clordid, "17=EXEC-0001", "20=0",
                        "150=0", "39=0", "55=%s" % (field_of(text, "55") or "600000"),
                        "54=%s" % (field_of(text, "54") or "1"), "38=100",
                        "44=10.1", "6=0", "14=0", "151=100", "58=New",
                    ]
                    conn.sendall(build_fix("8", fields, seq))
                    seq += 1
                    self.sent_exec.set()
        conn.close()


def main():
    gateway = MockGateway()
    gateway.start()
    gateway.ready.wait(2)

    events = []
    from fixgui.engine import FixEngine

    engine = FixEngine(events.append)
    profile = {
        "name": "本地模拟",
        "SocketConnectHost": "127.0.0.1",
        "SocketConnectPort": str(gateway.port),
        "SenderCompID": "TESTCLI",
        "TargetCompID": "TESTSRV",
        "SenderSubID": "P0001",
        "BeginString": BEGIN,
        "DefaultApplVerID": BEGIN,
        "HeartBtInt": "30",
        "ReconnectInterval": "5",
        "LogonTimeout": "10",
        "ResetOnLogon": True,
        "StartTime": "00:00:00",
        "EndTime": "23:59:59",
        "DataDictionary": "./dict/FIX42-server.xml",
        "FileStorePath": "./store/mock/",
        "FileLogPath": "./logs/fix/",
        "UseFileLog": True,
        "ClOrdIdPrefix": "T",
        "ClOrdIdMode": "时间戳",
        "ClOrdIdStart": "1",
    }
    engine.start(profile)
    deadline = time.time() + 15
    while time.time() < deadline and not engine.logged_on():
        time.sleep(0.2)
    if not engine.logged_on():
        print("FAIL 未登录")
        for event in events:
            print("  event:", event)
        engine.stop()
        return 1
    print("OK 登录成功:", engine.session_text())

    order = {
        "clordid": "T" + str(int(time.time() * 1000)),
        "account": "P0001", "client_id": "0001", "symbol": "600000", "exchange": "SH",
        "security_type": "STOCK", "side": "buy", "ordtype": "Limit", "qty": "100",
        "price": "10.10", "tif": "Day", "handl_inst": "DMA", "position_effect": "default",
        "strategy": "", "currency": "CNY", "remark": "test", "extras": [("11000", "3")],
    }
    engine.send_new_order(order)
    gateway.sent_exec.wait(5)
    time.sleep(1.0)
    engine.stop()
    time.sleep(0.5)

    execs = [event for event in events if event.get("kind") == "exec"]
    print("OK 网关收到报文 %d 条，客户端收到回报 %d 条" % (len(gateway.messages), len(execs)))
    for text in gateway.messages:
        print("  gateway <-", text[:160])
    for event in execs:
        data = event["data"]
        print("  client  -> 回报", data.get("clordid"), data.get("status"),
              "cum", data.get("cum_qty"), "leaves", data.get("leaves_qty"))
    if not execs:
        print("FAIL 未解析到成交回报")
        return 1
    print("OK 端到端自测通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
