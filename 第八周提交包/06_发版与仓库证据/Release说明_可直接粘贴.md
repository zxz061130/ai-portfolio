> 用法：仓库 → **Releases** → *Draft a new release* → **Choose a tag** 选 `v1.0` →
> 标题填「v1.0 学科智能问答助手」→ 把下面整段粘进说明框 → *Publish release*。

## 功能

面向 HSK 3–4 教学的**备课问答助手**：先查 `data/` 里的学科资料再回答，答案标注《文件名》第N段；
`use_rag=True/False` 一个开关切换「基于资料」与「纯对话」两种模式。
三个问题各第一次成功输出见 [`week08_assistant_v1/answer_log.md`](week08_assistant_v1/answer_log.md)。

## 安装

```bash
pip install -r week08_assistant_v1/requirements.txt
ollama pull qwen2.5:0.5b && ollama pull nomic-embed-text
cp .env.example .env          # 填 DEEPSEEK_API_KEY（可跳过，纯本地也能跑）
```

## 用法

```bash
# 单问单答（默认本地引擎 + RAG）
python week08_assistant_v1/assistant_v1.py "HSK 4 级累计需要掌握多少词汇、多少汉字？"

# 关掉知识库做对照（同一问题，看它是不是开始编数字）
python week08_assistant_v1/assistant_v1.py "HSK 4 级累计需要掌握多少词汇、多少汉字？" --no-rag

# 三问三答 + 开/关 RAG 对照，并把真实输出写成证据文件
python week08_assistant_v1/assistant_v1.py --demo --out week08_assistant_v1/answer_log.md
```

## 这一版做了什么

- `assistant_v1.py` 是**唯一粘合层**：W2 提示词（`SYSTEM_HINT`）+ W7 检索（`rag_qa.RAG.retrieve` / `build_prompt`）+ W6 双引擎（`llm.LLM().ask(prefer=…)`），不重新实现任何引擎。
- 逐题 try/except：任何一题报错只打印「运行失败：原因」，下一题照跑，整个演示不挂。
- README 含官方 RAG 流水线 **5 行映射表**（自评 B 档：云端嵌入换本地 `nomic-embed-text` + Chroma 落盘）。

## 对照证据

同一句「HSK 4 级累计需要掌握多少词汇、多少汉字？」：

| 模式 | 回答 | 数字校验 |
|---|---|---|
| 开 RAG | 3245 词 / 1200 字（见《等级标准节选.txt》第5段） | ✓ 通过 |
| 关 RAG | 1200 词 / 600 字 | 两个数字都错 |

## 已知问题

1. 首次运行要拉模型 + 建 Chroma 库，可能 1–3 分钟；库建好后秒开。
2. Ollama 没起会失败（报错里写明是哪个引擎、什么原因）。
3. 本地 0.5b 会漏标出处、会把提示词占位符原样抄出来、会放弃答数字——证据见 `answer_log.md` 附录 A1/A2；演示建议 `--prefer api`。
