#!/bin/bash
# Regression suite for the personal-information hooks.
# Usage: .githooks/tests/regression.sh [HOOKDIR]; exits 1 when any case has the wrong outcome.
# A "bad" case must be BLOCKED; an "ok" case must be ALLOWED. Synthetic values are built
# at run time so this file passes its own hooks.
set -u
HOOKS=$(cd "${1:-$(dirname "$0")/..}" && pwd)
BASE=$(mktemp -d "${TMPDIR:-/tmp}/hookreg.XXXX")
export PYTHONDONTWRITEBYTECODE=1 GIT_CONFIG_NOSYSTEM=1 HOME="$BASE/hh-qzx"
mkdir -p "$HOME"; : > "$BASE/err"
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
commit() { git add -A >/dev/null 2>>"$BASE/err"; git commit -q -m "${1:-change}" >/dev/null 2>>"$BASE/err"; }
push() { git push -q origin HEAD:refs/heads/main >/dev/null 2>>"$BASE/err"; }
# outcome: BLOCKED if the bad content cannot reach the remote (commit or push refused)
reach() { if commit "$@" && push; then echo ALLOWED; else echo BLOCKED; fi; }
FAIL=0
r() { o=$3; grep -q 'check failed' "$BASE/err" 2>/dev/null && o=ERROR; : > "$BASE/err"
      printf '%-26s %-4s %s\n' "$1" "$2" "$o"
      case "$2:$o" in bad:BLOCKED|ok:ALLOWED) ;; *) FAIL=1 ;; esac; }

fresh ok-clean;      echo hello > a.txt;                         r ok-clean ok "$(reach)"
fresh plusplus;      printf '++ start\n%s\n' "$BAD" > a.txt;      r plusplus bad "$(reach)"
fresh quoted-name;   echo "$BAD" > 'q"uote.txt';                  r quoted-name bad "$(reach)"
fresh noprefix;      git config diff.noprefix true; echo "$BAD" > a.txt;       r noprefix bad "$(reach)"
fresh mnemonic;      git config diff.mnemonicPrefix true; echo "$BAD" > a.txt; r mnemonic-prefix bad "$(reach)"
fresh binary-attr;   echo '*.dat -diff' > .gitattributes; commit attrs; push; echo "$BAD" > x.dat; r binary-attr bad "$(reach)"
fresh merge-ident;   git checkout -q -b side; echo s > s.txt; commit side; git checkout -q -; echo m > m.txt; commit main
                     if git -c user.email="$BAD" merge -q --no-ff side -m merge >/dev/null 2>>"$BASE/err" && push; then o=ALLOWED; else o=BLOCKED; fi; r merge-identity bad $o
fresh pick-ident;    git checkout -q -b side; echo s > s.txt; commit side; git checkout -q -
                     if git -c user.email="$BAD" cherry-pick side >/dev/null 2>>"$BASE/err" && push; then o=ALLOWED; else o=BLOCKED; fi; r cherry-pick-identity bad $o
fresh launder;       mkdir third_party docs; echo "$BAD" > third_party/n.txt; commit vend
                     git mv third_party/n.txt docs/n.txt; r third-party-launder bad "$(reach)"
fresh self-exempt;   echo "# $BAD" >> .githooks/personal_info_check.py; r self-exemption bad "$(reach)"
fresh worktree;      echo 'acmesecret' > .git/info/personal-patterns; git worktree add -q ../worktree-wt >/dev/null 2>>"$BASE/err"; cd ../worktree-wt
                     echo "the AcmeSecret plan" > w.txt; if commit; then o=ALLOWED; else o=BLOCKED; fi; r worktree-private bad $o
fresh verbatim;      echo v > v.txt; git add -A; printf 'msg\n# %s\n' "$BAD" > ../msg
                     if git commit -q --cleanup=verbatim -F ../msg >/dev/null 2>>"$BASE/err" && push; then o=ALLOWED; else o=BLOCKED; fi; r verbatim-comment bad $o
