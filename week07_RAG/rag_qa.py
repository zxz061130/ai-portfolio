# -*- coding: utf-8 -*-
"""rag_qa.py —— W7 学科知识库问答器：加载 → 分块 → 向量化 → 检索 → llm 生成

课堂四步（讲义 PART 1，第 6~10 页）：
    ① 加载   TextLoader 把 data/ 下的学科文本读成 Document
    ② 分块   RecursiveCharacterTextSplitter(500/50)，按「。；，\\n」切，不切在句子中间
    ③ 向量化 OllamaEmbeddings("nomic-embed-text") → Chroma 落盘 chroma_db/，第二次运行直接复用
    ④ 检索   similarity_search(k=3) 取最像的 3 段，拼进提示词交给 W6 的 llm.ask()

两项进阶（作业一「进阶二选一」，本文件两项都实现了）：
    · 出处：每个块在 metadata 里带「文件 / 段号 / 小节」，提示词要求按《文件》第N段标注；
            另外 check_numbers() 把「答案里的数字是否真出现在检索到的资料里」做成机器校验，
            没通过的数字会单独列出来 —— 这是幻觉对照表里的硬证据，不靠人眼。
    · 多轮：RAG.ask() 记 history；追问时把「上一轮问题」拼进检索词、把「上一轮答案」拼进
            提示词。只用上一轮答案做上下文时，“那五级呢？”这种省略句检索必然跑偏。

命令行（Windows Git Bash）：
    python rag_qa.py --ingest                                   # 只建库，看分块统计
    python rag_qa.py "HSK 四级累计词汇量是多少"                    # 默认本地引擎 + RAG
    python rag_qa.py "HSK 四级累计词汇量是多少" --prefer api        # 云端引擎 + RAG
    python rag_qa.py "HSK 四级累计词汇量是多少" --bare              # 裸答（不给资料），对照用
    python rag_qa.py "HSK 四级累计词汇量是多少" --show-context      # 看检索到了哪 3 段
    python rag_qa.py --chat                                      # 多轮追问，/bye 退出
    python rag_qa.py "…" --rebuild --chunk-size 300              # 换参数要重建库

设计纪律（沿用 W6）：
    · 不吞异常：库里没数据、模型没拉、密钥缺失，都当场打印原因并给出可操作提示；
    · 嵌入可降级：--embed auto 时若 Ollama 不可用，退回离线哈希嵌入（HashEmbeddings），
      并在输出里明确声明「检索质量不等价」，绝不假装是 nomic；
    · 库与参数绑定：embed / chunk_size / chunk_overlap 一变，旧库自动失效重建，
      避免讲义第 13 页那个坑——「换了文本还在检索旧库」。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import warnings
from collections import Counter

# ---------------------------------------------------------------- 跨周导入
# 讲义固定三行：让 W6 的 llm.py 被找到，同时把 .env 读进 os.environ。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import weekpath                      # noqa: E402  加 sys.path、data_path()、load_env()
weekpath.load_env()

from llm import LLM                  # noqa: E402  W6 双引擎：prefer="local"/"api" + 双向回退

# ---------------------------------------------------------------- 常量
CORPUS_FILES = ("等级标准节选.txt", "愚公移山.txt", "生词表.csv")
PERSIST = weekpath.root_path("chroma_db")      # 库落在代码包根目录，和 week07_RAG 同级
COLLECTION = "w7_xkb"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K = 3
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# 中文语料没有空格，RecursiveCharacterTextSplitter 默认的 ["\n\n","\n"," ",""] 会退化到
# 逐字切。补上中文标点，让切点落在句子边界上——块内语义完整，检索才准。
ZH_SEPARATORS = ["\n\n", "\n", "。", "；", "！", "？", "，", ""]

# 块内出现这些开头的行，就当作小节标题，给答案的出处提供更高一级的定位。
HEADING_RE = re.compile(r"^(?:[一二三四五六七八九十]+、|【.+?】|第[一二三四五六七八九十百]+[章节部分])")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
CITED_RE = re.compile(r"《[^》]{1,40}》\s*第\s*\d+\s*段|第\s*\d+\s*段")
GAP_RE = re.compile(r"\s{2,}")
SPLITTER_VERSION = "table-rows-3"      # 分块策略改了要改这里，旧库才会自动失效


# ---------------------------------------------------------------- 小工具
def _utf8_stdout() -> None:
    """Windows 控制台默认 GBK，中文/箭头会炸；能改就改成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:            # noqa: BLE001  老版本 Python 没有 reconfigure
            pass


