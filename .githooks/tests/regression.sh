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
pushok() { if push; then echo ALLOWED; else echo BLOCKED; fi; }
fresh evil-merge;    git checkout -q -b side; echo s > s.txt; commit side; git checkout -q -; echo m > m.txt; commit main
                     git merge -q --no-commit --no-ff side >/dev/null 2>&1; echo "$BAD" > evil.txt; git add evil.txt
                     git commit -q -n -m merge >/dev/null 2>&1; r evil-merge bad "$(pushok)"
fresh tag-message;   git tag -a v1 -m "contact $BAD"
                     if git push -q origin v1 >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r tag-message bad $o
fresh tagger;        GIT_COMMITTER_EMAIL="$BAD" git tag -a v2 -m ok
                     if git push -q origin v2 >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r tagger-identity bad $o
fresh ok-tag;        git tag -a v3 -m release
                     if git push -q origin v3 >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r ok-annotated-tag ok $o
fresh ident-name;    echo 'acmesecret' > .git/info/personal-patterns; echo n > n.txt; git add -A
                     if git -c user.name=AcmeSecret commit -q -m name >/dev/null 2>&1 && push; then o=ALLOWED; else o=BLOCKED; fi; r identity-name bad $o
fresh utf16-bom;     python3 -c "import sys;open('u.txt','wb').write(sys.argv[1].encode('utf-16'))" "$BAD"; r utf16-bom bad "$(reach)"
fresh utf16-nobom;   python3 -c "import sys;open('u.txt','wb').write(sys.argv[1].encode('utf-16-le'))" "$BAD"; r utf16-no-bom bad "$(reach)"
fresh gzip;          echo "$BAD" | gzip > g.gz;                    r gzip bad "$(reach)"
fresh vendored-local; mkdir third_party; echo "built by $(basename "$HOME")" > third_party/x.txt; r vendored-unpinned-local bad "$(reach)"
fresh example-suffix; echo "dev${AT}example.com.acme-corp.io" > a.txt; r example-suffix bad "$(reach)"
fresh other-remote;  git init -q --bare "$BASE/mirror.git"; git remote add mirror "$BASE/mirror.git"; echo "$BAD" > a.txt
                     git add -A; git commit -q -n -m mirror >/dev/null 2>&1; git push -q --no-verify mirror HEAD:refs/heads/main >/dev/null 2>&1; git fetch -q mirror
                     if git push -q origin HEAD:refs/heads/new >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r other-remote-skip bad $o
fresh ok-vendored;   mkdir third_party; echo "upstream author dev${AT}upstream-project.org" > third_party/n.txt
                     printf '{"files": {"third_party/n.txt": "%s"}}\n' "$(sha256sum third_party/n.txt | cut -c1-64)" > upstream.lock.json
                     r ok-vendored-pinned ok "$(reach)"
fresh ok-ssh-url;    echo "remote git${AT}github.com:org/repo.git" > a.txt; r ok-ssh-url ok "$(reach)"
fresh ok-upper-nr;   git config user.email "1+Bot${AT}Users.Noreply.GitHub.com"; echo u > a.txt; r ok-uppercase-noreply ok "$(reach)"
fresh nested-tag;    git tag -a inner -m "contact $BAD"; git -c advice.nestedTag=false tag -a outer -m clean inner; git tag -d inner >/dev/null
                     if python3 .githooks/personal_info_check.py --history >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r nested-tag-history bad $o
fresh tag-blob;      b=$(echo "$BAD" | git hash-object -w --stdin); git tag -a tb -m clean "$b"
                     if git push -q origin tb >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r tag-to-blob bad $o
fresh tag-tree;      mkdir t; echo "$BAD" > t/x.txt; git add t; tr=$(git write-tree --prefix=t/); git reset -q; git tag -a tt -m clean "$tr"
                     if git push -q origin tt >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r tag-to-tree bad $o
fresh bom-utf8;      { printf '\377\376'; echo "$BAD"; } > b.txt;  r bom-prefixed-utf8 bad "$(reach)"
fresh gzip2;         echo "$BAD" | gzip | gzip > g2.gz;            r double-gzip bad "$(reach)"
fresh utf32;         python3 -c "import sys;open('u.txt','wb').write(sys.argv[1].encode('utf-32-le'))" "$BAD"; r utf32-no-bom bad "$(reach)"
fresh pin-unbound;   mkdir third_party; echo "upstream dev${AT}upstream-project.org" > third_party/n.txt
                     printf '{"unrelated": "%s"}\n' "$(sha256sum third_party/n.txt | cut -c1-64)" > upstream.lock.json
                     r vendored-unbound-pin bad "$(reach)"
