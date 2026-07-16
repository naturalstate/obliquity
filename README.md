# Obliquity Bust MVP

Obliquity Bust is an MVP CLI for staged `feroxbuster` orchestration.

It is not a replacement for feroxbuster. It wraps feroxbuster with:

- project setup
- host tracking
- JSON gameplans
- sequential discovery stages
- completed-stage skipping
- resume behavior
- raw output archiving
- JSONL parsing
- SQLite storage
- basic HTML reporting

## Current scope

Included:

- `feroxbuster` adapter
- built-in gameplans
- SQLite state
- HTML report
- dry-run mode
- proxy/header support for Burp-style testing

Not included yet:

- wordlist compiler/deduper
- subdomain discovery
- ffuf API fuzzing
- hashcat cracking
- Burp extension
- GUI dashboard

## Requirements

- Python 3.10+
- feroxbuster installed and available in `PATH`
- SecLists installed at `/usr/share/seclists` for the default profiles

On Kali-like systems, SecLists is often available under `/usr/share/seclists`.
If your wordlists live elsewhere, copy a built-in JSON profile and edit the paths.

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

Preview the plan:

```bash
obliquity bust plan acme https://app.acme.com --gameplan aspnet-standard
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
```

Use arrow keys, Enter, Tab, Space, Escape, and the letter shortcuts to explore workflow screens, settings, review pages, a live dashboard, tables, sparklines, and a simulated terminal stream.

## Built-in gameplans

- `generic-quick`
- `generic-standard`
- `aspnet-standard`
- `php-standard`
- `api-quick`
- `smoke-test` (seven entries, non-recursive; intended only for installation/workflow checks)

Use a custom gameplan path instead of a built-in name:

```bash
obliquity bust run acme https://app.acme.com --gameplan ./examples/custom-gameplan.json
```

## How resume works

Each stage gets a fingerprint based on:

- target URL
- gameplan name
- stage name
- wordlist
- extensions
- recursion setting
- depth
- status codes
- extra args

If a stage completed successfully before, Obliquity skips it unless `--force` is used.

```bash
obliquity bust run acme https://app.acme.com --gameplan aspnet-standard --force
```

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

This MVP intentionally keeps the design simple. The next obvious feature is the wordlist compiler:

```bash
obliquity wordlists build
```

That would generate deduplicated staged lists such as `quick`, `standard-delta`, and `large-delta`.
