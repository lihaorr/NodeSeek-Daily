# Lottery replies implementation plan

> For agentic workers: use executing-plans inline; the dedicated clone and feature branch isolate these changes.

**Goal:** Discover recent giveaways and reply once per post with a ten-comment library and a hard daily cap of ten.

**Architecture:** Keep the existing browser entrypoint, extract pure discovery/quota behavior into lottery.py and persistence into state_store.py. Preview consumes public RSS without account actions; live execution checkpoints every pending action and verifies the resulting reply before counting success.

**Tech Stack:** Python 3.11, unittest, requests, BeautifulSoup, Selenium, existing undetected-chromedriver.

## Global constraints
- Asia/Shanghai calendar dates; maximum 10 successful replies daily.
- New: published within 24 hours and no existing per-post record.
- No eligible posts: zero submission calls.
- Ten built-in Chinese comments; no paid AI dependency.
- No live publishing, workflow activation, or main-branch merge during development.

## Task 1: Discovery, quota and storage
Files: lottery.py, state_store.py, tests/test_lottery.py, tests/test_state_store.py.
- [x] Write behavior tests for synonyms, closed/irrelevant posts, URL/date validation, cap, day rollover, deduplication, unknown results and no-new behavior.
- [x] Run `python -m unittest discover -s tests -v`; observe missing interfaces.
- [x] Implement `parse_feed(xml)`, `eligible(post, now)`, `run_replies(posts, store, submit, ...)`, local atomic JSON, and SHA-checked GitHub persistence.
- [x] Run the same suite; verify checkpoint failure prevents submission and preview leaves storage untouched.

## Task 2: Browser and workflow
Files: nodeseek_daily.py, .github/workflows/daily.yml, tests/test_browser_actions.py.
- [x] Add failing tests for confirmed versus unknown reply results, false-valued reward setting, check-in independence and browser cleanup.
- [x] Replace unrelated trade-post selection with eligible-feed processing and confirmed DOM results; preserve Chrome version tests.
- [x] Use `python nodeseek_daily.py --feed-file tests/fixtures/giveaways.xml` for a deterministic no-browser preview.
- [x] Serialize the automation job, default to preview and require explicit live setting; persist reservations synchronously to automation-state through GitHub API.

## Task 3: Verification and handoff
Files: README.md, .env.example, outputs implementation report.
- [x] Document configuration, ten comments, feed coverage, state recovery and preview-first enablement.
- [x] Run `python -m unittest discover -s tests -v`, `python -m compileall -q .`, `git diff --check`, and public RSS preview without credentials.
- [x] Review requirement coverage and diff. Leave live forum acceptance explicitly unverified.

Local verification (2026-11-25): 38/38 tests passed with real loopback-only Chrome enabled; compileall, actionlint 1.7.12, diff whitespace check and offline preview passed. Branch publication and CI results are recorded in the handoff report.
