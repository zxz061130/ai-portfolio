#!/usr/bin/env bash
# 第5周 · 交互式对话（等于 ollama run，但顺手处理了 Git Bash 的两个坑）
#   bash bin/run.sh              # 默认 qwen2.5:0.5b
#   bash bin/run.sh qwen3:4b
# 退出：在对话里输入 /bye
set -uo pipefail

MODEL="${1:-${MODEL:-qwen2.5:0.5b}}"

if ! command -v ollama >/dev/null 2>&1; then
  echo '[FAIL] 找不到 ollama 命令：先装 OllamaSetup.exe，装完重开 Git Bash。'
  exit 1
fi

# 坑 1：Git Bash 的 mintty 不是真终端，ollama run 可能没回显/按键无反应 → 用 winpty 包一层
# 坑 2：中文显示成乱码 → 尽量用 UTF-8 locale（只影响本窗口）
if [ -z "${LANG:-}" ]; then
  export LANG=zh_CN.UTF-8
fi

echo "== 模型：$MODEL =="
echo "== 输入问题后回车；/bye 退出；Ctrl+C 也能退 =="
echo

if command -v winpty >/dev/null 2>&1 && [ -t 0 ] && [ -t 1 ]; then
  exec winpty ollama run "$MODEL"
else
  exec ollama run "$MODEL"
fi
