#!/usr/bin/env python3
"""Push local markdown file(s) to Google Docs.

Self-contained pipeline: preprocess markdown (flatten wiki-links, fix bold
pseudo-headings, extract mermaid), render mermaid with Merman (local, no
browser), build a single .docx with a patched style reference (Arial, black
text, 11pt body), strip heading bookmarks, then upload once and let Google
convert it to a Doc.

The deterministic pipeline runs here with no model in the loop. Two decisions
are deliberately left to the caller (the skill / the user), surfaced as
non-zero exits rather than guessed:

  * update-vs-new   - pass --update or --new; bare runs error on a title clash
  * kroki fallback  - if Merman can't render a diagram, the script stops unless
                      --allow-kroki is given (kroki.io is an external service)

Usage:
  push_to_gdocs.py FILE [FILE ...] [options]   push one or more docs
  push_to_gdocs.py --setup                     install/verify deps, write marker
  push_to_gdocs.py --check                     verify deps, print status, exit

Options:
  --folder ID|URL    destination Drive folder (default: Drive root)
  --update           update an existing same-title doc in the folder
  --new              always create a new doc, even if the title exists
  --account NAME     gws account profile (see "Accounts" below; default: ambient)
  --title TITLE      doc title (default: the markdown H1; else the file stem)
  --allow-kroki      permit the external kroki.io mermaid fallback
  --json             print one JSON object per doc to stdout
  -h, --help         show this help

Accounts:
  --account NAME maps, by convention, to a gws client profile:
    GOOGLE_WORKSPACE_CLI_CONFIG_DIR = ~/.config/gws/clients/NAME
    client id/secret from macOS Keychain services
      gws-NAME-client-id / gws-NAME-client-secret
  Omit --account to use whatever gws account is already active.

Exit codes: 0 ok; 2 usage error; 3 missing dependency (run --setup);
4 unrendered diagram (needs --allow-kroki); 5 title clash (pass --update/--new);
6 transport/upload failure.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GDOC_MIME = "application/vnd.google-apps.document"
MARKER = os.path.expanduser("~/.claude/.push-to-gdocs-setup.json")
# Bump when the dependency set changes so an old marker is treated as stale.
SETUP_SCHEMA = 1


# --- bounded subprocess ------------------------------------------------------

def run(cmd, timeout=60, retries=1, env=None):
    """Run cmd with a hard timeout; retry once on timeout/failure. Returns stdout."""
    last = ""
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, env=env)
            if r.returncode == 0:
                return r.stdout
            last = "exit %d: %s" % (r.returncode, (r.stderr or "")[:300])
        except subprocess.TimeoutExpired:
            last = "timed out after %ds" % timeout
        except FileNotFoundError:
            last = "not found: %s" % cmd[0]
            break
        if attempt < retries:
            time.sleep(2)
    raise RuntimeError("command failed (%s): %s" % (last, " ".join(map(str, cmd[:4]))))


def die(code, msg):
    sys.stderr.write(msg.rstrip() + "\n")
    sys.exit(code)


# --- accounts ----------------------------------------------------------------

def account_env(account):
    """Return an env dict for a named gws profile, or None for ambient gws."""
    if not account:
        return None
    env = dict(os.environ)
    env["GOOGLE_WORKSPACE_CLI_CONFIG_DIR"] = os.path.expanduser(
        "~/.config/gws/clients/%s" % account)

    def keychain(service):
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                               capture_output=True, text=True, timeout=10)
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    cid = keychain("gws-%s-client-id" % account)
    csec = keychain("gws-%s-client-secret" % account)
    if cid:
        env["GOOGLE_WORKSPACE_CLI_CLIENT_ID"] = cid
    if csec:
        env["GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"] = csec
    return env


# --- dependency checks / setup ----------------------------------------------

def check_deps(need_merman=False):
    """Return (ok_dict, missing_list)."""
    checks = {
        "pandoc": shutil.which("pandoc"),
        "python3": sys.executable,
        "gws": shutil.which("gws"),
    }
    if need_merman:
        checks["merman-cli"] = shutil.which("merman-cli")
    missing = [k for k, v in checks.items() if not v]
    return checks, missing


def write_marker(checks):
    os.makedirs(os.path.dirname(MARKER), exist_ok=True)
    data = {
        "setup_schema": SETUP_SCHEMA,
        "verified_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "tools": checks,
    }
    with open(MARKER, "w") as f:
        json.dump(data, f, indent=2)


def marker_ok():
    """True if the setup marker exists and matches the current schema."""
    try:
        with open(MARKER) as f:
            data = json.load(f)
        return data.get("setup_schema") == SETUP_SCHEMA
    except Exception:
        return False


def cmd_check():
    checks, missing = check_deps(need_merman=False)
    merman = shutil.which("merman-cli")
    print("Dependency check:")
    for k, v in checks.items():
        print("  [%s] %s%s" % ("ok" if v else "  ", k, ("  " + v if v else " - MISSING")))
    print("  [%s] merman-cli%s" % ("ok" if merman else "--",
          ("  " + merman if merman else " - not installed (only needed for mermaid diagrams)")))
    print("Marker: %s (%s)" % (MARKER, "current" if marker_ok() else "absent/stale"))
    if missing:
        die(3, "Missing required dependencies: %s. Run: push_to_gdocs.py --setup" % ", ".join(missing))
    print("Required dependencies present.")


def cmd_setup():
    """Verify deps, install what's missing where we safely can, write the marker."""
    print("Setting up push-to-google-docs dependencies...")

    # pandoc
    if not shutil.which("pandoc"):
        brew = shutil.which("brew")
        if brew:
            print("  installing pandoc via brew...")
            try:
                run([brew, "install", "pandoc"], timeout=300)
            except RuntimeError as e:
                die(3, "pandoc install failed (%s). Install it manually: brew install pandoc" % e)
        else:
            die(3, "pandoc missing and no brew found. Install pandoc: "
                   "https://pandoc.org/installing.html")
    print("  [ok] pandoc  %s" % shutil.which("pandoc"))

    # merman-cli (optional; needed only for mermaid)
    if shutil.which("merman-cli"):
        print("  [ok] merman-cli  %s" % shutil.which("merman-cli"))
    elif shutil.which("cargo"):
        print("  installing merman-cli via cargo (one-time ~2-3 min compile)...")
        try:
            run(["cargo", "install", "merman-cli", "--locked"], timeout=600)
            print("  [ok] merman-cli  %s" % (shutil.which("merman-cli") or "installed"))
        except RuntimeError:
            print("  [!!] merman-cli install failed; mermaid diagrams will need --allow-kroki "
                  "or a prebuilt binary (github.com/Latias94/merman). Continuing.")
    else:
        print("  [--] merman-cli not installed and no cargo. Only needed for mermaid diagrams. "
              "Install Rust (https://sh.rustup.rs) then: cargo install merman-cli --locked")

    # python3
    print("  [ok] python3  %s" % sys.executable)

    # gws transport
    if shutil.which("gws"):
        print("  [ok] gws  %s" % shutil.which("gws"))
        try:
            status = run(["gws", "auth", "status"], timeout=20)
            user = re.search(r'"user"\s*:\s*"([^"]+)"', status)
            print("       active account: %s" % (user.group(1) if user else "unknown"))
        except RuntimeError:
            print("       (could not read gws auth status; sign in with `gws auth login`)")
    else:
        die(3, "No gws CLI found. Install gws and authenticate it, or set up another "
               "Google transport (Drive/Docs MCP or OAuth creds), then re-run --setup.")

    checks, missing = check_deps(need_merman=False)
    if missing:
        die(3, "Still missing after setup: %s" % ", ".join(missing))
    write_marker(checks)
    print("Setup complete. Marker written to %s" % MARKER)
    print("Future pushes can skip the dependency check.")


