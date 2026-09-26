<div align="center">

<img src="../docs/images/banner.svg" alt="Obliquity" width="720">

### Test Lab

**A throwaway, localhost-only target set for exercising every Obliquity feature.**
Two full walkthroughs below — one in regular CLI mode, one in the interactive console.

[← Back to the main README](../README.md)

</div>

---

> ⚠️ **Authorized testing only.** Everything here binds to `127.0.0.1`, uses
> intentionally weak credentials, and is meant to be attacked *by you, on your
> own machine*. Point Obliquity at these local targets only.

Two tiers:

- **Tier A — zero install (works now):** a pure-Python web target + hash fixtures. Covers **bust, fuzz, crack, brute(http)**.
- **Tier B — Docker (optional):** real **FTP / SSH / SMB** for the network `brute` services.

All commands run from the repo root (`obliquity-main/`), and assume `obliquity`
is on your `PATH` (see the main README's install notes).

---

## Setup (do this once)

```bash
# from the repo root, in a spare terminal, start the web target and LEAVE IT RUNNING
python3 -m testlab.web                    # http://127.0.0.1:8000

# in another terminal: generate hash fixtures for the crack pillar
python3 -m testlab.hashes                 # -> testlab/fixtures/  (+ answers.txt)

# install the wordlists the built-in bust/crack gameplans use
obliquity wordlists install seclists-common seclists-big rockyou

# (optional) start the network services for FTP/SSH/SMB brute
cd testlab && docker compose up -d && cd ..
```

---

## Admin center & watching scans live

Sign in to the web target (default `admin` / `password123`) and open
**`/admin`** — a branded dashboard that:

- shows a **live request log** (auto-refreshing) so you can *watch a scan hit
  paths in real time* while `obliquity bust run` is going -- with a **full
  detailed log** page (`/admin/log`: client IP, bytes, user-agent) that holds up
  to 50,000 entries in a scrollable list, so a big scan really fills it;
- lets you **add paths** (dirs/files) and **parameters** at runtime — add
  `/secret/` and watch the next bust find it, or add a param and watch fuzz find it;
- lets you **import a config profile** (paste JSON) to reshape the site on the fly.

Mimic a real stack from the start with `--config`:

```bash
python3 -m testlab.web --config testlab/profiles/wordpress.json   # /wp-admin/, xmlrpc.php, /wp-login.php, wp params...
python3 -m testlab.web --verbose                                  # also print each request to the terminal
python3 -m testlab.web --access-log testlab/fixtures/access.log   # also write a real Apache-style logfile
```

Write your own profile (Joomla, Drupal, IIS/ASP.NET, an API, a client's stack)
using the format in [`testlab/profiles/README.md`](profiles/README.md).

---

# Mode 1 — Regular CLI

A complete run through every pillar and most features, top to bottom.

```bash
# --- project + host -------------------------------------------------------
obliquity doctor                                  # check installed tools
obliquity project create lab
obliquity project use lab                         # make it the active project
obliquity host add lab http://127.0.0.1:8000 --tech php --server apache
obliquity project list
obliquity project current                         # hosts, per-tool gameplans, options

# --- wordlists ------------------------------------------------------------
obliquity wordlists list
obliquity wordlists inspect seclists-common       # size / extensions / preview
obliquity gameplans list                          # every gameplan for every tool
obliquity explore                                 # TUI: browse gameplans + wordlists (q to quit)

# --- bust (content discovery) --------------------------------------------
obliquity bust plan --gameplan generic-quick      # preview stages, no execution
obliquity bust run --gameplan generic-quick       # finds admin, backup, config.php, robots.txt, login...
obliquity bust run --gameplan generic-standard    # bigger pass
obliquity bust run --gameplan generic-quick --filter-status 404   # noise control
obliquity bust resume --gameplan generic-standard # skip completed stages
# flood guard: restart the web target with  OBLIQUITY_LAB_WILDCARD=1  then:
obliquity bust run --gameplan generic-quick       # every path 200 -> detects flood, offers re-run

# --- fuzz (parameters) ----------------------------------------------------
obliquity fuzz run --gameplan parameter-names-quick --endpoint /search   # finds q, id, page, debug...

# --- crack (offline hashes) ----------------------------------------------
obliquity crack job add lab testlab/fixtures/hashes-md5.txt --hash-type 0 --name md5
obliquity crack job add lab testlab/fixtures/hashes-ntlm.txt --hash-type 1000 --name ntlm
obliquity crack plan md5 --gameplan quick-dictionary
obliquity crack run md5 --gameplan quick-dictionary     # cracks the 7 common ones
obliquity crack run md5 --gameplan rules-basic          # try rules
obliquity crack run ntlm --gameplan quick-dictionary
# compare against the key:
cat testlab/fixtures/answers.txt

# --- brute (online logins) -----------------------------------------------
obliquity brute job add lab 127.0.0.1 --service http-post-form --name weblogin \
  --port 8000 --form-spec "/login:user=^USER^&pass=^PASS^:F=Login failed"
obliquity brute run weblogin --gameplan weak-creds       # recovers admin/password123, user/letmein, root/toor
obliquity brute creds lab                                # list recovered creds
# Tier B (Docker) services:
obliquity brute job add lab 127.0.0.1 --service ftp --name ftp --port 21
obliquity brute run ftp  --gameplan weak-creds
obliquity brute job add lab 127.0.0.1 --service ssh --name ssh --port 2222
obliquity brute run ssh  --gameplan weak-creds
obliquity brute job add lab 127.0.0.1 --service smb --name smb --port 445
obliquity brute run smb  --gameplan weak-creds

# --- stored options (set once, run with no flags) ------------------------
obliquity set fuzz endpoint /search
obliquity set fuzz gameplan parameter-names-quick
obliquity options fuzz
obliquity fuzz run                                # uses the stored options

# --- project defaults (auto-load a gameplan per tool) --------------------
obliquity project set-gameplan bust generic-standard
obliquity project current

# --- reporting & review ---------------------------------------------------
obliquity coverage lab                            # what ran per host/tool
obliquity history lab                             # unified log across all pillars
obliquity report html lab --open                  # HTML report (dirs, params, creds, cracked)
obliquity report json lab
obliquity report csv lab --kind found-credentials
obliquity report markdown lab
```

---

# Mode 2 — Interactive console (REPL)

The exact same walkthrough, in `obliquity console`. Type commands **without** the
`obliquity` prefix; `use <tool>` selects a tool so bare `run`/`set`/`options` target it.

```text
obliquity console                                 # enter the REPL

# --- project + host -------------------------------------------------------
obliquity(no project) > project create lab
obliquity(no project) > project use lab
obliquity(lab) > host add lab http://127.0.0.1:8000 --tech php --server apache
obliquity(lab) > project current

# --- bust -----------------------------------------------------------------
obliquity(lab) > use bust
obliquity(lab:bust) > options
obliquity(lab:bust) > set gameplan generic-quick
obliquity(lab:bust) > plan
obliquity(lab:bust) > run
obliquity(lab:bust) > set gameplan generic-standard
obliquity(lab:bust) > run
obliquity(lab:bust) > back

# --- fuzz -----------------------------------------------------------------
obliquity(lab) > use fuzz
obliquity(lab:fuzz) > set gameplan parameter-names-quick
obliquity(lab:fuzz) > set endpoint /search
obliquity(lab:fuzz) > options
obliquity(lab:fuzz) > run
obliquity(lab:fuzz) > back

# --- crack ----------------------------------------------------------------
obliquity(lab) > crack job add lab testlab/fixtures/hashes-md5.txt --hash-type 0 --name md5
obliquity(lab) > use crack
obliquity(lab:crack) > set gameplan quick-dictionary
obliquity(lab:crack) > run md5
obliquity(lab:crack) > back

# --- brute ----------------------------------------------------------------
obliquity(lab) > brute job add lab 127.0.0.1 --service http-post-form --name weblogin --port 8000 --form-spec "/login:user=^USER^&pass=^PASS^:F=Login failed"
obliquity(lab) > use brute
obliquity(lab:brute) > set gameplan weak-creds
obliquity(lab:brute) > run weblogin
obliquity(lab:brute) > creds lab
obliquity(lab:brute) > back

# --- review & quit --------------------------------------------------------
obliquity(lab) > coverage lab
obliquity(lab) > history lab
obliquity(lab) > report html lab --open
obliquity(lab) > help
obliquity(lab) > exit
```

---

## What it should find (expected results)

| Pillar | Command | Expected |
|---|---|---|
| **bust** | `bust run --gameplan generic-quick` | `admin`, `backup`, `config.php`, `robots.txt`, `login`, `api`, `uploads` … |
| **fuzz** | `fuzz run … --endpoint /search` | param names: `q`, `id`, `page`, `debug`, `search`, `admin`, `api_key`, `redirect` |
| **crack** | `crack run md5` | the 7 common passwords in `answers.txt` (3 random ones won't crack) |
| **brute** | `brute run weblogin --gameplan weak-creds` | `admin`/`password123`, `user`/`letmein`, `root`/`toor` |
| **flood** | `OBLIQUITY_LAB_WILDCARD=1` + `bust run` | flood detected → offers to re-run filtered |

## Docker services & credentials (Tier B)

| Service | Host:port | credentials |
|---|---|---|
| FTP | `127.0.0.1:21` | `ftpuser`/`password123`, `admin`/`admin` |
| SSH | `127.0.0.1:2222` | `labuser`/`password123` |
| SMB | `127.0.0.1:445` | `smbuser`/`password123`, `admin`/`admin` |

## Cleanup

```bash
docker compose -f testlab/docker-compose.yml down   # stop network services
# Ctrl-C the web target; then optionally:
obliquity project delete lab --yes
rm -rf testlab/fixtures
```
