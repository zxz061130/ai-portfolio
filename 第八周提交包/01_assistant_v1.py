# -*- coding: utf-8 -*-
"""assistant_v1.py —— W8 阶段项目一：学科智能问答助手 v1.0（粘合层）

三块积木，一条主线：
    W2 提示词库   prompt-library/（身份 + 对象 + 要求，抽成 SYSTEM_HINT）
    W6 双引擎     week06_双引擎/llm.py      —— LLM().ask(prompt, prefer="local"/"api")
    W7 知识库     week07_RAG/rag_qa.py     —— RAG().retrieve() + build_prompt()

本文件只做「接线」和「开关注入」，不重新实现任何引擎：
    use_rag=True   → 先检索、把资料拼进提示词，再交给 llm.ask()   （基于资料的问答）
    use_rag=False  → 只发 SYSTEM_HINT + 问题                      （纯对话）

一句话调用：
    from assistant_v1 import answer
    print(answer("HSK 4 级累计词汇量是多少？")["answer"])

命令行（Windows Git Bash，先 cd 到仓库根目录）：
    python week08_assistant_v1/assistant_v1.py "HSK 4 级累计词汇量是多少？"
    python week08_assistant_v1/assistant_v1.py "HSK 4 级累计词汇量是多少？" --no-rag   # 关掉 RAG 对照
    python week08_assistant_v1/assistant_v1.py "HSK 4 级累计词汇量是多少？" --prefer api
    python week08_assistant_v1/assistant_v1.py --demo                 # 三问三答（词库/数字/引证）
    python week08_assistant_v1/assistant_v1.py --demo --out answer_log.md

设计纪律（沿用 W6/W7，第 16 页那五个卡点都在这里兜住）：
    · 异常不吞：任何一个问题报错都打印「运行失败：原因」，下一个问题照跑，
      整个演示不因为一条挂掉；退出码用求和的方式回报（0 = 全部成功）。
    · 开关注入而不是复制代码：use_rag 只决定「拼不拼资料」，检索和生成还是 W7/W6 的人。
    · 模块路径固定三行：weekpath 把 week* 目录都加进 sys.path，
      所以 `from llm import LLM` 在仓库任何子目录下都不会 ModuleNotFoundError。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# ---------------------------------------------------------------- 跨周导入
# 讲义固定三行（不用相对导入，也不用 cd 到某个周目录）：W6/W7 的人本来就在别的目录。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import weekpath                      # noqa: E402
weekpath.load_env()

from llm import LLM                  # noqa: E402  W6 双引擎（prefer 切路 + 双向回退）
import rag_qa                        # noqa: E402  W7 检索与提示词（retrieve / build_prompt）

# ---------------------------------------------------------------- W2：身份
# 来源：prompt-library/ 六份模板的共同骨架「角色 + 对象 + 要求」。
# 一句话定三件事：我是谁（国际中文教师的教学助手）、给谁用（HSK 3–4 学习者）、
# 输出要求（先查再答、标出处、资料里没有就说没有）。换学科只改这一行。
SYSTEM_HINT = (
    "你是国际中文教学助手，面向 HSK 3–4 学习者与任课教师；"
    "回答先给结论再给依据，凡引用资料必须标出《文件名》第N段，"
    "资料里没有的内容直接说「资料中未提及」，不要猜、不要编。"
)

# 三问三答的题面（讲义第 15 页：词库类 / 数字指标 / 活动设计，各覆盖一块积木）
DEMO_QUESTIONS = [
    ("词库类", "把字句的教学难点有哪些？该怎么给 HSK 3 级学生讲？"),
    ("数字指标", "HSK 4 级累计需要掌握多少词汇、多少汉字？"),
    ("引证类", "《愚公移山》可以设计什么课堂活动？"),
]


# ---------------------------------------------------------------- 接线：检索器
class Retriever:
    """把 W7 的 RAG 包成一个只有 retrieve() 的薄壳（库里已经建好的话是秒开）。

    不在这里 import langchain / chromadb：重活都在 rag_qa 里，本层只管
    「问一句 → 拿回 3 段」，这样换向量库、换嵌入都不用到助手层来改。
    """

    def __init__(self, k: int = 3, embed: str = "auto", rebuild: bool = False):
        self.k = k
        self.rag = rag_qa.RAG(k=k, embed=embed, rebuild=rebuild)

    def retrieve(self, question: str):
        return self.rag.retrieve(question)

    def remember(self, question: str, answer: str) -> None:
        """把这一问一答塞回 W7 的 history：追问「那五级呢？」时检索词才带得上上一问。"""
        self.rag.history.append({"问": question, "答": answer})
        self.rag.history = self.rag.history[-self.rag.keep_turns:]


# ---------------------------------------------------------------- 唯一粘合层
def answer(question: str, use_rag: bool = True, prefer: str = "local",
           retriever: Retriever | None = None, llm: LLM | None = None,
           k: int = 3, temperature: float = 0.2, max_tokens: int = 600,
           remember: bool = False) -> dict:
    """一问一答：检索（可选）→ 拼提示词 → 交给 W6 生成。

    返回 dict，字段就是 answer_log.md 每一列要填的东西：
        question / answer / use_rag / prefer / engine / fallback / seconds
        docs（检索到的块）/ citations（出处在不在本次检索里）/ unverified（编造的数字）
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("问题为空：至少给一句要问的话")

    llm = llm or LLM()
    started = time.perf_counter()

    docs, ctx = [], ""
    if use_rag:
        retriever = retriever or Retriever(k=k)
        docs = retriever.retrieve(question)
        ctx = rag_qa.format_context(docs) if docs else ""
        prompt = SYSTEM_HINT + "\n\n" + rag_qa.build_prompt(question, ctx)
    else:
        prompt = SYSTEM_HINT + "\n\n" + question

    text = llm.ask(prompt, prefer=prefer, temperature=temperature, max_tokens=max_tokens)

    # 两把机器尺子（W7 的进阶件）：出处落在本次检索里吗？数字在资料里对得上吗？
    good, bad = rag_qa.verify_citations(text, docs) if use_rag else ([], [])
    result = {
        "question": question,
        "answer": text,
        "use_rag": use_rag,
        "prefer": prefer,
        "engine": llm.last.get("engine", "-"),
        "fallback": bool(llm.last.get("fallback")),
        "seconds": llm.last.get("seconds", time.perf_counter() - started),
        "docs": docs,
        "citations": (good, bad),
        "unverified": rag_qa.check_numbers(text, ctx) if use_rag else [],
        "prompt": prompt,
    }
    if remember and use_rag and retriever is not None:
        retriever.remember(question, text)      # 只给「连续追问」用：下一句检索时会带上这一问
    return result