# --- markdown preprocessing --------------------------------------------------

WIKILINK_SUBS = [
    (re.compile(r'\[\[[^#\]|]*#[^\]|]+\|([^\]]+)\]\]'), r'\1'),  # [[Doc#Sec|text]] -> text
    (re.compile(r'\[\[[^#\]|]*#([^\]|]+)\]\]'),          r'\1'),  # [[Doc#Sec]] -> Sec
    (re.compile(r'\[\[[^\]|]+\|([^\]]+)\]\]'),           r'\1'),  # [[Doc|text]] -> text
    (re.compile(r'\[\[([^\]]+)\]\]'),                    r'\1'),  # [[Doc]] -> Doc
]
_FENCE = re.compile(r'^\s*(```|~~~)')
_BOLD_ONLY = re.compile(r'^\s*\*\*.+\*\*\s*$')


def flatten_wikilinks(md):
    for pat, repl in WIKILINK_SUBS:
        md = pat.sub(repl, md)
    return md


def isolate_bold_headings(md):
    """Ensure a bold-only line (e.g. **Why it works.**) sits in its own paragraph.

    In GFM a non-blank line right after a list item is a lazy continuation, so
    pandoc folds such a bold label into the bullet above it. Guarantee a blank
    line before and after it. Code fences are left untouched.
    """
    lines = md.split('\n')
    out = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and _BOLD_ONLY.match(line):
            if out and out[-1].strip() != '':
                out.append('')
            out.append(line)
            nxt = lines[i + 1] if i + 1 < len(lines) else ''
            if nxt.strip() != '':
                out.append('')
            continue
        out.append(line)
    return '\n'.join(out)


