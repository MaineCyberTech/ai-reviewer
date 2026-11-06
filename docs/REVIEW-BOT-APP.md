# Optional GitHub App identity

The approval workflow uses the caller repository's `GITHUB_TOKEN`, which is
sufficient when `can_approve_pull_request_reviews` is enabled.

A separate GitHub App is optional if the org wants bot approvals to come from a
distinct identity. It requires an owner to create and install the app through
GitHub's manifest flow; the API cannot create an app headlessly.

The sanitized manifest is at `config/review-bot-manifest.json`. If the app is
created, store `REVIEW_BOT_APP_ID` and `REVIEW_BOT_PRIVATE_KEY` as secrets and
replace the approval step with an app-token action.

Do not let an app auto-approve based solely on the AI comment. Keep the
human-triggered label or another explicit human gate.
