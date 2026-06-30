---
name: push-to-google-docs
description: Push a local markdown file to Google Docs with tables, images, and mermaid diagrams. Renders mermaid locally with Merman (no browser), packs everything into a single .docx with embedded image bytes, and uploads it once for Google to convert. Uses whatever Google access the project already has (gws CLI, a Drive/Docs MCP, or OAuth). The local file is the source of truth. On first use, run `/push-to-google-docs --setup` to install the dependencies (pandoc, Merman/Rust, a Google transport); an installing agent should offer this before the first push.
user-invocable: true
---

# Push Markdown to Google Docs

Convert local markdown to a Google Doc. The whole deterministic pipeline lives in `push_to_gdocs.py` (in this skill's directory) — one script call does preprocessing, mermaid rendering, the `.docx` build, and the upload. Your job is to launch the script and handle the two decisions it deliberately leaves to you. Do **not** re-implement the pipeline inline.

`SCRIPT` below means the `push_to_gdocs.py` file sitting next to this `SKILL.md` (use its absolute path). The local markdown file is always the source of truth; the script re-reads it fresh from disk on every run.

## Launch sequence

1. **Setup check (cheap, skip when possible).** A marker at `~/.claude/.push-to-gdocs-setup.json` records that dependencies were verified.
   - If `~/.claude/.push-to-gdocs-setup.json` exists, assume deps are ready and go straight to step 2. No dependency probing.
   - If it is absent, run `python3 SCRIPT --setup` once. It installs/verifies pandoc, Merman, python3, and a Google transport, then writes the marker. After it succeeds, continue.
   - If invoked as `/push-to-google-docs --setup`, run `python3 SCRIPT --setup` regardless and stop there.
2. **Destination.** If the user named a folder (ID or URL), pass it as `--folder`. Otherwise ask where the doc should go (Drive root by default, a named folder, or a folder ID/URL) before creating anything. A Drive folder URL works as-is — the script extracts the ID.
3. **Account.** If the project uses a specific Google account, pass `--account NAME` (maps to the gws profile `~/.config/gws/clients/NAME` + Keychain `gws-NAME-client-id`/`-secret`). For this workspace that is `--account boundless`. Omit it to use the active gws account.
4. **Push.** Run the script (one call, all files at once):
   ```
   python3 SCRIPT FILE [FILE ...] --folder FOLDER --account NAME [--update|--new] [--json]
   ```
   Use `--json` when you want to parse the returned doc IDs/URLs.

## The two decisions the script hands back

The script never guesses these — it exits non-zero and tells you what to do.

- **Update vs. new (exit 5).** A bare run errors if a doc with the same title already exists in the folder. Decide with the user (or from context): pass `--update` to replace that doc in place (keeps its ID, URL, sharing) or `--new` to create another. When you already know the doc exists and should be replaced (e.g. re-pushing an edit), pass `--update` up front.
- **Mermaid fallback (exit 4).** If Merman can't render a diagram, the script stops rather than leaking the diagram. Ask the user whether to render it via **kroki.io**, stating plainly that kroki is an external web service that receives the diagram source over the network (a confidentiality concern). Only on an explicit yes, re-run with `--allow-kroki`. If they decline, remove the diagram or abort.

## Other exit codes

`2` usage error · `3` missing dependency (run `--setup`) · `6` transport/upload failure. On any of these, report the script's stderr message to the user; don't paper over it.

## What the script does (reference, not steps to perform)

Per file: re-read from disk → flatten wiki-links (`[[Doc|text]]` → text) → isolate bold-only pseudo-heading lines (`**Why it works.**`) into their own paragraphs → extract and render mermaid with Merman (`default` theme, white background), referenced by filename via pandoc `--resource-path` so paths with spaces still resolve → build a patched pandoc reference (Arial, black text, 11pt body, headings left larger; a gray monospace `SourceCode` style for code blocks) → convert to `.docx` → post-process the docx: strip per-heading bookmark anchors, give every table a 1pt black grid, and bold the header row (Google Docs drops the style-level table borders and header formatting pandoc relies on, so these are applied inline) → upload once via gws and let Google convert. Images (local and remote `http(s)`) are embedded by pandoc; nothing else is uploaded to Drive and there is no public sharing. Internal links/anchors are intentionally not preserved. The doc title comes from the markdown H1 unless `--title` is given.

## Transports

The script uses the gws CLI. If a project has no gws but does have a Drive/Docs MCP or OAuth credentials on disk, that path isn't wired into the script yet — fall back to the manual transport (gws install, or a docx-importing MCP) and tell the user. The single operation needed is: upload a `.docx` and convert it to a Google Doc.
