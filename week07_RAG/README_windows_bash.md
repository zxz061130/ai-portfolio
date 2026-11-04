# W7 · RAG 入门：让 AI 基于你的资料回答（Windows + bash）

对应讲义《第七次课：RAG 入门》。本周交付：

| 交付物 | 文件 | 状态 |
|---|---|---|
| 课堂产物：四步齐全的知识库问答器 | `week07_RAG/rag_qa.py` | ✅ 跑了真机 |
| 课堂产物：幻觉对照表（≥3 组） | `week07_RAG/幻觉对照表.md` | ✅ 6 组 |
| 课后作业 1：补全 rag_qa.py + 进阶二选一 | 同上（两项进阶都做了） | ✅ |
| 课后作业 2：对照表扩到 ≥5 组 + 200 字反思 | 同上 | ✅ |
| 课后作业 3：W8 项目预习 | `week07_RAG/作业3_W8项目预习.md` | ✅ |
| 附：机器原始记录 / 检索实验 / 运行记录 | `hallucination_raw.md`、`检索实验.md`、`运行记录.txt` | ✅ 可复现 |

**你机器的现状（我今天实测）**：Ollama 0.40.12 在跑，`nomic-embed-text`（274 MB）已拉、`qwen2.5:0.5b`、`qwen3:4b` 都在；`langchain 1.4.8 / langchain-chroma 1.1.0 / langchain-ollama 1.1.0 / chromadb 1.5.9` 装好了；`.env` 里的云端密钥可用。三条路（纯本地、纯云端、RAG+双引擎）都真跑过。

---

## 0. 三分钟跑完课堂任务

```bash
cd /d/ai-portfolio/week07_RAG

python rag_qa.py --ingest                                  # ① 建库：加载→分块→向量化
python rag_qa.py "HSK 四级累计词汇量是多少？"                 # ② 检索+生成（本地 0.5b）
python rag_qa.py "HSK 四级累计词汇量是多少？" --prefer api     # ③ 同一问题走云端
python rag_qa.py "…" --show-context                        # ④ 把检索到的 3 段原文打出来

python selftest_offline.py                                 # 不联网的 42 项逻辑自测
python run_hallucination.py                                # 重跑幻觉对照表（4 列 × 6 题）
python make_run_log.py                                     # 重跑一遍并落成 运行记录.txt（可截图的那份）
```

跑完打开 `幻觉对照表.md`（人工结论）与 `hallucination_raw.md`（模型原话）。

**关于截图**：`运行记录.txt` 就是为「要一份能交/能截图的运行证据」准备的——它含完整环境
（系统、依赖版本、Ollama 模型、分块参数、git 提交号）+ 6 题 × 4 列原话 + 每格引擎/耗时/命中段/数字校验。
文本比截图可核（能 diff、能搜），要交图片时直接截它的前两屏即可。生成时**不会**写入任何密钥；
`python make_run_log.py` 会**同时**刷新 `运行记录.txt` 与 `hallucination_raw.md`，两份永远同源。

## 1. 讲义四步 ↔ 代码在哪

| 讲义 | 函数 | 关键细节（为什么这么写） |
|---|---|---|
| ① 加载 | `load_documents()` | `TextLoader(encoding="utf-8")` 读 `data/` 三个文件；中文路径交给 `weekpath.data_path()`，不手写相对路径 |
| ② 分块 | `split_documents()` | 正文 `RecursiveCharacterTextSplitter(500/50)`，分隔符补了中文标点（默认会退化到逐字切）；**表格按行切**，见 §3 |
| ③ 向量化 | `make_embeddings()` + `get_vectorstore()` | `OllamaEmbeddings("nomic-embed-text")` → Chroma 落盘 `chroma_db/`；库的元信息记住 embed/分块参数，参数一变自动重建（讲义第 13 页那个坑） |
| ④ 检索 | `hybrid_search()` / `retrieve()` | 向量召回候选池 + 关键词（中文二元组 + 数字）重排，默认 k=3 |
| 生成 | `build_prompt()` + `RAG.ask()` | 三条硬限定：只用资料、没有就说「资料中未提及」、数字必须与资料完全一致；`llm.ask(prefer=…)` 复用 W6 双引擎 |

`get_retriever()` / `rag_q()` 这两个讲义骨架里的名字都保留了，方便对照。

## 2. 与讲义骨架的差异（改了什么、为什么）

| 讲义片段 | 我的实现 | 差异与理由 |
|---|---|---|
| 片段 1 `get_retriever` | `get_vectorstore()` + `get_retriever()` | 多了「库元信息」：把 embed/chunk/分块策略/语料清单写进 `chroma_db/w7_meta.json`，下次参数对不上就自动重建。讲义原版每次 `from_documents` 都会重建、或反过来复用旧库——这就是「换了文本还在检索旧库」的根源 |
| 片段 2 `retrieve` | `retrieve()` / `hybrid_search()` | 检索从「一次向量 top-k」改成「先召回候选池、再关键词重排」，因为纯向量在中文 + 数字表格上会翻车（§3 有数据） |
| 片段 3 `build_prompt` | `build_prompt(question, ctx, history)` | 多了两条：出处格式（`（见《文件》第N段）`）与多轮历史；另加 `check_numbers()` 做数字校验 |
| 片段 3 `rag_q` | `RAG` 类 + `rag_q()` | 有状态的会话需要类：`history` 支撑多轮追问，`clear()` 清上下文；`rag_q()` 保留成一行版本 |

## 3. 两项进阶（讲义说「二选一」，两样都做了）

**进阶 A：每段记来源，答案附出处**

