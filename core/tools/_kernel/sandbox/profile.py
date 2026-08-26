"""Generate macOS Seatbelt sandbox profiles (for sandbox-exec).

Functions:
- generate_default:      network profile (global read + workspace write + full network)
- generate_air_gapped:   air-gapped profile (global read + workspace write + no network)

Policy highlights:
- (deny default): deny everything by default
- Global file-read*: simple and cannot miss paths
- file-write* limited to the workspace + temp dirs such as /tmp
- Network is all-or-nothing
"""

import os


def _generate(workspace: str, allow_network: bool = True) -> str:
    """Generate a Seatbelt .sb profile string.

    Policy:
      - (deny default): deny everything by default
      - Global file-read*: simple, cannot miss paths
      - file-write* limited to the workspace + /tmp
      - Network: all-or-nothing

    Args:
        workspace: Absolute path of the workspace root (read/write whitelist).
        allow_network: True allows network, False fully blocks it.

    Returns:
        The Seatbelt profile string.
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
    """Network mode: global read + workspace write + full network access.

    Args:
        workspace: Absolute path of the workspace root.

    Returns:
        The Seatbelt profile string.
    """
    return _generate(workspace, allow_network=True)


def generate_air_gapped(workspace: str) -> str:
    """Air-gapped mode: global read + workspace write + no network.

    Args:
        workspace: Absolute path of the workspace root.

    Returns:
        The Seatbelt profile string.
    """
    return _generate(workspace, allow_network=False)
