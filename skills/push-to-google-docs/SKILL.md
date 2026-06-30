---
name: push-to-google-docs
description: Push a local markdown file to Google Docs with tables, images, and mermaid diagrams. Renders mermaid locally with Merman (no browser), packs everything into a single .docx with embedded image bytes, and uploads it once for Google to convert. Uses whatever Google access the project already has (gws CLI, a Drive/Docs MCP, or OAuth). The local file is the source of truth. On first use, run `/push-to-google-docs --setup` to install the dependencies (pandoc, Merman/Rust, a Google transport); an installing agent should offer this before the first push.
user-invocable: true
---

# Push Markdown to Google Docs

Convert a local markdown file to a Google Doc with tables, formatting, and images. The pipeline renders any mermaid diagrams to PNG locally, then builds a single `.docx` with the image bytes embedded and uploads that one file for Google Drive to convert to a Google Doc. Nothing is uploaded except the final document: no per-image uploads, no public sharing, no cleanup. The local file is the source of truth. Handles new documents and updates to an existing one.

## When to use

When the user asks to push, publish, or create a Google Doc from a local markdown file.

**Always convert the file fresh from disk.** Re-read the current bytes of the source file at the moment of conversion (Step 1 copies it in) — never build the Doc from memory, a summary, or content loaded earlier in the conversation. The user may have edited the file since, and the local file is the source of truth. If you already have an older copy in context, discard it and read the file again before preprocessing.

**First run:** if invoked as `/push-to-google-docs --setup`, or if this is the first use and the dependencies below are not installed, run the Setup section first so the first push does not fail partway. An agent that installs this skill should offer to run `--setup` before the first push.

## Why .docx (not HTML)

Google converts an uploaded `.docx` to a Google Doc with images, tables, headings, code, and internal links intact. Because a `.docx` is a zip with the image bytes embedded inside it, the diagrams travel *in the file* — there is no need to upload each image to Drive, make it public, reference it by URL, and delete it later (the old HTML-import path required all of that, and left images briefly world-readable). One upload, one conversion.

## Prerequisites

- **pandoc** — markdown → docx. Check `command -v pandoc`; install if missing.
- **merman-cli** — local, browserless mermaid renderer (only needed if the doc has mermaid diagrams). Needs **Rust/cargo**; install with `cargo install merman-cli --locked`. If `cargo install` complains about the rustc version, pin a compatible release, e.g. `cargo install merman-cli --version 0.7.0-alpha.1 --locked`. A prebuilt binary may also be available from the Merman releases (github.com/Latias94/merman). No browser, Node, or Docker required.
- **python3** — small preprocessing scripts.
- **A Google transport** — gws CLI, a Drive/Docs MCP, or OAuth credentials (see Connecting to Google). Only one operation is needed: upload a file and convert it to a Google Doc.

Merman is an independent, parity-focused reimplementation of Mermaid and is currently alpha. It renders common diagrams (sequence, flowchart) faithfully, but may not cover every diagram type. See the fallback in Step 2.

## Setup (`--setup`)

