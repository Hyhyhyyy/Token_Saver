# Security Policy

Please report vulnerabilities through GitHub private vulnerability reporting. Do not open
a public issue for path traversal, arbitrary file writes, credential exposure, unsafe
backup/restore behavior, or provider-request data leakage.

The supported line is the latest commit on `main` until the first versioned release. Never
include real API keys, private prompts, personal skill files, or SQLite data in a report;
use a minimal synthetic reproduction.

The local rule engine is the privacy-preserving default. Configuring an external LLM
provider sends the selected content to that provider under its own terms.

SkillForge has no remote-user authentication. Run it only on loopback; the provided
launcher and Compose configuration bind to `127.0.0.1`. Do not publish port 8000 through
a router, reverse proxy, tunnel, or public container platform. Browser cross-origin writes
are rejected, but that is defense in depth rather than a substitute for authentication.