fresh binary-nul;    printf 'x\0y\n%s\n' "$BAD" > b.bin;            r binary-nul bad "$(reach)"
fresh file-name;     echo x > "$BAD.txt";                         r file-name bad "$(reach)"
fresh bad-pattern;   echo '(unclosed' > .git/info/personal-patterns; echo x > a.txt; r invalid-pattern bad "$(reach)"
fresh home-case;     echo "path /HO${HM#/ho}ME/someone/x" > a.txt;         r home-uppercase bad "$(reach)"
fresh home-userdot;  echo "path ${HM}me/user.name/x" > a.txt;       r home-user-prefix bad "$(reach)"
fresh ok-placeholder; echo "path ${HM}me/runner/work and ${HM}me/\$USER" > a.txt; r ok-placeholder ok "$(reach)"
fresh ok-noreply;    echo "$NR" > a.txt;                          r ok-noreply ok "$(reach)"
fresh ok-merge;      git checkout -q -b side; echo s > s.txt; commit side; git checkout -q -; echo m > m.txt; commit main
                     if git merge -q --no-ff side -m merge >/dev/null 2>>"$BASE/err" && push; then o=ALLOWED; else o=BLOCKED; fi; r ok-merge ok $o
fresh ok-web-flow;   echo w > w.txt; git add -A
                     if GIT_COMMITTER_EMAIL=noreply@github.com git commit -q -m web >/dev/null 2>>"$BASE/err" && push; then o=ALLOWED; else o=BLOCKED; fi; r ok-web-flow-committer ok $o
fresh web-flow-author; echo w > w.txt; git add -A
                     if GIT_AUTHOR_EMAIL=noreply@github.com git commit -q -m web >/dev/null 2>>"$BASE/err" && push; then o=ALLOWED; else o=BLOCKED; fi; r web-flow-as-author bad $o
pushok() { if push; then echo ALLOWED; else echo BLOCKED; fi; }
fresh evil-merge;    git checkout -q -b side; echo s > s.txt; commit side; git checkout -q -; echo m > m.txt; commit main
                     git merge -q --no-commit --no-ff side >/dev/null 2>>"$BASE/err"; echo "$BAD" > evil.txt; git add evil.txt
                     git commit -q -n -m merge >/dev/null 2>>"$BASE/err"; r evil-merge bad "$(pushok)"
fresh tag-message;   git tag -a v1 -m "contact $BAD"
                     if git push -q origin v1 >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r tag-message bad $o
fresh tagger;        GIT_COMMITTER_EMAIL="$BAD" git tag -a v2 -m ok
                     if git push -q origin v2 >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r tagger-identity bad $o
fresh ok-tag;        git tag -a v3 -m release
                     if git push -q origin v3 >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r ok-annotated-tag ok $o
fresh ident-name;    echo 'acmesecret' > .git/info/personal-patterns; echo n > n.txt; git add -A
                     if git -c user.name=AcmeSecret commit -q -m name >/dev/null 2>>"$BASE/err" && push; then o=ALLOWED; else o=BLOCKED; fi; r identity-name bad $o
fresh utf16-bom;     python3 -c "import sys;open('u.txt','wb').write(sys.argv[1].encode('utf-16'))" "$BAD"; r utf16-bom bad "$(reach)"
fresh utf16-nobom;   python3 -c "import sys;open('u.txt','wb').write(sys.argv[1].encode('utf-16-le'))" "$BAD"; r utf16-no-bom bad "$(reach)"
fresh gzip;          echo "$BAD" | gzip > g.gz;                    r gzip bad "$(reach)"
fresh vendored-local; mkdir third_party; echo "built by $(basename "$HOME")" > third_party/x.txt; r vendored-unpinned-local bad "$(reach)"
fresh example-suffix; echo "dev${AT}example.com.acme-corp.io" > a.txt; r example-suffix bad "$(reach)"
fresh other-remote;  git init -q --bare "$BASE/mirror.git"; git remote add mirror "$BASE/mirror.git"; echo "$BAD" > a.txt
                     git add -A; git commit -q -n -m mirror >/dev/null 2>>"$BASE/err"; git push -q --no-verify mirror HEAD:refs/heads/main >/dev/null 2>>"$BASE/err"; git fetch -q mirror
                     if git push -q origin HEAD:refs/heads/new >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r other-remote-skip bad $o
