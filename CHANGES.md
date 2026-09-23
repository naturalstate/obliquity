# Obliquity session notes -- 2026-09-22

This documents everything changed in this session: what was done, why, in
what order, and which decisions were yours vs. judgment calls I made. Second
half is the prioritized roadmap built from the original planning doc you
shared, cross-referenced against what actually exists in the code today.

Git was not in use before this session (`git init` was the first action
taken). All work below is in 5 commits on `main`; `git log --stat` has the
full diffs. Nothing has been pushed anywhere -- this is all local.

---

## Part 1 -- Changelog

### 0. Before git existed (folded into the initial commit)

You asked how to get the tool running on your Mac. In the course of that:

- Set up a venv, installed `feroxbuster`/`ffuf`/`hashcat` via Homebrew.
- Added `require_host()` to `cli.py` so `bust plan/run/resume` don't require
  retyping the host URL when a project only has one host -- you asked for
  this explicitly ("I shouldn't have to type all of that back in again").

This is commit `885a94b` ("Initial commit: Obliquity Bust MVP baseline") --
the starting snapshot for everything below, including the above.

### 1. Full codebase review

Read every module and test file, ran the existing 19 tests (all passing),
and produced a list of issues, labeled A1-A5 (small fixes), B (multi-host +
friendly names), C9 (no-arg help), D (hashcat/crack). You asked me to
explain A1-A5 in detail before touching anything, which I did -- no code
changed in this phase.

**Your instruction on B:** hold off entirely -- you're still designing how
multi-host/sequential scanning should interact with gameplans, and didn't
want me guessing at that design. **B is still untouched.**

### 2. Commit `0a613d1` -- A2, A4, C9

- **A2**: `bust {plan,run,resume}` and `fuzz {run,resume}` previously
  hand-duplicated ~20 `add_argument()` calls per subcommand (with a dead,
  abandoned loop in the old code that tried and gave up on copying them
  automatically). Replaced with shared parent `ArgumentParser`s
  (`project_host_args`, `bust_scan_args`, `fuzz_scan_args`). Side effect:
  `bust resume` gained `--report`/`--open-report`, which it had been
  missing purely because nobody remembered to hand-add it -- direct proof
  of why the duplication was a real bug generator, not just untidy.
- **A4**: `fuzz run`/`fuzz resume` now use the same optional-host resolution
  `bust` already had. You confirmed: "globally I only want users to define a
  host/IP once, then they just run the project."
- **C9**: `obliquity` with zero arguments now prints help and exits 0,
  instead of an argparse error. You flagged this directly.

**A3 (original plan: demote hashcat to "optional" in `doctor` since nothing
used it yet) was superseded** -- you said hashcat/crack was a real pillar,
not a stub, so it was built for real instead (see next section), and stayed
listed as a **required** core tool in `doctor`, which is now accurate.

### 3. Commit `2931fa8` -- `crack` (hashcat) as a third pillar

