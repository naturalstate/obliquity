# Obliquity test lab

A throwaway **localhost-only** target set for exercising all four pillars.
Everything binds to `127.0.0.1`, weak creds are intentional. Two tiers:

- **Tier A — zero install (works now):** a pure-Python web target + hash
  fixtures. Covers **bust, fuzz, crack, brute(http)**.
- **Tier B — Docker (when installed):** real **FTP / SSH / SMB** for the other
  `brute` services. Requires Docker Desktop.

> Only run this against this lab. Point Obliquity at these local targets only.

---

## Tier A — no install

### 1. Web target (bust / fuzz / brute-http)

```bash
# from the repo root, with the venv active
python -m testlab.web                 # http://127.0.0.1:8000
# soft-404 / wildcard mode to test the flood guard:
OBLIQUITY_LAB_WILDCARD=1 python -m testlab.web
```

Then, in another terminal:

```bash
obliquity project create lab
obliquity project use lab
obliquity host add lab http://127.0.0.1:8000

# bust -- should find: admin, backup, api, uploads, config.php, robots.txt,
#         login, old, dev, test (whatever's in the wordlist)
obliquity bust run --gameplan generic-quick

# fuzz -- should find recognized param names: q, id, page, debug, search,
#         admin, api_key, redirect
obliquity fuzz run --gameplan parameter-names-quick --endpoint /search

# brute (http form) -- should recover admin/password123, user/letmein, root/toor
obliquity brute job add lab 127.0.0.1 --service http-post-form --name weblogin \
  --port 8000 --form-spec "/login:user=^USER^&pass=^PASS^:F=Login failed"
obliquity brute run weblogin
```

**Flood guard:** start the web target with `OBLIQUITY_LAB_WILDCARD=1`, then run a
bust -- every path returns 200, so Obliquity should detect the flood and offer
to re-run filtered.

### 2. Hash fixtures (crack)

```bash
python -m testlab.hashes              # writes testlab/fixtures/*
```

Produces `hashes-md5.txt` (`-m 0`), `hashes-sha1.txt` (`-m 100`),
`hashes-sha256.txt` (`-m 1400`), `hashes-ntlm.txt` (`-m 1000`), and
`answers.txt` (the key). 7 of 10 per file are common passwords (crackable with
rockyou / the bundled lists); 3 are random and won't crack.

```bash
obliquity crack job add lab testlab/fixtures/hashes-md5.txt --hash-type 0 --name md5
obliquity crack run md5 --gameplan quick-dictionary
# check answers.txt to confirm the 7 it should have cracked
```

---

## Tier B — Docker (FTP / SSH / SMB)

```bash
cd testlab
docker compose up -d          # web + ftp + ssh + smb, all on 127.0.0.1
docker compose down           # stop + remove
```

Credentials (all intentional):

| Service | Host:port | creds |
|---|---|---|
| FTP | 127.0.0.1:21 | `ftpuser`/`password123`, `admin`/`admin` |
| SSH | 127.0.0.1:2222 | `labuser`/`password123` |
| SMB | 127.0.0.1:445 | `smbuser`/`password123`, `admin`/`admin` |

```bash
obliquity brute job add lab 127.0.0.1 --service ftp  --name ftp  --port 21
obliquity brute run ftp                    # ftp-default plan -> ftpuser/admin

obliquity brute job add lab 127.0.0.1 --service ssh  --name ssh  --port 2222
obliquity brute run ssh

obliquity brute job add lab 127.0.0.1 --service smb  --name smb  --port 445
obliquity brute run smb
```

(The bundled `ftp-default` / `ssh-default` / `smb-default` loginplans use
service-appropriate username lists; `password123`/`admin` are in the bundled
`passwords-common.txt`, so they should be recovered.)
