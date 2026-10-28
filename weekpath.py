"""weekpath —— 跨周模块导入 + 数据路径 + .env 加载的统一入口。

每个脚本开头固定这三行（照抄即可，第 12 周后可讲解其原理）：

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import weekpath; weekpath.load_env()

它解决三个真实问题：
    1. 跨周导入：llm.py 在 week06、rag_qa.py 在 week07，但 W8/W11/W15 都要用它们。
       直接 `from llm import LLM` 会 ModuleNotFoundError。本模块把所有 week*_ 目录
       加入 sys.path，让"一条主线贯穿 16 周"真正跑得通。
    2. 数据路径：不再依赖"当前工作目录"，data_path() 永远指向 data/ 下的真实文件。
    3. .env 加载：Windows 下 os.getenv() 读不到 .env，需要显式 load_env()。
       未安装 python-dotenv 时安全跳过（此时请用系统环境变量）。

只做路径与环境变量，不做任何业务逻辑，也不上传任何数据。
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")


def _register():
    """把代码包根目录和所有 week*_ 目录加入 sys.path（幂等）。"""
    paths = [ROOT]
    for name in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, name)
        if os.path.isdir(p) and name.startswith("week"):
            paths.append(p)
    for p in paths:
        if p not in sys.path:
            sys.path.insert(0, p)


def root_path(*parts):
    """定位代码包根目录下的文件，例如 root_path("chroma_db")。"""
    return os.path.join(ROOT, *parts)


def data_path(*parts):
    """定位 data/ 下的文件，例如 data_path("生词表.csv")。"""
    return os.path.join(DATA_DIR, *parts)


def load_env():
    """读取根目录 .env 到环境变量；未安装 python-dotenv 则静默跳过。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    env_file = os.path.join(ROOT, ".env")
    if os.path.exists(env_file):
        load_dotenv(env_file, override=False)
        return True
    return False


_register()

if __name__ == "__main__":
    print("代码包根目录：", ROOT)
    print("数据目录：", DATA_DIR)
    print("已加入 sys.path 的周目录：")
    for p in sys.path[:12]:
        if os.path.isdir(p) and os.path.basename(p).startswith("week"):
            print("   ", os.path.basename(p))
    print(".env 加载：", "成功" if load_env() else "跳过（未安装 python-dotenv 或无 .env）")
