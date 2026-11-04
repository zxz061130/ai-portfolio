# -*- coding: utf-8 -*-
"""selftest_offline.py —— 不联网、不用密钥、不用 Ollama 的自测（Windows 上先跑这个）

为什么要有它：机房断网、Ollama 没起、密钥没配，都不该妨碍你验证「代码逻辑对不对」。
这里把嵌入换成 HashEmbeddings、把 LLM 换成 FakeLLM，只测 RAG 自己的四步与两条进阶：
    分块带没带出处 / 提示词有没有限定语 / 检索能不能返回 k 段 /
    数字校验抓不抓得到编造 / 多轮有没有把上一轮带进检索词与提示词 / 换参数会不会重建库

用法：python selftest_offline.py [-v]
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import rag_qa                                    # noqa: E402
from rag_qa import (                              # noqa: E402
    HashEmbeddings, RAG, build_bare_prompt, build_prompt, check_numbers,
    format_context, hybrid_search, load_documents, split_documents, verify_citations,
)

PASS, FAIL = [], []
VERBOSE = "-v" in sys.argv


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not cond else ""))
    return bool(cond)


class FakeLLM:
    """假的 LLM：记录收到的提示词，返回一句可预测的话（里面故意带一个资料里没有的数字）。"""

    def __init__(self, answer="按资料：累计 3245 个，另外我猜是 9999 个。"):
        self.answer = answer
        self.prompts = []
        self.last = {}

    def ask(self, prompt, prefer="local", **kw):
        self.prompts.append(prompt)
        self.last = {"engine": prefer, "fallback": False, "seconds": 0.01, "prefer": prefer}
        return self.answer


def main() -> int:
    rag_qa._utf8_stdout()
    tmp = tempfile.mkdtemp(prefix="w7_selftest_")
    old_persist, old_llm = rag_qa.PERSIST, rag_qa.LLM
    rag_qa.PERSIST = os.path.join(tmp, "chroma_db")
    rag_qa.LLM = FakeLLM

    try:
        print("\n[1] 加载 + 分块：出处信息全不全")
        docs = load_documents()
        check("读到 3 个语料文件", len(docs) == 3, f"实际 {len(docs)}")
        check("每篇都带文件名", all(d.metadata.get("文件") for d in docs))
        chunks = split_documents(docs)
        check("分块非空", len(chunks) >= 6, f"实际 {len(chunks)} 块")
        check("每块都有 文件/段号", all(c.metadata.get("文件") and c.metadata.get("段号") for c in chunks))
        check("没有超长块（<= chunk_size）",
              all(len(c.page_content) <= rag_qa.CHUNK_SIZE for c in chunks),
              f"最长 {max(len(c.page_content) for c in chunks)}")
        check("段号在文件内从 1 递增",
              all(c.metadata["段号"] >= 1 for c in chunks))
        check("断句落在中文标点（不是切在字中间）",
              any(c.page_content.rstrip().endswith(("。", "；", "！", "？")) for c in chunks))

        print("\n[2] 提示词：限定语 + 出处要求 + 上下文拼接")
        ctx = format_context(chunks[:2])
        prompt = build_prompt("HSK 四级词汇量是多少？", ctx)
        check("要求「资料中未提及」兜底", "资料中未提及" in prompt)
        check("要求标出处", "第N段" in prompt or "出处" in prompt)
        check("要求数字不得改写", "数字必须与资料完全一致" in prompt)
        check("上下文真的拼进去了", chunks[0].page_content[:10] in prompt)
        check("裸答提示词不含资料", build_bare_prompt("问题") == "问题")
        check("裸答提示词不带限定语", "资料中未提及" not in build_bare_prompt("问题"))

        print("\n[3] 离线哈希嵌入：可用、可复现")
        h = HashEmbeddings()
        v1, v2 = h.embed_query("四级词汇"), h.embed_query("四级词汇")
        check("维度 512", len(v1) == 512)
        check("同一输入向量一致", v1 == v2)
        check("已归一化", abs(sum(x * x for x in v1) - 1.0) < 1e-6)
        check("不同文本向量不同", h.embed_query("语法") != h.embed_query("词汇"))

        print("\n[4] 建库 / 复用 / 换参数自动重建")
        vs = rag_qa.get_vectorstore(embed="hash", chunk_size=500, chunk_overlap=50, rebuild=True)
        n1 = len(vs.get(limit=1000)["ids"])
        check("库里有块", n1 >= 6, f"实际 {n1}")
        meta = rag_qa._read_meta()
        check("元信息记录了 chunk_size", meta and meta["chunk_size"] == 500)
        again = rag_qa.get_vectorstore(embed="hash", chunk_size=500, chunk_overlap=50)
        check("参数不变时复用旧库", len(again.get(limit=1000)["ids"]) == n1)
        vs2 = rag_qa.get_vectorstore(embed="hash", chunk_size=300, chunk_overlap=50)
        check("chunk_size 变了会重建", rag_qa._read_meta()["chunk_size"] == 300)
        check("重建后块数变多", len(vs2.get(limit=1000)["ids"]) > n1)

        print("\n[5] 检索：k 段 + 混合重排")
        rag_qa.get_vectorstore(embed="hash", chunk_size=500, chunk_overlap=50, rebuild=True)
        vs = rag_qa.get_vectorstore(embed="hash", chunk_size=500)
        got_none = hybrid_search(vs, "HSK 四级累计词汇量", k=3, rerank="none")
        check("纯向量返回 3 段", len(got_none) == 3, f"实际 {len(got_none)}")
        got_hy = hybrid_search(vs, "HSK 四级累计词汇量", k=3, rerank="hybrid")
        check("混合检索返回 3 段", len(got_hy) == 3, f"实际 {len(got_hy)}")
        check("混合检索结果都带段号", all(d.metadata.get("段号") for d in got_hy))

        print("\n[6] 幻觉体检：数字校验 / 出处校验")
        check("资料里有的数字不报错", check_numbers("累计 3245 个", "1000/3245") == [])
        check("资料里没有的数字被抓出", check_numbers("一共 9999 个", "1000/3245") == ["9999"])
        check("引用坐标里的数字不算编造",
              check_numbers("答案是 3245（见《等级标准节选.txt》第12段）", "1000/3245") == [])
        check("单位数（如「4级」）不误报",
              check_numbers("HSK 4级累计 3245 个", "1000/3245") == [])
        good, bad = verify_citations("（见《等级标准节选.txt》第2段）", chunks[:3])
        check("引用检索到的段 → 合法", len(good) == 1 and not bad)
        good2, bad2 = verify_citations("（见《愚公移山.txt》第99段）", chunks[:3])
        check("引用没检索到的段 → 可疑", not good2 and len(bad2) == 1)

        print("\n[7] RAG 组装：一次问答的完整链路")
        bot = RAG(k=3, embed="hash", prefer="local")
        res = bot.ask("HSK 四级累计词汇量是多少？")
        check("返回了答案", bool(res["answer"]))
        check("带了 3 段上下文", len(res["docs"]) == 3, f"实际 {len(res['docs'])}")
        check("提示词里有资料块", "【资料1" in bot.llm.prompts[-1])
        check("编造的数字被标记", "9999" in res["unverified"], f"{res['unverified']}")
        check("记录走了哪个引擎", res["engine"] == "local")

        print("\n[8] 多轮追问：上一轮问题进检索词、上一轮答案进提示词")
        bot = RAG(k=3, embed="hash", prefer="local")      # 干净会话
        bot.ask("HSK 四级累计词汇量是多少？")
        q2 = bot.search_query("那五级呢？")
        check("追问的检索词带上了上一轮", "四级" in q2 and "五级" in q2)
        res2 = bot.ask("那五级呢？")
        check("提示词里有【之前的对话】", "【之前的对话】" in bot.llm.prompts[-1])
        check("历史记住了两轮", len(bot.history) == 2)
        bot.clear()
        check("clear() 清空历史", bot.history == [])
        res3 = bot.ask("那五级呢？")
        check("清空后检索词就是问题本身", res3["query"] == "那五级呢？")

        print("\n[9] 裸答模式：不带资料")
        bot2 = RAG(k=3, embed="hash", prefer="local")
        bot2.ask("HSK 四级累计词汇量是多少？", rag=False, remember=False)
        check("裸答提示词没有资料块", "【资料1" not in bot2.llm.prompts[-1])
        check("裸答没有检索结果", bot2.history == [])

    except Exception:                 # noqa: BLE001  自测脚本自己崩了，也要看得懂原因
        traceback.print_exc()
        FAIL.append("脚本异常中断")
    finally:
        rag_qa.PERSIST, rag_qa.LLM = old_persist, old_llm
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(PASS) + len(FAIL)
    print("\n" + "=" * 60)
    print(f"共 {total} 项：PASS {len(PASS)}，FAIL {len(FAIL)}")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        print("=" * 60)
        return 1
    print("结论：RAG 四步与两条进阶的逻辑都通了（真机效果另跑 run_hallucination.py）")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
