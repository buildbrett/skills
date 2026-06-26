---
name: push-to-google-docs
description: Push a local markdown file to Google Docs with tables, images, and mermaid diagrams. Renders mermaid locally with Merman (no browser), packs everything into a single .docx with embedded image bytes, and uploads it once for Google to convert. Uses whatever Google access the project already has (gws CLI, a Drive/Docs MCP, or OAuth). The local file is the source of truth.
---

# Push Markdown to Google Docs

Convert a local markdown file to a Google Doc with tables, formatting, and images. The pipeline renders any mermaid diagrams to PNG locally, then builds a single `.docx` with the image bytes embedded and uploads that one file for Google Drive to convert to a Google Doc. Nothing is uploaded except the final document: no per-image uploads, no public sharing, no cleanup. The local file is the source of truth. Handles new documents and updates to an existing one.

## When to use

When the user asks to push, publish, or create a Google Doc from a local markdown file.

## Why .docx (not HTML)

Google converts an uploaded `.docx` to a Google Doc with images, tables, headings, code, and internal links intact. Because a `.docx` is a zip with the image bytes embedded inside it, the diagrams travel *in the file* — there is no need to upload each image to Drive, make it public, reference it by URL, and delete it later (the old HTML-import path required all of that, and left images briefly world-readable). One upload, one conversion.

## Prerequisites

- **pandoc** — markdown → docx. Check `command -v pandoc`; install if missing.
- **merman-cli** — local, browserless mermaid renderer (only needed if the doc has mermaid diagrams). Install with `cargo install merman-cli --locked`. If `cargo install` complains about the rustc version, pin a compatible release, e.g. `cargo install merman-cli --version 0.7.0-alpha.1 --locked`. A prebuilt binary may also be available from the Merman releases (github.com/Latias94/merman). No browser, Node, or Docker required.
- **python3** — small preprocessing scripts.
- **A Google transport** — gws CLI, a Drive/Docs MCP, or OAuth credentials (see Connecting to Google). Only one operation is needed: upload a file and convert it to a Google Doc.

Merman is an independent, parity-focused reimplementation of Mermaid and is currently alpha. It renders common diagrams (sequence, flowchart) faithfully, but may not cover every diagram type. See the fallback in Step 2.

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

Run from `./.gdocs-tmp/` with the source copied in as `source.md`. Handle wiki-links, internal section links, and mermaid extraction.

```python
import re
md = open('source.md').read()

def slug(s):  # approximate pandoc gfm auto_identifier
    s = s.strip().lower(); s = re.sub(r'[^\w\s-]', '', s); return re.sub(r'\s+', '-', s)

# Obsidian internal links -> markdown anchor links (pandoc makes these in-doc bookmarks).
md = re.sub(r'\[\[#([^\]|]+)\|([^\]]+)\]\]', lambda m: '[%s](#%s)' % (m.group(2).strip(), slug(m.group(1))), md)
md = re.sub(r'\[\[#([^\]|]+)\]\]',          lambda m: '[%s](#%s)' % (m.group(1).strip(), slug(m.group(1))), md)
# Cross-file links keep their text; the cross-doc link is dropped.
md = re.sub(r'\[\[[^#\]|]+#[^\]|]+\|([^\]]+)\]\]', r'\1', md)
md = re.sub(r'\[\[[^#\]|]+#([^\]|]+)\]\]',          r'\1', md)
# Plain wiki-links.
md = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', md)
md = re.sub(r'\[\[([^\]]+)\]\]',            r'\1', md)

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

For each extracted block, render to PNG with `merman-cli`:

```bash
merman-cli -i mermaid_N.mmd -o mermaid_N.png -t neutral -b white
```

Then replace each `@@MERMAID_N@@` token in `preprocessed.md` with a local image reference, sized to fit the page (a Google Doc content area is ~6.5in wide):

```
![Diagram N](mermaid_N.png){width=6in}
```

**If merman-cli fails on a block** (it is alpha and may not support every diagram type), do not silently drop or degrade it. Stop and ask the user, with `AskUserQuestion`, whether to render that diagram with **kroki** instead. The prompt must state plainly that **kroki is an external web service**: choosing it sends the diagram's source over the network to kroki.io, which renders and returns the image — a confidentiality concern for sensitive diagrams. Only on an explicit yes, render via kroki:

```bash
curl -s -X POST https://kroki.io/mermaid/png --data-binary @mermaid_N.mmd -o mermaid_N.png
```

If the user declines, ask whether to leave that diagram as a fenced code block in the doc or abort.

### Step 3: Convert to .docx with pandoc

```bash
pandoc preprocessed.md -f gfm -t docx -o output.docx
```

Pandoc embeds the mermaid PNGs (and any local/remote images) into the `.docx`, and renders tables, headings, code blocks, block quotes, and the internal anchor links natively. No HTML post-processing is needed. For custom fonts/spacing, pass `--reference-doc=reference.docx`; the default styling is clean and usually fine.

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

## Transport recipes

### gws recipe

Run from inside `./.gdocs-tmp/` so the relative path sits within the current directory (gws rejects `--upload` paths outside cwd). gws prints a `Using keyring backend` line to stderr, so read JSON from stdout only (`2>/dev/null`). The docx MIME type is `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.

Create a Doc from the docx (omit `parents` for Drive root):
```bash
DOC_ID=$(gws drive files create \
  --json '{"name":"TITLE","mimeType":"application/vnd.google-apps.document","parents":["FOLDER_ID"]}' \
  --upload output.docx \
  --upload-content-type application/vnd.openxmlformats-officedocument.wordprocessingml.document \
  --format json 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
```

Update an existing Doc's content:
```bash
gws drive files update --params '{"fileId":"DOC_ID"}' \
  --upload output.docx \
  --upload-content-type application/vnd.openxmlformats-officedocument.wordprocessingml.document \
  -o gws_resp.json --format json 2>/dev/null
```

Find a doc by title in a folder (dedupe):
```bash
gws drive files list --format json \
  --params '{"q":"FOLDER_ID in parents and name = \"TITLE\" and trashed = false","fields":"files(id,name)"}'
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
- Internal links: Obsidian `[[#Section]]` becomes a markdown anchor link in Step 1; pandoc turns it into a working in-document bookmark link. The anchor must match pandoc's heading id — `slug()` approximates pandoc's gfm rule (lowercase, drop punctuation, spaces to hyphens). If a link lands dead, check the slug against the actual heading text.
- Title as H1: the markdown must carry the title as a single `# H1`; the Doc title-bar name is set by the upload metadata `name`.
- Merman is alpha: render failures are expected on uncommon diagram types. Handle them per Step 2 (ask before any external fallback); never send a diagram out without explicit consent.
- Updates replace all content: a full update keeps the doc ID, URL, and sharing. Comments anchored to specific text may lose their anchor.
- gws constraints: `--upload` and `-o` paths must be inside the current directory, and gws emits a keyring line on stderr. Work inside the temp subdir and parse stdout.
