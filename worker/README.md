# Test GitHub backend

This Cloudflare Worker serves the public `videoai/test-specs` viewer from the GitHub Pages `/test/` build, with same-origin GitHub App sign-in and confirmed comment-review submission. It refuses writes to every other repository, including `onvif/specs`. The main ONVIF Pages viewer stays static.

The initial URL is https://spec-review-test.kieronmesser.workers.dev/. The viewer and API share this origin, so sign-in does not rely on third-party cookies. Notes in this viewer belong to its browser origin; use backup/import to move notes from Pages or the desktop app.

## Deploy

Run `npm ci` and `npm test` in this directory, then `npx wrangler deploy` using your Cloudflare account. Set the account ID in `wrangler.jsonc` if deploying elsewhere. Use the free Workers plan with the SQLite Durable Object binding; no paid plan is required for this test deployment.

Set three Worker secrets: `SESSION_KEY` (a random value of at least 32 characters), `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`. Use `wrangler secret put NAME` or the Cloudflare dashboard. Keep secrets out of source files, chat and GitHub Actions logs. On a new Worker, deploy first and add secrets afterward.

For the initial videoai registration, `python3 register_app.py` runs a loopback setup page at http://127.0.0.1:8977. It posts a GitHub App manifest, validates the returned owner/permissions, and transfers the generated client credentials directly into Cloudflare secrets using Wrangler. The temporary secret file is deleted. No app private key is retained. Close the helper after registration.

The GitHub App must have **Pull requests: read/write**, **Contents: read**, and automatic Metadata read. Its OAuth callback is `https://spec-review-test.kieronmesser.workers.dev/auth/callback`. Webhooks are disabled. Install it only on **videoai/test-specs**, then sign in from the test viewer. The app uses user access tokens, so reviews are attributed to the signed-in user.

## Sessions and submission

GitHub tokens are encrypted inside Secure, HttpOnly, SameSite=Lax cookies, limited to one hour or the token's remaining lifetime. JavaScript never receives tokens, and the backend keeps no token database or refresh tokens. Cookie expiry/sign-out removes this browser session; users can revoke the GitHub App authorization on GitHub. Other browser sessions are unaffected.

OAuth uses random state, a short-lived flow cookie and PKCE. Writes require the same origin and a per-session CSRF value. Each submission is reconstructed from the trusted published test snapshot; repository, commit, block identities and suggestion ranges are checked server-side. App installation and repository write permission, current PR head and merge base are checked before sending. Sign-in alone does not grant repository write access. XML replacements are validated with a strict parser. No approvals, request-changes events, code commits or suggestion application are performed.

A single GitHub REST review request posts the summary and inline comments atomically. Comments without a reliable source line go into the overall summary. A Durable Object records each submission attempt before contacting GitHub, preventing an automatic duplicate after an uncertain response. Its journal contains timestamps/results only, no tokens or note bodies, and expires after 30 days. Definitive GitHub rejections retain their HTTP status and allow a new user-triggered attempt after the issue is fixed. Unknown network/server outcomes stay blocked. A legacy attempt without an error status can be retried only when GitHub proves the app was first installed after that attempt, so it could not have written. If a submission is uncertain, check the PR on GitHub before making another review.

Cloudflare request observability is disabled. Do not enable request-body or cookie logging. Tests use fixtures and never post real GitHub reviews. Production integration checks require the user to complete GitHub sign-in and make their own test review.
