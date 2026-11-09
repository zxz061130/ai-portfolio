# week08_assistant_v1 · 学科智能问答助手 v1.0

W8 阶段项目一：把前七周的三块积木拼成一个能交付的产品。
**不写新东西** —— 只做「接线」和「规范化」：W2 提示词库 + W6 双引擎 + W7 知识库。

## 功能

一句话：给 HSK 3–4 的中文课堂做备课问答，**先查资料再回答，答案带《文件名》第N段出处**。
`use_rag=True` 走「检索 → 拼提示词 → 生成」，`use_rag=False` 走纯对话，一个开关切两种模式。
语料是 `data/` 下的三份学科文件（等级标准节选、愚公移山、生词表），回答里的数字会被机器复核。

## 怎么装

1. 装依赖：`pip install -r week08_assistant_v1/requirements.txt`（W6/W7 的包都在里面）。
2. 装本地模型：`ollama pull qwen2.5:0.5b` 和 `ollama pull nomic-embed-text`（前者生成、后者嵌入）。
3. 云端可选：`cp .env.example .env` 后填入 `DEEPSEEK_API_KEY`；不填也能纯本地跑（W6 的懒加载）。

## 怎么用

```bash
# ① 仓库根目录下，单问单答（默认本地引擎 + RAG）
python week08_assistant_v1/assistant_v1.py "HSK 4 级累计需要掌握多少词汇、多少汉字？"

# ② 关掉知识库做对照（同一问题，看它是不是开始编数字）
python week08_assistant_v1/assistant_v1.py "HSK 4 级累计需要掌握多少词汇、多少汉字？" --no-rag

# ③ 三问三答 + 开/关 RAG 对照，并把真实输出写成证据文件
python week08_assistant_v1/assistant_v1.py --demo --out week08_assistant_v1/answer_log.md
```

常用开关：`--prefer api`（先走云端，挂了自动回退本地）、`--k N`（检索几段，默认 5；
讲义示例用 3，实测数字类问题 3 段会漏掉量化表那一行）、`--show-context`（把检索到的原文也打出来，核对数字时用）。

## 已知问题

1. **首次运行慢**：要拉本地模型 + 建 Chroma 库，第一次可能 1–3 分钟；库建好（`chroma_db/`）后是秒开。
2. **Ollama 没起会整条失败**：`use_rag` 依赖本地嵌入，`llm` 依赖本地生成；两个都挂时才报错（报错里写清是哪个引擎、什么原因）。
3. **小模型（0.5b）会漏标出处**：50% 左右的答案只写了结论、没写「第N段」，`check_numbers` 只能兜住数字类幻觉，语义类幻觉仍要人看。

## 三块积木怎么接（唯一粘合层）

```
assistant_v1.answer(question, use_rag=True, prefer="local")
        │
        ├─ W7 rag_qa.RAG.retrieve(question)      → docs（3 段，带「文件 / 段号」）
        │     └─ rag_qa.format_context(docs)     → ctx（拼成【资料】原文）
        │
        ├─ W2 SYSTEM_HINT（身份 + 对象 + 要求，取自 prompt-library/）
        │     └─ rag_qa.build_prompt(question, ctx)  → prompt（限定 + 拼接 + 要出处）
        │
        └─ W6 llm.LLM().ask(prompt, prefer=prefer)   → 答案（prefer 切路，双向回退）
                    │
                    └─ rag_qa.verify_citations / check_numbers → 出处与数字的机器复核
```

`use_rag=False` 时把中间两步摘掉，只留 `SYSTEM_HINT + question` 交给 W6 —— 这就是「纯对话」，
和 `--no-rag` 对照用的那条路是同一行代码的两个分支。

## 官方 RAG 流水线 ↔ 我的 rag_qa.py：5 行映射表

（LangChain 官方教程 *RAG / Retrieval* 是 2-Step 骨架；本仓库的对应实现按行对照）

| # | 官方流水线（llm-universe / LangChain 2-Step RAG） | 我的 `week07_RAG/rag_qa.py` 对应实现 | 差异 |
|---|---|---|---|
| 1 | **Load + Split**：`TextLoader` 读资料 + `RecursiveCharacterTextSplitter` 分块 | `load_documents()` 读 `data/` 三份文件；`split_documents()` 用 500/50，分隔符补了中文标点（`。；！？，`）与表格行 | 官方按字符切，我的切点落在句子/表格行边界 |
| 2 | **Embed + Store**：`Embeddings` + `VectorStore`（Chroma）持久化 | `OllamaEmbeddings("nomic-embed-text")` + `chromadb`，落盘 `chroma_db/`；嵌入不可用时退 `HashEmbeddings` 并在输出里声明 | 官方示例多用云端嵌入，我换成本地 nomic（不花 token、可离线） |
| 3 | **Retrieve**：`similarity_search(k=3)` | `RAG.retrieve()` → `hybrid_search()`：向量 top-k 池 + BM25 重排，最终 k=3 | 我在向量检索后加了一层关键词重排，专治专有名词/数字查不准 |
| 4 | **Prompt + Generate**：模板拼 `{context}` + `{question}`，调 LLM | `build_prompt()` 限定「只依据资料 + 标出处 + 数字不改写」；`LLM().ask(prefer=...)` 生成 | 官方用英文模板，我换成中文教学场景的身份与纪律 |
| 5 | **Deploy + Evaluate**：Streamlit 界面 / 评测脚本 | `week08_assistant_v1/assistant_v1.py`（CLI 助手 + `--demo` 三问三答）、`check_numbers()` / `verify_citations()` 做机器评测 | 我没做网页，用 CLI + 证据文件；评测是自动的（数字与出处两把尺子） |

**分档自评：B 档（8GB 跑道，只读 + 一个改造点）。**
改造点：把示例流水线里的「云端嵌入 + 内存向量库」换成 **本地 `nomic-embed-text` + Chroma 落盘**，
并把「出处/数字校验」做成不靠人眼的机器复核（第 3、5 行）。没有 fork 公开教程仓库、也没有换掉整套流程，
所以不报 A 档；C 档（只写 300 字反思）也够不上，因为 5 行都已落地且能跑。

## 运行证据

- `answer_log.md`：三问三答（词库类 / 数字指标 / 引证类）+ 同一题开/关 RAG 的对照，全部是真实运行输出。
- 复现：`python week08_assistant_v1/assistant_v1.py --demo --out week08_assistant_v1/answer_log.md`

## 目录

```
week08_assistant_v1/
├── assistant_v1.py      # 唯一粘合层：W2 提示词 + W7 检索 + W6 双引擎
├── answer_log.md        # 三问三答 + RAG 开/关对照（运行证据）
├── peer_review.md       # 互评表 + 第 9 周「助手该有的两个工具」
├── requirements.txt     # 本项目的依赖（W6/W7 合并，按周装也行）
└── README.md            # 本文件：四段式 + 5 行映射表
```
