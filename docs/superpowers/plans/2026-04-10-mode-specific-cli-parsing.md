# Mode-Specific CLI Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `main.py` 仅为当前 `--mode` 注册对应参数，避免 `m2` 专属参数被当作全局参数再做后置拦截。

**Architecture:** 保留现有 `--mode m0/m1/m2` 入口形式，先用基础解析器识别 mode，再按 mode 构建完整解析器做第二次解析。这样可以把参数可见性下沉到 `argparse`，同时保留现有分发逻辑和大部分调用方式。

**Tech Stack:** Python 3.10+, argparse, pytest

---

### Task 1: 锁定按模式注册参数的外部行为

**Files:**
- Modify: `D:\Program_python\free_stock\tests\unit\test_main.py`
- Test: `D:\Program_python\free_stock\tests\unit\test_main.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parse_cli_args_reports_once_as_unrecognized_outside_m2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main.parse_cli_args(
            [
                "--config",
                "config/sim_account.yaml",
                "--once",
            ]
        )

    captured = capsys.readouterr()
    assert "unrecognized arguments: --once" in captured.err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py::test_parse_cli_args_reports_once_as_unrecognized_outside_m2 -q`
Expected: FAIL because current parser still把 `--once` 注册为全局参数，并输出自定义错误而不是 `unrecognized arguments`

- [ ] **Step 3: Write minimal implementation**

```python
base_args, _ = base_parser.parse_known_args(argv)
parser = build_parser_for_mode(base_args.mode)
args = parser.parse_args(argv)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py::test_parse_cli_args_reports_once_as_unrecognized_outside_m2 -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_main.py main.py docs/superpowers/plans/2026-04-10-mode-specific-cli-parsing.md
git commit -m "refactor: parse cli args by mode"
```

### Task 2: 收敛解析器实现并回归主路径

**Files:**
- Modify: `D:\Program_python\free_stock\main.py`
- Test: `D:\Program_python\free_stock\tests\unit\test_main.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parse_cli_args_defaults_to_m0() -> None:
    args = main.parse_cli_args(["--config", "config/sim_account.yaml"])

    assert args.mode == "m0"
    assert not hasattr(args, "once")
    assert not hasattr(args, "max_rounds")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py::test_parse_cli_args_defaults_to_m0 -q`
Expected: FAIL because current parser为默认 m0 也会挂出 `once` / `max_rounds`

- [ ] **Step 3: Write minimal implementation**

```python
def build_base_parser() -> argparse.ArgumentParser:
    ...


def build_parser_for_mode(mode: str) -> argparse.ArgumentParser:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n stock_analysis pytest tests/unit/test_main.py::test_parse_cli_args_defaults_to_m0 -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_main.py main.py docs/superpowers/plans/2026-04-10-mode-specific-cli-parsing.md
git commit -m "test: cover mode-specific cli parsing"
```

### Task 3: 验证完整入口分发

**Files:**
- Modify: `D:\Program_python\free_stock\main.py`
- Test: `D:\Program_python\free_stock\tests\unit\test_main.py`

- [ ] **Step 1: Run targeted CLI tests**

```bash
conda run -n stock_analysis pytest tests/unit/test_main.py -q
```

- [ ] **Step 2: Verify no regression in main dispatch**

Expected:
- `m0` 默认入口仍然分发到 `run_m0_connectivity_check`
- `m1` 仍然要求交易参数
- `m2` 仍然支持 `--once` 和 `--max-rounds`

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_main.py main.py docs/superpowers/plans/2026-04-10-mode-specific-cli-parsing.md
git commit -m "refactor: scope cli args by mode"
```
