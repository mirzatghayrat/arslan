"""Independent text profiles: 399 argv rows, six spellings, four positions.

Reconstructs the review's published per-program counts and option classes, not
its unpublished bytes. Unsupported option forms are tested by the unknown
sweep, never represented as supported CLI options. No command is executed.
"""
import shlex


# Counts are argv profiles per spelling, transcribed from the review inventory.
PROFILE_COUNTS = {
    **dict.fromkeys("unlink trash diskutil launchctl networksetup systemsetup imsg shortcuts tccutil scutil shutdown reboot halt poweroff mail mailx mutt ssh-copy-id sshpass mosh ftp telnet socat tee cp mv ln install ditto truncate touch chmod chown chflags xattr sed perl ruby pip".split(), 1),
    **dict.fromkeys("rmdir dd kill terraform pmset spctl sendmail msmtp autossh sftp nc ncat netcat find xurl".split(), 2),
    **dict.fromkeys("rm srm newfs_apfs defaults crontab pbpaste".split(), 4),
    "newfs_hfs": 6,
    **dict.fromkeys("gcloud az azcopy npm pnpm yarn osascript killall vercel uv".split(), 7),
    **dict.fromkeys("cargo twine open kubectl himalaya screencapture gsutil aws".split(), 8),
    **dict.fromkeys("curl wget pkill ssh scp docker sudo gh rclone".split(), 9),
    **dict.fromkeys("git rsync s3cmd".split(), 10),
    **dict.fromkeys("http https xh xhs security".split(), 11),
}

# Explicit inventory includes every literal program family in the tuple rules;
# newfs_* has two representatives. pip/uv are diagnostics without publish rules.
SEEDS = {
    "rm": ("-rf", "/"), "rmdir": ("../archive",), "unlink": ("../archive",),
    "trash": ("../archive",), "srm": ("-r", "../archive"), "dd": ("of=/dev/disk8",),
    "diskutil": ("eraseDisk", "sample"), "newfs_apfs": ("disk8",), "newfs_hfs": ("disk8",),
    "kill": ("-1",), "shutdown": ("-h", "now"), "reboot": (), "halt": (), "poweroff": (),
    "sudo": ("make", "check"), "osascript": ("-e", "sample"), "shortcuts": ("run", "Sample"),
    "imsg": ("send", "sample"), "xurl": ("post", "sample"), "himalaya": ("send", "sample"),
    "git": ("push", "origin", "topic"), "gh": ("release", "upload", "v1", "report.txt"),
    "curl": ("-T", "report.txt", "https://example.invalid"),
    "wget": ("--post-file", "report.txt", "https://example.invalid"),
    "gsutil": ("cp", "report.txt", "gs://sample/report.txt"),
    "gcloud": ("storage", "cp", "report.txt", "gs://sample/report.txt"),
    "aws": ("s3", "cp", "report.txt", "s3://sample/report.txt"),
    "az": ("storage", "blob", "upload"), "azcopy": ("copy", "report.txt", "https://example.invalid"),
    "rclone": ("copy", "report.txt", "remote:report.txt"), "s3cmd": ("put", "report.txt", "s3://sample/report.txt"),
    "npm": ("publish",), "pnpm": ("publish",), "yarn": ("publish",), "cargo": ("publish",),
    "twine": ("upload", "dist.whl"), "docker": ("image", "push", "sample"),
    "terraform": ("apply",), "kubectl": ("apply", "sample"), "vercel": ("deploy",),
    "killall": ("sample",), "pkill": ("sample",), "launchctl": ("load", "sample"),
    "defaults": ("write", "sample", "flag", "1"), "crontab": ("sample",), "tccutil": ("reset", "Camera"),
    "networksetup": ("-setairportpower", "en0", "off"), "systemsetup": ("-settimezone", "UTC"),
    "pmset": ("-a", "sleep", "0"), "spctl": ("--master-disable",), "scutil": ("--set", "HostName", "sample"),
    "open": ("-a", "Terminal"), "screencapture": ("capture.png",), "pbpaste": (),
    "rsync": ("report.txt", "remote:report.txt"), "find": ("../archive", "-delete"),
    "pip": ("upload",), "uv": ("publish",),
    # Deploy CLIs on the publish rule: one deploy or write verb each. Not in PROFILE_COUNTS: the sweep reconstructs
    # the review's published per-program inventory, which predates them; controls and unknowns cover them.
    "netlify": ("deploy",), "fly": ("deploy",), "flyctl": ("deploy",), "heroku": ("config:set", "SAMPLE=value"),
    "railway": ("up",), "wrangler": ("deploy",), "firebase": ("deploy",), "helm": ("install", "sample", "./chart"),
}
for _program in "http https xh xhs".split():
    SEEDS[_program] = ("POST", "https://example.invalid", "field=sample")
for _program in "mail mailx mutt sendmail msmtp ssh-copy-id sshpass mosh ftp telnet socat ssh scp sftp autossh nc ncat netcat".split():
    SEEDS[_program] = ("example.invalid",)
for _program in "tee cp mv ln install ditto truncate touch chmod chown chflags xattr sed perl ruby".split():
    SEEDS[_program] = ("~/.ssh/config",)