# ---------------------------------------------------------------- 打印
def _cite_line(result: dict) -> str:
    good, bad = result["citations"]
    seen, uniq = set(), []
    for f, n in good:                      # 同一段被引用多次只报一次，读起来才像出处而不是复读
        if (f, n) not in seen:
            seen.add((f, n))
            uniq.append((f, n))
    parts = []
    if uniq:
        parts.append("、".join(f"《{f}》第{n}段" for f, n in uniq))
    if bad:
        parts.append("可疑：" + "、".join(f"《{f}》第{n}段" for f, n in bad))
    return "；".join(parts) if parts else "（本次答案未标出处，或资料里没有依据）"


def show(result: dict, show_context: bool = False) -> None:
    mode = "RAG（先查再答）" if result["use_rag"] else "纯对话（不给资料）"
    print("=" * 72)
    print(f"问：{result['question']}")
    print(f"模式：{mode} ｜ 引擎：{result['engine']} ｜ prefer={result['prefer']}"
          f" ｜ 回退：{'是' if result['fallback'] else '否'} ｜ {result['seconds']:.2f}s")
    if result["use_rag"]:
        files = "、".join(f"《{d.metadata['文件']}》第{d.metadata['段号']}段"
                         for d in result["docs"])
        print(f"检索：命中 {len(result['docs'])} 段 —— {files or '（库是空的）'}")
    print(f"答：{result['answer']}")
    if result["use_rag"]:
        print(f"出处：{_cite_line(result)}")
        print("[数字校验] " + ("✓ 答案里的数字都在检索到的资料里"
                              if not result["unverified"]
                              else "✗ 资料里找不到：" + "、".join(result["unverified"])))
    if show_context:
        print("-" * 72)
        print(rag_qa.format_context(result["docs"]))
    print()


