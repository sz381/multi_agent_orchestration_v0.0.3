"""测试配置

提供函数：
- workspace:        将工作区指向临时目录，保证测试文件落在工作区内
- tree:             构造标准 glob 测试树（供 glob_tool 测试使用）
- grep_tree:        构造标准 grep 测试树（供 grep_tool 测试使用）

"""

import pytest

from utils.settings import settings


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """
    将工作区指向临时目录，保证测试文件落在工作区内。
    """
    monkeypatch.setattr(settings, "workspace_dir", str(tmp_path))
    return tmp_path


@pytest.fixture()
def tree(workspace):
    """标准 glob 测试树：供 glob_tool 匹配语义用例复用。

    每个用例都获得一棵独立的新树（fixture 函数级作用域），结构如下：
    - 根下文件：hello.py / main.py / x.py / README.md / data.txt / .hidden.txt
    - 排除样本：.DS_Store（排除文件）、.venv/venv.py 与 logs/app.log（排除目录）
    - 子目录：a/b.py、a/c/note.txt、b/note.txt、sub/data.txt、sub/nested/deep.py

    Returns:
        workspace（pathlib.Path），即测试树根目录。
    """
    files = {
        "hello.py": "print('hello')\n",
        "main.py": "print('main')\n",
        "x.py": "print('x')\n",
        "README.md": "# readme\n",
        "data.txt": "data\n",
        ".hidden.txt": "secret\n",
        ".DS_Store": "ds\n",
        ".venv/venv.py": "print('venv')\n",
        "logs/app.log": "log\n",
        "a/b.py": "print('b')\n",
        "a/c/note.txt": "note\n",
        "b/note.txt": "note\n",
        "sub/data.txt": "data\n",
        "sub/nested/deep.py": "print('deep')\n",
    }
    for rel, content in files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workspace


@pytest.fixture()
def grep_tree(workspace):
    """标准 grep 测试树：供 grep_tool 匹配语义用例复用。

    每个用例都获得一棵独立的新树（fixture 函数级作用域），结构如下：
    - a.py：5 行，foo 命中 L1/L2/L5 共 3 条，L4 为 FOO 供大小写用例
    - b.py：2 行均命中（L2 一行三个 foo 也只计 1 条，逐行单条契约）
    - sub/c.py 命中 L2；sub/d.txt 无命中（跨子目录 + 混合扩展名）
    - deep/nested/e.py、.hidden.txt 各命中 1 条（深层递归 + 隐藏文件）
    - 排除样本：.DS_Store（排除文件）、.venv/f.py（排除目录）

    pattern "foo" 的基准统计：total_matches=8，命中文件 5 个
    （a.py / b.py / sub/c.py / deep/nested/e.py / .hidden.txt）。

    Returns:
        workspace（pathlib.Path），即测试树根目录。
    """
    files = {
        "a.py": "foo bar\nhello foo\nnothing here\nFOO case\nfoo\n",
        "b.py": "bar foo\nfoo foo foo\n",
        "sub/c.py": "hello\nfoo baz\n",
        "sub/d.txt": "no match here\n",
        "deep/nested/e.py": "foo deep\n",
        ".hidden.txt": "foo hidden\n",
        ".DS_Store": "foo\n",
        ".venv/f.py": "foo\n",
    }
    for rel, content in files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workspace