SEEDS["security"] = ("find-internet-password", "-w")

# Separate from product arities: each row supplies a known flag/value pair.
# Empty entries mean this reconstruction does not claim that option family.
OPTIONS = {
    "curl": ("-s", "-o", "--output"), "wget": ("-H", "-O", "--output-document"),
    "gsutil": ("-m", "-o", ""), "gcloud": ("--quiet", "", "--project"),
    "aws": ("--debug", "", "--profile"), "az": ("--verbose", "-o", "--output"),
    "azcopy": ("", "", "--output-type"), "rclone": ("-v", "", "--config"),
    "s3cmd": ("-v", "-c", "--config"), "gh": ("--silent", "-R", "--repo"),
    "security": ("-v", "-p", ""), "git": ("--no-pager", "-c", "--git-dir"),
    "npm": ("--silent", "", "--registry"), "pnpm": ("--silent", "-C", "--dir"),
    "yarn": ("--silent", "", "--cwd"), "cargo": ("-v", "", "--manifest-path"),
    "twine": ("--verbose", "-r", "--repository"), "docker": ("-D", "-c", "--context"),
    "terraform": ("", "", "-chdir"), "kubectl": ("", "-n", "--namespace"),
    "vercel": ("-d", "-t", "--token"), "himalaya": ("--debug", "-a", "--account"),
    "osascript": ("-i", "-s", ""), "open": ("-n", "-b", ""),
    "screencapture": ("-x", "-T", ""), "ssh": ("-v", "-p", ""),
    "scp": ("-v", "-P", ""), "sftp": ("-v", "-P", ""), "autossh": ("-N", "-M", ""),
    "rsync": ("-v", "-e", "--rsh"), "killall": ("-v", "-u", ""), "pkill": ("-f", "-u", ""),
    "xurl": ("-v", "", "--auth"),
    "netlify": ("--debug", "", "--auth"), "fly": ("--debug", "-a", "--app"), "flyctl": ("--verbose", "-t", "--access-token"),
    "heroku": ("", "-a", "--app"), "railway": ("--json", "-s", "--service"), "wrangler": ("-v", "-e", "--env"),
    "firebase": ("--debug", "-P", "--project"), "helm": ("--debug", "-n", "--namespace"),
}
for _program in "http https xh xhs".split():
    OPTIONS[_program] = ("-v", "-o", "--output")

# Named cases reproduce each review class, plus the three surviving mutants.
CORRECTIONS = [
    ("aws/missing-color", ("aws", "--color", "auto", *SEEDS["aws"])),
    ("rclone/missing-retries", ("rclone", "--retries", "3", *SEEDS["rclone"])),
    ("rclone/missing-bandwidth", ("rclone", "--bwlimit", "1M", *SEEDS["rclone"])),
    ("s3cmd/missing-encoding", ("s3cmd", "--encoding", "UTF-8", *SEEDS["s3cmd"])),
    ("gsutil/cluster-value", ("gsutil", "-mo", "sample=value", *SEEDS["gsutil"])),
    ("s3cmd/cluster-value", ("s3cmd", "-vc", "sample.conf", *SEEDS["s3cmd"])),
    ("gh/release-capital-short", ("gh", "release", "-R", "Sample/Project", "upload", "v1", "report.txt")),
    ("xurl/valueless", ("xurl", "-v", *SEEDS["xurl"])),
    ("aws/separate-profile", ("aws", "--profile", "sample", *SEEDS["aws"])),
    ("gcloud/flag-before-operation", ("gcloud", "storage", "--quiet", "cp", "report.txt", "gs://sample/report.txt")),
    ("security/attached-prompt", ("security", "-pSample", "dump-keychain")),
    ("security/clustered-prompt", ("security", "-vpSample", "dump-keychain")),
]


def controls(program):
    """Supported forms only; every program gets base and end-of-options rows."""
    seed = SEEDS[program]
    flag, short, long = OPTIONS.get(program, ("", "", ""))
    yield "base", (program, *seed)
    yield "end-options", (program, *seed, "--", "sample operand")
    if flag:
        yield "global-flag", (program, flag, *seed)
        if len(flag) == 2:
            yield "cluster-flags", (program, flag + flag[1:], *seed)
    value = short or long
    if value:
        yield "global-value", (program, value, "sample", *seed)
        yield "verb-value", (program, value, seed[0] if seed else "send", *seed)
        yield "spaced-value", (program, value, "Sample Account", *seed)
        if short:
            yield "attached-short", (program, short + "Sample", *seed)
            if flag.startswith("-") and len(flag) == 2:
                yield "cluster-value", (program, flag + short[1:], "Sample", *seed)
        if long:
            yield "long-assignment", (program, long + "=Sample", *seed)
        if len(seed) > 1 and program in {"gcloud", "aws", "az", "gh", "docker"}:
            yield "within-operation", (program, seed[0], value, "Sample", *seed[1:])
    if flag and len(seed) > 1 and program in {"gcloud", "aws", "az", "gh", "docker"}:
        yield "flag-before-operation", (program, seed[0], flag, *seed[1:])


