from __future__ import annotations

from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """注册仓库级 pytest marker。"""
    config.addinivalue_line(
        "markers",
        "real_env_debug: 需要显式指定 tests/debug 路径才执行的真实环境调试测试",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """默认跳过真实环境调试测试，避免把本地依赖带进常规回归。"""
    if _is_debug_path_explicitly_requested(config):
        return

    skip_marker = pytest.mark.skip(
        reason="真实环境调试测试需显式运行 tests/debug 路径",
    )
    for item in items:
        if item.get_closest_marker("real_env_debug") is not None:
            item.add_marker(skip_marker)


def _is_debug_path_explicitly_requested(config: pytest.Config) -> bool:
    """判断本次 pytest 是否显式指定了 tests/debug 路径。"""
    requested_paths = [
        Path(str(argument).split("::", maxsplit=1)[0]).as_posix()
        for argument in config.args
        if not str(argument).startswith("-")
    ]
    return any("tests/debug" in requested_path for requested_path in requested_paths)
