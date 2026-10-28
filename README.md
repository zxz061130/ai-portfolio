# 华文小助手 · AI 辅助教学作品集

《人工智能在学习环境中的应用与实践》（407P1122，汉语国际教育 A 轨）16 周课程的产出仓库。
每周一个目录，代码可直接运行；离线产物（练习、日志）一并留档，作为学习过程证据。

## 目录

| 目录 / 文件 | 周次 | 内容 |
|---|---|---|
| `week01_环境/hello.py` | W1 | 环境自检，跑通 Python |
| `prompt-library/` | W2 | 教学提示词库（6 类：作文批改、口语任务卡、文化点讲解、生词筛查、语法讲练、课堂活动） |
| `week03_Python/vocab_tool.py` | W3 | 读 `data/生词表.csv`，按 HSK 等级筛选，生成造句与填空挖空练习 |
| `week04_API/` | W4 | 命令行学科问答机器人（API 版）+ 离线自检 + 参数体验表 + 密钥自查表 |
| `week05_本地部署/` | W5 | Ollama 本地部署：环境体检、拉模型、问答、本地 vs 云端对比脚本 |
| `data/` | — | 学科语料：生词表、课文《愚公移山》、等级标准节选 |
| `weekpath.py` | — | 跨周模块导入 / 数据路径 / `.env` 加载的统一入口 |
| `setup_check.py` | — | 提交前自检：检查目录结构、密钥是否误入版本库 |

## 怎么跑

```bash
# W3：生成练习（无需第三方库）
python week03_Python/vocab_tool.py

# W4：第一次 API 调用（需要 .env 里的密钥）
cp .env.example .env          # 填入 DEEPSEEK_API_KEY
python week04_API/week4_api_bot.py "把字句的教学难点有哪些"
python week04_API/selfcheck_offline.py     # 不用密钥的离线自检

# W5：本地部署（先装 Ollama，再重开终端）
bash week05_本地部署/bin/check_env.sh
bash week05_本地部署/bin/pull_model.sh
bash week05_本地部署/bin/ask.sh "给《愚公移山》出一道 HSK4 阅读题"
```

## 依赖

- W1–W3：无第三方依赖
- W4：`pip install openai python-dotenv`
- W5：Ollama（Windows 安装包）+ `pip install requests`

## 约定

- **`.env` 永不入库**：`.gitignore` 已排除；仓库里只有 `.env.example` 占位。
- 脚本一律 LF 行尾（`.gitattributes` 强制），避免 Git Bash 报 `$'\r'`。
- 每周产物写到代码包根目录，路径由 `weekpath.py` 统一解析，换目录运行也不会丢文件。
