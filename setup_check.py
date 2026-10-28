#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华文小助手 · 环境自检脚本

用法（二选一）：
  1) 直接双击本文件（Windows 需已关联 .py）
  2) 终端运行：python setup_check.py

只做检查、不修改任何文件、不上传任何数据。
"""
import os
import sys
import platform
import shutil
import socket
import subprocess
import importlib.util

OK, WARN, MISS = "[OK]", "[!!]", "[XX]"
rows = []


def add(item, ok, detail, fix=""):
    """ok: True=通过 / None=警告 / False=缺失"""
    rows.append((item, ok, detail, fix))


def run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def total_ram_gb():
    """跨平台读取物理内存（GB），失败返回 None。"""
    try:
        if platform.system() == "Windows":
            import ctypes

            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            s = MEMSTAT()
            s.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return round(s.ullTotalPhys / (1024 ** 3), 1)
        if platform.system() == "Darwin":
            v = run(["sysctl", "-n", "hw.memsize"])
            return round(int(v) / (1024 ** 3), 1) if v.isdigit() else None
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / (1024 ** 2), 1)
    except Exception:
        return None
    return None


def free_disk_gb(path="."):
    try:
        st = os.statvfs(path) if hasattr(os, "statvfs") else None
        if st:
            return round(st.f_bavail * st.f_frsize / (1024 ** 3), 1)
        import ctypes
        free = ctypes.c_ulonglong()
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(os.path.abspath(path)), None, None, ctypes.byref(free))
        return round(free.value / (1024 ** 3), 1)
    except Exception:
        return None


def net_ok(host, port=443, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except Exception:
        return False


def main():
    print("=" * 58)
    print("华文小助手 · 环境自检")
    print("=" * 58)

    # 1. Python
    v = sys.version_info
    add("Python", v >= (3, 9), platform.python_version(),
        "建议安装 Python 3.10+（安装时勾选 Add to PATH）" if v < (3, 9) else "")

    # 2. pip
    has_pip = importlib.util.find_spec("pip") is not None
    add("pip", has_pip, "可用" if has_pip else "未找到", "重装 Python 或 python -m ensurepip")

    # 3. Git
    git = shutil.which("git")
    if git:
        gv = run(["git", "--version"]).replace("git version", "").strip()
        add("Git", True, gv or "已安装")
    else:
        add("Git", False, "未找到", "用离线包 Git-2.51.0-64-bit.exe 安装")

    # 4. VS Code（可选）
    code = shutil.which("code")
    add("VS Code（可选）", True if code else None,
        "已安装" if code else "未找到（可用其他编辑器）", "")

    # 5. Ollama
    oll = shutil.which("ollama")
    if not oll:
        add("Ollama", None, "未安装", "W5 前需装；用机房离线包 OllamaSetup")
    else:
        add("Ollama", True, "已安装")
        if net_ok("127.0.0.1", 11434, timeout=2):
            models = run(["ollama", "list"])
            n = max(len(models.splitlines()) - 1, 0)
            add("Ollama 服务", True, "运行中，已装模型 %d 个" % n)
        else:
            add("Ollama 服务", False, "未运行", "启动 Ollama 应用后重试")

    # 6. 依赖包（按周）
    pkgs = [("openai", "W4+"), ("dotenv", "W4+"), ("requests", "W5+"), ("ollama", "W5+"),
            ("langchain", "W7+"), ("chromadb", "W7+"), ("mcp", "W10"),
            ("streamlit", "W15")]
    for name, wk in pkgs:
        found = importlib.util.find_spec(name) is not None
        add("包 %s（%s）" % (name, wk), True if found else None,
            "已安装" if found else "未安装（该周前 pip install %s）" % name,
            "" if found else "pip install %s" % name)

    # 7. .env 与密钥（只显示变量名，绝不显示值）
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    # 必须先加载 .env 再检测：否则"配了 .env 但没设系统变量"会被误报成未配置
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
    except Exception:
        pass          # 未装 python-dotenv 时退回只读系统环境变量
    if not os.path.exists(env_path):
        add(".env 文件", None, "不存在", "复制 .env.example 为 .env 并填入你的密钥")
    else:
        keys = []
        try:
            for line in open(env_path, encoding="utf-8"):
                if "=" in line and not line.strip().startswith("#"):
                    k = line.split("=", 1)[0].strip()
                    if k:
                        keys.append(k)
        except Exception:
            pass
        real = [k for k in keys if os.getenv(k)]
        add(".env 文件", True if real else None,
            "已存在，检测到 %d 个变量" % len(real) if real else "已存在但未读到有效变量",
            "" if real else "确认变量名拼写，且不要带引号/空格")

    # 7.5 代码包完整性（缺文件比缺依赖更难自查）
    base = os.path.dirname(os.path.abspath(__file__))
    for f in ["weekpath.py", "requirements.txt", ".env.example", ".gitignore"]:
        add("文件 %s" % f, os.path.exists(os.path.join(base, f)),
            "存在" if os.path.exists(os.path.join(base, f)) else "缺失（重新解压代码包）", "")

    # 8. 样例数据（base 已在 7.5 中定义）
    for f in ["data/生词表.csv", "data/等级标准节选.txt", "data/愚公移山.txt"]:
        p = os.path.join(base, f)
        add("数据 %s" % f, os.path.exists(p),
            "存在" if os.path.exists(p) else "缺失", "" if os.path.exists(p) else "重新解压代码包")

    # 9. 内存与本地模型建议
    ram = total_ram_gb()
    if ram is None:
        add("物理内存", None, "无法读取", "")
    else:
        if ram >= 16:
            rec = "可跑 1.5b–7b 档本地模型"
        elif ram >= 8:
            rec = "建议 qwen2.5:0.5b–1.5b 档"
        else:
            rec = "内存偏低，本地部署降级为演示，改用云端 API"
        add("物理内存", ram >= 8, "%.1f GB —— %s" % (ram, rec),
            "" if ram >= 8 else "本机可继续上课，但 W5 本地部署只做演示")

    # 10. 磁盘
    disk = free_disk_gb(base)
    add("可用磁盘", (disk or 0) >= 5, "%.1f GB" % (disk or 0),
        "" if (disk or 0) >= 5 else "清理空间，本地模型需 0.5–1.5GB/个")

    # 11. 网络
    add("网络 api.deepseek.com", net_ok("api.deepseek.com"),
        "可达" if net_ok("api.deepseek.com") else "不可达",
        "" if net_ok("api.deepseek.com") else "W4 可用通义或课堂共享密钥"
        if net_ok("dashscope.aliyuncs.com") else "检查代理/防火墙")
    add("网络 dashscope.aliyuncs.com", net_ok("dashscope.aliyuncs.com"),
        "可达" if net_ok("dashscope.aliyuncs.com") else "不可达（可选）", "")
    add("网络 github.com", net_ok("github.com"),
        "可达" if net_ok("github.com") else "不可达",
        "" if net_ok("github.com") else "可先本地 git commit，恢复后再 push")

    # ===== 输出 =====
    print()
    w = max(len(r[0]) for r in rows)
    for item, ok, detail, fix in rows:
        mark = OK if ok is True else (WARN if ok is None else MISS)
        print("%s  %-*s  %s" % (mark, w, item, detail))
        if fix and ok is not True:
            print("        -> 处理：%s" % fix)
    print()

    miss = [r for r in rows if r[1] is False]
    warn = [r for r in rows if r[1] is None]
    print("=" * 58)
    print("通过 %d 项 / 警告 %d 项 / 缺失 %d 项" %
          (sum(1 for r in rows if r[1] is True), len(warn), len(miss)))
    if miss:
        print("必须先解决（缺失项）：")
        for r in miss:
            print("   - %s" % r[0])
    elif warn:
        print("核心环境已就绪；警告项多为「本周还未用到」，可按需安装。")
    else:
        print("全部就绪，可以开始本周任务。")
    print("=" * 58)
    print("提示：本脚本不会显示任何密钥内容。若需帮助，把上面的输出截图发给老师。")
    try:
        input("\n按回车键退出...")
    except Exception:
        pass


if __name__ == "__main__":
    main()
