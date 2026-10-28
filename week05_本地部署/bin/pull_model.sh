#!/usr/bin/env bash
# 第5周 · 拉一个本地模型（Windows / Git Bash）
# 用法：bash bin/pull_model.sh            # 默认 qwen2.5:0.5b（约 397MB）
#       bash bin/pull_model.sh qwen3:4b   # 换更大的（约 2.5GB，需 ≥16GB 内存）
set -uo pipefail

MODEL="${1:-${MODEL:-qwen2.5:0.5b}}"

if ! command -v ollama >/dev/null 2>&1; then
  cat <<'EOF'
[FAIL] 找不到 ollama 命令。
       1) 先装 OllamaSetup.exe（一路下一步）；
       2) 装完【重开】Git Bash 窗口（PATH 才会刷新）；
       3) 重开后再跑一次本脚本。
       临时救急（不重开）：export PATH="$LOCALAPPDATA/Programs/Ollama:$PATH"
EOF
  exit 1
fi

echo "== 拉取前：已装模型 =="
ollama list || true

if ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$MODEL"; then
  echo "[ OK ] $MODEL 已经装过，不用再拉。"
  exit 0
fi

echo
echo "== 开始拉取 $MODEL =="
echo "   体积参考：qwen2.5:0.5b≈397MB  qwen3:0.6b≈522MB  qwen3:4b≈2.5GB  deepseek-r1:8b≈5.2GB"
echo "   如果卡在百分之几超过 5 分钟：Ctrl+C 按一次，改用教师分发的离线包（README 第 6 节）"
echo

if ollama pull "$MODEL"; then
  echo
  echo "[ OK ] 拉取完成："
  ollama list
  echo
  echo "下一步：bash bin/ask.sh \"给《愚公移山》出一道 HSK4 阅读题\""
else
  rc=$?
  cat <<EOF

[FAIL] 拉取失败（退出码 $rc）。按顺序排查：
       1) 网络：浏览器能打开 https://ollama.com 吗？教室网常被限速；
       2) 换网络（手机热点）再试一次；
       3) 仍然不行 → 用离线包导入：
          · 若老师给的是 Modelfile + .gguf 文件：
              ollama create $MODEL -f ./Modelfile
          · 若老师给的是 models 目录压缩包：
              解压覆盖到  C:\\Users\\%USERNAME%\\.ollama\\models
          · 模型想放别的盘（体积大）：
              setx OLLAMA_MODELS "D:\\ollama-models"   # 然后重开终端、重启 Ollama
EOF
  exit "$rc"
fi
