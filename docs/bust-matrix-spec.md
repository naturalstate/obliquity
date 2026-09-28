# Bust Matrix — Design Spec

Status: **draft for review** · Scope: `bust` pillar only · No code yet.

Generalize a bust gameplan from "several wordlists against one host" into a
**matrix** of scan units over three axes — **targets × wordlists × config** —
executed on a **schedule**. Decisions already made:

- Targets are supplied **at run time** (`-iL` / `--targets`), not baked into the
  gameplan. A gameplan stays target-agnostic and reusable across engagements.
- Default schedule is **target-major, in file order** (finish a host before the
  next one).

---

## 0. This is entirely opt-in

Nothing about a normal single-host bust changes. `obliquity bust run <project>
<url>` behaves exactly as it does today. The matrix only activates when the user
*asks* for it, by supplying more than one scan unit. Specifically, it kicks in
when the user wants to:

- scan **more than one host**, or
- scan **more than one directory** on one or more hosts, or
- vary **settings** (extensions, recursion, filters, …) across those targets, or
- run **multiple wordlists** across multiple hosts.

If none of that is asked for, there is no matrix — it's a single cell, identical
to current behavior. No new required flags, no changed defaults, no migration.
The features below are opportunities the user reaches for only when they have
this shape of work.

---

## 1. Model

A **scan unit** is the atomic thing feroxbuster runs once:

```
scan unit = (target, stage)
target    = base URL, i.e. host + optional path      e.g. https://ex.com/dir1/
stage     = wordlist + config (extensions, recursion, filters)  ← today's Stage
```

A **run** expands to the cartesian product of the target list and the gameplan's
stages:

```
run  =  { (t, s)  for t in targets  for s in gameplan.stages }
```

Every case the user described is one shape of this product:

| Case | targets | stages |
|---|---|---|
| multi-wordlist (today) | 1 | N |
| multi-host, one list | host1,host2,host3 | 1 |
| multi-host, list+ext | host1,host2,host3 | big + dirbuster(w/ ext) |
| multi-directory | ex.com/, ex.com/d1/d2/, ex.com/d1/d2/api/… | 1 |
| nested / repeated sweep | those dirs | common, then raft-large, … |

**Key simplification:** a *target is just a base URL*. feroxbuster already scans
by appending wordlist entries to a base URL, so "multi-directory" needs **no new
scanning concept** — it is simply more targets that share a host. Nesting =
a deeper path. Same host may appear many times with different paths.

---

## 2. Targets

### 2.1 What a target is
A base URL string: `scheme://host[:port][/path/]`. The path (if any) is the
directory feroxbuster scans *from*. Examples:

```
https://example.com/
https://example.com/dir1/dir2/
https://example.com/dir1/dir2/api/resources/1/users/home/
http://10.0.0.5:8080/admin/
```

### 2.2 Where targets come from (precedence, highest first)
1. `-iL <file>` / `--targets-file <file>` — one target per line.
2. `--targets "<a>,<b>,<c>"` — inline, comma-separated.
3. positional `<url>` — the single-target case (unchanged, back-compatible).
4. If none given: the project's existing hosts (current behavior — one host).

`-iL` and `--targets` may be combined; the lists concatenate in that order.

### 2.3 Target file format
- One target per line.
- Blank lines and lines starting with `#` are ignored (comments).
- Leading/trailing whitespace trimmed.
- A bare host (`example.com`, `example.com/dir/`) with no scheme defaults to
  `https://` (matches existing `require_host` behavior).
- Duplicate targets (after normalization) are de-duplicated with a note; order
  of first occurrence is kept.

`-iL` is the nmap/ffuf-familiar switch; we keep it as the primary spelling with
`--targets-file` as a long alias.

### 2.4 Normalization
- Add `https://` when scheme is missing.
- Preserve the path exactly (do **not** strip a trailing `/`; feroxbuster treats
  `/dir` and `/dir/` differently).
- `host_id` for storage/reporting is derived from scheme+host+port only, so
  `ex.com/` and `ex.com/dir1/` map to the **same host** but distinct scan units.

### 2.5 Relationship to project hosts
- Each distinct host (scheme+host+port) is registered once in the project (as
  today, via `add_host`), so findings link to it and reports group by host.
- The **path** is per-scan-unit, not stored on the host row; it lives in the
  scan unit's URL and therefore in the run fingerprint (§5).
- Ad-hoc targets from `-iL` are auto-added to the project (with a printed note),
  consistent with today's "Added host to project" behavior.

---

## 3. Schedule

Two independent knobs on how the product is ordered.

### 3.1 Order (of the target list)
`--order {in-order|reverse|random}` — default **in-order** (file/inline order).
`random` accepts an optional `--seed <int>` for reproducibility.

### 3.2 Nesting (how targets and stages interleave)
`--nesting {target-major|wordlist-major}` — default **target-major**.

- **target-major** (default): for each target, run all stages, then next target.
  *Finish a host before moving on* — the natural pentest default.
  ```
  t1·s1  t1·s2  t1·s3   t2·s1  t2·s2  t2·s3   …
  ```
