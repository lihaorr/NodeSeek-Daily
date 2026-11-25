# Lottery reply design

User settings: identify new lottery/giveaway posts, prepare ten Chinese participation comments, at most ten successful replies per Asia/Shanghai day, no new eligible posts means no replies.

Use the site's public RSS for read-only keyword discovery (title and excerpt), then recheck the current first post in the existing browser before publishing. RSS currently contains only 20 items: this is bounded discovery, not exhaustive historical/forum search. New means published within 24 hours, a valid canonical NodeSeek post URL, and not previously processed. Exclude ended draws, discussions about lottery software, external-only participation and specified reply formats. The original post must explicitly allow a general reply to participate; ambiguity is skipped.

Retain Selenium and installed-Chrome version matching. Preview is the default and never starts a browser, signs in, publishes, or writes state. Live mode requires an explicit flag and a numeric forum user ID for account/reply verification. Browser challenges and unexpected markup stop actions; no challenge bypass is introduced. Check-in runs independently before comments and is recorded only when confirmed.

Store per-post pending/confirmed/unknown outcomes permanently. Reserve and checkpoint before each click; only a newly visible exact reply by the configured account counts as confirmed. Unknown submissions stop the batch and occupy quota until reviewed. Successful records count against the Beijing dates crossed during submission. Persistent state uses atomic local JSON or GitHub Contents API with SHA conflict checks and a workflow-wide concurrency group. Never silently reset corrupt state. Migrate only the verified empty version-1 legacy state.

Development does not publish forum replies, enable scheduled workflows, or merge into main. Deliver a tested feature branch and configuration documentation.