Run this before the first real use, or whenever invoked as `/push-to-google-docs --setup`. Check each dependency, offer to install anything missing (with the user's OK), and confirm the Google transport is authenticated. Bound every install/check command with the `run()` helper (Timeouts and retries).

1. **pandoc** — `command -v pandoc`. If missing, install it (macOS: `brew install pandoc`; Debian/Ubuntu: `apt-get install pandoc`; Windows: `winget install --id JohnMacFarlane.Pandoc`).
2. **Merman** (only if diagrams are expected) — `command -v merman-cli`. If missing: it needs **Rust/cargo**, so check `command -v cargo` first. With cargo present, `cargo install merman-cli --locked` (note the one-time ~2-3 min compile; if it fails on the rustc version, pin a compatible release, e.g. `--version 0.7.0-alpha.1 --locked`). If cargo is missing, either install Rust (`curl https://sh.rustup.rs -sSf | sh`) or point the user at a prebuilt Merman binary from github.com/Latias94/merman.
3. **python3** — `command -v python3` (runs the pipeline scripts).
4. **A Google transport** — confirm one of: gws (`command -v gws`, then `gws auth status` shows a signed-in user with the Drive scope), a connected Drive/Docs MCP, or OAuth credentials on disk. If none, walk the user through setting one up.

Finish by reporting a short checklist of what is present and what was installed, then say the skill is ready.

## Connecting to Google

This skill makes no assumption about how Google is reached. Find what the project already has and use it. Do not hardcode credential file paths. The skill needs exactly **one** operation from the transport: create a Google Doc from an uploaded `.docx` (or replace an existing doc's content with one).

- gws CLI: check `command -v gws`, then `gws auth status`. Confirm a signed-in user and the Drive scope `https://www.googleapis.com/auth/drive`.
- A Google Drive or Docs MCP: check whether this session exposes MCP tools for Drive or Docs (tool names containing `drive` or `docs`). Use it for folder browsing and, if it can import a `.docx`, for the upload.
- Direct Drive REST via OAuth: if gws and a usable MCP are both absent but the project has Google OAuth credentials on disk (for example from a `google-docs-mcp` setup), the REST fallback at the end of this file performs the upload directly. Discover the credentials directory at run time; never hardcode a path.

Prefer whatever can import a `.docx`; gws always can. If none is available, stop and tell the user to set one up, then re-run.

## Working directory and temp files

gws sandboxes uploads to the current directory. Work in a temp subdir inside the current project, for example `./.gdocs-tmp/`. Write every intermediate file there, run the upload from inside it, and delete it when done. Do not put files you upload through gws in `/tmp`.

## Pipeline

### Step 1: Read and preprocess

Run from `./.gdocs-tmp/` with the source copied in **fresh from disk** as `source.md` (re-read it now; do not reuse an earlier copy). Handle wiki-links and mermaid extraction.

```python
import re
md = open('source.md').read()

# Wiki-links -> plain text. Internal section links are not preserved (see note below).
md = re.sub(r'\[\[[^#\]|]*#[^\]|]+\|([^\]]+)\]\]', r'\1', md)  # [[Doc#Sec|text]] -> text
md = re.sub(r'\[\[[^#\]|]*#([^\]|]+)\]\]',          r'\1', md)  # [[Doc#Sec]] / [[#Sec]] -> Sec
md = re.sub(r'\[\[[^\]|]+\|([^\]]+)\]\]',           r'\1', md)  # [[Doc|text]] -> text
md = re.sub(r'\[\[([^\]]+)\]\]',                    r'\1', md)  # [[Doc]] -> Doc

# Pull each mermaid block to a file; leave a token to fill after rendering.
blocks = []
def repl(m):
    blocks.append(m.group(1)); return '@@MERMAID_%d@@' % len(blocks)
md = re.sub(r'```mermaid\n(.*?)```', repl, md, flags=re.DOTALL)
for i, b in enumerate(blocks, 1):
    open('mermaid_%d.mmd' % i, 'w').write(b)
open('preprocessed.md', 'w').write(md)
```

Local images (`![alt](path)` with a local path) need no special handling: pandoc embeds local image bytes into the `.docx` directly. Remote `http(s)` images are fetched and embedded by pandoc too. Leave both as-is.

### Step 2: Render mermaid with Merman (local, no browser)

For each extracted block, render to PNG with `merman-cli`, through the bounded `run()` helper (see Timeouts and retries):

```python
run(["merman-cli", "-i", "mermaid_N.mmd", "-o", "mermaid_N.png", "-t", "default", "-b", "white"], timeout=30)
```

Use the `default` theme (mermaid's standard colored palette), not `neutral` (which is grayscale). A diagram that specifies its own colors overrides this: an inline `%%{init: {"theme": "..."}}%%` directive or explicit `style`/`classDef` fills take precedence, so authored colors are preserved and only unstyled diagrams fall back to `default`.

Then replace each `@@MERMAID_N@@` token in `preprocessed.md` with a local image reference, sized to fit the page (a Google Doc content area is ~6.5in wide):

```
![Diagram N](mermaid_N.png){width=6in}
```

**If merman-cli fails on a block** (it is alpha and may not support every diagram type), do not silently drop or degrade it. Stop and ask the user, with `AskUserQuestion`, whether to render that diagram with **kroki** instead. The prompt must state plainly that **kroki is an external web service**: choosing it sends the diagram's source over the network to kroki.io, which renders and returns the image — a confidentiality concern for sensitive diagrams. Only on an explicit yes, render via kroki (bounded):

```python
run(["curl", "-s", "-X", "POST", "https://kroki.io/mermaid/png",
     "--data-binary", "@mermaid_N.mmd", "-o", "mermaid_N.png"], timeout=30)
```

If the user declines, ask whether to leave that diagram as a fenced code block in the doc or abort.

### Step 3: Build the style reference and convert to .docx

Pandoc's default reference document sets a theme font (recent pandoc defaults to Aptos, which Google has no match for and substitutes with "Play") and gives headings a themed color. To get plain Arial and all-black text and headings, generate a patched reference once and convert against it. The patch is version-robust — it rewrites whatever the local pandoc happens to default to, rather than assuming specific font names or color values:

```python
import zipfile, re, subprocess

default = subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"],
                         capture_output=True, timeout=30).stdout
open("ref_default.docx", "wb").write(default)
src = zipfile.ZipFile("ref_default.docx"); items = {n: src.read(n) for n in src.namelist()}; src.close()

# Theme major/minor fonts -> Arial (whatever they currently are).
th = items["word/theme/theme1.xml"].decode()
th = re.sub(r'(<a:majorFont>\s*<a:latin typeface=")[^"]*', r'\1Arial', th)
th = re.sub(r'(<a:minorFont>\s*<a:latin typeface=")[^"]*', r'\1Arial', th)
items["word/theme/theme1.xml"] = th.encode()

# Heading/Title/Subtitle color -> black, stripping any themeColor (which would override an explicit value).
st = items["word/styles.xml"].decode()
st = re.sub(r'<w:style\b[^>]*w:styleId="(?:Heading\d|Title|Subtitle)"[^>]*>.*?</w:style>',
            lambda m: re.sub(r'<w:color\b[^>]*/>', '<w:color w:val="000000"/>', m.group(0)),
            st, flags=re.DOTALL)
# Force black body text by default.
st = re.sub(r'(<w:rPrDefault>\s*<w:rPr>)', r'\1<w:color w:val="000000"/>', st, count=1)
items["word/styles.xml"] = st.encode()

with zipfile.ZipFile("reference.docx", "w", zipfile.ZIP_DEFLATED) as z:
    for n, d in items.items(): z.writestr(n, d)

run(["pandoc", "preprocessed.md", "-f", "gfm", "-t", "docx", "--reference-doc=reference.docx", "-o", "output.docx"], timeout=60)

# Strip heading bookmarks. Pandoc emits a <w:bookmarkStart/> per heading (for internal
# cross-references); Google Docs renders each as a visible bookmark anchor on the heading,
# which is noise. This skill does not use internal links, so remove all bookmarks.
zin = zipfile.ZipFile("output.docx"); parts = {n: zin.read(n) for n in zin.namelist()}; zin.close()
doc = parts["word/document.xml"].decode()
doc = re.sub(r'<w:bookmarkStart\b[^>]*/>', '', doc)
doc = re.sub(r'<w:bookmarkEnd\b[^>]*/>', '', doc)
parts["word/document.xml"] = doc.encode()
with zipfile.ZipFile("output.docx", "w", zipfile.ZIP_DEFLATED) as z:
    for n, d in parts.items(): z.writestr(n, d)
```

Pandoc embeds the mermaid PNGs (and any local/remote images) into the `.docx`, and renders tables, headings, code blocks, and block quotes natively. No HTML post-processing is needed. Code spans stay monospace (Consolas/Courier New); only body and heading text are forced to black. The bookmark-strip step above drops the per-heading anchors Google Docs would otherwise show.

### Step 4: Upload the .docx and convert to a Google Doc

Set the title from the markdown's H1 (or a title the user gave). Create a new doc, or update an existing one if the user pointed at a doc or one with the same title already exists in the target folder. See the transport recipes below. A full update replaces the body and keeps the doc ID, URL, and sharing.

### Step 5: Clean up and output the link

Delete `./.gdocs-tmp/`. There are no temporary Drive files to remove. Then:

```
Done:
- Document: https://docs.google.com/document/d/DOC_ID/edit
```

## Destination

Before creating a new doc, ask where it should go with `AskUserQuestion`: Drive root by default, a folder the user names, or a folder ID/URL pasted via "Other". If the user named a destination in their request, use it. Resolve a folder name to an ID with the transport. Before creating, check the target folder for a doc with the same title and offer update vs new.

## Timeouts and retries

Every network call (the Drive upload, kroki, any MCP/REST call) must be bounded — never run one unbounded. A single gws upload once hung for over two minutes; a bounded call with one retry recovers in seconds. macOS has no `timeout` command, so wrap calls in Python's `subprocess` timeout rather than shell `timeout`. Use this helper for all transport and external calls in this skill:

```python
import subprocess, time

def run(cmd, timeout=60, retries=1):
    """Run cmd with a hard timeout; retry once on timeout or failure. Returns stdout."""
    last = ""
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return r.stdout
            last = "exit %d: %s" % (r.returncode, (r.stderr or "")[:300])
        except subprocess.TimeoutExpired:
            last = "timed out after %ds" % timeout
        if attempt < retries:
            time.sleep(2)
    raise RuntimeError("command failed (%s): %s" % (last, " ".join(map(str, cmd[:4]))))
```

Render steps are local but still bound them defensively: `merman-cli` with `timeout=30`, `pandoc` with `timeout=60`, kroki with `timeout=30`. The Drive upload uses the default `timeout=60`. If a call exhausts its retry, stop and report the failure — do not hang or silently skip.

## Transport recipes

### gws recipe

Drive gws through the `run()` helper above so every call is bounded. Run from inside `./.gdocs-tmp/` so the relative path sits within the current directory (gws rejects `--upload` paths outside cwd). gws prints a `Using keyring backend` line to stderr; with `capture_output` that goes to `r.stderr`, so stdout stays clean JSON. The docx MIME type is `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.

```python
import json
GWS = "gws"; DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Create a Doc from the docx (omit parents for Drive root)
meta = {"name": "TITLE", "mimeType": "application/vnd.google-apps.document", "parents": ["FOLDER_ID"]}
doc_id = json.loads(run([GWS, "drive", "files", "create", "--json", json.dumps(meta),
    "--upload", "output.docx", "--upload-content-type", DOCX, "--format", "json"]))["id"]

# Update an existing Doc's content
run([GWS, "drive", "files", "update", "--params", '{"fileId":"DOC_ID"}',
     "--upload", "output.docx", "--upload-content-type", DOCX, "-o", "gws_resp.json", "--format", "json"])

# Find a doc by title in a folder (dedupe)
q = 'FOLDER_ID in parents and name = "TITLE" and trashed = false'
hits = json.loads(run([GWS, "drive", "files", "list", "--format", "json",
    "--params", json.dumps({"q": q, "fields": "files(id,name)"})]))
```

### Direct Drive REST fallback (OAuth)

Use only when neither gws nor a docx-importing MCP is available, but Google OAuth credentials exist on disk (what a `google-docs-mcp` setup leaves behind). Locate credentials, do not hardcode a path: resolve `$GOOGLE_DOCS_CREDS_DIR`, then a conventional location such as `~/.config/google-docs-mcp/`. If neither holds `token.json` and `credentials.json`, ask the user where they live (or to set `GOOGLE_DOCS_CREDS_DIR`) and stop. The token JSON must carry a `refresh_token`; the credentials JSON is the installed-app shape (`creds['installed']`), or `creds['web']`.

```python
import json, os, urllib.request, urllib.parse

creds_dir = os.environ.get('GOOGLE_DOCS_CREDS_DIR') or os.path.expanduser('~/.config/google-docs-mcp')
with open(os.path.join(creds_dir, 'token.json')) as f: tokens = json.load(f)
with open(os.path.join(creds_dir, 'credentials.json')) as f: creds = json.load(f)
client = creds.get('installed') or creds['web']
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
B = '===B==='

def access_token():
    data = urllib.parse.urlencode({
        'client_id': client['client_id'], 'client_secret': client['client_secret'],
        'refresh_token': tokens['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    return json.loads(urllib.request.urlopen(
        urllib.request.Request('https://oauth2.googleapis.com/token', data=data)).read())['access_token']

def _send(metadata, url, tok, method='POST'):
    body = (f'--{B}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'
            f'{json.dumps(metadata)}\r\n--{B}\r\n'
            f'Content-Type: {DOCX}\r\n\r\n').encode() + open('output.docx','rb').read() + f'\r\n--{B}--'.encode()
    req = urllib.request.Request(url, data=body, method=method,
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': f'multipart/related; boundary={B}'})
    return json.loads(urllib.request.urlopen(req).read() or b'{}')

def create_doc(title, tok, folder_id=None):
    md = {'name': title, 'mimeType': 'application/vnd.google-apps.document'}
    if folder_id: md['parents'] = [folder_id]
    return _send(md, 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id', tok)['id']

def update_doc(doc_id, tok):
    _send({}, f'https://www.googleapis.com/upload/drive/v3/files/{doc_id}?uploadType=multipart&fields=id', tok, method='PATCH')
```

## Implementation notes

- Single upload: the `.docx` carries the image bytes, so there are no per-image Drive uploads, no public permissions, and no temp-file cleanup on Drive. Deleting `./.gdocs-tmp/` is the only cleanup.
- Images: pandoc embeds local images by path and downloads + embeds remote `http(s)` images. Size with the `{width=Nin}` attribute; ~6in fits the default page. Mermaid PNGs from merman are referenced the same way.
- Tables, code, headings, quotes: pandoc's docx writer renders these natively. The old HTML post-processing (code-block tables, margin and whitespace hacks) is gone.
- Internal links are not supported. Wiki-links (`[[Doc]]`, `[[Doc|text]]`, `[[#Section]]`) are flattened to their display text in Step 1, and heading bookmarks are stripped in Step 3, so the Doc has no in-document anchors. This is intentional: the bookmarks Google Docs rendered on every heading were more noise than the links were worth.
- Title as H1: the markdown must carry the title as a single `# H1`; the Doc title-bar name is set by the upload metadata `name`.
- Merman is alpha: render failures are expected on uncommon diagram types. Handle them per Step 2 (ask before any external fallback); never send a diagram out without explicit consent.
- Updates replace all content: a full update keeps the doc ID, URL, and sharing. Comments anchored to specific text may lose their anchor.
- gws constraints: `--upload` and `-o` paths must be inside the current directory, and gws emits a keyring line on stderr. Work inside the temp subdir and parse stdout.
