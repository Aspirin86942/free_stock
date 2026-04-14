from __future__ import annotations

import re
from pathlib import Path


_STAGE_NAME_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[mM][0-4](?:(?=[A-Z_])|\b)"
)
_ALLOWED_SUFFIXES = {".py", ".md", ".yaml", ".yml"}


def _iter_scan_targets(repo_root: Path) -> list[Path]:
    return [
        repo_root / "main.py",
        repo_root / "observe_decisions.py",
        repo_root / "src",
        repo_root / "tests",
        repo_root / "AGENTS.md",
        repo_root / "config",
        repo_root / "tools",
    ]


def _iter_text_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]

    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and candidate.suffix in _ALLOWED_SUFFIXES
        and "__pycache__" not in candidate.parts
        and not candidate.relative_to(path).parts[:2] == ("docs", "superpowers")
    )


def test_active_files_do_not_contain_staged_mode_names() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations: list[str] = []

    for target in _iter_scan_targets(repo_root):
        for text_file in _iter_text_files(target):
            relative_path = text_file.relative_to(repo_root)
            content = text_file.read_text(encoding="utf-8")
            for line_no, line in enumerate(content.splitlines(), start=1):
                if _STAGE_NAME_PATTERN.search(line):
                    violations.append(f"{relative_path}:{line_no}: {line.strip()}")

    assert not violations, "活跃文件仍存在阶段编号残留:\n" + "\n".join(violations)
