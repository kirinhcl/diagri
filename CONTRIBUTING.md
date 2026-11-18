# Contributing

English | [简体中文](#参与贡献)

Thank you for helping. The full guide is the wiki page [Contributing](docs/wiki/en/Contributing.md): how changes are made here, the rules that hold, and the checklist reviewers use. This file is the short version.

1. **Set up** and get a green test run: [Development setup, testing and CI](docs/wiki/en/Development-Setup-Testing-and-CI.md). No test needs an AC5; the simulators stand in for it.
2. **Work on a branch**, not on `main`.
3. **Write the test first** where hardware moves: `control/`, `executor/` and `workflow/` decide what is written to a real device.
4. **Run the checks CI runs**:

   ```sh
   .venv/bin/ruff check src tests scripts
   .venv/bin/ruff format --check src tests scripts
   .venv/bin/pytest -q
   ```

5. **Update the docs in both languages, in the same commit.** Every wiki page exists in `docs/wiki/en/` and `docs/wiki/zh-CN/`. The tests in `tests/docs/` check that the reference pages still list the denial codes, CLI commands, configuration fields, routes and tools the code has, in both languages.
6. **Commit** as `<type>: <description>`, with a type from `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf` or `ci`.
7. **Open a pull request** and wait for all four CI jobs (Linux and macOS, Python 3.11 and 3.13).

Two rules are not negotiable: nothing may give a model role control of a stage or of the device ([Control and safety model](docs/wiki/en/Control-and-Safety-Model.md)), and no secret, device address or personal data goes into the repository.

Found a security problem? Do not open a public issue; follow [SECURITY.md](SECURITY.md).

---

# 参与贡献

[English](#contributing) | 简体中文

感谢你的帮助。完整的指南在 Wiki 页面[贡献流程](docs/wiki/zh-CN/Contributing.md)：这里怎样修改代码、哪些规则必须遵守、评审时用的检查清单。本文件是简版。

1. **准备环境**，先跑通一遍测试：[开发环境、测试与 CI](docs/wiki/zh-CN/Development-Setup-Testing-and-CI.md)。测试不需要 AC5，由模拟器代替。
2. **在分支上工作**，不要直接改 `main`。
3. **涉及硬件动作时先写测试**：`control/`、`executor/` 和 `workflow/` 决定往真实设备写什么。
4. **运行 CI 会跑的检查**：

   ```sh
   .venv/bin/ruff check src tests scripts
   .venv/bin/ruff format --check src tests scripts
   .venv/bin/pytest -q
   ```

5. **两种语言的文档在同一次提交里更新。** 每个 Wiki 页面在 `docs/wiki/en/` 和 `docs/wiki/zh-CN/` 下各有一份。`tests/docs/` 里的测试会检查参考页面列出的拒绝码、CLI 命令、配置项、路由和工具是否仍与代码一致，两种语言都查。
6. **提交信息**写成 `<类型>: <描述>`，类型从 `feat`、`fix`、`refactor`、`docs`、`test`、`chore`、`perf`、`ci` 中选。
7. **发起 Pull Request**，等 CI 的四个任务（Linux 和 macOS，Python 3.11 和 3.13）全部通过。

有两条规则没有商量余地：任何改动都不能让模型角色控制阶段或设备（[控制与安全模型](docs/wiki/zh-CN/Control-and-Safety-Model.md)）；仓库里不能出现密钥、设备地址或个人数据。

发现了安全问题？不要开公开 issue，请按 [SECURITY.md](SECURITY.md#安全策略) 处理。