def local_host() -> str:
    """Ollama 地址。用 127.0.0.1 而不是 localhost：Windows 上 localhost 可能解析到 IPv6 ::1。"""
    return os.getenv("LOCAL_HOST", "127.0.0.1:11434")


def _fmt_seconds(started: float) -> str:
    return f"{time.perf_counter() - started:.2f}s"


def _show(path: str) -> str:
    """给日志看的路径：能相对就相对；库被指到别的盘（自测会这样）就原样显示。

    Windows 上 os.path.relpath 跨盘会抛 ValueError，不兜住的话自测会在打印时崩。
    """
    try:
        return os.path.relpath(path, _ROOT) + "/"
    except ValueError:
        return path


# ---------------------------------------------------------------- ③ 嵌入函数
class HashEmbeddings:
    """离线兜底嵌入：字符 1~3 gram 哈希到 512 维后归一化。

    它不懂语义，只保证「没装 Ollama 时整条流水线还能跑通、还能被验收」。
    讲义第 13 页写的「C 路径：改写云端嵌入」，思路就是这个位置可以换实现——
    只要满足 embed_documents / embed_query 两个方法，Chroma 不关心你用什么算向量。
    """

    name = "hash-512"
    dim = 512

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _one(self, text: str):
        vec = [0.0] * self.dim
        for n in (1, 2, 3):
            weight = 1.0 if n == 1 else 1.5      # 词组比单字更有区分度
            for i in range(len(text) - n + 1):
                gram = text[i:i + n]
                h = int(hashlib.md5(gram.encode("utf-8")).hexdigest()[:16], 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 60) & 1 else -1.0
                vec[idx] += sign * weight
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts):
        return [self._one(t) for t in texts]

    def embed_query(self, text):
        return self._one(text)

    def __repr__(self):
        return f"<HashEmbeddings dim={self.dim}>"


def make_embeddings(kind: str = "auto"):
    """kind: ollama | hash | auto（默认：先试 ollama，失败退回 hash 并声明）。"""
    kind = (kind or "auto").lower()
    if kind in ("ollama", "auto"):
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError as exc:
            if kind == "ollama":
                raise RuntimeError(
                    "没装 langchain-ollama：pip install langchain-ollama") from exc
            print(f"[警告] 没装 langchain-ollama（{exc}），改用离线哈希嵌入")
            return HashEmbeddings()

        emb = OllamaEmbeddings(model=EMBED_MODEL, base_url=f"http://{local_host()}")
        try:
            probe = emb.embed_query("检索测试")
            if not probe:
                raise RuntimeError("嵌入接口返回空向量")
            print(f"[嵌入] Ollama {EMBED_MODEL}（{len(probe)} 维）@ {local_host()}")
            return emb
        except Exception as exc:     # noqa: BLE001  连不上/没拉模型，都走这里
            hint = (f"  排查：`ollama list` 看有没有 {EMBED_MODEL}；"
                    f"没有就 `ollama pull {EMBED_MODEL}`；"
                    f"再 `curl -sS --noproxy '*' http://{local_host()}/api/version`")
            if kind == "ollama":
                raise RuntimeError(f"Ollama 嵌入不可用：{exc}\n{hint}") from exc
            print(f"[警告] Ollama 嵌入不可用（{type(exc).__name__}: {exc}）")
            print(f"{hint}\n[警告] 已回退到离线哈希嵌入：流程能跑通，但"
                  f"「语义相近」不成立，检索质量不等价于 {EMBED_MODEL}。")
            return HashEmbeddings()

    if kind == "hash":
        print("[嵌入] 离线哈希嵌入（明确指定 --embed hash）")
        return HashEmbeddings()
    raise ValueError(f"不认识的 --embed：{kind}（可选 auto/ollama/hash）")


