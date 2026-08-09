"""测试工具模块

提供函数：
- read_json: 读取 JSON 字符串并返回 JSON 对象
- make_file: 生成指定行数与行长的文本文件，返回文件路径
- make_indexed_file: 生成每行内容带行号的文件，用于校验行号与内容对应
- rels: 将绝对路径列表转为相对路径集合（基于 realpath 归一化后的工作区根）

使用注意：
- 本模块仅存放测试辅助函数，不包含测试用例
"""

import json
import os


def read_json(raw: str) -> dict:
    """ 读取 JSON 字符串并返回 JSON 对象

    Args:
        raw: JSON 字符串。

    Returns:
        JSON 对象。
    """
    return json.loads(raw)


def make_file(
    workspace, 
    name: str, 
    line_count: int, 
    line_len: int = 21, 
    subdir: str | None = None
):
    """生成指定行数与行长的文本文件。

    每行内容为 line_len-1 个字符 'x' 加一个换行符，
    保证单行（含换行）恰好为 line_len 字节，便于精确控制文件大小。

    Args:
        workspace:       目标目录，通常为 pytest 的 tmp_path fixture 返回值。
        name:            文件名。
        line_count:      要生成的行数。
        line_len:        每行字节数（含换行符），默认 21。
        subdir:          可选子目录名，文件将创建在 workspace/subdir 下（不存在则自动创建）。

    Returns:
        生成文件的完整路径（pathlib.Path）。
    """
    path = (workspace / subdir if subdir else workspace) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    line = "x" * (line_len - 1) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(line_count):
            f.write(line)
    return path


def make_indexed_file(workspace, name: str, line_count: int):
    """生成每行内容带行号的文件（第 i 行内容为 line-{i}）。

    与 make_file 的同质内容（全 x）不同，本函数用于验证读取结果中
    行号与内容的一一对应关系，内容错位类 bug 在此数据下必然暴露。

    Args:
        workspace:   目标目录，通常为 pytest 的 tmp_path fixture 返回值。
        name:        文件名。
        line_count:  要生成的行数。

    Returns:
        生成文件的完整路径（pathlib.Path）。
    """
    path = workspace / name
    with open(path, "w", encoding="utf-8") as f:
        for i in range(1, line_count + 1):
            f.write(f"line-{i}\n")
    return path


def rels(workspace, files: list[str]) -> set[str]:
    """将绝对路径列表转为相对路径集合（基于真实路径的工作区根）。

    工具（如 glob_tool）返回的是绝对路径，直接与期望列表对比时，
    根目录写法（如 macOS 的 /var 与 /private/var 符号链接差异）会
    导致断言脆弱；本函数先对工作区根做 realpath 归一化，再统一转成
    以根为基准的相对路径集合，断言只关注路径结构与文件名。

    Args:
        workspace: 工作区目录，通常为 pytest 的 tmp_path fixture 返回值。
        files:     工具返回的绝对路径列表（如 glob_tool 响应的 files 字段）。

    Returns:
        相对路径集合，元素不含工作区根前缀（如 {"a/b.py", "sub/data.txt"}）。
    """
    abs_ws = os.path.realpath(str(workspace))
    return {os.path.relpath(f, abs_ws) for f in files}