def extract_mermaid(md, workdir):
    """Pull each ```mermaid block to a .mmd file; leave a token. Returns count."""
    blocks = []

    def repl(m):
        blocks.append(m.group(1))
        return '@@MERMAID_%d@@' % len(blocks)

    md = re.sub(r'```mermaid\n(.*?)```', repl, md, flags=re.DOTALL)
    for i, b in enumerate(blocks, 1):
        with open(os.path.join(workdir, 'mermaid_%d.mmd' % i), 'w') as f:
            f.write(b)
    return md, len(blocks)


def render_mermaid(md, count, workdir, allow_kroki):
    """Render each extracted diagram; replace its token with an image ref."""
    for i in range(1, count + 1):
        mmd = os.path.join(workdir, 'mermaid_%d.mmd' % i)
        png = os.path.join(workdir, 'mermaid_%d.png' % i)
        rendered = False
        if shutil.which("merman-cli"):
            try:
                run(["merman-cli", "-i", mmd, "-o", png, "-t", "default", "-b", "white"],
                    timeout=30)
                rendered = os.path.exists(png)
            except RuntimeError:
                rendered = False
        if not rendered:
            if not allow_kroki:
                die(4, "Mermaid diagram %d did not render with Merman. Re-run with "
                       "--allow-kroki to render it via the external kroki.io service "
                       "(sends the diagram source over the network), or remove the diagram." % i)
            run(["curl", "-s", "-X", "POST", "https://kroki.io/mermaid/png",
                 "--data-binary", "@" + mmd, "-o", png], timeout=30)
            if not os.path.exists(png) or os.path.getsize(png) == 0:
                die(6, "kroki render failed for diagram %d." % i)
        # Absolute path so pandoc finds the PNG regardless of its cwd; the
        # width attribute needs the gfm `attributes` extension (see convert_to_docx).
        md = md.replace('@@MERMAID_%d@@' % i,
                        '![Diagram %d](%s){width=6in}' % (i, os.path.abspath(png)))
    return md


# --- docx build --------------------------------------------------------------

# Pandoc tags fenced code blocks with the "SourceCode" paragraph style but the
# default reference doesn't define one, so they render as plain text. Define it
# here: gray fill + monospace, so each block reads as a code box (Word/Google
# merge consecutive same-styled paragraphs into one shaded block).
SOURCECODE_STYLE = (
    '<w:style w:type="paragraph" w:customStyle="1" w:styleId="SourceCode">'
    '<w:name w:val="Source Code"/>'
    '<w:basedOn w:val="Normal"/>'
    '<w:link w:val="VerbatimChar"/>'
    '<w:pPr>'
    '<w:wordWrap w:val="off"/>'
    '<w:shd w:val="clear" w:color="auto" w:fill="F0F0F0"/>'
    '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
    '<w:ind w:left="200" w:right="200"/>'
    '</w:pPr>'
    '<w:rPr>'
    '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>'
    '<w:sz w:val="20"/>'
    '</w:rPr>'
    '</w:style>'
)

