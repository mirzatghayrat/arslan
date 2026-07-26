#!/usr/bin/env bash
# Assert that a freshly built sidecar bundle is fit to ship (S4.3-a).
#
# Run by build_dmg.sh right after PyInstaller, BEFORE anything is signed or
# staged — every check here is cheap, and every one of them corresponds to a
# way a bundle can look fine and be broken:
#
#   1. --selftest       every feature module actually imports. /health returning
#                       200 does NOT prove this: the app boots happily with
#                       half its features unloadable. An earlier revision of
#                       arslan-server.spec excluded PIL, which took the whole
#                       PPTX deck feature down in a bundle that served 200s.
#   2. no AGPL          pymupdf/fitz must never reach a distributed build.
#   3. no databases     a .db shipped inside the .app would be someone else's
#                       data, and would also shadow the real one.
#   4. no secrets       .env / *.key / api_token must not be swept in.
#
# Exits non-zero with a named reason. Usage:
#   packaging/verify_bundle.sh path/to/dist/arslan-server
set -euo pipefail

BUNDLE="${1:?usage: verify_bundle.sh <bundle-dir>}"
EXE="$BUNDLE/arslan-server"
fail() { echo "verify_bundle: $*" >&2; exit 1; }

[ -d "$BUNDLE" ] || fail "no such bundle dir: $BUNDLE"
[ -x "$EXE" ]    || fail "no executable at $EXE"

echo "==> [1/4] selftest (every feature module imports)"
# HOME is redirected so the run cannot touch the developer's real brain or
# mint a secret into their ~/.arslan.
SELFTEST_HOME="$(mktemp -d)"
trap 'rm -rf "$SELFTEST_HOME"' EXIT
if ! HOME="$SELFTEST_HOME" "$EXE" --selftest; then
  fail "selftest failed — see the module list above; something the app needs is not in the bundle"
fi

echo "==> [2/4] no AGPL rasterizer"
# -iname on the whole tree, not just _internal/: a stray dylib or dist-info
# anywhere is still shipped. Note "pil" is a substring of "compiler", so match
# these names precisely rather than with a bare *PIL* glob.
for pat in 'pymupdf*' 'fitz*' 'libmupdf*'; do
  hits="$(find "$BUNDLE" -iname "$pat" 2>/dev/null || true)"
  [ -z "$hits" ] || fail "AGPL component in the bundle ($pat):\n$hits"
done

echo "==> [3/4] no databases"
hits="$(find "$BUNDLE" \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) 2>/dev/null || true)"
[ -z "$hits" ] || fail "database file(s) inside the bundle:\n$hits"

echo "==> [4/4] no secrets"
hits="$(find "$BUNDLE" \( -name '.env' -o -name '*.p12' -o -name '*.p8' \
        -o -name 'api_token' -o -name 'secret_key' -o -name 'crypto_salt' \) 2>/dev/null || true)"
[ -z "$hits" ] || fail "secret-shaped file(s) inside the bundle:\n$hits"

echo "verify_bundle: OK ($(du -sh "$BUNDLE" | cut -f1))"
