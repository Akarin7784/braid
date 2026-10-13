# 参与开发

## 首次克隆后

```bash
pip install -e ".[dev]"
scripts/install-hooks.sh   # 启用 pre-commit 钩子（core.hooksPath=scripts/hooks）
```

钩子只检查、不改文件：对暂存的 `.py` 跑 `ruff check --no-fix` 和 `ruff format --check`。
ruff 先找当前 worktree 的 `.venv/bin/ruff`，再找 `PATH`，都没有会报错拦下提交。
修复后重新 `git add`；紧急情况可 `git commit --no-verify`，CI 的 lint 仍会检查。

注意：钩子路径相对每个 worktree 解析。分支还没包含 `scripts/hooks/` 时 git 会静默跳过钩子，
请先变基到最新的 main。

## 跑测试

```bash
pytest
```

借用其他 worktree 的 venv 时要加 `PYTHONPATH=src`，否则会导入别处的代码；
`tests/conftest.py` 会断言 `braid` 来自当前 worktree 的 `src`。

## 分支与合并

在自己的 worktree 和功能分支上开发，ruff、mypy、pytest 全过后报提交号，由主理人推送和合并，不直接推 main。