- **wordlist-major**: for each stage, run it across all targets, then next stage.
  *Breadth-first* — a quick common.txt pass over everything before deeper lists.
  ```
  t1·s1  t2·s1  t3·s1   t1·s2  t2·s2  t3·s2   …
  ```

Order applies to the target axis in both nesting modes.

---

## 4. CLI surface

Added to `bust run` / `bust plan` / `bust resume` (they share `bust_scan_args`):

```
-iL, --targets-file PATH     file of targets, one host[+path] per line
     --targets "a,b,c"       inline comma-separated targets
     --order {in-order,reverse,random}     default: in-order
     --seed INT              seed for --order random (reproducible)
     --nesting {target-major,wordlist-major}   default: target-major
```

Unchanged:
- Positional single `<url>` still works and means a one-target run.
- All existing per-stage override flags (`--depth`, `--no-recurse`, filters,
  `--no-extract-links`, `--ferox-ui`, rate/threads/proxy/header) apply to
  **every** scan unit in the matrix, as they do today.

Stored options (Metasploit-style `set`): `--order` and `--nesting` are
persistable per project; target lists are not stored (they're per-engagement),
matching the runtime-targets decision.

---

## 5. Fingerprinting, resume, dedup

The run fingerprint already keys on the full URL and the stage
([gameplan.py:68](../obliquity/core/gameplan.py)). Because a target's path is
part of its URL, **every (target, stage) cell fingerprints uniquely for free**:

- `ex.com/` + common ≠ `ex.com/dir1/` + common ≠ `ex.com/` + raft-large.
- `resume` skips completed cells and runs only the missing ones.
- A repeated identical target collapses to one cell (dedup).

No schema change is required for correctness. (Optional later: a `batch`/`run
group` id to report a whole matrix as one logical run.)

---

## 6. Execution UX

- **Dry-run** (`--dry-run`) prints the fully expanded matrix in execution order,
  numbered `unit k/K  (target i/T · stage j/S)`, with the command per cell — so
  the user can eyeball the plan before committing.
- **Live progress**: the existing one-line bar gains a target counter, e.g.
  `Target 2/3 ex.com/dir1  ·  Stage 1/2 raft  [####----] 41% …`.
- **`--ferox-ui`**: unchanged semantics — each *cell* hands the terminal to
  feroxbuster in turn; Obliquity's header/summary bracket each cell.
- **Run summary**: totals across the matrix (cells completed/skipped/failed,
  new findings), plus a per-host findings rollup.

---

## 7. Reporting

- Findings continue to link to a host; multi-directory targets on one host
  aggregate under that host, with the discovering base path recorded on the
  finding's source/URL (already stored).
- The HTML report groups by host; a matrix run adds a small "scanned bases"
  line per host so it's clear which directories were swept.

---

## 8. Presets (separate, follow-on)

"simple / medium / large, with/without extensions/recursion" is a
**wordlist-bundle** concern, orthogonal to the matrix. Presets are just
gameplans; this spec does **not** require new preset machinery to ship the
matrix. Proposed as a fast-follow once the matrix lands:

- `simple`  → common.txt, no ext, no recurse
- `medium`  → raft-medium-directories + light ext, shallow recurse
- `large`   → raft-large + ext + recurse

They'd live alongside today's `generic-quick`/`generic-deep` and be selectable
with the existing `--gameplan` / `set bust gameplan`.

---

## 9. Backward compatibility

- No positional/flag removed; a plain `bust run <project> <url>` behaves exactly
  as today (single-cell matrix).
- Existing gameplans load unchanged (targets come from the CLI/project, not the
  file).
- Existing fingerprints/resume data stay valid (URL-keyed).

---

## 10. Implementation plan (milestones, each independently revertible)

1. **Target expansion** — parse `-iL`/`--targets`/positional into a normalized,
   de-duplicated target list; register hosts; build the (target × stage) matrix;
   target-major/in-order only. Wire into `run_gameplan` and dry-run. *(Delivers
   multi-host and multi-directory immediately.)*
2. **Schedule** — add `--order` (in-order/reverse/random+seed) and `--nesting`
   (target-major/wordlist-major); stored-options support.
3. **UX polish** — matrix-aware dry-run listing, target counter in the progress
   line, per-host summary/report rollup.
4. **Presets** (optional fast-follow) — `simple/medium/large` gameplans.

Tests per milestone: target-file parsing (comments/dedup/scheme defaulting),
matrix expansion counts, schedule ordering (all four order×nesting combos),
resume-skips-completed-cells, and back-compat single-URL.

---

## 11. Open questions

1. **Scope for path targets + recursion.** If a target has a path and the stage
   enables recursion, feroxbuster recurses *below that path*. Assumed desired —
   confirm. (In-scope host is still the bare host.)
2. **Per-host vs global rate limit.** `--rate-limit` currently applies per
   feroxbuster process = per cell. With many cells on one host run sequentially
   that's fine; if we ever parallelize hosts, we'd want a per-host cap. Keep
   sequential for now?
3. **Auto-registering many ad-hoc hosts** from a big `-iL` file — okay to add
   them all to the project silently (with a count note), or gate behind a
   confirm/`--add-hosts`?
4. **Matrix run grouping** — do you want a single "batch id" so `history` shows
   one matrix run as a unit, or is per-cell history (today's model) fine?