fresh ok-vendored;   mkdir third_party; echo "upstream author dev${AT}upstream-project.org" > third_party/n.txt
                     printf '{"files": {"third_party/n.txt": "%s"}}\n' "$(sha256sum third_party/n.txt | cut -c1-64)" > upstream.lock.json
                     r ok-vendored-pinned ok "$(reach)"
fresh ok-ssh-url;    echo "remote git${AT}github.com:org/repo.git" > a.txt; r ok-ssh-url ok "$(reach)"
fresh ok-upper-nr;   git config user.email "1+Bot${AT}Users.Noreply.GitHub.com"; echo u > a.txt; r ok-uppercase-noreply ok "$(reach)"
fresh nested-tag;    git tag -a inner -m "contact $BAD"; git -c advice.nestedTag=false tag -a outer -m clean inner; git tag -d inner >/dev/null
                     if python3 .githooks/personal_info_check.py --history >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r nested-tag-history bad $o
fresh tag-blob;      b=$(echo "$BAD" | git hash-object -w --stdin); git tag -a tb -m clean "$b"
                     if git push -q origin tb >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r tag-to-blob bad $o
fresh tag-tree;      mkdir t; echo "$BAD" > t/x.txt; git add t; tr=$(git write-tree --prefix=t/); git reset -q; git tag -a tt -m clean "$tr"
                     if git push -q origin tt >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r tag-to-tree bad $o
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
                     if git push -q origin "$b:refs/tags/rawblob" >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r direct-blob-ref bad $o
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
                     if git commit -q -m sub >/dev/null 2>>"$BASE/err" && push && python3 .githooks/personal_info_check.py --history >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r ok-submodule-entry ok $o
mkarc() { python3 - "$@" <<'PY'
import io,sys,zipfile,gzip,tarfile,lzma,bz2
kind,out,value=sys.argv[1],sys.argv[2],sys.argv[3]
def tar(entries,mode='w',fmt=tarfile.GNU_FORMAT):
    b=io.BytesIO(); t=tarfile.open(fileobj=b,mode=mode,format=fmt)
    for info,data in entries:
        if data is not None: info.size=len(data)
        t.addfile(info,io.BytesIO(data) if data is not None else None)
    t.close(); return b.getvalue()
def ti(name,**kw):
    i=tarfile.TarInfo(name)
    for k,v in kw.items(): setattr(i,k,v)
    return i
clean=b'clean content\n'
if kind=='tar-uname': data=tar([(ti('a.txt',uname=value,gname='staff'),clean)])
elif kind=='tar-symlink': data=tar([(ti('l',type=tarfile.SYMTYPE,linkname=value),None)],'w:gz')
elif kind=='tar-pax': data=tar([(ti('a.txt',pax_headers={'comment':value}),clean)],'w:gz',tarfile.PAX_FORMAT)
elif kind=='zip-comment':
    b=io.BytesIO(); z=zipfile.ZipFile(b,'w'); z.writestr('a.txt',clean); z.comment=value.encode(); z.close(); data=b.getvalue()
elif kind=='zip-member-comment':
    b=io.BytesIO(); z=zipfile.ZipFile(b,'w'); i=zipfile.ZipInfo('a.txt'); i.comment=value.encode(); z.writestr(i,clean); z.close(); data=b.getvalue()
elif kind=='gzip-fname':
    b=io.BytesIO(); g=gzip.GzipFile(filename=value,mode='wb',fileobj=b); g.write(clean); g.close(); data=b.getvalue()
elif kind=='xz-second': data=lzma.compress(clean)+lzma.compress(value.encode())
elif kind=='bz2-second': data=bz2.compress(clean)+bz2.compress(value.encode())
elif kind=='gzip-depth5':
    data=value.encode()
    for _ in range(5): data=gzip.compress(data)
elif kind=='zip-prefix':
    b=io.BytesIO(); z=zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED); z.writestr('m.txt',value); z.close(); data=b'\x00'*64+b.getvalue()