- 每块 metadata 带 `文件 / 段号 / 小节`，提示词里编成 `【资料1｜《等级标准节选.txt》第5段｜一、语言量化指标总表】`；
- 答案要求按 `（见《文件》第N段）` 标注；`verify_citations()` 检查引用的段是否真在本次检索结果里（乱标会被抓）；
- `check_numbers()`：把答案里的数字逐个和检索到的原文比对，列出「资料里查无此数」。Q1 的 0.5b 就是因为做除法生成了 0.245、0.012 被抓出来的。

**进阶 B：多轮追问**

- `RAG.history` 存最近 4 轮；追问时 **检索词** = 上一轮问题 + 本轮问题（`search_query()`），**提示词** = 最近两轮问答；
- 为什么检索词也要拼：单独拿「那五级呢？」去检索，向量里没有任何锚点，top-3 必然跑偏；
- `--chat` 模式：`/clear` 清上下文、`/bare` 临时关检索（现场演示裸答 vs RAG 很方便）。

## 4. 本机实测（2026-11-04，RTX 5080 Laptop / Ultra 9 275HX）

| 项目 | 数字 |
|---|---|
| 嵌入模型 | `nomic-embed-text`，768 维，`127.0.0.1:11434` |
| 语料 | 3 个文件、约 2.9k 字 → **17 块**（正文 9 块 + 量化表 8 行） |
| 建库耗时 | 首次 14.8s（含模型装载）；之后 **0.5s**；复用库时启动约 4s |
| 检索命中（8 题，k=3） | 讲义原版纯向量 **5/8** → 表格按行 + 关键词重排 **8/8**（见 `检索实验.md`） |
| 单次问答耗时 | 本地 0.5b **0.1–0.3s**；云端 deepseek-chat **0.8–3.6s** |
| 回答正确率 | RAG·云端 **6/6**；裸答·云端 1/6；RAG·0.5b 2/6；裸答·0.5b 0/6（见 `幻觉对照表.md`） |

**分块是这周真正的技术点**。整张量化指标表 300 多字，被平均成一个向量后，问「四级累计词汇量」只排到第 6 名（相似度 0.508，而含「中等四级」字样的段落是 0.680），k=3 根本进不了上下文——于是 0.5b 把初等的 2245 当成四级的答案，数字全对得上，级别是错的。把表按行拆开、把列名和「新增/累计」写进行里，再把关键词重排接上，同一批问题 8/8 命中。`检索实验.md` 里有四组对照的逐题记录。

## 5. Windows + bash 的坑（这周会遇到的）

| 现象 | 原因 | 处理 |
|---|---|---|
| `ollama pull nomic-embed-text` 卡住 / 报错 | 没外网或代理拦了 | 用机房离线包导入；或先 `ollama list` 确认有没有；实在不行 `--embed hash` 让流程先跑通（会明确警告「检索质量不等价」） |
| `ModuleNotFoundError: langchain_text_splitters` | 只装了 `langchain` | `pip install -U langchain langchain-community langchain-chroma langchain-ollama chromadb` |
| 建库报 `WinError 32 另一个程序正在使用` | `chroma_db/` 被别的 python 进程占着 | 关掉其它终端里的脚本，再 `--rebuild` |
| 明明换了语料，答案还是旧的 | 复用了旧向量库 | `--rebuild`；或改 `SPLITTER_VERSION`（元信息对不上会自动重建） |
| 终端中文/箭头乱码 | Windows 控制台默认 GBK | `export PYTHONUTF8=1`；脚本里也做了 `reconfigure(encoding="utf-8")` |
| `connection refused` 但托盘有羊驼 | `localhost` 解析到 IPv6 `::1` | 一律用 `127.0.0.1:11434`（代码已固定） |
| 第一次问答卡 10 秒以上 | 0.5b 冷启动装载 | `ollama run qwen2.5:0.5b "你好"` 预热一次；或 `.env` 里 `LOCAL_TIMEOUT=180` |
| `bash: $'\r': command not found` | 文件存成了 CRLF | 仓库 `.gitattributes` 已固定 LF |
| `ValueError: path is on mount 'C:', start on mount 'D:'` | `os.path.relpath` 不能跨盘（自测把库指到系统临时目录时就会撞上） | 已用 `_show()` 兜住；自己写路径时同理，别假设同盘 |

## 6. 提交

```bash
cd /d/ai-portfolio
git status                      # 确认没有 .env、没有 chroma_db/
git add week07_RAG README.md .gitignore
git commit -m "W7: RAG 四步 + 出处/多轮进阶 + 幻觉对照表 6 组"
git push
```

`chroma_db/` 不入库（二进制、可重建）。助教/老师拿到仓库后跑 `python rag_qa.py --ingest` 即可复现。

## 7. 验收对照

- **达标**：`rag_qa.py` 四步齐全、能问答 → `python selftest_offline.py` 42 项全 PASS + 真机问答跑通
- **良好**：出处可核、多轮可追问、对照表 ≥5 组且差距说得清 → 本周两项进阶 + 6 组表
- **优秀**：能说清「为什么检索之后答案就靠谱了」——`检索实验.md` 的四组数据 + 幻觉对照表里「0.5b 拿到对的资料照样读错行」的反例

## 8. 复现失败时先看这三处

1. `python rag_qa.py --ingest --rebuild`：库到底建成了没有、几块、什么长度；
2. `python rag_qa.py "问题" --show-context`：检索到的原文里到底有没有答案（没有 → 分块/检索问题；有 → 模型问题）；
3. `python selftest_offline.py -v`：逻辑层有没有被改坏。