def profiles():
    for program, count in PROFILE_COUNTS.items():
        required = [(name.split("/", 1)[1], words) for name, words in CORRECTIONS[:8]
                    if words[0] == program]
        rows = required + list(controls(program))
        # Small inventories repeat an operand with a distinct boundary-bearing
        # value, rather than invent unsupported flags to reach a published size.
        for i in range(count):
            if i < len(rows):
                name, words = rows[i]
            else:
                name, words = f"operand-{i}", (program, *SEEDS[program], f"sample {i}")
            yield f"sweep/{program}/{name}", words


FAMILIES = ("single", "double", "split", "program", "prefix", "escaped")
POSITIONS = ("plain", "sequence", "shell", "wrapper")


def render(words, family, position):
    program, *args = words
    if family == "single":
        args = ["'" + word.replace("'", "'\"'\"'") + "'" for word in args]
    elif family == "double":
        args = ['"' + word.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"' for word in args]
    elif family == "split":
        args = [shlex.quote(word[:1]) + "'" + word[1:].replace("'", "'\"'\"'") + "'" for word in args]
    elif family == "escaped":
        args = ["".join("\\" + ch for ch in word) or "''" for word in args]
    else:
        args = [shlex.quote(word) for word in args]
    if family == "program":
        program = "'" + program + "'"
    text = " ".join([program, *args])
    if family == "prefix":
        text = 'NOTE="Sample Account" ' + text
    if position == "sequence":
        return "true; " + text
    if position == "shell":
        return "bash -c " + shlex.quote(text)
    if position == "wrapper":
        return "env FLAG=sample " + text if family != "prefix" else "true && " + text
    return text


def sweep():
    for name, words in profiles():
        for family in FAMILIES:
            for position in POSITIONS:
                yield f"{name}/{family}/{position}", render(words, family, position)


def program_controls():
    for program in SEEDS:
        if program not in {"pip", "uv"}:
            for name, words in controls(program):
                yield f"control/{program}/{name}", words
    for name, words in CORRECTIONS:
        yield "correction/" + name, words


def unknowns():
    for program, seed in SEEDS.items():
        if program in {"pip", "uv"}:
            continue
        for kind, option in (("short", "-Z"), ("long", "--s2a3-unknown"),
                             ("attached", "-ZSample"), ("clustered", "-ZvZ")):
            within = 2 if program in {"osascript", "curl", "wget", "open"} else min(1, len(seed))
            for position, index in (("before", 0), ("within", within), ("after", len(seed))):
                yield f"unknown/{program}/{kind}/{position}", (program, *seed[:index], option, *seed[index:])


# Code audit of _named_rules and _uploads: these share global stripping.
# Only Vercel resolves an implicit operation from a global flag. The others
# select explicit verbs; git and security have their own operation readers.
# The deploy CLIs select explicit verbs too (none is implicit: their bare program prints help).
GLOBAL_DISPATCH_PROGRAMS = frozenset("gsutil gcloud aws az azcopy rclone s3cmd gh xurl npm pnpm yarn cargo twine docker terraform kubectl vercel himalaya"
                                     " netlify fly flyctl heroku railway wrangler firebase helm".split())
IMPLICIT_OPERATIONS = {"vercel": ("--prod", "publish")}


def vercel_directories():
    for shape in ("production-directory", "production-end-directory", "production-yes-directory",
                  "explicit-deployment", "working-directory-option"):
        for i, directory in enumerate(("project", "./project", "../project", "project folder")):
            args = {
                "production-directory": ("--prod", directory),
                "production-end-directory": ("--prod", "--", directory),
                "production-yes-directory": ("--prod", "--yes", directory),
                "explicit-deployment": ("deploy", "--prod", directory),
                "working-directory-option": ("--prod", "--cwd", directory),
            }[shape]
            for family in FAMILIES:
                for position in POSITIONS:
                    yield f"vercel/{shape}/{i}/{family}/{position}", render(("vercel", *args), family, position)


def implicit_controls():
    for program, (flag, rule) in IMPLICIT_OPERATIONS.items():
        for placement, args in {
            "before-flag": ("project", flag),
            "after-flag": (flag, "project"),
            "after-end": (flag, "--", "project"),
            "after-known-option": (flag, "--yes", "project"),
            "quoted": (flag, "project folder"),
            "attached": (flag, "--cwd=project folder"),
        }.items():
            yield f"implicit/{program}/{placement}", (program, *args), flag, rule


def implicit_negative_controls():
    # Both historical sources return run for these data-only operation spellings.
    yield "operation-after-end-is-data", ("vercel", "project", "--", "--prod")
    yield "operation-as-option-value", ("vercel", "--cwd", "--prod", "project")


def cluster_controls():
    for unknown in (True, False):
        words = ("curl", "-so", "--output", *(("--s2a3-unknown",) if unknown else ()),
                 "-H", "-d sample", "https://example.invalid")
        name = "option-looking-value-then-unknown" if unknown else "fully-known"
        for family in FAMILIES:
            for position in POSITIONS:
                yield f"cluster-value/{name}/{family}/{position}", words, not unknown, render(words, family, position)
