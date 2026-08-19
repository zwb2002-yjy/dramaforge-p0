# DramaForge Codex Rules

## Authoritative Planning Documents

- Read `DramaForge总开发文档.md` first for product direction and scope.
- Read only the task-relevant contract under `docs/current/` before changing product, runtime, quality, or roadmap behavior.
- `docs/开发执行检查点.md` is the live implementation-status source, not a product-definition source.
- Deleted legacy planning/specification documents remain available only through Git history. They cannot generate tasks or regain authority through restoration.
- Do not create another parallel master plan. Update the active contract or add an ADR/Task Contract as routed by `docs/README.md`.

## Image Evidence Handling

- Treat Playwright screenshots as evidence artifacts, not conversational input.
- Do not use `view_image` for an additional visual spot-check after Playwright assertions have already established the result.
- Use Playwright DOM, accessibility, network, console, layout, and business-flow assertions as the primary verification method.
- Before calling `view_image`, inspect the image file size and dimensions.
- Do not call `view_image` on an image larger than 200 KiB or with a long edge over 1200 pixels.
- If automated evidence cannot answer a narrowly defined visual question, create the smallest useful temporary thumbnail or focused crop. The derived image must stay within both limits before it is passed to `view_image`, and only that specific question may be inspected.
- If Playwright evidence and a minimal visual sample are still insufficient or ambiguous, do not load additional or larger images. Ask the user to perform a manual visual review with concrete steps and expected observations, then confirm or modify the implementation from the user's feedback.
- Keep original evidence screenshots unchanged and in place. Use metadata, dimensions, SHA-256 hashes, Playwright assertions, and structured evidence files for primary verification.
- Do not print base64 data, hex dumps, or binary file contents through shell commands.
- Do not use `Get-Content` or equivalent text readers on PNG, JPEG, WebP, MP4, ZIP, or other binary files.
- Do not pass local evidence screenshots to `view_image` when metadata or automated assertions answer the question.
- For the existing P0 evidence screenshots under `tmp/p0-evidence/`, verify existence, dimensions, hashes, and assertion results without loading the original pixels into the conversation.

## Local Path and Image Input

- A Windows path is usable by a local tool but is not directly readable by the model or a remote provider.
- `view_image` reads the local file on the client side and packages the image bytes as a data URL, commonly `data:image/<format>;base64,...`, for multimodal model input.
- Treat that encoded image as conversation payload. It can be persisted in the session and replayed on later turns.
- Prefer local metadata and structured test evidence. Use a bounded thumbnail or crop only when visual inspection is necessary.
