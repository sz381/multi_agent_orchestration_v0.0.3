"""生成 macOS Seatbelt 沙箱 profile（供 sandbox-exec 使用）。

提供函数：
- generate_default:      网络模式 profile（全局读 + 工作区写 + 全网络）
- generate_air_gapped:   禁网模式 profile（全局读 + 工作区写 + 禁网）

策略要点：
- (deny default)：默认拒绝一切
- 全局 file-read*：简单且不会漏路径
- file-write* 仅限工作区 + /tmp 等临时目录
- 网络全有或全无
"""

import os


def _generate(workspace: str, allow_network: bool = True) -> str:
    """生成 Seatbelt .sb profile 字符串。

    策略：
      - (deny default)：默认拒绝一切
      - 全局 file-read*：简单，不会漏路径
      - file-write* 仅限工作区 + /tmp
      - 网络：全有或全无

    Args:
        workspace: 工作区根目录绝对路径（读写白名单）。
        allow_network: True 允许网络，False 完全禁网。

    Returns:
        Seatbelt profile 字符串。
    """
    header = "(version 1)\n(deny default)\n"

    basic = """
            (allow process-exec*)
            (allow process-fork)
            (allow signal (target self))
            (allow sysctl-read)
            (allow mach-lookup)
            (allow file-map-executable)
            """

    reads = """
            (allow file-read*)
            """

    filesystem = f"""
            (allow file-read* file-write* (subpath "{workspace}"))
            (allow file-read* file-write* (subpath "/tmp"))
            (allow file-read* file-write* (subpath "/private/tmp"))
            (allow file-read* file-write* (subpath "/var/folders"))
            (allow file-read* file-write* (subpath "/private/var/folders"))
            (allow file-read* file-write* (literal "/dev/null"))
            """

    home = os.path.expanduser("~")
    denies = f"""
            (deny file-read*
                (subpath "{home}/.trae-cn")
                (subpath "{home}/.ssh")
                (literal "{home}/.zsh_history")
                (literal "{home}/.bash_history")
                (subpath "{home}/Library/Application Support/Google/Chrome")
                (subpath "{home}/Library/Application Support/Chromium")
                (subpath "{home}/Library/Keychains")
            )
            """

    if allow_network:
        network = "(allow network*)\n"
    else:
        network = "(deny network*)\n"

    return header + basic + filesystem + reads + denies + network


def generate_default(workspace: str) -> str:
    """网络模式：全局读 + 工作区写 + 全网络访问。

    Args:
        workspace: 工作区根目录绝对路径。

    Returns:
        Seatbelt profile 字符串。
    """
    return _generate(workspace, allow_network=True)


def generate_air_gapped(workspace: str) -> str:
    """禁网模式：全局读 + 工作区写 + 禁止网络。

    Args:
        workspace: 工作区根目录绝对路径。

    Returns:
        Seatbelt profile 字符串。
    """
    return _generate(workspace, allow_network=False)
