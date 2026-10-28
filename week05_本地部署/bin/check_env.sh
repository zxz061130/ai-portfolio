#!/usr/bin/env bash
# 第5周 · 环境体检（Windows / Git Bash）
# 用法：bash bin/check_env.sh
set -uo pipefail

HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
BASE="http://${HOST}"
MODEL="${MODEL:-qwen2.5:0.5b}"
OK=0; BAD=0

pass()  { OK=$((OK+1));  printf '  [ OK ] %s\n' "$*"; }
fail()  { BAD=$((BAD+1)); printf '  [FAIL] %s\n' "$*"; }
info()  { printf '         %s\n' "$*"; }
title() { printf '\n%s\n' "$*"; }

printf '第5周 · 本地部署环境体检\n'
printf '=================================================\n'
printf 'shell    : %s\n' "$BASH_VERSION"
printf '系统     : %s %s\n' "$(uname -s)" "$(uname -r)"
printf '当前目录 : %s\n' "$(pwd)"
printf '服务地址 : %s\n' "$BASE"
printf '默认模型 : %s\n' "$MODEL"

title '1) bash 类型'
case "$(uname -s)" in
  MINGW*|MSYS*) pass "Git Bash（MSYS2，$(uname -s)）—— 本课程推荐" ;;
  CYGWIN*)      pass "Cygwin（命令基本可用，路径写法略有差别）" ;;
  Linux)        pass "Linux 或 WSL（同样可用；WSL 里 ollama 要装在 WSL 内）" ;;
  Darwin)       pass "macOS" ;;
  *)            fail "未知环境：$(uname -s)" ;;
esac

title '2) ollama 命令是否在 PATH'
if command -v ollama >/dev/null 2>&1; then
  pass "已安装：$(command -v ollama)"
  info "版本：$(ollama --version 2>&1 | head -n 1)"
else
  fail "PATH 里没有 ollama"
  info '装法：双击 OllamaSetup.exe（一路下一步），装完【重开】Git Bash 窗口'
  info "默认位置：\$LOCALAPPDATA\\Programs\\Ollama\\ollama.exe"
  info '临时救急（不重开窗口）：export PATH="$LOCALAPPDATA/Programs/Ollama:$PATH"'
fi

title '3) 本地服务（默认 127.0.0.1:11434）'
version_json="$(curl -sS --noproxy '*' --max-time 3 "$BASE/api/version" 2>/dev/null || true)"
if [ -n "$version_json" ]; then
  pass "服务在跑：$BASE"
  info "版本：$(printf '%s' "$version_json" | tr -d '\r\n')"
else
  fail "连不上 $BASE（connection refused / 超时）"
  info 'Windows 托盘有羊驼图标 = 服务已起；没有就另开一个 bash 终端：ollama serve'
  info '端口没占上？export OLLAMA_HOST=127.0.0.1:11434 后重启 Ollama'
fi

title '4) 已装模型'
tags=""
if [ -n "$version_json" ]; then
  tags="$(curl -sS --noproxy '*' --max-time 5 "$BASE/api/tags" 2>/dev/null || true)"
fi
if [ -z "$tags" ]; then
  info '（服务没起来，跳过；起来后重跑本脚本）'
else
  names="$(printf '%s' "$tags" | sed -E 's/\}[[:space:]]*,[[:space:]]*\{/}\n{/g' \
           | sed -n 's/.*"name":[[:space:]]*"\([^"]*\)".*/\1/p')"
  if [ -z "$names" ]; then
    fail '一个模型都没有 —— 先拉一个：bash bin/pull_model.sh'
  else
    printf '%s\n' "$names" | while IFS= read -r n; do
      size="$(printf '%s' "$tags" | sed -E 's/\}[[:space:]]*,[[:space:]]*\{/}\n{/g' \
              | grep -F "\"$n\"" | sed -n 's/.*"size":[[:space:]]*\([0-9]*\).*/\1/p' | head -n 1)"
      printf '         %-24s %s MB\n' "$n" "$(awk -v s="${size:-0}" 'BEGIN{printf "%.0f", s/1048576}')"
    done
    if printf '%s\n' "$names" | grep -qx "$MODEL"; then
      pass "默认模型 $MODEL 已就绪"
    else
      fail "默认模型 $MODEL 不在本机"
      info "拉取：bash bin/pull_model.sh $MODEL"
      info "或换一个已装的：export MODEL=${MODEL} 改成上面的名字"
    fi
  fi
fi

title '5) 代理（本机 11434 最常被它拦掉）'
proxy_hit=0
for v in http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; do
  val="${!v:-}"
  if [ -n "$val" ]; then
    info "$v=$val"; proxy_hit=1
  fi
done
if [ "$proxy_hit" = 0 ]; then
  pass '没有设置代理变量，curl 直连本机没问题'
else
  case "${NO_PROXY:-${no_proxy:-}}" in
    *127.0.0.1*|*localhost*) pass '有代理，但 NO_PROXY 已排除本机' ;;
    *) fail '有代理且 NO_PROXY 没排除本机 —— 连 11434 会被送去代理'
       info '临时解决：export NO_PROXY=localhost,127.0.0.1'
       info '本包脚本已加 curl --noproxy "*"，但 ollama 自己的请求仍受系统代理影响' ;;
  esac
fi

title '6) Python 与 requests（第12页的直连要用）'
if command -v python >/dev/null 2>&1; then
  pass "python $(python -c 'import sys;print(sys.version.split()[0])' 2>/dev/null)（$(command -v python)）"
  if python -c 'import requests' >/dev/null 2>&1; then
    pass "requests $(python -c 'import requests;print(requests.__version__)' 2>/dev/null) 已装"
  else
    fail 'requests 未装：python -m pip install requests'
  fi
else
  fail 'PATH 里没有 python（第12页直连需要）'
fi

title '结论'
printf '  通过 %d 项，失败 %d 项\n' "$OK" "$BAD"
if [ "$BAD" -eq 0 ]; then
  printf '  可以往下走：\n'
  printf '    bash bin/ask.sh "给《愚公移山》出一道 HSK4 阅读题"\n'
else
  printf '  先把 FAIL 修掉；刚装完 Ollama 一定要【重开】Git Bash（PATH 才会刷新）\n'
fi
[ "$BAD" -eq 0 ] || exit 1
