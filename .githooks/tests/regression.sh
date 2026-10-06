#!/bin/bash
# Regression suite for the personal-information hooks.
# Usage: .githooks/tests/regression.sh [HOOKDIR]; exits 1 when any case has the wrong outcome.
# A "bad" case must be BLOCKED; an "ok" case must be ALLOWED. Synthetic values are built
# at run time so this file passes its own hooks.
set -u
HOOKS=$(cd "${1:-$(dirname "$0")/..}" && pwd)
BASE=$(mktemp -d "${TMPDIR:-/tmp}/hookreg.XXXX")
export PYTHONDONTWRITEBYTECODE=1 GIT_CONFIG_NOSYSTEM=1 HOME="$BASE/hh-qzx"
mkdir -p "$HOME"
AT=$(printf '\100'); HM=/ho; BAD="dev${AT}acme-corp.io"
NR=1+bot@users.noreply.github.com
fresh() {
  R="$BASE/$1"; rm -rf "$R" "$R.git"; git init -q --bare "$R.git"; git init -q "$R"; cd "$R"
  git config user.email "$NR"; git config user.name bot; git config commit.gpgsign false
  mkdir .githooks && find "$HOOKS" -maxdepth 1 -type f -exec cp -t .githooks/ {} + && git config core.hooksPath .githooks
  [ -x .githooks/pre-commit ] || { echo "hook setup failed" >&2; exit 2; }
  git remote add origin "$R.git"; echo base > base.txt; git add -A; git commit -q -n -m base
  git push -q origin HEAD:refs/heads/main 2>/dev/null
}
commit() { git add -A >/dev/null 2>&1; git commit -q -m "${1:-change}" >/dev/null 2>&1; }
push() { git push -q origin HEAD:refs/heads/main >/dev/null 2>&1; }
# outcome: BLOCKED if the bad content cannot reach the remote (commit or push refused)
reach() { if commit "$@" && push; then echo ALLOWED; else echo BLOCKED; fi; }
FAIL=0
r() { printf '%-26s %-4s %s\n' "$1" "$2" "$3"
      case "$2:$3" in bad:BLOCKED|ok:ALLOWED) ;; *) FAIL=1 ;; esac; }

fresh ok-clean;      echo hello > a.txt;                         r ok-clean ok "$(reach)"
fresh plusplus;      printf '++ start\n%s\n' "$BAD" > a.txt;      r plusplus bad "$(reach)"
fresh quoted-name;   echo "$BAD" > 'q"uote.txt';                  r quoted-name bad "$(reach)"
fresh noprefix;      git config diff.noprefix true; echo "$BAD" > a.txt;       r noprefix bad "$(reach)"
fresh mnemonic;      git config diff.mnemonicPrefix true; echo "$BAD" > a.txt; r mnemonic-prefix bad "$(reach)"
fresh binary-attr;   echo '*.dat -diff' > .gitattributes; commit attrs; push; echo "$BAD" > x.dat; r binary-attr bad "$(reach)"
fresh merge-ident;   git checkout -q -b side; echo s > s.txt; commit side; git checkout -q -; echo m > m.txt; commit main
                     if git -c user.email="$BAD" merge -q --no-ff side -m merge >/dev/null 2>&1 && push; then o=ALLOWED; else o=BLOCKED; fi; r merge-identity bad $o
fresh pick-ident;    git checkout -q -b side; echo s > s.txt; commit side; git checkout -q -
                     if git -c user.email="$BAD" cherry-pick side >/dev/null 2>&1 && push; then o=ALLOWED; else o=BLOCKED; fi; r cherry-pick-identity bad $o
fresh launder;       mkdir third_party docs; echo "$BAD" > third_party/n.txt; commit vend
                     git mv third_party/n.txt docs/n.txt; r third-party-launder bad "$(reach)"
fresh self-exempt;   echo "# $BAD" >> .githooks/personal_info_check.py; r self-exemption bad "$(reach)"
fresh worktree;      echo 'acmesecret' > .git/info/personal-patterns; git worktree add -q ../worktree-wt >/dev/null 2>&1; cd ../worktree-wt
                     echo "the AcmeSecret plan" > w.txt; if commit; then o=ALLOWED; else o=BLOCKED; fi; r worktree-private bad $o
fresh verbatim;      echo v > v.txt; git add -A; printf 'msg\n# %s\n' "$BAD" > ../msg
                     if git commit -q --cleanup=verbatim -F ../msg >/dev/null 2>&1 && push; then o=ALLOWED; else o=BLOCKED; fi; r verbatim-comment bad $o
fresh binary-nul;    printf 'x\0y\n%s\n' "$BAD" > b.bin;            r binary-nul bad "$(reach)"
fresh file-name;     echo x > "$BAD.txt";                         r file-name bad "$(reach)"
fresh bad-pattern;   echo '(unclosed' > .git/info/personal-patterns; echo x > a.txt; r invalid-pattern bad "$(reach)"
fresh home-case;     echo "path /HO${HM#/ho}ME/someone/x" > a.txt;         r home-uppercase bad "$(reach)"
fresh home-userdot;  echo "path ${HM}me/user.name/x" > a.txt;       r home-user-prefix bad "$(reach)"
fresh ok-placeholder; echo "path ${HM}me/runner/work and ${HM}me/\$USER" > a.txt; r ok-placeholder ok "$(reach)"
fresh ok-noreply;    echo "$NR" > a.txt;                          r ok-noreply ok "$(reach)"
fresh ok-merge;      git checkout -q -b side; echo s > s.txt; commit side; git checkout -q -; echo m > m.txt; commit main
                     if git merge -q --no-ff side -m merge >/dev/null 2>&1 && push; then o=ALLOWED; else o=BLOCKED; fi; r ok-merge ok $o
fresh ok-web-flow;   echo w > w.txt; git add -A
                     if GIT_COMMITTER_EMAIL=noreply@github.com git commit -q -m web >/dev/null 2>&1 && push; then o=ALLOWED; else o=BLOCKED; fi; r ok-web-flow-committer ok $o
fresh web-flow-author; echo w > w.txt; git add -A
                     if GIT_AUTHOR_EMAIL=noreply@github.com git commit -q -m web >/dev/null 2>&1 && push; then o=ALLOWED; else o=BLOCKED; fi; r web-flow-as-author bad $o
rm -rf "$BASE"
exit $FAIL
