# -*- coding: utf-8 -*-
"""local_chat.py —— 用 Python 直连本机 Ollama（第5周讲义第12页的代码，可直接运行）

    python local_chat.py "给《愚公移山》出一道 HSK4 阅读题"
    python local_chat.py --model qwen3:4b "解释把字句的构成条件"
    python local_chat.py --host 127.0.0.1:11434 --timeout 120 "..."
    python local_chat.py            # 交互输入一行问题

为什么走 http 直连而不是装 ollama 的 SDK：
    不依赖 SDK 版本，/api/chat 是稳定接口；下周 llm.py 双引擎只是换层皮。
两个 Windows 必踩的坑（讲义第12、13页）：
    1) trust_env=False —— 机房/校园网配了代理，requests 会把 localhost 也送去代理；
    2) timeout 给足 120 秒 —— 首次调用要把模型装载进内存，给太短会误判"服务挂了"。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

try:
    import requests
except ModuleNotFoundError:
    sys.exit("缺少 requests：python -m pip install requests")

DEFAULT_MODEL = "qwen2.5:0.5b"
DEFAULT_HOST = "127.0.0.1:11434"


def _force_utf8_stdout() -> None:
    """Windows + Git Bash：Python 默认按 GBK 输出，中文到 mintty 里就是乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if (stream.encoding or "").lower() not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
        except Exception:
            pass


_force_utf8_stdout()


def ask(question: str, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST,
        timeout: float = 120.0, temperature: float = 0.7) -> dict:
    session = requests.Session()
    session.trust_env = False                 # ← 关键：别让系统代理拦掉 127.0.0.1
    started = time.perf_counter()
    resp = session.post(
        f"http://{host}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": question}],
            "stream": False,                  # True = 逐字流出，第15周做界面时再开
            "options": {"temperature": temperature},
        },
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started
    resp.raise_for_status()
    data = resp.json()
    data["_wall_seconds"] = elapsed
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="直连本机 Ollama 问一句")
    parser.add_argument("question", nargs="*", help="要问的问题（不加引号也行）")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--host", default=DEFAULT_HOST, help="默认 127.0.0.1:11434")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--temperature", type=float, default=0.7)
    args = parser.parse_args()

    question = " ".join(args.question).strip() or input("问题> ").strip()
    if not question:
        print('用法：python local_chat.py "你的问题"', file=sys.stderr)
        return 2

    try:
        data = ask(question, args.model, args.host, args.timeout, args.temperature)
    except requests.exceptions.ConnectionError:
        print(f"错误：连不上 http://{args.host}\n"
              "      1) 任务栏有羊驼图标吗？没有 → 另开终端跑 ollama serve\n"
              "      2) 端口换过？用 --host 127.0.0.1:11434\n"
              "      3) 检查 base_url 里别写成 localhost（IPv6 时可能解析到 ::1）", file=sys.stderr)
        return 1
    except requests.exceptions.Timeout:
        print(f"错误：{args.timeout:g} 秒内没返回。首次装载慢，调大 --timeout 180 再试。",
              file=sys.stderr)
        return 1
    except requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("error", "")
        except Exception:
            detail = getattr(exc.response, "text", "")[:200]
        print(f"错误：{exc}\n      服务端说：{detail}\n"
              "      模型没拉？ollama pull " + args.model, file=sys.stderr)
        return 1

    if "error" in data:
        print(f"错误：{data['error']}", file=sys.stderr)
        return 1

    print(data.get("message", {}).get("content", "").strip())

    count = data.get("eval_count") or 0
    gen = (data.get("eval_duration") or 0) / 1e9
    load_s = (data.get("load_duration") or 0) / 1e9
    print("-" * 62)
    print(f"模型 {data.get('model', args.model)} | 输出 {count} token | 生成 {gen:.1f}s "
          f"| 约 {count / gen if gen else 0:.0f} tok/s")
    print(f"首次装载 {load_s:.1f}s | 端到端 {data['_wall_seconds']:.1f}s "
          f"| 输入 {data.get('prompt_eval_count', 0)} token")
    return 0


if __name__ == "__main__":
    sys.exit(main())
