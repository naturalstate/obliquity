# Obliquity Bust MVP

Obliquity Bust is an MVP CLI for staged penetration-testing tool orchestration,
built around three pillars, each wrapping a separate underlying tool:

- **bust** -- staged content discovery via `feroxbuster`
- **fuzz** -- parameter/API fuzzing via `ffuf`
- **crack** -- staged hash cracking via `hashcat`

It is not a replacement for any of those tools. It wraps them with:

- project setup
- host/job tracking
- JSON gameplans
- sequential staged execution
- completed-stage skipping
- resume behavior
- raw output archiving
- JSONL parsing
- SQLite storage
- unified HTML reporting across bust/fuzz/crack

## Current scope

Included:

- `feroxbuster` adapter (bust)
- `ffuf` adapter (fuzz)
- `hashcat` adapter (crack)
- built-in gameplans/crackplans
- SQLite state
- unified HTML report
- dry-run mode
- proxy/header support for Burp-style testing

Not included yet:

- wordlist compiler/deduper
- subdomain discovery
- Burp extension
- GUI dashboard
- alternate-tool backends (`gobuster`, `wfuzz`, `john`) as swappable
  alternatives to feroxbuster/ffuf/hashcat -- planned once bust/fuzz/crack
  are solid, defaulting to the current tools

## Requirements

- Python 3.10+
- `feroxbuster`, `ffuf`, and `hashcat` installed and available in `PATH`
  (`obliquity doctor` checks for all three)
- SecLists installed at `/usr/share/seclists` for the default bust/crack profiles
  (rockyou.txt is used as the default crack wordlist) -- or let Obliquity
  download the specific files it needs, see **Wordlist setup** below

On Kali-like systems, SecLists is often available under `/usr/share/seclists`.
If your wordlists live elsewhere, copy a built-in JSON profile and edit the paths.
On macOS, install the tools with Homebrew: `brew install feroxbuster ffuf hashcat`.

## Wordlist setup

Obliquity doesn't require the full SecLists repo -- it can download just the
specific files its built-in gameplans reference (a handful of individual
files, not a multi-GB clone), stored under `~/.obliquity/wordlists/`. A
built-in gameplan that references e.g. `/usr/share/seclists/...` will
automatically fall back to the downloaded copy if that system path doesn't
exist, with no profile edits needed.

`obliquity project create` checks for missing default wordlists and offers
to download them right there if run interactively; otherwise (or any time
later) run it explicitly:

```bash
obliquity wordlists status                  # what's missing
obliquity wordlists setup                   # interactive: ask per wordlist
obliquity wordlists install seclists-common rockyou   # install specific ones
obliquity wordlists install --all-missing   # install everything referenced by built-ins
obliquity wordlists list                    # full catalog + install status
```

`rockyou` is the largest catalog entry (~50MB download, ~133MB extracted) and
is only needed for the crack gameplans beyond `smoke-test`. For anything
outside this small catalog -- CMS-specific lists, Assetnote's
technology-specific collections, etc. -- `obliquity wordlists list` prints
links to the full SecLists repo and Assetnote's wordlist site; download those
yourself and point a custom gameplan JSON at them, the same way `bust run
... --gameplan ./my-plan.json` already works.

## Install locally

From inside this folder:

```bash
python3 -m pip install -e .
```

You can also run without installing:

```bash
python3 -m obliquity.cli --help
```

## First run

Create a project:

```bash
obliquity project create acme
```

Add a host:

```bash
obliquity host add acme https://app.acme.com --profile aspnet --server iis --tech aspnet
```

Preview the plan. `--gameplan` is optional -- with `--tech`/`--server`/
`--profile` on the host (as above), Obliquity recommends a matching
built-in gameplan (`aspnet-standard` here) instead of always defaulting to
`generic-quick`; the summary shows why (`recommended: tech=aspnet`), and an
explicit `--gameplan` always overrides it:

```bash
obliquity bust plan acme https://app.acme.com
```

Dry-run the feroxbuster commands:

```bash
obliquity bust run acme https://app.acme.com --gameplan aspnet-standard --dry-run
```

Run the plan:

```bash
obliquity bust run acme https://app.acme.com --gameplan aspnet-standard
```

Resume later:

```bash
obliquity bust resume acme https://app.acme.com --gameplan aspnet-standard
```

The host URL is only needed when a project has more than one host. If a
project has exactly one host, every `bust`/`fuzz` `plan`/`run`/`resume`
command will use it automatically:

```bash
obliquity bust run acme --gameplan aspnet-standard
```

Generate report:

```bash
obliquity report html acme
```

Generate and open the report automatically after a successful scan:

```bash
obliquity bust run acme https://app.acme.com --gameplan generic-quick --open-report
```

Archive an old project before reusing its name:

```bash
obliquity project archive acme --yes --if-exists
```

Project files are moved to `~/.obliquity/archive/` and the active database record is removed.

The report will be written to:

```text
~/.obliquity/projects/acme/report.html
```

## Burp proxy example

```bash
obliquity bust run acme https://app.acme.com \
  --gameplan generic-quick \
  --proxy http://127.0.0.1:8080 \
  --header 'Cookie: session=replace-me'
```

## ffuf parameter and API fuzzing

Feroxbuster is used for content discovery. ffuf is used when the fuzz value belongs inside a request: parameter names, parameter values, or a raw API request body.

List ffuf gameplans:

```bash
obliquity gameplans list
```

Discover accepted GET parameter names:

```bash
obliquity fuzz run acme https://app.acme.com \
  --gameplan parameter-names-quick \
  --endpoint /search
```

Fuzz values for a known parameter:

```bash
obliquity fuzz run acme https://app.acme.com \
  --gameplan parameter-values-quick \
  --template '/search?q=FUZZ'
```

