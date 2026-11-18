# Visual design reference

This document describes the existing interface, not a redesign or task board. Source of truth: `apps/desktop/src/styles.css`, `apps/desktop/src/App.tsx` and `apps/desktop/src/features/live/`. Product boundaries remain in [architecture](docs/architecture.md); acceptance evidence remains in [Live Mode](docs/live-mode.md).

## Purpose and hierarchy

- Prioritize readable interview assistance over decorative dashboard elements. Live is the primary workspace; Knowledge Base and basic Practice remain available in the navigation.
- Keep session state, provider and capture actions in one compact header. On wide layouts, transcript sits on the left (35%) and answers on the right (65% of column space, excluding the gap). Answers come first in DOM/keyboard order and in stacked layouts.
- Keep both feeds independently scrollable. Show new transcript fragments first and update one provisional entry in place. Do not let growing transcripts push answers out of view.
- Keep manual document lookup and technical diagnostics secondary in native, initially closed disclosures. Consent, provider/language selection and the real Start click stay in the auxiliary window.

## Existing visual language

- Live uses a restrained navy palette: page `#0c111b`, panel `#121a27`, reading surface `#182232`, border `#2b384b`. A small set of `--live-*` CSS variables defines these roles; no component framework is added.
- Primary text is `#e8edf5`; supporting text is `#a7b5c9`. Indigo actions use `#4d5cbb`, with `#5968c7` hover and a light focus outline. Provenance colors decorate labels and thin accents, not whole tinted cards.
- The Live shell has a quieter brand mark, 208 px navigation and a wrapping topbar with a 56 px minimum for the interface-language selector. Other pages retain their established layout and branding; this is not a global dashboard rebuild.
- Keep Segoe UI/system fonts. Live uses a 24 px heading, 16 px questions, 17 px answer text (16 px when stacked), 14 px transcripts and 12 px supporting copy. Answer line height is 1.65, with a 68ch maximum measure. No remote fonts or assets.
- Panel gaps are 16 px; reading-card padding is 20 px, reduced to 16 px when stacked. Controls use at least 40 px height; auxiliary actions use 42 px. Keep spacing consistent without turning these few roles into a general design-system abstraction.
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
- Keep keyboard-focus outlines on controls, disclosure summaries and scroll regions. Navigation has explicit accessible names and current-page state even when labels are hidden. Status/error text uses semantic roles; do not rely on colored dots alone.
- Announce the latest final transcript through a dedicated polite status region, not every interim change or the complete history. Duplicate auxiliary feeds do not continuously announce updates. Actual assistive-technology behavior needs Windows validation.
- The topbar exposes a labeled EN/ES interface selector. Switching updates authored labels, known states/warnings and accessible names without reloading or remounting the workspace. Only the interface preference persists in the main renderer; STT/LLM language and supplied interview/document content remain unchanged. At narrow widths the selector label stays available to assistive technology while visually hidden.
- Privacy copy states that system capture includes all Windows output. Main-window protection is requested/best-effort, not guaranteed invisibility; the auxiliary window is not protected.

## Responsive behavior and limits

- The Live sidebar becomes an icon rail at 880 px window width. Below 660 px of usable content width, a CSS container query stacks answers before transcripts. Each feed keeps its own viewport-bounded height; short windows allow page scrolling rather than clipping controls. No drag handles or persistent layout settings.
- Native scroll anchoring is enabled for prepended histories; the changing provisional row is not an anchor. No focus jumps or forced scroll-to-top are introduced. Stability while reading older entries still requires a rendered Windows check.
- Histories are bounded and memory-only. Do not present them as a durable session archive or imply that a retained answer applies to a newer question.
- Integrated auxiliary controls default to 560 × 720 px, retaining the 490 × 520 px minimum. Provider/language, Deepgram profile when selected, full consent, cloud/sharing warnings, availability, Start/Stop and session status remain outside disclosures. Diagnostics and duplicate feeds start collapsed, with bounded scroll areas when opened. The action/status strip is sticky; it does not auto-start or auto-authorize anything.
- Auxiliary styles are scoped to `.capture-page`; the raw-audio lab keeps its layout. The shared transcription page also remains usable standalone. Hidden diagnostic DOM still updates through the existing capture script; collapsing it does not bound its accumulation or change capture/lifecycle behavior.
- Once backend readiness and the connected, running AudioWorklet path are confirmed, integrated capture hides the auxiliary and skips both taskbar buttons. A native recovery tray must exist first; its click restores the main workspace and its menu exposes controls/stop. Showing controls reuses the same window; an explicit hide-without-stop action is available during active capture. Stop/error restores normal taskbar behavior. Missing PCM progress or a nonrunning audio context restores controls and prevents rehide until a new attempt. These are recovery mechanisms, not invisibility or audio-health guarantees; real Windows acceptance remains pending.
- Visual balance, contrast, keyboard behavior, minimum window size and Windows scaling still need owner review. Source inspection and passing component tests are not a formal accessibility audit or proof of screen-sharing exclusion.
