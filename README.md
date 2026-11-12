# ONVIF Spec Review

Review public pull requests as formatted, side-by-side documents. DocBook keeps headings, paragraphs, tables, parameter lists, and diagrams. Other text files use source diffs; raster images have before/after previews. Other binary files show metadata.

## Hosted viewer on GitHub Pages

Open the published URL, choose a label/PR/file, and review. No checkout, Python, personal token, or application login is needed. GitHub Actions precomputes comparisons using trusted tool code; PR content is read as data and never executed. The site includes only public repository content, branch names, commit IDs, and generated comparison data. Build artifacts do not include local notes, reviewed marks, Git metadata, or credentials.

The build timestamp and exact compared commits identify each snapshot. **Check for updates** reloads the latest published build; it does not fetch new Git history or start an Actions run. Existing GitHub feedback loads separately from the public API and can be refreshed without rebuilding comparisons. API rate limits and partial failures are shown, with cached results where available.

Notes and reviewed marks are stored in **IndexedDB in the current browser**, keyed by repository and PR. They are not uploaded or shared. Clearing site data removes them; use Back up PR review regularly. Switching browsers or computers requires backup/import. Local-server notes remain in Git metadata and can be transferred using the same backup format.

### Copy feedback to GitHub

There are no direct submission buttons, OAuth login, or GitHub write API calls.

1. Save your notes and choose **More → Preview review…**.
2. **Copy entire review** copies Markdown with the PR summary, file notes, and only commented chunks, including quoted context and reviewed commits.
3. **Open PR on GitHub** opens Files changed. Use your normal GitHub login, click Review changes, paste into the summary, choose the review type, and submit there. This creates one summary; Markdown sections do not become separate threads.
4. For individual discussions, use each note's **Copy comment** and **Open GitHub location**. Add it as a file/line comment to a pending review, then submit on GitHub.
5. **Export Markdown** downloads the same review if clipboard access is unavailable.

Line links use the reviewed source location where it can be mapped reliably. Automatic numbering changes, binary/image changes, or other chunks without a changed source line link to the file, with the reason shown. If the PR has moved since the build, check its current diff before adding a comment. The tool never claims a copied review has been posted.

## Local tool

From a checkout of the specs repository:

```sh
./tools/xml-review/start.sh
```

Python 3.9 or newer is required. The standard library is sufficient. The command opens `http://127.0.0.1:8765`; keep the terminal running and use Ctrl+C to stop it. Options include `--no-open`, `--port 8766`, and `--repo /path/to/specs`.

Choose a same-repository PR; forks are excluded. Base/proposed versions are fixed to the PR's merge base and head, displayed with branch names and short SHAs. **Refresh from GitHub** fetches origin and refreshes PR metadata. Missing/shallow history may require `git fetch origin` or `git fetch --unshallow`.

Public repositories can be read anonymously. For private repositories in local mode, or higher API limits, run `gh auth login` or set `GH_TOKEN`/`GITHUB_TOKEN`. Tokens stay server-side and are used for reads only. Metadata is cached in Git metadata for ten minutes, including rate-limit backoff and labelled stale results.

## Review workflow

- A label filter narrows the PR list without additional GitHub requests. Each file and the toolbar show review progress across all changed files.
- Opening a PR resumes at the first unreviewed change across its files. **More → Resume review** returns there. Failed renders keep the PR incomplete.
- First, Previous, Next, and Last navigate only. **Reviewed & Next** saves the mark before advancing. Checking Reviewed or saving a nonempty change note also advances. Unchecking Reviewed lets you revisit a change.
- Changes only and Hide reviewed filter the view. Home returns to PR/file selection. Navigation controls stay visible while scrolling.
- **PR summary…**, **File note…**, and change notes serve different levels of feedback. A file note does not mark every change in that file reviewed. Draft warnings protect unfinished edits.
- Whole-file completion offers a link to the next unreviewed change. When all changes are reviewed, a banner says so. These local marks are not GitHub approvals.
- **GitHub feedback…** shows comments for the selected file, PR discussion, and submitted review summaries. Text is displayed safely as Markdown source. Author, time, replies, line location, and outdated locations are shown where supplied. Replying/resolving happens on GitHub.