def _set_run_prop(inner, tag, attrs):
    """Replace <w:TAG .../> inside an rPr fragment, or append it if absent."""
    new = '<w:%s %s/>' % (tag, attrs)
    if re.search(r'<w:%s\b' % tag, inner):
        return re.sub(r'<w:%s\b[^>]*/>' % tag, new, inner)
    return inner + new


def patch_rprdefault(st):
    """Force black body text and 11pt body size in docDefaults."""
    m = re.search(r'(<w:rPrDefault>\s*<w:rPr>)(.*?)(</w:rPr>\s*</w:rPrDefault>)',
                  st, flags=re.DOTALL)
    if not m:
        inject = ('<w:rPrDefault><w:rPr><w:color w:val="000000"/>'
                  '<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>')
        return re.sub(r'(<w:docDefaults>)', r'\1' + inject, st, count=1)
    inner = m.group(2)
    inner = _set_run_prop(inner, "color", 'w:val="000000"')
    inner = _set_run_prop(inner, "sz", 'w:val="22"')
    inner = _set_run_prop(inner, "szCs", 'w:val="22"')
    return st[:m.start()] + m.group(1) + inner + m.group(3) + st[m.end():]


def build_reference(workdir):
    """Generate a patched pandoc reference.docx: Arial, black text, 11pt body."""
    default = subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"],
                             capture_output=True, timeout=30).stdout
    ref_default = os.path.join(workdir, "ref_default.docx")
    ref = os.path.join(workdir, "reference.docx")
    with open(ref_default, "wb") as f:
        f.write(default)
    src = zipfile.ZipFile(ref_default)
    items = {n: src.read(n) for n in src.namelist()}
    src.close()

    th = items["word/theme/theme1.xml"].decode()
    th = re.sub(r'(<a:majorFont>\s*<a:latin typeface=")[^"]*', r'\1Arial', th)
    th = re.sub(r'(<a:minorFont>\s*<a:latin typeface=")[^"]*', r'\1Arial', th)
    items["word/theme/theme1.xml"] = th.encode()

    st = items["word/styles.xml"].decode()
    # Heading/Title/Subtitle color -> black (strip any themeColor override).
    st = re.sub(r'<w:style\b[^>]*w:styleId="(?:Heading\d|Title|Subtitle)"[^>]*>.*?</w:style>',
                lambda m: re.sub(r'<w:color\b[^>]*/>', '<w:color w:val="000000"/>', m.group(0)),
                st, flags=re.DOTALL)
    st = patch_rprdefault(st)
    # Drop the Table style's firstRow conditional formatting. Its unsized, uncolored
    # <w:bottom w:val="single"/> wins over our 1pt black inline grid on the header
    # row's bottom edge, leaving that one border faint and unstyled in Google Docs.
    st = re.sub(r'<w:tblStylePr\b[^>]*w:type="firstRow".*?</w:tblStylePr>', '',
                st, flags=re.DOTALL)
    if 'w:styleId="SourceCode"' not in st:
        st = st.replace('</w:styles>', SOURCECODE_STYLE + '</w:styles>', 1)
    items["word/styles.xml"] = st.encode()

    with zipfile.ZipFile(ref, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in items.items():
            z.writestr(n, d)
    return ref


TBL_BORDERS = (
    '<w:tblBorders>'
    '<w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
    '<w:left w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
    '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
    '<w:right w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
    '<w:insideH w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
    '<w:insideV w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
    '</w:tblBorders>'
)


def add_table_borders(doc):
    """Give every table a 1pt black grid. Pandoc's reference only puts a
    bottom rule under the header row, and Google Docs drops style-level table
    borders on import, so inject inline tblBorders (which Google honors) into each
    table's tblPr. Placed before <w:tblLook> to keep the tblPr child order valid."""
    def repl(m):
        pr = m.group(0)
        if '<w:tblBorders' in pr:
            return pr
        if '<w:tblLook' in pr:
            return pr.replace('<w:tblLook', TBL_BORDERS + '<w:tblLook', 1)
        return pr.replace('</w:tblPr>', TBL_BORDERS + '</w:tblPr>', 1)
    return re.sub(r'<w:tblPr>.*?</w:tblPr>', repl, doc, flags=re.DOTALL)


def bold_table_headers(doc):
    """Bold every run in a table's header row. Pandoc marks the header row with
    <w:tblHeader> but leaves bolding to the table style's firstRow conditional
    formatting, which Google Docs drops on import, so the header reads like a
    plain first data row. Apply <w:b/> inline (which Google honors) instead."""
    def bold_runs(row):
        # Runs that already have an rPr: prepend bold inside it.
        row = re.sub(r'(<w:r>\s*<w:rPr>)', r'\1<w:b/>', row)
        # Runs with no rPr: give them one (rPr must be the run's first child).
        row = re.sub(r'<w:r>(?!\s*<w:rPr>)', '<w:r><w:rPr><w:b/></w:rPr>', row)
        return row

    def repl_row(m):
        row = m.group(0)
        return bold_runs(row) if '<w:tblHeader' in row else row
    return re.sub(r'<w:tr\b.*?</w:tr>', repl_row, doc, flags=re.DOTALL)


def convert_to_docx(pre_md, ref, out_docx):
    # gfm+attributes so the {width=6in} on rendered mermaid images is parsed as an
    # image attribute rather than left as literal text after the picture.
    run(["pandoc", pre_md, "-f", "gfm+attributes", "-t", "docx",
         "--reference-doc=" + ref, "-o", out_docx], timeout=60)
    # Strip per-heading bookmark anchors that Google Docs would render as noise.
    zin = zipfile.ZipFile(out_docx)
    parts = {n: zin.read(n) for n in zin.namelist()}
    zin.close()
    doc = parts["word/document.xml"].decode()
    doc = re.sub(r'<w:bookmarkStart\b[^>]*/>', '', doc)
    doc = re.sub(r'<w:bookmarkEnd\b[^>]*/>', '', doc)
    doc = add_table_borders(doc)
    doc = bold_table_headers(doc)
    parts["word/document.xml"] = doc.encode()
    with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in parts.items():
            z.writestr(n, d)


def first_h1(md):
    m = re.search(r'^#\s+(.+?)\s*$', md, flags=re.MULTILINE)
    return m.group(1).strip() if m else None


# --- gws transport -----------------------------------------------------------

def folder_id_from(arg):
    """Accept a raw folder ID or a Drive folder URL."""
    if not arg:
        return None
    m = re.search(r'/folders/([A-Za-z0-9_-]+)', arg)
    return m.group(1) if m else arg


def gws_find_by_title(title, folder_id, env):
    scope = ("'%s' in parents and " % folder_id) if folder_id else ""
    q = '%sname = "%s" and trashed = false' % (scope, title.replace('"', '\\"'))
    out = run(["gws", "drive", "files", "list", "--format", "json",
               "--params", json.dumps({"q": q, "fields": "files(id,name)"})], env=env)
    return json.loads(out).get("files", [])


def gws_create(title, folder_id, docx, env):
    meta = {"name": title, "mimeType": GDOC_MIME}
    if folder_id:
        meta["parents"] = [folder_id]
    out = run(["gws", "drive", "files", "create", "--json", json.dumps(meta),
               "--upload", docx, "--upload-content-type", DOCX_MIME,
               "--format", "json"], env=env)
    return json.loads(out)["id"]


def gws_update(doc_id, docx, env):
    run(["gws", "drive", "files", "update", "--params", json.dumps({"fileId": doc_id}),
         "--upload", docx, "--upload-content-type", DOCX_MIME,
         "-o", "gws_resp.json", "--format", "json"], env=env)
    return doc_id


# --- per-file pipeline -------------------------------------------------------

def push_one(path, args, env):
    with open(path, "r") as f:
        raw = f.read()

    title = args.title or first_h1(raw) or os.path.splitext(os.path.basename(path))[0]

    workdir = tempfile.mkdtemp(prefix=".gdocs-", dir=os.getcwd())
    try:
        md = flatten_wikilinks(raw)
        md = isolate_bold_headings(md)
        md, n_mermaid = extract_mermaid(md, workdir)
        if n_mermaid:
            md = render_mermaid(md, n_mermaid, workdir, args.allow_kroki)
        pre_md = os.path.join(workdir, "preprocessed.md")
        with open(pre_md, "w") as f:
            f.write(md)

        ref = build_reference(workdir)
        out_docx = os.path.join(workdir, "output.docx")
        convert_to_docx(pre_md, ref, out_docx)

        folder_id = folder_id_from(args.folder)

        # update-vs-new decision (gws is run from inside workdir for --upload sandbox)
        cwd = os.getcwd()
        os.chdir(workdir)
        try:
            rel_docx = os.path.basename(out_docx)
            existing = []
            if not args.new:
                existing = gws_find_by_title(title, folder_id, env)
            if args.update:
                if len(existing) == 1:
                    doc_id = gws_update(existing[0]["id"], rel_docx, env)
                    action = "updated"
                elif len(existing) == 0:
                    doc_id = gws_create(title, folder_id, rel_docx, env)
                    action = "created"
                else:
                    die(5, "Multiple docs titled %r in the folder; can't pick one to update: %s"
                        % (title, ", ".join(e["id"] for e in existing)))
            elif args.new:
                doc_id = gws_create(title, folder_id, rel_docx, env)
                action = "created"
            else:
                if existing:
                    die(5, "A doc titled %r already exists (%s). Pass --update to replace it "
                        "or --new to create another." % (title, existing[0]["id"]))
                doc_id = gws_create(title, folder_id, rel_docx, env)
                action = "created"
        finally:
            os.chdir(cwd)

        return {
            "file": path,
            "title": title,
            "action": action,
            "doc_id": doc_id,
            "url": "https://docs.google.com/document/d/%s/edit" % doc_id,
            "mermaid": n_mermaid,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --- main --------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(add_help=True, description="Push markdown to Google Docs.")
    p.add_argument("files", nargs="*", help="markdown file(s) to push")
    p.add_argument("--folder", help="destination Drive folder ID or URL")
    p.add_argument("--update", action="store_true", help="update a same-title doc")
    p.add_argument("--new", action="store_true", help="always create a new doc")
    p.add_argument("--account", help="gws account profile name")
    p.add_argument("--title", help="doc title (default: markdown H1)")
    p.add_argument("--allow-kroki", action="store_true", help="permit kroki.io mermaid fallback")
    p.add_argument("--json", action="store_true", help="emit JSON per doc")
    p.add_argument("--setup", action="store_true", help="install/verify deps, write marker")
    p.add_argument("--check", action="store_true", help="verify deps and exit")
    args = p.parse_args()

    if args.setup:
        cmd_setup()
        return
    if args.check:
        cmd_check()
        return
    if not args.files:
        die(2, "No input files. Usage: push_to_gdocs.py FILE [FILE ...] [--folder ID]")
    if args.update and args.new:
        die(2, "--update and --new are mutually exclusive.")

    _, missing = check_deps(need_merman=False)
    if missing:
        die(3, "Missing dependencies: %s. Run: push_to_gdocs.py --setup" % ", ".join(missing))

    for f in args.files:
        if not os.path.isfile(f):
            die(2, "No such file: %s" % f)

    env = account_env(args.account)
    results = []
    for f in args.files:
        results.append(push_one(f, args, env))

    if args.json:
        for r in results:
            print(json.dumps(r))
    else:
        print("Done:")
        for r in results:
            print("- %s (%s): %s" % (r["title"], r["action"], r["url"]))


if __name__ == "__main__":
    main()