Fuzz a raw request captured from Burp:

```bash
obliquity fuzz run acme https://api.acme.com \
  --gameplan api-request-quick \
  --request ./request.txt
```

Review operation coverage across tools:

```bash
obliquity coverage acme
obliquity coverage acme https://api.acme.com
```

## Hash cracking (crack / hashcat)

Feroxbuster and ffuf discover web content and parameters. hashcat cracks
password hashes gathered during an engagement (dumped NTLM hashes, captured
hashes, etc.), staged the same way bust/fuzz gameplans are: try a plain
dictionary first, then the same dictionary with rules, then fall back to a
mask -- each stage runs only if the previous one didn't recover everything.

Add a hash file as a crack job (a hash file plays the role a host URL plays
for bust/fuzz -- give it a name so you don't have to keep typing the path):

```bash
obliquity crack job add acme ./dumped-hashes.txt --hash-type 1000 --name ntlm-dump
```

`--hash-type` is hashcat's `-m` mode number (e.g. `0` = MD5, `1000` = NTLM,
`1800` = sha512crypt -- see `hashcat --help` for the full list).

List crack jobs, and built-in crackplans:

```bash
obliquity crack job list acme
obliquity gameplans list
```

Preview, dry-run, and execute a crackplan (the job name is optional the same
way the host URL is, when the project has exactly one job):

```bash
obliquity crack plan acme --gameplan quick-dictionary
obliquity crack run acme --gameplan quick-dictionary --dry-run
obliquity crack run acme --gameplan standard --open-report
```

Resume later (completed stages are skipped, same fingerprinting model as
bust, keyed on hash file + hash type + attack parameters instead of a URL):

```bash
obliquity crack resume acme --gameplan standard
```

A hashcat exit code of 1 ("exhausted this wordlist/mask, hashes remain")
is treated as a normal stage completion, not a failure -- that's what lets
a crackplan fall through to its next stage automatically.

Check core and optional tools:

```bash
obliquity doctor
```

Feroxbuster, ffuf, and hashcat are core tool recommendations. Missing tools produce warnings, but Obliquity remains installable and each operation checks for its own executable when run. Gobuster, wfuzz, and John are optional adapters for future expansion.

## Textual UI demo

The repository includes a standalone fake-data terminal UI playground. It does not run tools or write the Obliquity database. Install its optional dependency and launch it with:

```bash
python -m pip install -r requirements-tui-demo.txt
python -m obliquity.tui_demo

# Minimal terminal-style experiment
python -m obliquity.tui_terminal_demo

# Posting-inspired keyboard UI experiment
python -m obliquity.tui_posting_demo
```

Use arrow keys, Enter, Tab, Space, Escape, and the letter shortcuts to explore workflow screens, settings, review pages, a live dashboard, tables, sparklines, and a simulated terminal stream.

## Built-in gameplans

Bust (feroxbuster):

- `generic-quick`
- `generic-standard`
- `aspnet-standard`
- `php-standard`
- `api-quick`
- `smoke-test` (seven entries, non-recursive; intended only for installation/workflow checks)

Fuzz (ffuf): `parameter-names-quick`, `parameter-values-quick`, `api-request-quick`.

Crack (hashcat):

- `quick-dictionary` (single rockyou pass)
- `standard` (rockyou, then rockyou+best66 rules, then a policy-shaped mask)
- `smoke-test` (tiny bundled wordlist, no SecLists needed; for verifying the hashcat integration works)

Use a custom gameplan path instead of a built-in name:

```bash
obliquity bust run acme https://app.acme.com --gameplan ./examples/custom-gameplan.json
```

## How resume works

Each bust stage gets a fingerprint based on:

- target URL
- gameplan name
- stage name
- wordlist
- extensions
- recursion setting
- depth
- status codes
- extra args

Crack stages are fingerprinted the same way, but keyed on hash file + hash
type instead of a URL, plus attack mode / wordlist / rules / mask.

If a stage completed successfully before, Obliquity skips it unless `--force` is used.

```bash
obliquity bust run acme https://app.acme.com --gameplan aspnet-standard --force
obliquity crack run acme --gameplan standard --force
```

`bust resume`/`crack resume` always skip completed stages silently -- that's
their whole job. A plain `bust run`/`crack run` is different: if you run it
interactively and the *entire* gameplan/crackplan has already completed
against the target, Obliquity stops before doing anything, tells you when it
last finished and what it found, and offers the next step up a small
escalation ladder (`generic-quick` -> `generic-standard`,
`quick-dictionary` -> `standard`) -- accept with `y`. Decline that (or
there's no escalation defined yet) and it falls back to an explicit
"rerun anyway?" confirmation. This only triggers for a real terminal
session; scripts and `--force`/`--dry-run` runs are unaffected.

## Scan history

```bash
obliquity history acme
obliquity history acme --tool hashcat
obliquity history acme --status failed --limit 20
```

A single readable log across bust/fuzz/crack -- timestamp, tool, status,
target, gameplan/stage, finding count, and duration per run. (`obliquity
runs` still exists as the lower-level bust/fuzz-only view.)

## Data location

By default, Obliquity stores data here:

```text
~/.obliquity/
```

Override with:

```bash
export OBLIQUITY_HOME=/path/to/workdir
```

## Notes

This MVP intentionally keeps the design simple. Two planned follow-ups:

- a wordlist compiler/deduper (`obliquity wordlists build`) that would
  generate deduplicated staged lists such as `quick`, `standard-delta`,
  and `large-delta`
- alternate-tool backends -- `gobuster` as an alternative to feroxbuster,
  `wfuzz` as an alternative to ffuf, `john` as an alternative to hashcat --
  selectable per run, defaulting to the current feroxbuster/ffuf/hashcat
  trio
