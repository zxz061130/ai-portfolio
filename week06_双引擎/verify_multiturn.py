# -*- coding: utf-8 -*-
"""verify_multiturn.py —— 作业1（多轮对话）的现场验证

分两层看，别混在一起：
    ① 机制（代码对不对）：第 2 轮真的把历史发过去了吗？/clear 真的清空了吗？
       —— 用「发出的消息条数」判定，确定性，与模型好坏无关。
    ② 质量（模型行不行）：0.5b 能不能记住 32？—— 只作观察，答偏了不怪代码。

跑法：python verify_multiturn.py                # 默认 prefer="local"
     python verify_multiturn.py --prefer api
输出：三行 TSV（给 test_paths.sh 拼表），结论打印到 stderr。
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from llm import LLM, LLMError
except Exception as exc:                       # noqa: BLE001
    sys.exit(f"导入 llm 失败：{exc}")

FACT = "请记住：我的班级有 32 个学生。"
ASK = "我们班有多少人？只回答数字。"


def shorten(text: str, width: int = 40) -> str:
    return " ".join((text or "").split())[:width]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefer", choices=("local", "api"), default="local")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    llm = LLM(local_model=args.model)

    #  spies：记录每次真正发出去的消息条数（这是「历史有没有传进去」的硬证据）
    sent: list[int] = []
    original = llm._ask_messages

    def spy(messages, prefer="local", **kw):
        sent.append(len(messages))
        return original(messages, prefer=prefer, **kw)

    llm._ask_messages = spy      # type: ignore[method-assign]

    try:
        a1 = llm.chat(FACT, prefer=args.prefer)
        m1 = dict(llm.last)
        n1 = sent[-1]
        a2 = llm.chat(ASK, prefer=args.prefer)
        m2 = dict(llm.last)
        n2 = sent[-1]
        llm.clear()
        a3 = llm.chat(ASK, prefer=args.prefer)
        m3 = dict(llm.last)
        n3 = sent[-1]
    except LLMError as exc:
        print(f"[FAIL] 多轮验证没跑起来：{exc}", file=sys.stderr)
        return 1

    print("\t".join(["多轮第1轮（说明事实）", f"{n1} 条消息", m1.get("engine", "-"),
                     f"{m1.get('seconds', 0):.2f}", shorten(a1)]))
    print("\t".join(["多轮第2轮（追问）", f"{n2} 条消息", m2.get("engine", "-"),
                     f"{m2.get('seconds', 0):.2f}", shorten(a2)]))
    print("\t".join(["clear() 后再问", f"{n3} 条消息", m3.get("engine", "-"),
                     f"{m3.get('seconds', 0):.2f}", shorten(a3)]))

    ok_history = (n1, n2, n3) == (1, 3, 1)
    print(f"[{'PASS' if ok_history else 'FAIL'}] 机制：发出消息条数 1→3→1（历史被带上，clear 后清空）",
          file=sys.stderr)
    recalled = "32" in a2
    print(f"[{'PASS' if recalled else 'WARN'}] 模型质量：第2轮回答里"
          f"{'有' if recalled else '没有'}“32”（0.5b 常答偏，换 4b 更稳；这不影响机制判定）",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
