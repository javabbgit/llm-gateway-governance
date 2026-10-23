"""用 OpenAI 官方 Python SDK 经网关调用：应用只改 base_url 和 api_key。

由 p2check.py sdk 在 LiteLLM 锁定镜像里运行（镜像自带 openai 包），不在 Ubuntu 上安装任何 Python 包。
每个检查输出一行 JSON：{"status", "item", "detail"}。
"""
import json
import os
import time

import openai
from openai import OpenAI


def out(status, item, detail=""):
    print(json.dumps({"status": status, "item": item, "detail": detail}, ensure_ascii=False), flush=True)


client = OpenAI(base_url=os.environ.get("GW_URL", "http://127.0.0.1:4000/v1"), api_key=os.environ["GW_KEY"], timeout=150)
out("INFO", "openai SDK 版本", openai.__version__)

try:
    ids = [m.id for m in client.models.list()]
    out("PASS" if {"chat-default", "chat-fallback"} <= set(ids) else "FAIL", "SDK 列出模型", ", ".join(ids))
except Exception as e:  # noqa: BLE001
    out("FAIL", "SDK 列出模型", f"{type(e).__name__}: {e}")

for alias in ["chat-default", "chat-fallback"]:
    t0 = time.time()
    try:
        r = client.chat.completions.create(model=alias, messages=[{"role": "user", "content": "Reply with one word: pong"}], max_tokens=32)
        ans = (r.choices[0].message.content or "").strip()
        out("PASS" if ans else "FAIL", f"SDK 调用 {alias}", f"{time.time() - t0:.1f}s，回答：{ans[:40]}")
    except Exception as e:  # noqa: BLE001
        out("FAIL", f"SDK 调用 {alias}", f"{type(e).__name__}: {e}")

t0, n, text = time.time(), 0, ""
try:
    stream = client.chat.completions.create(model="chat-default", messages=[{"role": "user", "content": "Count from 1 to 5."}], max_tokens=64, stream=True)
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            n += 1
            text += chunk.choices[0].delta.content
    out("PASS" if n >= 2 else "FAIL", "SDK 流式 chat-default", f"{n} 个正文块，{time.time() - t0:.1f}s，内容：{' '.join(text.split())[:40]}")
except Exception as e:  # noqa: BLE001
    out("FAIL", "SDK 流式 chat-default", f"{type(e).__name__}: {e}")

try:
    client.chat.completions.create(model="no-such-model", messages=[{"role": "user", "content": "x"}], max_tokens=8)
    out("FAIL", "SDK 请求未配置的模型被拒", "竟然成功了")
except openai.APIStatusError as e:
    out("PASS", "SDK 请求未配置的模型被拒", f"HTTP {e.status_code}")
except Exception as e:  # noqa: BLE001
    out("WARN", "SDK 请求未配置的模型被拒", f"{type(e).__name__}")
