# Lab config profiles

Load one to make the web target mimic a specific server / CMS:

    python -m testlab.web --config testlab/profiles/wordpress.json

...or paste a profile's JSON into the **admin center** (`/admin`) at runtime.

## Format

```json
{
  "server":     {"name": "...", "header": "Apache/2.4", "powered_by": "PHP/8.1"},
  "login_path": "/wp-login.php",           // where the brute form lives
  "fail_marker":"ERROR: ...",              // hydra F= string for a failed login
  "creds":      [["admin","password123"]], // valid username/password pairs
  "params":     ["s","p","page_id"],       // param names fuzz should find at /search
  "paths": {                                // dirs/files bust should find
    "/wp-admin/":     {"status": 302, "body": "..."},
    "/wp-config.php.bak": {"status": 200, "body": "...", "ctype": "text/plain"}
  }
}
```

Everything merges onto the defaults, so a profile only needs the parts it changes.
Add your own to replicate a client's stack (Joomla, Drupal, IIS/ASP.NET, an API, ...).
