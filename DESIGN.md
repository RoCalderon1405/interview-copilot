# Visual design reference

This document describes the existing interface, not a redesign or task board. Source of truth: `apps/desktop/src/styles.css`, `apps/desktop/src/App.tsx` and `apps/desktop/src/features/live/`. Product boundaries remain in [architecture](docs/architecture.md); acceptance evidence remains in [Live Mode](docs/live-mode.md).

## Purpose and hierarchy

- Prioritize readable interview assistance over decorative dashboard elements. Live is the primary workspace; Knowledge Base and basic Practice remain available in the navigation.
- Keep session state and capture controls above the working content. Transcript sits on the left; the wider answer panel sits on the right.
- Keep both feeds independently scrollable. Show new transcript fragments first and update one provisional entry in place. Do not let growing transcripts push answers out of view.
- Keep manual document lookup secondary in a collapsible section. Consent, provider/language selection and the real Start click stay in the auxiliary window.

## Existing visual language

- Dark navy shell: page `#09111d`, sidebar `#0c1521`, panels `#111c2b`. Subtle blue-gray borders separate surfaces.
- Light text (`#e5edf8`) carries primary content; muted blue-gray supports labels and metadata. Indigo actions link the Live workspace to the existing application shell.
- Live uses mostly flat surfaces, restrained borders and rounded corners. The existing brand mark retains its gradient/shadow; that treatment is not repeated across Live result cards.
- Segoe UI/system sans-serif is the current font stack. Live uses a 28 px heading, approximately 14 px reading text, and smaller supporting labels. Answer text favors comfortable line height over dense paragraphs.
- Live panel gaps are 16 px; card/control padding is generally 13–20 px. These are current CSS values, not a newly introduced token system.
- Use the existing Lucide outline icons alongside text. Icons and color do not replace action labels, provenance or warnings.

## Provenance must remain visible

- **Exact documentary answer:** green-accented card, exact-match label and document source. Exact matching is not factual certification.
- **Semantic candidate:** amber treatment, explicit review label, source and stored question when supplied.
- **No evidence:** neutral blue-gray treatment and an explicit absence-of-evidence message. It is not a model or STT failure.
- **Generated suggestion:** lavender/indigo treatment, provider/model, no documentary source and an unverified-content warning. Keep it separate from documentary results, including the preceding no-evidence card.
- **Interim transcript:** dashed blue container with a provisional label; finalized text has a quieter divider and Final label. Render all supplied text as text, never HTML.

## Controls and states

- Keep one primary capture-preparation/show-controls action and a secondary stop-and-close action. Disable unavailable/busy actions instead of implying capture started.
- Distinguish authorization, connecting, listening, stopping, stopped and error states. Leave provider/audio state unconfirmed when the existing events do not establish it; distinguish local from cloud STT.
- Keep keyboard-focus outlines on controls, the manual-search summary and scroll regions. Status/error text uses semantic roles; do not rely on colored dots alone.
- Existing navigation uses English labels while Live operational copy is Spanish. This reference does not introduce a localization migration.
- Privacy copy states that system capture includes all Windows output. Main-window protection is requested/best-effort, not guaranteed invisibility; the auxiliary window is not protected.

## Responsive behavior and limits

- The shell narrows its sidebar at existing breakpoints. Live uses a viewport-oriented desktop layout; below 760 px its feeds stack as separate 420 px panels.
- Histories are bounded and memory-only. Do not present them as a durable session archive or imply that a retained answer applies to a newer question.
- The auxiliary window retains its diagnostic layout and isolated security role. It is not a second version of the main workspace.
- Visual balance, contrast, keyboard behavior, minimum window size and Windows scaling still need owner review. Source inspection and passing component tests are not a formal accessibility audit or proof of screen-sharing exclusion.