def _markdown_block(index: int, tag: str, result: dict) -> str:
    """answer_log.md 的每一条记录：题面 + 四列 + 一段原文（截断 800 字）。"""
    mode = "RAG" if result["use_rag"] else "纯对话"
    text = result["answer"].strip()
    if len(text) > 800:
        text = text[:800].rstrip() + "……（原文较长，此处截断）"
    lines = [
        f"### Q{index}（{tag}）{result['question']}",
        "",
        f"- 模式：`use_rag={result['use_rag']}`（{mode}）｜ prefer=`{result['prefer']}`",
        f"- 引擎：`{result['engine']}`｜ 回退：{'是' if result['fallback'] else '否'}"
        f"｜ 耗时：{result['seconds']:.2f}s",
    ]
    if result["use_rag"]:
        files = "、".join(f"《{d.metadata['文件']}》第{d.metadata['段号']}段"
                         for d in result["docs"])
        lines.append(f"- 检索：{files or '（无）'}")
        lines.append(f"- 引据：{_cite_line(result)}")
        lines.append("- 数字校验：" + ("✓ 通过" if not result["unverified"]
                                    else "✗ 可疑：" + "、".join(result["unverified"])))
    lines += ["", "```text", text, "```", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- 演示
def run_demo(prefer: str, k: int, out: str | None, contrast: bool = True) -> int:
    """三问三答，外加一次「开/关 RAG」对照（讲义第 9 页的进阶项）。

    任何一个问题报错都不打断演示：打印「运行失败：原因」后继续下一题，
    最后把失败条数作为退出码的提示（0 = 三题全过）。
    """
    failures = 0
    blocks = []
    retriever = None
    llm = LLM()
    try:
        retriever = Retriever(k=k)
        retriever.rag.store()          # 先建库/预热，把「库没建好」的错提前暴露
    except Exception as exc:           # noqa: BLE001
        print(f"[提示] 知识库预热失败，RAG 题会逐条报错：{exc}")

    for i, (tag, q) in enumerate(DEMO_QUESTIONS, 1):
        try:
            if retriever is not None:
                retriever.rag.clear()   # 三道题各自独立：带上上一题会让检索词被旧问题污染
            result = answer(q, use_rag=True, prefer=prefer, retriever=retriever, llm=llm, k=k)
            show(result)
            blocks.append(_markdown_block(i, tag, result))
        except Exception as exc:       # noqa: BLE001  —— 不吞：打印原因，继续下一题
            failures += 1
            print(f"运行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            print(f"（Q{i} 未完成，继续下一题）", file=sys.stderr)

    if contrast:
        tag, q = DEMO_QUESTIONS[1]                     # 用「数字指标」这道题做对照
        for use_rag in (True, False):
            label = "对照·开 RAG" if use_rag else "对照·关 RAG"
            try:
                result = answer(q, use_rag=use_rag, prefer=prefer,
                                retriever=retriever, llm=llm, k=k)
                show(result)
                blocks.append(_markdown_block(len(blocks) + 1, label, result))
            except Exception as exc:   # noqa: BLE001
                failures += 1
                print(f"运行失败：{type(exc).__name__}: {exc}", file=sys.stderr)

    if out:
        header = [
            "# 三问三答（W8 阶段项目一 运行证据）",
            "",
            "> 本文件由 `python week08_assistant_v1/assistant_v1.py --demo --out answer_log.md` 直接生成，",
            "> 内容为真实运行输出（未手改答案），只对超长原文做了截断。",
            "",
            f"- 运行时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 引擎顺序：prefer=`{prefer}`（另一个引擎作为回退）",
            f"- 检索：top_k={k}，语料 `data/`（等级标准节选 / 愚公移山 / 生词表）",
            "",
        ]
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(header + blocks))
        print(f"已写入 {out}")
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="assistant_v1.py",
        description="W8 学科智能问答助手 v1.0：W2 提示词 + W6 双引擎 + W7 知识库")
    parser.add_argument("question", nargs="*", help="要问的问题；用 --demo 时忽略")
    parser.add_argument("--no-rag", action="store_true", dest="no_rag",
                        help="关掉知识库，纯对话（对照实验用）")
    parser.add_argument("--prefer", choices=("local", "api"),
                        default=os.getenv("ASSISTANT_PREFER", "local"),
                        help="先用哪个引擎，另一个自动回退（默认 local）")
    parser.add_argument("--k", type=int, default=5,
                        help="检索返回几段（默认 5：讲义用 3，实测数字类问题 3 段会漏掉量化表那一段）")
    parser.add_argument("--demo", action="store_true", help="跑三问三答并做开/关 RAG 对照")
    parser.add_argument("--out", default=None, help="把 --demo 的结果写成 markdown（如 answer_log.md）")
    parser.add_argument("--show-context", action="store_true", dest="show_context",
                        help="同时打印检索到的原文，方便核对数字")
    args = parser.parse_args(argv)

    if args.demo:
        return run_demo(args.prefer, args.k, args.out)

    question = " ".join(args.question).strip()
    if not question:
        try:
            question = input("问题> ").strip()
        except EOFError:
            print('错误：没有输入问题。用法：python assistant_v1.py "你的问题"', file=sys.stderr)
            return 2

    try:
        result = answer(question, use_rag=not args.no_rag, prefer=args.prefer, k=args.k)
    except Exception as exc:           # noqa: BLE001  —— 打印原因，不让程序静默退出
        print(f"运行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    show(result, show_context=args.show_context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
