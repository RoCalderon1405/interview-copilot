# Roadmap — Interview Copilot

Live Mode is the primary product. This order reflects the owner's priorities, not authorization to implement every item.

## Established baseline

- Owner-validated isolated Windows lab: system audio, PCM, Vosk English, conversational question detection, exact Q&A with sources and local FastEmbed retrieval with 204 indexed questions.
- Implemented: main Live integration, Spanish support, document management, manual search and native protection controls. Implementation does not establish complete Windows or conferencing acceptance; see [current validation](live-mode.md).
- Existing basic Practice sessions/lexical feedback remain available; expanded Practice is future work.

## Ordered priorities

1. **Current:** complete main Live Windows acceptance using the existing backend, database and cache. Test one spoken question, main-window transcript/source-backed result, abstention and stop/restart. Track EN and ES separately; do not infer Spanish validation from English.
2. Review task-level architecture decisions within the approved pragmatic Clean Architecture direction; then refactor incrementally with clear React/Electron feature boundaries. Preserve APIs, retrieval policy, permissions and validated capture. The refactor is not completed.
3. Add a small Windows backend-start script after approval; it does not exist yet.
4. Define and approve LLM fallback provider, context/privacy boundaries, trigger behavior and evaluation before implementation. No fallback is currently available.
5. Improve Live from real user feedback. As a core Live acceptance requirement, validate screen-sharing exclusion in actual Windows Teams, Zoom and Google Meet sessions before making compatibility claims. The native protection request alone is insufficient.
6. Consider expanded Practice Mode later; do not design or implement additional exercises or AI evaluation now.

Packaged production capture remains disabled. Its bootstrap/authentication/origin design and independent Windows acceptance are separate pending work, not part of development-mode validation.

Each adopted task needs one objective, scope/exclusions, automated checks, human acceptance where applicable and small Conventional Commits. No unapproved dependencies, downloads, custom agents or changes to the working audio pipeline.
