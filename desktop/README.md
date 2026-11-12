# Mac prototype

Build from the repository root on an Apple Silicon Mac running macOS 26:

```sh
brew install git gh
python3 -m venv .venv-mac
.venv-mac/bin/pip install pyinstaller
.venv-mac/bin/python desktop/build_mac.py
```

Open `dist/ONVIF Spec Review.app`. Python, Git, GitHub CLI and their runtime dependencies are included. End users do not run a terminal command or web server. The app starts its own private loopback service on a random port and stops it when the window closes. A parent-process watcher also exits the service if the app crashes.

The first prototype is built for Apple Silicon/macOS 26. It is ad-hoc signed for local testing, not Developer ID signed or notarized. A public downloadable release still needs signing/notarization, Intel/older-macOS builds if required, and a clean-machine packaging test. The Mac native shell is AppKit/WebKit; the Windows prototype uses WinForms/WebView2. The Python service and viewer are shared.

## Workspace and credentials

The app manages `onvif/specs` itself. It initializes a private bare Git repository at `~/Library/Application Support/ONVIF Spec Review/repositories/onvif-specs.git`, then downloads the complete base/proposed histories needed for each selected PR. There is no working tree and no developer checkout is needed. Downloads show Git progress. Cached revisions are pinned by refs so Git cleanup does not discard them.

Review data is separate at `~/Library/Application Support/ONVIF Spec Review/reviews/onvif-specs`. GitHub metadata and PR download manifests live in `cache/onvif-specs`. Removing/rebuilding the Git cache cannot erase notes, reviewed marks, backups or submission journals. Existing review JSON files are copied once from `~/Documents/GitHub/specs` and the earlier app's `specs` cache, after validating their origins. `XML_REVIEW_REPO`, if set, identifies an additional legacy source for migration; the desktop app does not use it as its live repository. Originals are never edited or deleted, and existing app reviews are never overwritten. Invalid files cause a visible warning and can be retried on restart. Backups still use the same import/export format.

On opening, the app refreshes GitHub's PR list and reopens the last selected PR at its first unreviewed change. If GitHub cannot be reached, cached metadata and already downloaded histories remain usable with a visible cached/offline notice and timestamp. PRs not downloaded before going offline require a connection. GitHub feedback and submission still require GitHub connectivity, subject to the feedback cache.

During a review, Refresh and periodic checks only check GitHub metadata. They never replace the active comparison. A changed PR shows **Load updated version**; clicking it downloads the updated history and retains content-based reviewed marks. Unsaved-note protection runs before switching. Closed PRs can still be read from the downloaded comparison. No other user's working checkout or local branches are touched.

Runtime logs are in `~/Library/Logs/ONVIF Spec Review/backend.log`.

Finish review previews the summary and separate file/chunk comments. It reuses an existing GitHub CLI login, or starts GitHub CLI's browser/device sign-in. The browser completes authentication with GitHub; credentials never enter the web UI. GitHub CLI uses the macOS credential store when available, with its own documented file fallback. Existing `GH_TOKEN`/`GITHUB_TOKEN` environment variables take precedence. This prototype does not request a repo-limited token: GitHub CLI's OAuth permissions can cover other repositories. The app's submission code is restricted to `onvif/specs`. Revoke access through GitHub's application settings or manage the shared CLI login with `gh auth`.

Submission posts a **comment review**, not an approval. It checks current PR head/base and the saved-note preview, requires explicit confirmation, and records a per-account submission journal before making any GitHub write. An interrupted submission blocks automatic retries: check GitHub for a pending review before resolving it. It does not silently delete pending reviews or retry uncertain requests.

The service requires a random per-launch HttpOnly/SameSite session cookie. Its bootstrap secret is not logged. Desktop write endpoints additionally validate request origin and JSON content. External navigation opens the normal browser. Imports and exports use native Mac file dialogs; PDF uses the Mac print dialog's Save as PDF.

## Review controls

- **Notes**: PR summary, file note, and saved change notes.
- **Finish review**: preview and explicitly submit to GitHub in the app; the Pages/browser version retains copy/export.
- **More**: Resume, GitHub feedback, Export, Backup & restore.
- **Backup & restore**: backup/import, reset, undo reset/import. These remain local.

The Review menu provides the same actions with shortcuts. No GitHub write is performed during automated tests. Run `python3 -m unittest discover -p 'test_*.py'` and both frontend `.cjs` test files from the root. The Pages build remains supported and is not published by building the Mac app.

A submission journal is retained in `.git/xml-review-submissions-pr-N.json`. A blocked uncertain submission deliberately requires checking GitHub before attempting a new review; the prototype has no automated pending-review cleanup. The browser-based local viewer keeps using Git metadata; after migration its reviews and the app’s reviews are independent. Do not run two instances of the desktop app against the same app storage at once.


## Review playground and suggestions

The Repository selector switches between `onvif/specs` and the disposable public `videoai/test-specs` playground. Switching restarts the private backend, so requests and saved state cannot cross between repositories. Both repositories have separate Git caches, metadata, preferences, notes and submission journals. The selected repository persists between app launches. The playground never imports notes from an ONVIF working checkout.

In a changed block, choose **Add note → Suggest a change…**. The app shows the exact proposed XML/text lines, ready to edit. Save the note/suggestion, then use **Finish review** to preview and explicitly submit it. A suggestion may be saved without an ordinary note. It is posted as a GitHub suggestion thread; the PR author applies it using GitHub's Commit suggestion action. The app does not apply or commit suggestions itself.

Suggestions are limited to reliable proposed-source ranges inside a GitHub diff hunk (at most 60 lines). Removed blocks, renamed files, binary/image changes and rendered-only changes without changed source lines use ordinary notes. XML replacements must leave the document well formed. Source locations are validated again before posting, so a stale suggestion must be edited and saved against the current comparison. Backup/import and exports retain suggested replacement text. Native Pages browsing remains supported; suggestion creation is a local desktop/server feature.
