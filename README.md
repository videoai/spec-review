# ONVIF Spec Review — V1

A local web viewer for reviewing ONVIF specification pull requests, including formatted DocBook, source files, and images. Requires **Python 3.9+ and Git**. No Python packages, build step, or Node installation is needed to run it.

## Start

From your specs checkout:

```sh
./tools/xml-review/start.sh
```

This finds the enclosing repository, starts a loopback-only server at http://127.0.0.1:8765, and opens your browser. Keep the terminal running; stop with Ctrl+C.

```sh
./tools/xml-review/start.sh --port 8766
./tools/xml-review/start.sh --no-open
```

On Windows, run `py -3 tools/xml-review/server.py --open` (or use `python3`). To point at another checkout: `python3 tools/xml-review/server.py --repo /path/to/specs --open`.

## Review workflow

1. Choose a PR. The open PR list loads automatically from the repository's GitHub `origin`; same-repository source branches are supported, forks are excluded.
2. Choose a changed file. The comparison loads automatically. Base is the common ancestor with the target branch; proposed is the PR head. Branch labels show short SHAs, with full SHAs on hover.
3. First/Previous/Next/Last navigate without marking anything. **Reviewed & Next** marks the selected change and advances after saving succeeds. Checking Reviewed or saving a nonempty note does the same.
4. Changes only and Hide reviewed narrow the view. Disable Hide reviewed to revisit or uncheck reviewed changes.
5. The toolbar shows both document progress and **PR-wide progress across every changed file**, including files you have not opened. The file dropdown shows individual counts. Failed renders are reported as incomplete, never as fully reviewed.
6. **More → Export PR notes** downloads the PR summary, file notes, and only commented changes in the current PR comparison, with PR details, branch names/SHAs, section, before/after context, and the note. Uncommented changes and files without notes are omitted.

The last PR, document, filters, and selected change are remembered in browser storage for this checkout. Reopening a URL with an explicit PR takes precedence over the remembered PR.

## Notes and reviewed marks

Notes are automatically saved under the PR number in Git metadata, for example `.git/xml-review-notes-pr-877.json` (the precise location follows `git rev-parse --git-path`). Switching PRs loads that PR's notes. Notes are tied to the exact document comparison; **More → Saved notes** keeps older revisions under the same PR, with their original quoted context and an export option. Unassigned legacy notes are not supported.

Use Add note and Save note. Reviewed and Add note share a line. Once reviewed, Add note is hidden; existing notes remain visible and editable. Deleting a note does not uncheck Reviewed. A draft warning lets you stay or discard before switching PR/document or refreshing. Closing/reloading the browser warns about unfinished notes. Failed saves stay visible; automatic advancement occurs only after a successful save.

Reviewed marks are saved per PR in Git metadata, for example `xml-review-reviewed-pr-877.json`. They carry forward only for identical rendered before/after content in the same document and section. Repeated identical changes are distinguished by occurrence; reorganizing duplicates may need manual rechecking. These are local reviewed marks, not GitHub approvals. Draft notes remain local until you explicitly submit a review. Reviewed marks are never sent as GitHub approvals; none of these local files are committed.

## Refresh from GitHub

The single refresh button runs `git fetch --no-tags origin`, reloads PR metadata, and updates the selected PR. It never checks out, merges, or edits specification files. Startup loads PR metadata but does not fetch automatically.

After refreshing, the viewer reports new changes, reviewed changes retained, changes needing another look, and earlier changes replaced or removed. Matching revised changes to previously reviewed changes uses document/section context, so the recheck count is conservative; only exact content matches retain reviewed marks. Earlier notes stay under their PR's Saved notes. A successful refresh displays its completion time.

Public GitHub repositories work without authentication. For private repositories or higher API limits, install GitHub CLI and run `gh auth login`, or supply `GH_TOKEN`/`GITHUB_TOKEN` in the environment. Tokens stay server-side. Fetching uses Git's configured repository credentials. Authentication failures suggest running `git fetch origin` in your terminal. A shallow clone may need `git fetch --unshallow`.

## Rendering limits

This is a focused DocBook renderer, not the repository's PDF publishing pipeline. It renders headings, paragraphs, lists, tables, cross-reference titles, and code. Prose indentation/reflow is ignored; code whitespace is preserved. Embedded raster/SVG diagrams are loaded from the matching Git revision. Definition/parameter lists, CALS horizontal and vertical spans (including named spans), and column-width proportions are rendered. Unavailable or unsupported image formats remain labelled placeholders. XInclude/DTD/entity expansion is unsupported. Unsupported XML is reported explicitly. Alignment is heuristic; moves can appear as deletion/addition. Formatting-only edits can flag a block without word highlights.