elif kind=='zip-no-cd':
    b=io.BytesIO(); z=zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED); z.writestr('m.txt',value); z.close(); v=b.getvalue(); data=v[:v.find(b'PK\x01\x02')]
elif kind=='tar-truncated':
    data=tar([(ti('a.gz'),gzip.compress(value.encode())),(ti('b.bin'),b'z'*5000)],'w',tarfile.USTAR_FORMAT)[:1024+512+700]
elif kind=='ok-zip':
    b=io.BytesIO(); z=zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED); z.writestr('a.txt',clean); z.close(); data=b.getvalue()
elif kind=='ok-tar': data=tar([(ti('a.txt'),clean)],'w',tarfile.USTAR_FORMAT)
elif kind=='ok-targz': data=tar([(ti('a.txt'),clean)],'w:gz',tarfile.USTAR_FORMAT)
elif kind=='ok-big-targz': data=tar([(ti('big.bin'),b'\0'*(36*1024*1024))],'w:gz',tarfile.USTAR_FORMAT)
open(out,'wb').write(data)
PY
}
LOGIN=$(basename "$HOME")
fresh tar-uname;     mkarc tar-uname a.tar "$LOGIN";                      r tar-owner-name bad "$(reach)"
fresh tar-symlink;   mkarc tar-symlink a.tar.gz "${HM}me/someone/x";       r tar-symlink-target bad "$(reach)"
fresh tar-pax;       mkarc tar-pax a.tar.gz "$BAD";                       r tar-pax-header bad "$(reach)"
fresh zip-comment;   mkarc zip-comment a.zip "$BAD";                      r zip-archive-comment bad "$(reach)"
fresh zip-mcomment;  mkarc zip-member-comment a.zip "$BAD";               r zip-member-comment bad "$(reach)"
fresh gzip-fname;    mkarc gzip-fname a.gz "$BAD";                        r gzip-header-name bad "$(reach)"
fresh xz-second;     mkarc xz-second a.xz "$BAD";                         r xz-second-stream bad "$(reach)"
fresh bz2-second;    mkarc bz2-second a.bz2 "$BAD";                       r bzip2-second-stream bad "$(reach)"
fresh gzip-depth5;   mkarc gzip-depth5 a.gz "$BAD";                       r archive-depth-limit bad "$(reach)"
fresh zip-prefix;    mkarc zip-prefix a.bin "$BAD";                       r zip-after-prefix bad "$(reach)"
fresh zip-no-cd;     mkarc zip-no-cd a.zip "$BAD";                        r corrupt-zip bad "$(reach)"
fresh tar-trunc;     mkarc tar-truncated a.tar "$BAD";                    r truncated-tar-member bad "$(reach)"
fresh commit-header; t=$(git rev-parse HEAD^{tree}); p=$(git rev-parse HEAD)
                     c=$(printf 'tree %s\nparent %s\nauthor bot <%s> 1 +0000\ncommitter bot <%s> 1 +0000\nx-contact %s\n\nclean\n' "$t" "$p" "$NR" "$NR" "$BAD" | git hash-object -t commit -w --literally --stdin)
                     git update-ref refs/heads/extra "$c"
                     if python3 .githooks/personal_info_check.py --history >/dev/null 2>>"$BASE/err" && git push -q origin extra >/dev/null 2>>"$BASE/err"; then o=ALLOWED; else o=BLOCKED; fi; r extra-commit-header bad $o
