# V1 R7 current dual-path evidence

This directory is the redacted, committed evidence set for the final V1 R7
dual-path acceptance completed on 2026-09-09.

- Final runtime candidate: `adf1b9434f59f7dfacf5819d04a77997244e783e`
- Preserved real-media source: `b22dde32fad3bb3fde39658f8a1682bc56109984`
- Candidate promotion is bounded by `candidate-equivalence-adf1b94.json`: the
  intervening product change only makes concurrent Artifact identity insertion
  race-safe. Provider request compilation, model/credential binding, submission,
  polling, and all accepted media prompts are unchanged.
- Runtime migration: `20260908_0060`
- Formal entry: `127.0.0.2:8080`; the pre-existing user stack remains available
  independently on `127.0.0.1:8080`.
- Template + AUTO: 5 Formal shots and a 24.027-second H.264/AAC Final Film.
- Free + ASSIST: 4 Formal shots and a 19.239-second H.264/AAC Final Film.
- Both films contain dialogue audio and burned Timeline subtitles and have a
  matching downloadable SRT. Hashes and ffprobe assertions are recorded in
  `golden-adf1b94.json`.
- Four real `litellm/script-quality` Story/Shot/Editing turns have persisted
  context/output hashes. Eighteen accepted Agnes image/video operations and one
  Repair video operation succeeded without fallback.
- Provider-reported cost was absent, so every external operation is recorded as
  `cost_status=unknown`, never free. Six transport-indeterminate submissions are
  preserved as `replay_allowed=false`; one Free shot was completed only after an
  explicit, materially different prompt revision.
- The Repair video was interrupted after durable remote identity persistence;
  the same heavy worker image recovered the same remote task. The hashed remote
  identity is unchanged and the ProviderOperation count stayed at one.
- The formal Playwright run used the real gateway, projects, edit sessions and
  downloads with zero failed API responses, page errors, or console errors.

The two MP4 files are playable review artifacts. The SRT files are independent
delivery outputs. No credential, signed URL, raw remote task identifier, cookie,
or authorization header is included in this directory.