fresh short-binary;  printf 'x\000%s\000y' "$(basename "$HOME")" > s.bin; r short-local-in-binary bad "$(reach)"
fresh gzip-trunc;    printf '%s\n%s\n' "$BAD" "$(head -c 4000 /dev/zero | tr '\0' a)" | gzip > t.gz; truncate -s -12 t.gz; r truncated-gzip bad "$(reach)"
fresh gzip-trail;    { echo "$BAD" | gzip; printf 'trailing'; } > t.gz; r gzip-trailing-data bad "$(reach)"
fresh zip;           python3 -c "import sys,zipfile;z=zipfile.ZipFile('a.zip','w',zipfile.ZIP_DEFLATED);z.writestr('m.txt',sys.argv[1]);z.close()" "$BAD"; r deflated-zip bad "$(reach)"
fresh blob-ref;      b=$(echo "$BAD" | git hash-object -w --stdin)
                     if git push -q origin "$b:refs/tags/rawblob" >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r direct-blob-ref bad $o
fresh firstparty-pin; mkdir tools; echo "owner $BAD" > tools/x.py
                     printf '{"files": {"tools/x.py": "%s"}}\n' "$(sha256sum tools/x.py | cut -c1-64)" > upstream.lock.json
                     r lock-bound-first-party bad "$(reach)"
fresh ok-wheel;      mkdir container; python3 -c "import sys,zipfile;z=zipfile.ZipFile('container/up-1.0-py3-none-any.whl','w',zipfile.ZIP_DEFLATED);z.writestr('METADATA','Author-email: '+sys.argv[1]);z.close()" "maintainer${AT}upstream-project.org"
                     printf '{"inputs": [{"path": "container/up-1.0-py3-none-any.whl", "sha256": "%s"}]}\n' "$(sha256sum container/up-1.0-py3-none-any.whl | cut -c1-64)" > upstream.lock.json
                     r ok-pinned-upstream-wheel ok "$(reach)"
mkzip() { python3 - "$@" <<'PY'
import io,sys,zipfile,gzip,tarfile,struct
kind,out,value=sys.argv[1],sys.argv[2],sys.argv[3].encode()
def z(entries,method=zipfile.ZIP_DEFLATED):
    b=io.BytesIO(); f=zipfile.ZipFile(b,'w',method)
    for n,d in entries: f.writestr(n,d)
    f.close(); return b.getvalue()
if kind=='zip-in-zip': data=z([('outer/inner.zip',z([('m.txt',value)]))])
elif kind=='gzip-in-zip': data=z([('m.txt.gz',gzip.compress(value))])
elif kind=='gz-in-targz':
    b=io.BytesIO(); t=tarfile.open(fileobj=b,mode='w:gz'); inner=gzip.compress(value)
    i=tarfile.TarInfo('inner.gz'); i.size=len(inner); t.addfile(i,io.BytesIO(inner)); t.close(); data=b.getvalue()
elif kind=='tar':
    b=io.BytesIO(); t=tarfile.open(fileobj=b,mode='w'); i=tarfile.TarInfo('m.txt'); i.size=len(value); t.addfile(i,io.BytesIO(value)); t.close(); data=b.getvalue()
elif kind=='bad-method':
    data=bytearray(z([('a.bin',b'x'*64),('m.txt',value)],zipfile.ZIP_STORED))
    data[8:10]=struct.pack('<H',9); c=data.find(b'PK\x01\x02'); data[c+10:c+12]=struct.pack('<H',9); data=bytes(data)
elif kind=='member-cap': data=z([(f'f{i}.txt',b'x') for i in range(4097)]+[('last.txt',value)],zipfile.ZIP_STORED)
open(out,'wb').write(data)
PY
}
fresh zip-in-zip;    mkzip zip-in-zip a.zip "$BAD";     r zip-in-zip bad "$(reach)"
fresh gzip-in-zip;   mkzip gzip-in-zip a.zip "$BAD";    r gzip-in-zip bad "$(reach)"
fresh gz-in-targz;   mkzip gz-in-targz a.tar.gz "$BAD"; r gz-in-tar-gz bad "$(reach)"
fresh plain-tar;     mkzip tar a.tar "$BAD";            r plain-tar bad "$(reach)"
fresh xz;            echo "$BAD" | xz > a.xz;            r xz bad "$(reach)"
fresh bzip2;         echo "$BAD" | bzip2 > a.bz2;        r bzip2 bad "$(reach)"
fresh bad-method;    mkzip bad-method a.zip "$BAD";     r undecodable-zip-member bad "$(reach)"
fresh member-cap;    mkzip member-cap a.zip "$BAD";     r zip-member-cap bad "$(reach)"
fresh short-email;   printf 'x\000a%sbc.io\000y' "$AT" > s.bin; r short-email-in-binary bad "$(reach)"
fresh ok-gitlink;    git update-index --add --cacheinfo "160000,$(git rev-parse HEAD),sub"
                     if git commit -q -m sub >/dev/null 2>&1 && push && python3 .githooks/personal_info_check.py --history >/dev/null 2>&1; then o=ALLOWED; else o=BLOCKED; fi; r ok-submodule-entry ok $o
rm -rf "$BASE"
exit $FAIL
