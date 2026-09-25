# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately using GitHub's **Report a vulnerability** button on the repository's Security tab (private vulnerability reporting). Do not open a public issue.

Include what you found, how to reproduce it, and the impact you expect. Do not include real API keys or other credentials, including your own.

You can expect an acknowledgement within a few days. Fixes are released as soon as they are ready, and reporters are credited unless they prefer not to be.

## Supported versions

Only the latest release on `main` receives security fixes.

## Scope

In scope: the backend (fetching, parsing, pipeline, API, CLI), the frontend, and the default configuration in this repository.

Out of scope: third-party feeds and their content, the language-model providers themselves, and deployments that change the documented configuration (for example exposing the API without a reverse proxy when that matters to you).

How the application defends itself is described in [docs/security.md](docs/security.md).