You clarified the tool's original intent: three pillars, one tool each --
**bust** (feroxbuster), **fuzz** (ffuf), **crack** (hashcat) -- with staged
execution, auto-detection of completion, and automatic retry with a
different wordlist/rules/mask on to the next stage. hashcat had zero
implementation before this (confirmed when you asked "did we add hashcat
functionality yet at all?" -- no, it did not exist).

Built to match the existing bust/fuzz architecture exactly:

- `obliquity/adapters/hashcat.py` -- builds dictionary (`-a 0`) and mask
  (`-a 3`) attack commands.
- `obliquity/core/crackplan.py` -- `CrackStage`/`CrackPlan`, same
  stage-fingerprint-and-skip resume model as `gameplan.py`, keyed on hash
  file + hash type + attack params instead of a URL.
- `obliquity/core/crack_runner.py` -- staged execution with
  **hashcat-specific exit-code handling**, different from feroxbuster's:
  exit 1 ("exhausted this wordlist, hashes remain") is a normal stage
  completion that falls through to the next stage, not a failure; exit 0
  (everything cracked) stops the plan early since later stages have
  nothing left to find; exit 2/130 (aborted) and anything else stop it as
  a real problem.
- New DB tables `crack_jobs`/`crack_runs`/`cracked_hashes` -- a "crack job"
  (a hash file) plays the role a host plays for bust/fuzz. Cracking has no
  URL to key off of, so it got its own table rather than overloading
  `hosts`.
- CLI: `crack job add/list/remove`, `crack plan/run/resume`. Built-in
  crackplans: `smoke-test` (bundled tiny wordlist, no external deps --
  used to prove the integration works at all), `quick-dictionary` and
  `standard` (rockyou-based).
- `reporting.py`: added Cracked Hashes / Crack Runs sections to the report.

**Bug caught live, not in review:** I ran an actual crack against a real MD5
hash of `password123` to demonstrate this. hashcat's raw log showed
`Recovered: 1/1 (100.00%)` -- it cracked it -- but Obliquity reported
"Newly cracked: 0". Root cause: `--outfile-format 2` writes plaintext only,
no hash, and my parser expected `hash:plaintext`. **`--outfile-format` is a
comma-separated list of codes, not a summable bitmask** -- `3` alone
produces `hex_plain`, not `hash:plain`. Fixed to `1,2` (`hash[:salt]` +
`plain`), re-ran, confirmed `Newly cracked: 1`. This is exactly why the live
terminal demo mattered instead of just trusting the code read-through.

You separately caught that the HTML report's `<h1>` still said "Obliquity
Bust Report" even though it now also shows fuzz/crack data -- fixed to
"Obliquity Report" (the `<title>` tag was already generic; only the
visible heading was stale).

I also ran a real `fuzz`/ffuf scan at your request, in the visible
terminal, to prove that pillar works too. It returned 0 findings against
the local static test server -- verified this is *correct* (ffuf's
autocalibration filtering out identical baseline responses), not a bug, by
independently running raw `ffuf` against a target that *does* return
different responses per path and confirming it does emit real JSON matches.

### 4. Commit `9bb3360` -- README catch-up

README still described Obliquity as feroxbuster-only and listed "hashcat
cracking" under Not Included Yet. Updated: three-pillar framing, the
optional-host behavior, a full crack usage section, updated built-in
gameplan list, and the future gobuster/wfuzz/john backends explicitly
framed as **deferred until bust/fuzz/crack are solid** -- your instruction
("We'll add the three backup tools when we're done with the tool").

### 5. Commit `4ab3d07` -- downloadable wordlist catalog

You asked whether Obliquity offers to download SecLists if missing (it
didn't -- README just said "git clone it yourself") and asked for that,
plus links to other popular wordlists, offered during setup.

- `obliquity/core/wordlists.py` -- a small **curated** catalog (not an
  attempt to mirror all of SecLists): `seclists-common`, `seclists-big`,
  two raft directory lists, DirBuster medium, `rockyou`, and hashcat's
  rules file. Downloaded individually via stdlib `urllib` (no new
  dependency) into `~/.obliquity/wordlists/<same-path-suffix-the-profile-
  uses>`. `rockyou` comes from SecLists' `.tar.gz` form (GitHub's 100MB
  file limit means it isn't stored unpacked there) and is extracted on
  download.
- `gameplan.py`/`fuzzplan.py`/`crackplan.py` loaders now fall back to a
  downloaded copy when a profile's hardcoded `/usr/share/...` path doesn't
  exist -- **no profile JSON edits needed** once a wordlist is installed.
- CLI: `wordlists list/status/install/setup`. `project create` now checks
  for missing defaults and, **only when run interactively** (`stdin.isatty()`
  gated so scripts/CI aren't blocked waiting on input), offers to download
  them right there -- this is the "Obliquity asks during setup" behavior
  you asked for.
- `wordlists list` prints links to the full SecLists repo and Assetnote's
  wordlist site for anything outside the small catalog, rather than trying
  to automate those (Assetnote's lists are large, technology-specific,
  multi-file collections -- a link is the right fit, not a download button).

**Bug caught while verifying download URLs, not guessed:** checked the real
hashcat GitHub repo before hardcoding a URL, and found hashcat upstream
renamed `best64.rule` to `best66.rule` -- the old name doesn't exist there
anymore. `crack_profiles/standard.json` was still referencing the dead
name; fixed to `best66.rule`.

**Live demo:** asked your permission before actually downloading anything
(per my own operating rules -- downloads need explicit confirmation). You
chose "small only." Ran `obliquity wordlists install seclists-common` live
in the terminal, confirmed the real 4,751-line file landed, `wordlists
status` no longer listed it as missing, and `bust plan` for `generic-quick`
picked up the local copy automatically with zero config changes.

### Test coverage added this session

19 -> 40 passing tests. New files: `tests/test_hashcat.py`,
`tests/test_crackplan.py`, `tests/test_wordlists.py`. All network calls in
tests are mocked -- nothing in the test suite hits the real internet.

### Explicitly parked, not forgotten

- **B (multi-host + sequential scanning + friendly host names)** -- on hold
  per your instruction, pending your own gameplan-feature design work.
- **A5 (broader test coverage for `database.py`/`reporting.py`/CLI
  handlers)** -- you said you weren't sure yet, need to research; untouched.
- **gobuster/wfuzz/john alternate backends** -- explicitly deferred by you
  until bust/fuzz/crack are solid.
- **Wordlist compiler/deduper** (`obliquity wordlists build`) -- still just
  a stated future feature, nothing built.

---

## Part 2 -- Roadmap from the planning doc

Your planning doc describes a considerably larger vision than what exists
today. Here's every section of it, honestly marked against current state,
grouped into priority tiers. "Done" means it actually works today, not that
it's planned. Updated to fold in the second planning-doc drop (Output and
Reporting, expanded Obliquity Fuzz, expanded Obliquity Crack, Burp Suite
integration, cross-tool data sharing).

### Tier 1 -- builds directly on what already exists, moderate effort each

| Feature (from planning doc) | Status | Notes |
|---|---|---|
| Host/Application Awareness -- auto-recommend a plan from host metadata (`bust plan app1` suggesting a gameplan from `--server`/`--tech`) | Not built | `host add` already stores `--server`/`--tech`/`--profile`/`--notes`; nothing reads them to *choose* a gameplan yet. `bust plan` only previews a gameplan you already named. This is a mapping table + a recommender function -- the data it needs is already being collected and just sitting unused. **This is what we agreed to build next.** |
| Extension Intelligence -- don't double-append extensions to a wordlist that already has them; intensity-tiered extension sets (low/medium/high) reusable across profiles | Not built | Gameplan JSON stages specify a flat `extensions` list by hand today, no logic distinguishing directory-only wordlists from ones with baked-in extensions. Real correctness gap the doc calls out specifically. |
| Wordlist Scheduling escalation -- common -> big -> raft-medium -> raft-large -> CMS/tech-specific, as the doc's example sequence | Partially built | Gameplans already run stages in order and skip completed ones (this *is* the scheduling engine). What's missing is built-in profiles that actually use the escalation the doc describes -- `big.txt` and the raft lists are already in the wordlist catalog (this session) but no built-in gameplan stage references them yet. Low effort now that the downloader exists. |
| Structured export formats -- JSON, CSV, Markdown alongside the existing HTML report | Not built | `get_findings`/`get_cracked_hashes`/`get_runs` already return the structured rows every one of these formats would need; this is serialization, not new data collection. Cheapest item on the whole list. Raw tool output and SQLite storage (also on the doc's format list) already exist today. |
| Crack hybrid/combinator attack modes (`?u?l?l?l?l?d?d?d` appended to a wordlist, or combinator of two wordlists) | Not built | `CrackStage.attack_mode` currently only supports `dictionary` (`-a 0`) and `mask` (`-a 3`); hashcat's hybrid (`-a 6`/`-a 7`) and combinator (`-a 1`) modes aren't wired up. Same shape as the existing two modes -- small addition to `hashcat.py`'s `ATTACK_MODES` map and `CrackStage` validation, not a new subsystem. |

### Tier 2 -- valuable, needs real design decisions, bigger lift

| Feature | Status | Notes |
|---|---|---|
| Intensity/profile taxonomy (`quick`/`standard`/`full`/`insane`/`ctf`/`stealth`) | Partially built | Named built-in gameplans exist (`generic-quick`, `aspnet-standard`, etc.) but there's no formal "intensity" concept separate from picking a specific gameplan file. Could start as sugar over gameplan selection, formalize later. |
| Recursive Discovery -- auto-queue follow-up scans against newly-found interesting directories (`/admin`, `/backup`, `/api`), with `--max-depth`/`--max-jobs-per-host`/`--only-recurse-interesting` | Not built | feroxbuster's own `--depth`/recursion flag is used per-stage, but Obliquity itself doesn't feed findings back into new queued work. This is a real new runner capability -- a feedback loop from findings to the stage queue -- with real termination/noise-control design needed. |
| Multi-host / `--all-hosts` sequential scanning, friendly host names | Parked (your call) | This is item **B** from earlier -- intentionally held until your gameplan design is settled, since the doc's own examples (`--all-hosts`, `--intensity`) show it's tightly coupled to whatever the gameplan/intensity model ends up being. |
| HTML report filters -- only-200s, only-403s, unusual content length, new findings only, by host/base-path/wordlist/tool | Not built | The current report is static generated HTML with plain tables, no client-side interactivity. Needs either JS-based filtering baked into the generated page, or a served/dynamic report instead of a flat file -- a real design decision, not just more rows in a table. |
| Cross-tool findings feedback loop -- e.g. a directory `bust` finds automatically becomes a target `fuzz` tests | Partially built at the storage layer, not automated | `bust` (feroxbuster) and `fuzz` (ffuf) already write into the **same** `findings` table today, so the data is already co-located per project -- but nothing reads bust's results and automatically queues fuzz work from them. The doc's "newly discovered endpoints fed into another tool" is a real orchestration feature still to build, not just a schema change. |
| Project export/import -- move or reopen a project on another machine | Partially built, partially not | Reopening/resuming a project **on the same machine** already works with zero new code -- there's no "closed" state, `bust resume`/`crack resume`/`fuzz resume` just pick up where they left off via the existing fingerprint model. Moving a project **to a different machine** is not built: `~/.obliquity/projects/<name>` and the single global `obliquity.db` are both tied to one machine today, and there's no `project export`/`project import` that packages a project's DB rows + its `runs/` output directory into a portable bundle. |
| Hash-type auto-identification (`hashid`/`name-that-hash`-style) instead of requiring `--hash-type` by hand | Not built | `crack job add` requires you to already know the hashcat `-m` mode number. Auto-detecting from the hash's shape (length, charset, prefix) is a bounded, well-understood problem -- could shell out to `hashid`/`name-that-hash` as optional tools, or implement basic pattern matching directly. |
| Indefinite crack campaign mode (`--campaign full --until-complete`, runtime/budget/GPU-temp limits) | Not built | Current `crack run` executes a fixed, finite crackplan and stops. An open-ended "keep going until X" mode is a different execution model layered on top of the existing staged runner, not a replacement for it. |
| Recon-tool-sourced fuzz targets (`katana`, `gau`, `waybackurls`, `httpx` feeding endpoint lists into fuzz gameplans) | Not built | `fuzz` today only takes an endpoint/template/request you already know about. Sourcing endpoints from crawling/wayback tools first is several new tool integrations plus a new "route collection" stage type before fuzzing even starts. |
| Request-based auto fuzz-point detection (parse a raw Burp request, auto-identify query params/POST fields/JSON fields/headers/cookies/path segments/IDs as candidate fuzz points) | Not built | `fuzz run --request` today fuzzes wherever *you* put the `FUZZ` marker in the raw request -- there's no parsing of the request to suggest fuzz points itself. A real, self-contained parsing feature; doesn't require any other tool integration first. |

### Tier 3 -- larger architectural changes, revisit after Tier 1/2

| Feature | Status | Notes |
|---|---|---|
| Full profile composition (CMS + tech + auth + noise-tolerance + time-budget as independent, combinable axes, rather than one static JSON file per combination) | Not built | Today a gameplan is a fixed, hand-written JSON file. The doc envisions something closer to a plan *compiler* -- combine "aspnet" + "high intensity" + "unauthenticated" into a generated stage list. Bigger rearchitecture of the gameplan model itself; only worth doing once Tier 1's extension intelligence and Tier 2's intensity taxonomy exist to compose from. |
| Alternate-tool backends (gobuster/wfuzz/john) | Parked (your call) | Explicitly deferred until bust/fuzz/crack are solid. |
| Wordlist compiler/deduper (`obliquity wordlists build` -- generate deduplicated `quick`/`standard-delta`/`large-delta` staged lists) | Not built | Still just the README's stated "next obvious feature," unchanged this session. |
| Burp-compatible export (push discovered paths/findings into a Burp-importable sitemap/project format) | Not built | Needs the actual Burp import format researched and matched correctly before building -- not something to guess at. One-directional (Obliquity -> Burp) piece of the larger Burp integration below; could ship standalone before the rest of it. |
| Granular crack progress state -- potfile location, remaining-hash count, estimated completion, attack history as first-class tracked fields | Partially built | `crack_jobs`/`crack_runs`/`cracked_hashes` already track job/stage/status/exit-code/cracked results (this session). What's missing is finer-grained per-hash-file progress (how many of N hashes remain right now, not just per-stage completion) and explicit potfile path tracking. |
| API-endpoint gameplan pipeline (known routes -> JS-discovered routes -> wayback history -> fuzz common paths -> versioned paths -> resource names -> methods -> hidden params -> export, chained end to end) | Not built | This chains several of the Tier 2 items above (recon-tool sourcing, request parsing, hybrid fuzzing) into one gameplan-style flow. Worth doing once those individual pieces exist, not before -- trying to build the whole chain at once would mean building all of Tier 2's fuzz items simultaneously. |
| cewl/crunch-generated wordlists feeding crack gameplans | Not built | `cewl` (crawl a target, generate a wordlist from its content) and `crunch` (generate wordlists from a mask/charset) are both new tool integrations. Straightforward adapters individually (same shape as the hashcat adapter), but there's no target-content-crawling capability in Obliquity yet for `cewl` to run against. |

### Tier 4 -- Burp Suite integration (a separate subsystem, not a CLI feature)

The doc's Burp integration is categorically different from everything else on
this list: it requires committing to a **Burp extension** (a separate
codebase in whatever language/SDK Burp extensions use), plus a **local HTTP
API server running inside Obliquity** for that extension to talk to, plus a
stable request/response contract between them. Every other item above is
"add a feature to the existing CLI/DB"; this is "build and maintain a second
piece of software with its own packaging and versioning." Not recommending
this until the CLI-side tool (bust/fuzz/crack) is mature, per your own
"we'll add the backup tools when we're done with the tool" instruction on a
smaller version of the same principle.

- **Burp -> Obliquity**: send a host/request/sitemap/parameters/auth context
  from Burp into Obliquity to seed a project and build a gameplan from it.
- **Obliquity -> Burp**: push discovered paths into Burp's sitemap, send
  interesting requests to Repeater, export findings as a Burp-importable
  project. (The plain Burp-compatible *export* piece, without the live
  extension/API bridge, is listed separately in Tier 3 above and could ship
  first, standalone.)

### Already solid (from the doc, done before or during this session)

- Project-based target management: projects, multiple hosts per project,
  per-host `--server`/`--tech`/`--profile`/`--notes` metadata.
- Deduplication and state tracking: stage fingerprinting keyed on target +
  gameplan + wordlist + extensions + recursion + depth + status codes +
  extra args (bust), and the crack-specific equivalent keyed on hash file +
  hash type + attack params. Completed stages are skipped; resume works.
- JSON gameplans, sequential staged execution, raw output archiving, JSONL
  parsing, SQLite storage, unified HTML reporting -- all three pillars now.
- Shared storage across tools: bust and fuzz findings already live in the
  same `findings` table per project (not yet an active feedback loop, but
  the "one shared DB per project" foundation the doc asks for is real).
- Resuming a project after walking away from it: already works today with
  no explicit close/reopen step, via the same fingerprint-and-skip model --
  just re-run `bust resume`/`crack resume`/`fuzz resume` whenever you come
  back to it. (Moving that project to a *different machine* is not solved
  yet -- see the project export/import row in Tier 2.)

---

*Generated from the actual git history and conversation log for this
session. Re-run `git log --stat` on this repo for the underlying diffs.*