# ---------------------------------------------------------------- ① 加载 + ② 分块
def load_documents(corpus_files=None):
    """把 data/ 下的学科文本读成 Document，metadata 里记下文件名。"""
    with warnings.catch_warnings():
        # langchain 1.x 给 langchain-community 挂了 sunset 警告，跟本课无关，别让它刷屏
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from langchain_community.document_loaders import TextLoader

    docs = []
    for name in (corpus_files or CORPUS_FILES):
        path = weekpath.data_path(name)
        if not os.path.exists(path):
            print(f"[跳过] data/{name} 不存在")
            continue
        try:
            loaded = TextLoader(path, encoding="utf-8").load()
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                f"data/{name} 不是 UTF-8。Windows 上另存为 UTF-8，或换 encoding='gbk'") from exc
        for d in loaded:
            d.metadata["文件"] = name
            docs.append(d)
    if not docs:
        raise FileNotFoundError(
            f"data/ 里没有可读的语料（找的是 {', '.join(corpus_files or CORPUS_FILES)}）")
    return docs


def _is_table_line(line: str) -> bool:
    """一行里出现两处以上「连续空格」→ 当它是空格对齐的表格行。

    这份语料的量化指标表就是这种写法：等次    级别    音节    汉字    词汇    语法点
    """
    return len(GAP_RE.findall(line.rstrip())) >= 2


def _table_row_chunk(header_cells, header_line: str, row_line: str, rule: str) -> str:
    """表头 + 一行 → 一块，并把「116/724」这种写法摊成一句人话。

    为什么要把表拆成「一行一块」：整张表 300 多字，向量被平均数稀释，问「四级词汇量」
    时它排不进 top-3（实测第 6 名）；按行拆开并带上列名后，行里的「四级 / 词汇 /
    1000/3245」才有机会被关键词和向量同时抓住（实测 5/8 → 8/8，见 README）。

    为什么还要摊成句子：0.5b 看不懂空格对齐的列，但看得懂「词汇新增1000、累计3245」。
    数字一个不改，只把「/ 前为新增、后为累计」这条规则写进句子里。
    """
    cells = [c for c in GAP_RE.split(row_line.strip()) if c]
    text = f"{header_line.strip()}\n{row_line.strip()}"

    if len(cells) == len(header_cells) and len(cells) >= 3:
        parts = []
        for head, val in zip(header_cells[2:], cells[2:]):
            if "/" in val:
                new, total = val.split("/", 1)
                parts.append(f"{head}新增{new}、累计{total}")
            else:
                parts.append(f"{head}{val}")
        text += f"\n{cells[0]}{cells[1]}：" + "；".join(parts) + "。"
    if rule:
        text += f"\n（{rule}）"
    return text


