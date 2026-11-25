# Search and short-comment follow-up

User request: replace verbose replies with 3–5 character phrases, and fix discovery beyond the RSS's latest 20 entries.

1. Inspect official public HTML and actual guest search behavior. Completed: newest sort and pager, original creation time, title identity, `.content-item` author and stable comment IDs. Guest search redirects to Google; authenticated results remain to be accepted with an account.
2. Add failing tests for short comments, multi-source/page deduplication, old bumped posts, empty/repeated pages, unsafe next links, site errors, and read-only search preview. Implement pure HTML parsing plus the bounded browser discovery loop.
3. Integrate discovery into live mode and a separate `--search-preview`; keep RSS-only/offline preview. Preserve daily quota, permanent history, checkpoints, check-in independence and stopped-workflow boundaries.
4. Adapt loopback Chrome fixtures to observed public DOM, verify search pagination without editor writes, rerun quota/state tests, compileall and actionlint. Update README, existing draft PR and delivery notes with verified evidence and account acceptance limitations.

Defaults: five newest pages, two search pages for 抽奖, forty original inspections, three seconds between navigations. Optional term count <=5, search pages 1–3 and newest pages 1–20. No full-site/full-text guarantee; no automatic retries; no forum account actions during development.
