"""The full Obliquity manual, rendered in-terminal by `obliquity manual`.

A reformatted, command-oriented version of the README so users have the whole
reference offline and cross-platform (including Windows, where `man` isn't
available). The same content is shipped as a roff man page at
`docs/obliquity.1` for `man obliquity` on Linux/macOS.
"""

from __future__ import annotations

from obliquity.core.console import blank, c, section, subsection


# (heading, [(command, description), ...]) -- the single source for the
# in-terminal manual. Kept concise: one line per command with a real example.
SECTIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("OVERVIEW", "",
     [("obliquity <command> --help", "detailed help for any command"),
      ("obliquity doctor", "check that feroxbuster/ffuf/hashcat/hydra are installed")]),
    ("PROJECTS & HOSTS", "One project groups many hosts/jobs, results, and settings.",
     [("obliquity project create acme", "create a project"),
      ("obliquity project use acme", "make it the active project (so you can omit its name)"),
      ("obliquity project list", "list projects with host/job/run counts"),
      ("obliquity project current", "show the active project: hosts, metadata, per-tool gameplans, options"),
      ("obliquity project unset", "clear the active project"),
      ("obliquity project archive acme --yes", "back up files + drop the DB record"),
      ("obliquity project delete acme --yes", "permanently delete (no backup)"),
      ("obliquity host add acme https://app.acme.test --tech php --server apache", "add a host with metadata"),
      ("obliquity host list acme", "list a project's hosts")]),
    ("STATEFUL OPTIONS (Metasploit-style)", "Set options once, then run with no flags. Flags still override.",
     [("obliquity set fuzz endpoint /search", "store an option on the active project"),
      ("obliquity options fuzz", "show a tool's options (OPTION/VALUE/REQUIRED/SOURCE)"),
      ("obliquity unset fuzz endpoint", "clear one option"),
      ("obliquity project set-gameplan bust generic-deep", "set the default gameplan for a tool")]),
    ("bust -- content discovery (feroxbuster)", "Staged directory/file discovery.",
     [("obliquity bust", "list bust gameplans"),
      ("obliquity bust run acme --gameplan generic-quick", "run (host optional if only one)"),
      ("obliquity bust run acme --depth 3", "override recursion depth"),
      ("obliquity bust run acme --filter-status 404,500", "drop noisy status codes"),
      ("obliquity bust plan acme --gameplan aspnet-standard --dry-run", "preview the exact commands"),
      ("obliquity bust resume acme", "skip completed stages, retry the rest")]),
    ("fuzz -- parameter/API fuzzing (ffuf)", "Fuzz parameter names/values or a raw request.",
     [("obliquity fuzz", "list fuzz gameplans"),
      ("obliquity fuzz run acme --gameplan parameter-names-quick --endpoint /search", "fuzz parameter names"),
      ("obliquity fuzz run acme --gameplan parameter-values-quick --template '/search?q=FUZZ'", "fuzz a value"),
      ("obliquity fuzz run acme --gameplan api-request-quick --request req.txt", "fuzz inside a raw request")]),
    ("crack -- offline hash cracking (hashcat)", "Staged password cracking against a hash file.",
     [("obliquity crack job add acme ./hashes.txt --hash-type 1000 --name ntlm", "add a hash file as a job"),
      ("obliquity crack run acme --gameplan quick-dictionary", "run a crackplan"),
      ("obliquity crack resume acme --gameplan standard", "resume mid-keyspace from hashcat's checkpoint")]),
    ("brute -- online login attacks (thc-hydra)", "Live credential attacks against a service.",
     [("obliquity brute job add acme 10.0.0.5 --service ssh --name ssh-box", "add a login target"),
      ("obliquity brute job add acme app.test --service http-post-form --form-spec \"/login:user=^USER^&pass=^PASS^:F=invalid\"", "web login form"),
      ("obliquity brute run acme ssh-box --gameplan common-creds", "run a loginplan"),
      ("obliquity brute creds acme", "list recovered credentials")]),
    ("WORDLISTS", "A small downloadable catalog + an explorer.",
     [("obliquity wordlists list", "show the catalog and install status"),
      ("obliquity wordlists inspect raft-medium-files.txt", "size, extensions, preview of a list"),
      ("obliquity wordlists install seclists-common rockyou", "download catalog entries"),
      ("obliquity explore", "interactive TUI: browse gameplans + wordlists (Enter loads a gameplan)")]),
    ("REPORTS & HISTORY", "One shared database per project; several output formats.",
     [("obliquity coverage acme", "what's been run per host/tool"),
      ("obliquity history acme", "unified log across all four pillars"),
      ("obliquity report html acme --open", "generate + open the HTML report"),
      ("obliquity report json|csv|markdown acme", "other export formats")]),
]

INTRO = (
    "Obliquity is a CLI that orchestrates penetration-testing tools in four "
    "pillars -- bust (feroxbuster), fuzz (ffuf), crack (hashcat), brute "
    "(thc-hydra) -- with projects, staged gameplans, resume, and unified "
    "reporting. Each pillar only needs its own tool installed."
)

FOOTER = (
    "Full docs & source: https://github.com/naturalstate/obliquity\n"
    "On Linux/macOS you can also install the man page (see the README) for "
    "'man obliquity'."
)


def print_manual() -> None:
    section("OBLIQUITY MANUAL", "cyan")
    for line in _wrap(INTRO):
        print(line)
    for heading, blurb, rows in SECTIONS:
        subsection(heading, "magenta")
        if blurb:
            print(c(blurb, "gray"))
        for cmd, desc in rows:
            print(f"  {c(cmd, 'yellow', bold=True)}")
            print(f"      {desc}")
    blank()
    section("MORE", "cyan")
    for line in FOOTER.split("\n"):
        print(c(line, "gray"))


def _wrap(text: str, width: int = 78) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width)


def _roff_escape(text: str) -> str:
    # roff: leading '.'/'\'' are control chars; backslash is the escape char.
    return text.replace("\\", "\\\\").replace("-", "\\-")


def render_manpage() -> str:
    """Generate the roff (man) source from the same SECTIONS, so `man obliquity`
    and `obliquity manual` never drift. Regenerate docs/obliquity.1 with:
        python -c "from obliquity.manual import render_manpage; \
                   open('docs/obliquity.1','w').write(render_manpage())"
    """
    out = [
        '.TH OBLIQUITY 1 "" "Obliquity" "Obliquity Manual"',
        ".SH NAME",
        "obliquity \\- staged orchestration of feroxbuster, ffuf, hashcat, and thc-hydra",
        ".SH SYNOPSIS",
        ".B obliquity",
        ".I command",
        "[options]",
        ".SH DESCRIPTION",
        _roff_escape(INTRO),
    ]
    for heading, blurb, rows in SECTIONS:
        out.append(".SH " + _roff_escape(heading.upper()))
        if blurb:
            out.append(_roff_escape(blurb))
        for cmd, desc in rows:
            out.append(".TP")
            out.append(".B " + _roff_escape(cmd))
            out.append(_roff_escape(desc))
    out.append(".SH SEE ALSO")
    out.append("Full docs and source: https://github.com/naturalstate/obliquity")
    return "\n".join(out) + "\n"