fresh ok-zip;        mkarc ok-zip a.zip x;                                r unpinned-clean-zip bad "$(reach)"
fresh ok-tar;        mkarc ok-tar a.tar x;                                r unpinned-clean-tar bad "$(reach)"
fresh ok-targz;      mkarc ok-targz a.tar.gz x;                           r unpinned-clean-tar-gz bad "$(reach)"
fresh ok-big;        mkarc ok-big-targz big.tar.gz x;                     r unpinned-large-tar-gz bad "$(reach)"
mkbad() { python3 - "$@" <<'PY'
import io,sys,zipfile,gzip,tarfile,lzma,bz2
kind,out,value=sys.argv[1],sys.argv[2],sys.argv[3].encode()
body=b'filler line\n'*2000+value+b'\n'+b'filler line\n'*2000
def flip(data,pos): b=bytearray(data); b[pos]^=1; return bytes(b)
if kind=='gzip-crc': d=gzip.compress(body); data=flip(d,len(d)-6)
elif kind=='xz-mid': d=lzma.compress(body); data=flip(d,len(d)//2)
elif kind=='bz2-crc':
    d=bz2.compress(body); data=flip(d,len(d)-3)
elif kind=='tar-concat':
    def tar(name,content):
        b=io.BytesIO(); t=tarfile.open(fileobj=b,mode='w',format=tarfile.USTAR_FORMAT); i=tarfile.TarInfo(name); i.size=len(content); t.addfile(i,io.BytesIO(content)); t.close(); return b.getvalue()
    data=tar('a.txt',b'clean\n')+tar('b.txt',value)
elif kind=='zip-unlisted':
    a=io.BytesIO(); z=zipfile.ZipFile(a,'w',zipfile.ZIP_DEFLATED); z.writestr('hidden.txt',value); z.close(); av=a.getvalue(); local=av[:av.find(b'PK\x01\x02')]
    b=io.BytesIO(); z=zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED); z.writestr('clean.txt',b'clean'); z.close(); data=local+b.getvalue()
elif kind=='depth-prefixed-zip':
    b=io.BytesIO(); z=zipfile.ZipFile(b,'w'); z.writestr('m.txt',value); z.close(); data=b'\x00'*64+b.getvalue()
    for _ in range(4): data=gzip.compress(data)
open(out,'wb').write(data)
PY
}
fresh sparse-tar;    truncate -s 100M ../sparse.bin && tar --sparse --format=gnu --owner=root --group=root -cf a.tar -C .. sparse.bin && rm -f ../sparse.bin; r sparse-tar-budget bad "$(reach)"
fresh gzip-crc;      mkbad gzip-crc a.gz "$BAD";                         r corrupt-gzip-crc bad "$(reach)"
fresh xz-mid;        mkbad xz-mid a.xz "$BAD";                           r corrupt-xz-stream bad "$(reach)"
fresh bz2-crc;       mkbad bz2-crc a.bz2 "$BAD";                         r corrupt-bzip2-crc bad "$(reach)"
fresh tar-concat;    mkbad tar-concat a.tar "$BAD";                      r concatenated-tar bad "$(reach)"
fresh zip-unlisted;  mkbad zip-unlisted a.zip "$BAD";                    r zip-unlisted-local-entry bad "$(reach)"
fresh depth-prefix;  mkbad depth-prefixed-zip a.gz "$BAD";               r depth-limit-prefixed-zip bad "$(reach)"
fresh masked-output; mkarc tar-uname a.tar "$LOGIN"; git add -A
                     if git commit -q -m masked >/dev/null 2>"$BASE/out"; then o=ALLOWED; elif grep -q -F "$LOGIN" "$BASE/out"; then o=LEAKED; else o=BLOCKED; fi; r masked-metadata-output bad $o
fresh ok-pinned-tar;  mkdir -p container/foundation-inputs; mkarc ok-tar container/foundation-inputs/up.tar x
                     printf '{"inputs": [{"path": "container/foundation-inputs/up.tar", "sha256": "%s"}]}\n' "$(sha256sum container/foundation-inputs/up.tar | cut -c1-64)" > foundation.lock.json
                     r ok-pinned-upstream-tar ok "$(reach)"
rm -rf "$BASE"
exit $FAIL
