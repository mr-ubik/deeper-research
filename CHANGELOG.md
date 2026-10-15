# Changelog

## v0.3.2 — 2026-10-15

Re-freezes the instrument. Runs made with v0.3.1 defaults are not comparable
to v0.3.2-default runs without pinning the models: the defaults changed.

### Changed

- **Default worker model: `sonnet` → `opus`.** Search, rerank, and
  fetch/extract workers run on Opus unless `workerModel` says otherwise.
- **Default verifier model: `haiku` → `opus`.** Haiku caught 4/10 strict
  decoys in our measurements. Set `verifierModel: "haiku"` to restore the
  cheaper default.
- **Vote relay default (`cli` verifier `wrapperModel`): `sonnet` → `haiku`.**
  The relay only runs one command with the page attached by path.
- **Plan-review relay default (`cli` plan reviewer `wrapperModel`): worker
  model → `haiku`.** The session writes the prompt file; the relay only runs
  the command.
- The draft-review relay still defaults to the worker model (now Opus): it
  copies the draft and evidence ledger into the prompt file verbatim.
- Reviewer examples use GPT-6.1-sol (`openai-codex/gpt-6.1-sol`) instead of
  GPT-5.6-sol.

### Added

- README **Models** section: every role and the model it runs on.
- This changelog.

Earlier releases: see the git tags `v0.1` through `v0.3.1`.