## Verification

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/xml-review -v
```

Optional developer-only JavaScript checks (Node required for these, not to run the tool):

```sh
node --check tools/xml-review/app.js
node tools/xml-review/test_frontend.cjs
```

Tests cover alignment, escaping, whitespace, local persistence, PR note isolation, fetch behaviour/failures, PR-wide summaries and render failures, revision carry-forward, refresh classification, and full PR exports. The launcher was also checked from a fresh temporary Git checkout with no extra packages.

The sticky toolbar uses two compact rows at normal desktop widths: navigation/review actions above filters and progress. **More** contains change counts, saved notes, exports, and the highlight legend.

## GitHub caching and rate limits

PR metadata is cached locally in Git metadata (`xml-review-github-cache.json`) for ten minutes and survives server restarts. Loading a PR list also caches each PR's details, so selecting one normally requires no additional GitHub call. **Refresh from GitHub** bypasses the freshness interval and requests current metadata. Conditional requests reuse GitHub's ETags where available.

When GitHub returns a rate limit, the viewer shows its reset time in the browser's local time. It stops making requests for that authentication identity until the reset or retry-after time. Existing cached metadata remains usable and is explicitly labelled as cached/stale, so local comparisons, notes, and exports remain available. Without cached metadata, it displays the wait time instead of pretending a PR is current. Other permission-related 403 errors are distinguished from rate limits.

Unauthenticated GitHub REST access normally allows 60 requests/hour per public IP. Signing in with `gh auth login` or setting `GH_TOKEN` typically raises that to 5,000/hour. The cache separates authentication identities and never stores tokens. GitHub CLI authentication is reused for HTTP requests; an API error is not silently retried as an unauthenticated request.

## Export PDF

Choose **More → Export PDF** to open a print-ready snapshot of the **selected document**. Click **Print / Save as PDF**, then choose the browser/system PDF destination (on macOS, PDF → Save as PDF). The default print stylesheet uses A4 landscape with side-by-side versions, repeated version headers, change highlighting, commit metadata, and saved notes. Save/cancel drafts first.

The entire selected document is included, regardless of Changes only or Hide reviewed. This is separate from Export PR notes, which exports Markdown for the PR summary, file notes, and commented changes. Print controls are omitted from paper/PDF. Use Back to review to return to the review cursor. The print snapshot stays only in this tab's session storage, and requires no new GitHub calls or PDF library installation. Pagination follows the browser's print engine; the system print dialog lets the user change paper size or scaling.


## Label filter and Reset review

The **Label** dropdown filters open PRs using GitHub labels such as `WG_ai`. **All labels** shows the complete list. Filtering uses cached PR metadata without additional GitHub requests, and the selected filter is remembered. An explicit PR link takes precedence if the saved filter would hide it.

**More → Reset review…** clears the PR summary, file notes, and all change notes (including saved older revisions) and Reviewed marks for the selected PR, across all its files. A confirmation identifies the PR before anything changes. Other PRs are unaffected. **Undo last reset…** restores the most recent pre-reset snapshot for that PR; it also confirms before replacing notes or marks added after the reset. Only the latest reset backup is retained, locally in Git metadata.


## Review all changed files

The **File** selector includes every file in the PR, not just XML. PR-wide progress counts all changed files.

- DocBook books keep the formatted headings, paragraphs, and tables. Their existing note/review identities are preserved.
- YAML, HTML, Mermaid (`.mmd`), and other UTF-8 text use escaped side-by-side source diffs with line ranges and word highlights. Whitespace is preserved. Long changes are split into blocks of up to 35 lines so they can be reviewed in sections.
- Added and deleted files are labelled in the selector. Deleted content is visible on the base side and remains reviewable.
- PNG, JPEG, GIF, and WebP images show before/after previews. Click an image to open it at full size. Image Reviewed marks match content hashes, not the preview URL.
- Other binary formats show size and SHA256 metadata as one reviewable change. SVG is treated as source, not executed as an inline image. Mermaid currently shows source rather than a generated diagram.

All these views use the same notes, Reviewed controls, PR progress, reset, commented-only notes export, and PDF print view. Source review identities ignore line-number shifts when the before/after content is otherwise identical.


## Rich DocBook rendering

Parameters and request/response definitions render as nested term/description lists. Tables support `namest`/`nameend`, `spanname`/`spanspec`, `morerows`, explicit column numbers, and proportional/physical column widths.

Embedded PNG, JPEG, GIF, WebP, and SVG diagrams resolve relative to the document at the base/proposed commit. Content-addressed asset URLs avoid false changes when only a commit SHA changes, while an actual diagram edit is detected. Click a diagram to inspect it at full size. SVG responses use a sandboxed content policy that blocks scripts and external resource loads. External image URLs and paths outside the repository are not loaded.

The richer layout is also used in PDF print views. Existing note identities are retained for unchanged parameter-list/table content; visual-only span changes and diagram-content changes are reviewable. Footnotes still use basic inline rendering.


## PR summaries, file notes, and GitHub reviews

Use **More → PR summary…** for overall feedback, and **More → File note…** for feedback about the selected file. These save locally by PR number in Git metadata (`xml-review-draft-pr-N.json`) and reload when switching PRs. File notes follow their path across PR revisions; saving one does not mark its changes reviewed. Change notes retain their exact comparison and quoted context. Saved notes and Markdown exports include all three levels. The selected-file PDF also includes the PR summary and that file's note.

**More → Preview review…** shows the saved PR summary and one grouped comment per noted file, containing its file note and only commented change blocks with before/after context. Export preview downloads this as Markdown. Unsaved edits must be saved or discarded first.

To post, sign in with `gh auth login` or provide `GH_TOKEN`/`GITHUB_TOKEN` with permission to write pull-request reviews for the repository. Tokens remain server-side. In the preview, explicitly check the posting confirmation and click **Submit comment review to GitHub**. The tool creates a pending review, adds file-level threads, then submits it as a **Comment** review. It does not submit Approve or Request changes. Local Reviewed marks stay separate. No comments are posted just by saving notes or opening a preview.

Submission checks the live PR is open and still has the reviewed head and merge base. Changed notes invalidate an earlier preview. Identical successful submissions are recorded locally to prevent repeats. If a network/API error leaves the outcome uncertain, the tool blocks automatic retries and links to the PR: inspect any pending or submitted review on GitHub before continuing. Submission records live in `xml-review-submissions-pr-N.json`; resetting local notes does not delete a GitHub review.

GitHub submission is covered by mocked API tests. A live review is not posted as part of development testing.