def split_documents(docs, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP,
                    table_rows: bool = True):
    """分块：正文按句子切，表格按行切；每块补「段号 / 小节」——出处的两个维度。

    table_rows=False 时退回讲义原版（整篇按 chunk_size 切），留给 tune_retrieval.py
    做「按行分块到底有没有用」的对照实验。
    """
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=ZH_SEPARATORS,
        keep_separator="end",       # 句号留在上一块末尾，读起来是完整句子
    )

    if not table_rows:
        chunks = []
        for doc in docs:
            fname = doc.metadata.get("文件", "?")
            section = ""
            for n, text in enumerate((t.strip() for t in
                                      splitter.split_text(doc.page_content)), 1):
                if not text:
                    continue
                for line in text.splitlines():
                    if HEADING_RE.match(line.strip()):
                        section = line.strip()[:24]
                chunks.append(Document(page_content=text, metadata={
                    "文件": fname, "段号": n, "小节": section}))
        return chunks

    chunks = []
    for doc in docs:
        fname = doc.metadata.get("文件", "?")
        section = ""
        pieces = []
        prose = []
        table_rule = ""

        def flush():
            text = "\n".join(prose).strip()
            if text:
                pieces.extend(splitter.split_text(text))
            prose.clear()

        lines = doc.page_content.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            # 连续两行以上都是表格行，才当成表；单行（标题行）仍走正文
            if _is_table_line(line) and i + 1 < len(lines) and _is_table_line(lines[i + 1]):
                j = i
                while j < len(lines) and _is_table_line(lines[j]):
                    j += 1
                for prev in prose[-3:]:                 # 表前的说明行（“/”前为本级新增…）
                    if "前为" in prev or "表中" in prev:
                        table_rule = prev.strip().strip("。")
                flush()
                header_cells = [c for c in GAP_RE.split(line.strip()) if c]
                for row in lines[i + 1:j]:
                    pieces.append(_table_row_chunk(header_cells, line, row, table_rule))
                i = j
            else:
                if HEADING_RE.match(line.strip()):
                    table_rule = ""
                prose.append(line)
                i += 1
        flush()

        n = 0
        for text in pieces:
            text = text.strip()
            if not text:
                continue
            n += 1
            for line in text.splitlines():          # 块里若带了小标题，记下来给后面的块复用
                line = line.strip()
                if HEADING_RE.match(line):
                    section = line[:24]             # 取块内最后一个标题：它才是这块所在的节
            chunks.append(Document(
                page_content=text,
                metadata={"文件": fname, "段号": n, "小节": section},
            ))
    return chunks


def chunk_report(chunks) -> str:
    """建库后的自检数字：块数、块长分布 —— 分块参数调没调对，先看这三个数。"""
    lens = sorted(len(c.page_content) for c in chunks)
    if not lens:
        return "0 块"
    avg = sum(lens) / len(lens)
    return (f"{len(lens)} 块 ｜ 长度 min/avg/max = {lens[0]}/{avg:.0f}/{lens[-1]} ｜ "
            f"文件：{', '.join(sorted({c.metadata['文件'] for c in chunks}))}")


# ---------------------------------------------------------------- ③ 建库 / 复用
def _meta_path() -> str:
    return os.path.join(PERSIST, "w7_meta.json")


def _stamp(embed_name: str, chunk_size: int, chunk_overlap: int,
           table_rows: bool = True) -> dict:
    return {"embed": embed_name, "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap, "collection": COLLECTION,
            "splitter": SPLITTER_VERSION, "table_rows": table_rows,
            "corpus": list(CORPUS_FILES)}


