---
name: push-to-google-docs
description: Push a local markdown file to Google Docs with tables, images, and mermaid diagrams. Uses whatever Google access the project already has (the gws CLI or a Google Drive/Docs MCP); if none is set up, it asks you to add one. The local file is the source of truth.
---

# Push Markdown to Google Docs

Convert a local markdown file to a Google Doc with tables, formatting, and images. The local file is the source of truth. Handles new documents and updates to an existing one.

## When to use

When the user asks to push, publish, or create a Google Doc from a local markdown file.

## Connecting to Google

This skill makes no assumption about how Google is reached. Find what the project already has and use it. Do not hardcode credential file paths.

- gws CLI: check `command -v gws`, then `gws auth status`. Confirm a valid signed-in user and the Drive scope `https://www.googleapis.com/auth/drive`. In a per-client setup, gws may need its config and OAuth values supplied inline (see the project's own guidance); use those.
- A Google Drive or Docs MCP: check whether this session exposes MCP tools for Google Drive or Docs (tool names containing `drive` or `docs`).
- Direct Drive REST via OAuth: if gws and a usable MCP are both absent but the project has Google OAuth credentials on disk (for example from a `google-docs-mcp` setup), the REST fallback at the end of this file runs the same operations directly. Discover the credentials directory at run time; never hardcode a path.

Use whichever is available. If more than one is, prefer the one that can import HTML and set file sharing; gws does both. If none is available, stop and tell the user to set one up (install and authenticate gws, connect a Google Drive MCP, or provide OAuth credentials), then re-run.

Whatever the transport, the skill needs three operations from it:
1. Upload an image to Drive and get a URL the Doc converter can fetch (usually the file must be shared so anyone with the link can read).
2. Create a Google Doc by importing HTML, or replace an existing doc's content.
3. Delete temporary uploaded images.

The gws recipe below shows these concretely. With an MCP, map the same steps onto its tools. If the available MCP cannot import HTML, fall back to gws or tell the user.

## Working directory and temp files

gws sandboxes uploads and outputs to the current directory. Work in a temp subdir inside the current project, for example `./.gdocs-tmp/`. Write every intermediate file there, run the upload commands from inside it, and delete it when done. Do not put files you upload through gws in `/tmp`.

## Pipeline

### Step 1: Read and preprocess

Run this from `./.gdocs-tmp/` with the source markdown copied in as `source.md`. It handles wiki-links, mermaid extraction, and mermaid placeholders.

```python
import re
md = open('source.md').read()

def enc(s): return s.strip().replace(' ', '__SP__')

# Internal section links -> anchor links, resolved to real heading ids in step 5.
# A bare [[#Section]] in Obsidian links to a heading in the same doc; keep it working.
md = re.sub(r'\[\[#([^\]|]+)\|([^\]]+)\]\]', lambda m: f'[{m.group(2).strip()}](#__internal__::{enc(m.group(1))})', md)
md = re.sub(r'\[\[#([^\]|]+)\]\]',          lambda m: f'[{m.group(1).strip()}](#__internal__::{enc(m.group(1))})', md)
# Cross-file links keep their text; the cross-doc link is dropped.
md = re.sub(r'\[\[[^#\]|]+#[^\]|]+\|([^\]]+)\]\]', r'\1', md)
md = re.sub(r'\[\[[^#\]|]+#([^\]|]+)\]\]',          r'\1', md)
# Plain wiki-links.
md = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', md)
md = re.sub(r'\[\[([^\]]+)\]\]',            r'\1', md)

# Mermaid: pull each block to a file, leave a token to fill after rendering+upload.
blocks = []
def repl(m):
    blocks.append(m.group(1)); return f'@@MERMAID_{len(blocks)}@@'
md = re.sub(r'```mermaid\n(.*?)```', repl, md, flags=re.DOTALL)
for i, b in enumerate(blocks, 1):
    open(f'mermaid_{i}.mmd', 'w').write(b)
open('preprocessed.md', 'w').write(md)
```

Local images: also find every `![alt](path)` whose path is a local file (not `http://` or `https://`). They must be uploaded to Drive, because Google's HTML converter strips local paths and `data:` URIs. Treat them like mermaid PNGs in steps 2-3 (upload, cap width, swap in the public URL). Remote `http(s)` image URLs are left untouched; Google fetches them.

### Step 2: Render mermaid to PNG

For each mermaid block:
```bash
npx --yes @mermaid-js/mermaid-cli -i ./.gdocs-tmp/mermaid_N.mmd -o ./.gdocs-tmp/mermaid_N.png -b white -t neutral --scale 2
```
`--scale 2` keeps it crisp; `-b white` reads cleanly in Docs.

### Step 3: Upload images and rewrite references, capping width

For each local image and rendered mermaid PNG: upload to Drive, share it so anyone with the link can read, then replace its token in `preprocessed.md` with an `<img>` tag whose width is capped to fit the page. Keep the uploaded file IDs for cleanup.

Cap the width: a Google Doc's content area is 6.5in (about 624px at 96dpi). An image imported at native width overflows the page. Set `width` to `min(native_px, 600)`; Google scales height proportionally. Read a PNG's pixel width from its header; for non-PNG local images you cannot easily measure, so cap at 600.

```python
import struct
MAXW = 600
def png_width(path):
    with open(path, 'rb') as f:
        f.read(16)                     # 8-byte signature + 4 len + 4 'IHDR'
        return struct.unpack('>I', f.read(4))[0]
# For token @@MERMAID_N@@ backed by mermaid_N.png and public URL:
W = min(png_width('mermaid_N.png'), MAXW)
img = f'<img src="https://drive.google.com/uc?export=view&id=FILE_ID" width="{W}" alt="Diagram N" />'
# md = md.replace('@@MERMAID_N@@', img)
```

### Step 4: Convert markdown to HTML with pandoc

Check `command -v pandoc`; if missing, `brew install pandoc`. Pandoc handles nested lists, complex tables, and mixed formatting that simpler converters get wrong, so do not substitute a Python converter.

```bash
pandoc ./.gdocs-tmp/preprocessed.md -f gfm -t html5 -s --syntax-highlighting=none --wrap=none -o ./.gdocs-tmp/output.html
```
`--wrap=none` stops pandoc inserting line breaks inside table cells, which Google can read as content. Do not pass `--metadata=title:` or `-V title=`: with standalone mode (`-s`), pandoc renders title metadata as an `<h1>`, duplicating the H1 already in the markdown. The Doc's title is set by the upload metadata.

### Step 5: Post-process the HTML

Run this once. It writes back to `./.gdocs-tmp/output.html`.

```python
import re, html as H
html = open('output.html').read()

# 1. Strip pandoc's <style> block (max-width/padding that Google reads as narrow margins).
html = re.sub(r'<style>.*?</style>', '', html, flags=re.DOTALL)

# 2. Wrap <pre> code blocks in a single-cell table so Google renders a code block
#    (gray background, padding, monospace). Run before the table whitespace cleanup.
def replace_pre(m):
    return ('<table style="width:100%;border-collapse:collapse;margin-bottom:12pt;">'
            '<tr><td style="background-color:#f3f4f6;padding:12px 16px;border:1px solid #e0e0e0;">'
            + m.group(0) + '</td></tr></table>')
html = re.sub(r'<pre[^>]*>.*?</pre>', replace_pre, html, flags=re.DOTALL)

# 3. Inline padding on data cells (skip cells that already have a style).
html = re.sub(r'<th\b(?![^>]*style)', '<th style="padding:4px 8px;"', html)
html = re.sub(r'<td\b(?![^>]*style)', '<td style="padding:2px 8px;"', html)

# 4. Strip whitespace between table tags; Google treats it as spurious cell content.
html = re.sub(r'>\s+<(/?(?:table|thead|tbody|tr|th|td))', r'><\1', html)
html = re.sub(r'\s+</t([hd])>', r'</t\1>', html)

# 5. Monospace for code.
html = re.sub(r'<pre(?![^>]*style)', '<pre style="font-family:Courier New,monospace;font-size:10pt;white-space:pre-wrap;margin:0;"', html)
html = html.replace('<code>', '<code style="font-family:Courier New,monospace;font-size:10pt;">')

# 6. Resolve internal section links. Google turns an anchor whose href is a
#    heading id into a working in-document link. Match each sentinel link to a
#    heading by text (pandoc gives headings ids; read the actual ids).
heads = {}
for m in re.finditer(r'<h[1-6][^>]*\bid="([^"]+)"[^>]*>(.*?)</h[1-6]>', html, re.DOTALL):
    text = H.unescape(re.sub('<[^>]+>', '', m.group(2)))
    heads[re.sub(r'\s+', ' ', text).strip().lower()] = m.group(1)
def resolve(m):
    name = H.unescape(m.group(1)).replace('__SP__', ' ')
    hid = heads.get(re.sub(r'\s+', ' ', name).strip().lower())
    return f'href="#{hid}"' if hid else 'href="#"'
html = re.sub(r'href="#__internal__::([^"]+)"', resolve, html)

# 7. Block spacing. Google imports <p> with zero space below, so paragraphs,
#    tables, and adjacent images run together. Add margins (Google maps CSS
#    margin to paragraph spacing). Skip elements that already carry a style.
html = re.sub(r'<p(?![^>]*style)', '<p style="margin:0 0 10pt 0;"', html)
html = re.sub(r'<table(?![^>]*style)', '<table style="margin-bottom:12pt;"', html)
html = re.sub(r'<ul(?![^>]*style)', '<ul style="margin-bottom:10pt;"', html)
html = re.sub(r'<ol(?![^>]*style)', '<ol style="margin-bottom:10pt;"', html)
html = re.sub(r'<blockquote(?![^>]*style)', '<blockquote style="margin:0 0 10pt 0;"', html)

open('output.html', 'w').write(html)
```

### Step 6: Upload the HTML as a Google Doc

Set the Doc title from the markdown's H1 (or a title the user gave). Create a new doc, or update an existing one if the user pointed at a doc or one with the same title already exists in the target folder. A full update replaces the body and keeps the doc ID, URL, and sharing.

### Step 7: Clean up

Delete the temp Drive images by file ID, then remove `./.gdocs-tmp/`.

### Step 8: Output the link

```
Done:
- Document: https://docs.google.com/document/d/DOC_ID/edit
```

## Destination

Before creating a new doc, ask where it should go with `AskUserQuestion`: Drive root by default, a folder the user names, or a folder ID/URL pasted via "Other". If the user named a destination in their request, use it directly. Resolve a folder name to an ID with the transport (with gws, list folders by name). Before creating, check the target folder for a doc with the same title and offer update vs new.

## gws recipe

Run these from inside `./.gdocs-tmp/` so the relative paths sit within the current directory (gws rejects paths outside cwd). gws prints a `Using keyring backend` line to stderr, so read JSON from stdout only (`2>/dev/null`).

Upload an image, share it, build its URL:
```bash
ID=$(gws drive files create --json '{"name":"img.png"}' \
  --upload img.png --upload-content-type image/png --format json 2>/dev/null \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
gws drive permissions create --params "{\"fileId\":\"$ID\"}" \
  --json '{"role":"reader","type":"anyone"}' --format json 2>/dev/null >/dev/null
# URL: https://drive.google.com/uc?export=view&id=$ID
```

Create a doc from HTML (omit `parents` for Drive root):
```bash
DOC_ID=$(gws drive files create \
  --json '{"name":"TITLE","mimeType":"application/vnd.google-apps.document","parents":["FOLDER_ID"]}' \
  --upload output.html --upload-content-type text/html --format json 2>/dev/null \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
```

Update an existing doc's content:
```bash
gws drive files update --params '{"fileId":"DOC_ID"}' \
  --upload output.html --upload-content-type text/html -o gws_resp.json --format json 2>/dev/null
```

Delete a temp image (gws writes the empty response to the `-o` file, which must be inside cwd):
```bash
gws drive files delete --params "{\"fileId\":\"$ID\"}" -o gws_resp.json 2>/dev/null
```

## Direct Drive REST fallback (OAuth)

Use this only when neither gws nor an HTML-importing MCP is available, but Google OAuth credentials exist on disk (this is what a `google-docs-mcp` setup leaves behind). It performs the same three operations against the Drive REST API.

Locate credentials, do not hardcode a path. Resolve the directory in order: `$GOOGLE_DOCS_CREDS_DIR`, then a conventional location such as `~/.config/google-docs-mcp/`. If neither holds `token.json` and `credentials.json`, ask the user where they live (or to set `GOOGLE_DOCS_CREDS_DIR`) and stop until you have them. The token JSON must carry a `refresh_token`; the credentials JSON is the installed-app shape (`creds['installed']`), or `creds['web']` for a web client.

Unlike gws, these REST calls have no cwd restriction, so they read the files in `./.gdocs-tmp/` by path. Keep the token in memory and run image upload, doc create/update, and cleanup in one Python process.

```python
import json, os, urllib.request, urllib.parse

creds_dir = os.environ.get('GOOGLE_DOCS_CREDS_DIR') or os.path.expanduser('~/.config/google-docs-mcp')
with open(os.path.join(creds_dir, 'token.json')) as f: tokens = json.load(f)
with open(os.path.join(creds_dir, 'credentials.json')) as f: creds = json.load(f)
client = creds.get('installed') or creds['web']
B = '===B==='

def access_token():
    data = urllib.parse.urlencode({
        'client_id': client['client_id'], 'client_secret': client['client_secret'],
        'refresh_token': tokens['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data)
    return json.loads(urllib.request.urlopen(req).read())['access_token']

def _multipart(metadata, content, content_type):
    return (f'--{B}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'
            f'{json.dumps(metadata)}\r\n--{B}\r\n'
            f'Content-Type: {content_type}\r\n\r\n').encode() + content + f'\r\n--{B}--'.encode()

def _post_upload(metadata, content, content_type, tok, url=None, method='POST'):
    url = url or 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id'
    req = urllib.request.Request(url, data=_multipart(metadata, content, content_type),
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': f'multipart/related; boundary={B}'},
        method=method)
    return json.loads(urllib.request.urlopen(req).read() or b'{}')

def upload_image(path, tok, folder_id=None):
    md = {'name': os.path.basename(path)}
    if folder_id: md['parents'] = [folder_id]
    fid = _post_upload(md, open(path, 'rb').read(), 'image/png', tok)['id']
    perm = json.dumps({'role': 'reader', 'type': 'anyone'}).encode()
    urllib.request.urlopen(urllib.request.Request(
        f'https://www.googleapis.com/drive/v3/files/{fid}/permissions',
        data=perm, headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}))
    return fid  # URL: https://drive.google.com/uc?export=view&id=<fid>

def create_doc(html_path, title, tok, folder_id=None):
    md = {'name': title, 'mimeType': 'application/vnd.google-apps.document'}
    if folder_id: md['parents'] = [folder_id]
    return _post_upload(md, open(html_path, 'rb').read(), 'text/html', tok)['id']

def update_doc(html_path, doc_id, tok):
    url = f'https://www.googleapis.com/upload/drive/v3/files/{doc_id}?uploadType=multipart&fields=id'
    _post_upload({}, open(html_path, 'rb').read(), 'text/html', tok, url=url, method='PATCH')

def delete_file(fid, tok):
    urllib.request.urlopen(urllib.request.Request(
        f'https://www.googleapis.com/drive/v3/files/{fid}',
        headers={'Authorization': f'Bearer {tok}'}, method='DELETE'))
```

## Implementation notes

- Tables: pandoc converts pipe tables to `<table>`, which Google's importer turns into native tables. `<th>` headers render bold. `<br>` inside cells is valid GFM; do not convert it to a newline during preprocessing, that breaks the pipe table.
- Title as H1: the markdown must carry the title as a single `# H1`. Pandoc converts it. Do not also inject a title via metadata or post-processing, or the doc gets two titles. The title-bar name is set by the upload metadata.
- Images need public URLs: `data:` URIs and local paths are stripped by Google's converter. That is why local images and mermaid PNGs are uploaded to Drive first, shared, referenced by URL, then deleted. Once the doc is created Google rehosts the image, so deleting the temp Drive file does not break the doc.
- Margins: pandoc's standalone CSS sets a narrow `max-width`; step 5 strips the `<style>` block so Google uses its default margins. Cell padding is then re-added inline.
- Code blocks: step 5 wraps `<pre>` in a gray single-cell table that reads as a code block, with monospace inside.
- Image width: Google imports an image at its native pixel width, so a wide diagram overflows the 6.5in page. Step 3 caps each uploaded image at 600px wide (`min(native, 600)`); Google scales the height. Without this, mermaid diagrams run off the page.
- Paragraph spacing: Google imports `<p>` with zero space below, so paragraphs, tables, and stacked images look jammed together. Step 5 adds `margin` to `<p>`, `<table>`, lists, and blockquotes; Google maps CSS margin to paragraph spacing.
- Internal links: Obsidian `[[#Section]]` links are converted in step 1 to anchor links and resolved in step 5 to the heading's id by matching section text. Google then makes them working in-document (bookmark) links. Stripping them to plain text, the old behavior, left a dead table of contents.
- Updates replace all content: a full update keeps the doc ID, URL, and sharing. Comments anchored to specific text may lose their anchor after a full replacement.
- Pandoc is required: check `command -v pandoc` first so you do not trigger a slow `brew` when it is already present.
- gws constraints: uploads and `-o` outputs must be within the current directory, and gws emits a keyring line on stderr. Work inside the temp subdir and parse stdout.