Local-server notes live in Git metadata, for example `xml-review-notes-pr-877.json`, `xml-review-draft-pr-877.json`, and `xml-review-reviewed-pr-877.json`. Change notes retain their exact comparison and context; older comparisons remain under Saved notes. Identical content can retain Reviewed marks across revisions. New or changed content needs review. None of these files is committed.

## Backup, reset, and exports

**More → Back up PR review** downloads JSON containing the selected PR's summary, file notes, change notes from all saved comparisons, and reviewed marks. **Import PR backup…** validates the repository, PR, schema, and size (10 MB maximum), shows counts, then asks before replacing that PR's data. Other PRs are unchanged. Import replaces rather than merges conflicting edits.

**Reset review…** clears that PR's local notes and marks, including older comparisons. **Undo last reset / import…** restores the previous snapshot; only the latest undo is retained. Browser data can be imported into the local tool and vice versa. Backups do not contain credentials, Git history, browser preferences, or existing GitHub comments.

**Export PR notes** and Saved notes export commented content as Markdown. **Export PDF** opens a print-ready snapshot of the complete selected file, irrespective of filters, with notes, commits, highlighting, and repeated version headings. Use Print / Save as PDF in the browser's print dialog. Browser pagination determines page breaks.

## Build and publish the static site

For a local trial build of a public repository:

```sh
python3 tools/xml-review/build_site.py --repo . --fetch --output /tmp/spec-review-site
python3 -m http.server 8766 --directory /tmp/spec-review-site
```

Then open `http://127.0.0.1:8766`. The output directory must be empty. Add `--pr 877` to build just one PR. The exporter verifies the repository is public, reads open same-repository PRs, and generates content-addressed JSON and deduplicated assets. It does not write notes. Exported SVGs have active content and external references removed. A CSP restricts scripts to the site itself. Existing local note/review identities are retained in exported comparisons.

The workflow `.github/workflows/spec-review-pages.yml` builds on changes pushed to `AI/spec-review` or `development`, and can run manually. Its hourly schedule takes effect once the workflow is on the default branch. It checks out trusted branch code, reads PR files via Git, and uploads a downloadable `spec-review-static-preview` artifact. A failed build preserves the existing deployment. Preview artifacts have a three-day retention; Pages artifacts have a one-day retention.

Publishing is deliberately a separate manual action:

1. In the repository's Settings → Pages, choose GitHub Actions as the source.
2. This repository already publishes its root documentation from `development`. The workflow builds that documentation using the official Pages Jekyll builder, then adds the viewer under `/review/`. Check both parts in the downloadable preview before switching the Pages source.
3. Run Publish ONVIF Spec Review on the trusted branch with **publish** enabled. The viewer will be at `https://onvif.github.io/specs/review/`. The `github-pages` environment may require approval or branch permissions configured by a repository administrator.

The build job has only content/PR read permission. Only the deploy job has `pages: write` and `id-token: write`. The exporter stops above a 900 MB viewer budget; the workflow checks that documentation plus viewer stay below 950 MB. Use standard hosted Linux runners; paid larger runners are unnecessary for this workload. Automatic comparison builds do not publish by default. After merging into `development` and enabling Pages, set the repository Actions variable `SPEC_REVIEW_PAGES_PUBLISH` to `true` to publish scheduled and push builds on that branch automatically. Branch trial builds stay unpublished unless manually requested.

## Rendering and tests

DocBook supports nested variable lists, CALS spans/rowspans and column widths, and embedded diagrams relative to each Git revision. Source changes are split into blocks of up to 35 lines. Deleted files remain reviewable. Mermaid and standalone SVG use source diffs. Footnotes use basic inline rendering.

From `tools/xml-review`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q
node test_frontend.cjs
node test_static_frontend.cjs
```

Tests cover comparison alignment, content identities, notes/review persistence, reset/import rollback, backup validation, source locations, read-only GitHub feedback, copy/paste exports, and static publication without private local review data. No real GitHub comments are posted by tests.