def _read_meta():
    try:
        with open(_meta_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_meta(stamp: dict) -> None:
    try:
        with open(_meta_path(), "w", encoding="utf-8") as fh:
            json.dump(stamp, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"[警告] 写库元信息失败（不影响检索）：{exc}")


def get_vectorstore(embed: str = "auto", chunk_size: int = CHUNK_SIZE,
                    chunk_overlap: int = CHUNK_OVERLAP, rebuild: bool = False,
                    table_rows: bool = True):
    """返回 Chroma 库。参数或语料变了会自动重建 —— 这是讲义第 13 页那个坑的解药。"""
    from langchain_chroma import Chroma

    emb = make_embeddings(embed)
    stamp = _stamp(getattr(emb, "name", type(emb).__name__), chunk_size, chunk_overlap,
                   table_rows)
    have = _read_meta()
    need_build = rebuild or have != stamp or not os.path.isdir(PERSIST)

    if need_build:
        if rebuild:
            reason = "--rebuild"
        elif not have:
            reason = "库里没有"
        else:
            changed = {"embed": "嵌入方式", "chunk_size": "分块大小",
                       "chunk_overlap": "重叠长度", "splitter": "分块策略",
                       "table_rows": "表格分块开关", "corpus": "语料清单"}.items()
            diffs = [label for key, label in changed if have.get(key) != stamp.get(key)]
            reason = "、".join(diffs) + "变了" if diffs else "库不完整"
        print(f"[建库] {reason} → 重新分块并写入 {_show(PERSIST)}")
        started = time.perf_counter()
        chunks = split_documents(load_documents(), chunk_size, chunk_overlap,
                                 table_rows=table_rows)
        print(f"[分块] {chunk_report(chunks)}")
        shutil.rmtree(PERSIST, ignore_errors=True)
        vs = Chroma.from_documents(chunks, emb, persist_directory=PERSIST,
                                   collection_name=COLLECTION)
        _write_meta(stamp)
        print(f"[建库] 完成，{_fmt_seconds(started)}")
        return vs

    print(f"[复用] 已有库（{stamp['embed']}，chunk={chunk_size}/{chunk_overlap}）："
          f"{_show(PERSIST)}；要重建加 --rebuild")
    return Chroma(collection_name=COLLECTION, embedding_function=emb,
                  persist_directory=PERSIST)


def get_retriever(k: int = TOP_K, rebuild: bool = False, **kw):
    """讲义骨架里的名字，保留：返回 langchain Retriever，供不关心出处的调用方使用。"""
    vs = get_vectorstore(rebuild=rebuild, **kw)
    return vs.as_retriever(search_kwargs={"k": k})


# ---------------------------------------------------------------- ④ 检索 + 提示词
def format_context(docs) -> str:
    """把检索到的段落编成【资料N】块；编号/文件/段号就是答案出处的坐标系。"""
    blocks = []
    for i, d in enumerate(docs, 1):
        head = f"【资料{i}｜《{d.metadata.get('文件', '?')}》第{d.metadata.get('段号', '?')}段"
        if d.metadata.get("小节"):
            head += f"｜{d.metadata['小节']}"
        blocks.append(f"{head}】\n{d.page_content.strip()}")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------- 混合检索
# 为什么加这一层：nomic-embed-text 主要是英文语料训的，中文问句和「文字表格」
# 在向量空间里并不算近——实测「HSK 四级累计词汇量」的 top-3 里根本没有那张量化表，
# 小模型于是拿初等的 2245 当答案（数字全对得上，却是另一级）。纯向量 5/7，加这层 7/7。
STOP_GRAMS = {"的了", "是在", "和与", "及多", "多少", "什么", "怎么", "个什"}


def _tokens(text: str):
    """中文二元组 + 阿拉伯数字：中文没有空格，二元组当“词”用，数字单独成词。"""
    flat = re.sub(r"\s+", "", text)
    grams = [flat[i:i + 2] for i in range(len(flat) - 1) if flat[i:i + 2] not in STOP_GRAMS]
    return grams + NUM_RE.findall(flat)


def _bm25(query: str, docs, k1: float = 1.5, b: float = 0.75):
    """十几块的小库上，BM25 手写 30 行就够，不必再引 rank_bm25。"""
    tok_docs = [_tokens(d.page_content) for d in docs]
    n = len(docs)
    avgdl = sum(len(t) for t in tok_docs) / max(n, 1)
    df = Counter()
    for t in tok_docs:
        df.update(set(t))
    q = _tokens(query)
    scores = []
    for t in tok_docs:
        tf = Counter(t)
        s = 0.0
        for g in set(q):
            if g not in tf:
                continue
            idf = math.log(1 + (n - df[g] + 0.5) / (df[g] + 0.5))
            s += idf * tf[g] * (k1 + 1) / (tf[g] + k1 * (1 - b + b * len(t) / avgdl))
        scores.append(s)
    return scores


def _norm(xs):
    top = max(xs) if xs else 0.0
    return [x / top for x in xs] if top > 0 else [0.0] * len(xs)


def hybrid_search(vs, question: str, k: int = TOP_K, rerank: str = "hybrid",
                  pool: int | None = None):
    """向量召回 pool 块 → 关键词打分 → 融合后取前 k 块。

    rerank="none" 就是讲义原版的纯向量检索，留着给对照实验用。
    """
    if rerank in (None, "", "none"):
        return vs.similarity_search(question, k=k)

    want = pool or max(k * 4, 20)
    got = vs.similarity_search_with_score(question, k=want)
    if not got:
        return []
    if len(got) <= k:
        return [d for d, _ in got]

    docs = [d for d, _ in got]
    sims = [1.0 / (1.0 + float(score)) for _, score in got]      # Chroma 给的是 L2 距离
    lex = _bm25(question, docs)
    fused = [0.5 * a + 0.5 * b for a, b in zip(_norm(sims), _norm(lex))]
    order = sorted(range(len(docs)), key=lambda i: -fused[i])[:k]
    return [docs[i] for i in order]


def build_prompt(question: str, ctx: str, history: str = "") -> str:
    """把检索到的片段拼进提示词（讲义 PART 2：限定 + 拼接 + 复用 + 附出处）。"""
    rules = (
        "你是中文教学备课助手。请只依据下面提供的资料回答，不要使用资料以外的知识。\n"
        "1) 每个结论后面用（见《文件名》第N段）标注出处，只标你真正用过的那几段；\n"
        "2) 资料里没有的，直接回答「资料中未提及」，不要猜、不要编；\n"
        "3) 数字必须与资料完全一致，不要换算、四舍五入或改写。"
    )
    parts = [rules, "", "【资料】", ctx]
    if history:
        parts += ["", "【之前的对话】", history]
    parts += ["", f"问题：{question}"]
    return "\n".join(parts)


def build_bare_prompt(question: str, history: str = "") -> str:
    """裸答：不给资料、不加限定语 —— 幻觉对照表的对照组，必须保持“干净”。"""
    return (history + "\n" + question).strip() if history else question


def check_numbers(answer: str, ctx: str):
    """答案里的数字是否真在检索到的资料里出现过。返回「查无此数」的列表。

    两条降噪规则（都会让校验偏宽松，宁可漏报不误报——它的定位是「编造报警器」）：
      · 引用坐标（《…》第3段）本身含数字，先剔掉再比；
      · 只校验两位以上的数字：单位数多半是「HSK 4级」这种写法，资料里用的是汉字数字
        （四级/五级），拿来比对只会天天误报——实测 Q1 就报过一个假警（"4"）。
    """
    if not ctx:
        return []
    pool = set(NUM_RE.findall(ctx))
    body = CITED_RE.sub(" ", answer)
    return [n for n in NUM_RE.findall(body) if len(n) >= 2 and n not in pool]


def verify_citations(answer: str, docs):
    """答案引用的「第N段」是否落在本次检索到的块里；返回 (合法, 可疑) 两个列表。"""
    allowed = {(d.metadata.get("文件"), str(d.metadata.get("段号"))) for d in docs}
    cited = re.findall(r"《([^》]{1,40})》\s*第\s*(\d+)\s*段", answer)
    good = [(f, n) for f, n in cited if (f, n) in allowed or
            any(f.endswith(a[0]) and n == a[1] for a in allowed)]
    bad = [(f, n) for f, n in cited if (f, n) not in good]
    return good, bad


# ---------------------------------------------------------------- 组装：RAG
class RAG:
    """检索 + 生成。一个实例 = 一个会话，history 就是多轮记忆。"""

    def __init__(self, k: int = TOP_K, embed: str = "auto", prefer: str = "local",
                 chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP,
                 rebuild: bool = False, temperature: float = 0.1, max_tokens: int = 600,
                 rerank: str = "hybrid", pool: int | None = None, table_rows: bool = True):
        self.k = k
        self.embed = embed
        self.prefer = prefer
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.rebuild = rebuild
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.rerank = rerank
        self.pool = pool
        self.table_rows = table_rows
        self.history = []            # [{"问":…, "答":…}]，只留最近 keep_turns 轮
        self.keep_turns = 4
        self.llm = LLM()
        self._vs = None

    # -- 库 -----------------------------------------------------------------
    def store(self):
        if self._vs is None:
            self._vs = get_vectorstore(embed=self.embed, chunk_size=self.chunk_size,
                                       chunk_overlap=self.chunk_overlap, rebuild=self.rebuild,
                                       table_rows=self.table_rows)
            self.rebuild = False          # 只重建一次
        return self._vs

    # -- 检索 ---------------------------------------------------------------
    def search_query(self, question: str) -> str:
        """追问时把上一轮问题拼进检索词。

        “那五级呢？”单独去检索，向量里没有任何和五级有关的锚点，必然跑偏；
        拼上“HSK 四级累计词汇量是多少”之后，top-k 才落在同一张表附近。
        """
        if not self.history:
            return question
        return f"{self.history[-1]['问']} {question}"

    def retrieve(self, question: str, k: int | None = None):
        return hybrid_search(self.store(), self.search_query(question), k=k or self.k,
                             rerank=self.rerank, pool=self.pool)

    # -- 生成 ---------------------------------------------------------------
    def _history_text(self, turns: int = 2) -> str:
        if not self.history:
            return ""
        lines = []
        for item in self.history[-turns:]:
            lines.append(f"问：{item['问']}\n答：{item['答']}")
        return "\n".join(lines)

    def ask(self, question: str, rag: bool = True, remember: bool = True) -> dict:
        started = time.perf_counter()
        docs = self.retrieve(question) if rag else []
        ctx = format_context(docs) if docs else ""
        history = self._history_text()
        prompt = build_prompt(question, ctx, history) if rag else build_bare_prompt(question, history)

        answer = self.llm.ask(prompt, prefer=self.prefer,
                              temperature=self.temperature, max_tokens=self.max_tokens)

        result = {
            "question": question,
            "answer": answer,
            "rag": rag,
            "docs": docs,
            "query": self.search_query(question),
            "rerank": self.rerank,
            "unverified": check_numbers(answer, ctx) if rag else [],
            "citations": verify_citations(answer, docs) if rag else ([], []),
            "engine": self.llm.last.get("engine", "-"),
            "prefer": self.prefer,
            "fallback": bool(self.llm.last.get("fallback")),
            "seconds": self.llm.last.get("seconds", time.perf_counter() - started),
        }
        if remember:
            self.history.append({"问": question, "答": answer})
            self.history = self.history[-self.keep_turns:]
        return result

    def clear(self) -> None:
        self.history.clear()


# 讲义骨架里的名字，保留给「一句话调用」：
def rag_q(question: str, prefer: str = "local", k: int = TOP_K, **kw) -> str:
    """一行版本：print(rag_q("HSK 四级累计词汇量是多少"))"""
    return RAG(k=k, prefer=prefer, **kw).ask(question)["answer"]


# ---------------------------------------------------------------- 打印
def render(result: dict, show_context: bool = False) -> None:
    print("-" * 68)
    if result["rag"]:
        files = "、".join(f"《{d.metadata['文件']}》第{d.metadata['段号']}段" for d in result["docs"])
        mode = "向量+关键词重排" if result.get("rerank", "hybrid") != "none" else "纯向量"
        print(f"[检索] {mode} 命中 {len(result['docs'])} 段：{files}")
        if result["query"] != result["question"]:
            print(f"[检索词] {result['query']}   ← 追问时自动带上上一轮问题")
    print(f"[答] {result['answer']}")
    if result["rag"]:
        good, bad = result["citations"]
        if good:
            print("[出处] " + "、".join(f"《{f}》第{n}段" for f, n in good))
        if bad:
            print("[出处可疑] 答案引用了本次没检索到的段：" +
                  "、".join(f"《{f}》第{n}段" for f, n in bad))
        if result["unverified"]:
            print("[数字校验] ✗ 这些数字在检索到的资料里找不到：" +
                  "、".join(result["unverified"]))
        else:
            print("[数字校验] ✓ 答案里的数字都能在资料里对上")
    print(f"[引擎] {result['engine']} ｜ {result['seconds']:.2f}s ｜ "
          f"回退: {'是' if result['fallback'] else '否'} ｜ prefer={result.get('prefer', '-')}")
    if show_context:
        print("-" * 68)
        print(format_context(result["docs"]))


def ingest(embed: str, chunk_size: int, chunk_overlap: int, rebuild: bool,
           table_rows: bool = True) -> int:
    started = time.perf_counter()
    vs = get_vectorstore(embed=embed, chunk_size=chunk_size,
                         chunk_overlap=chunk_overlap, rebuild=rebuild, table_rows=table_rows)
    got = vs.get(limit=1)
    print(f"[自检] 库里可检索：{'是' if got.get('ids') else '否'} ｜ "
          f"总耗时 {_fmt_seconds(started)}")
    if not got.get("ids"):
        print("[自检] ✗ 库是空的，检查 data/ 与 --embed 参数", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------- 命令行
def chat_loop(rag: RAG) -> int:
    print(f"学科知识库问答（prefer={rag.prefer}，k={rag.k}）。"
          f"输入 /bye 退出，/clear 清空上下文，/bare 临时关掉检索。")
    bare = False
    while True:
        try:
            question = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0
        if question in ("/bye", "/exit", "exit", "quit"):
            print("已退出。")
            return 0
        if question == "/clear":
            rag.clear()
            print("（上下文已清空）")
            continue
        if question == "/bare":
            bare = not bare
            print(f"（检索已{'关闭，接下来是裸答' if bare else '打开'}）")
            continue
        if not question:
            continue
        try:
            render(rag.ask(question, rag=not bare))
        except Exception as exc:      # noqa: BLE001  单轮失败不该把整个会话带走
            print(f"错误：{exc}", file=sys.stderr)


def main(argv=None) -> int:
    _utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="rag_qa.py",
        description="W7 学科知识库问答器：加载→分块→向量化→检索→llm 生成")
    parser.add_argument("question", nargs="*", help="要问的问题")
    parser.add_argument("--prefer", choices=("local", "api"), default="local",
                        help="先用哪个引擎（另一个自动回退）")
    parser.add_argument("--k", type=int, default=TOP_K, help=f"检索几段（默认 {TOP_K}）")
    parser.add_argument("--rerank", choices=("hybrid", "none"), default="hybrid",
                        help="hybrid=向量召回+关键词重排（默认）；none=纯向量，讲义原版")
    parser.add_argument("--pool", type=int, default=None,
                        help="混合检索的候选池大小（默认 max(4k,20)）")
    parser.add_argument("--embed", choices=("auto", "ollama", "hash"), default="auto",
                        help="嵌入后端；auto=先试 Ollama，失败退回离线哈希")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, dest="chunk_size")
    parser.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP, dest="chunk_overlap")
    parser.add_argument("--rebuild", action="store_true", help="强制重建向量库")
    parser.add_argument("--table-rows", action=argparse.BooleanOptionalAction, default=True,
                        dest="table_rows",
                        help="表格按行分块（默认开；--no-table-rows 退回讲义原版整篇切）")
    parser.add_argument("--ingest", action="store_true", help="只建库并自检")
    parser.add_argument("--bare", action="store_true", help="裸答：不给资料（对照组）")
    parser.add_argument("--chat", action="store_true", help="多轮追问模式")
    parser.add_argument("--show-context", action="store_true", dest="show_context",
                        help="打印检索到的原文，核对“检索准不准”")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=600, dest="max_tokens")
    args = parser.parse_args(argv)

    if args.ingest:
        return ingest(args.embed, args.chunk_size, args.chunk_overlap, args.rebuild,
                      args.table_rows)

    rag = RAG(k=args.k, embed=args.embed, prefer=args.prefer,
              chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap,
              rebuild=args.rebuild, temperature=args.temperature, max_tokens=args.max_tokens,
              rerank=args.rerank, pool=args.pool, table_rows=args.table_rows)

    try:
        if args.chat:
            rag.store()                      # 进会话前先建/验库，免得第一句就卡住
            return chat_loop(rag)

        question = " ".join(args.question).strip()
        if not question:
            try:
                question = input("问题> ").strip()
            except EOFError:
                print('用法：python rag_qa.py "HSK 四级累计词汇量是多少"', file=sys.stderr)
                return 2
        result = rag.ask(question, rag=not args.bare)
        render(result, show_context=args.show_context)
        return 0
    except Exception as exc:             # noqa: BLE001  顶层兜底：报错要能看懂
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
