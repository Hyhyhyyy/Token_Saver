# Contributing

Contributions are welcome when they improve correctness, measurable token accounting,
safe file handling, provider compatibility, or the first-run experience.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt pytest httpx
python -m pytest tests -q
python verify_independent.py
```

When changing frontend classes, also run `npm ci && npm run build:css` and commit the
generated CSS. Runtime users do not need Node.js and the dashboard makes no CDN request.

On Windows, activate with `.venv\Scripts\activate`. A pull request should include a
regression test and explain whether a reported saving is measured, estimated, or
simulated.

## Safety rules

- Use synthetic skills and prompts in tests; do not commit personal skill directories.
- Never include API keys, conversation logs, private prompts, or generated databases.
- Do not silently overwrite a user's skill. Preserve the existing backup and atomic-write
  behavior.
- Keep offline rule-based operation functional; optional LLM providers must remain optional.

Large features should start with an issue. By participating, you agree to follow
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
