# Interview Copilot — Nova-3 technical keyterms

## Scope

The static catalog in `apps/api/app/infrastructure/technical_vocabulary.py` covers AI/ML, LLM/RAG, software architecture, frontend, backend, cybersecurity, cloud services, DevOps/SRE, databases, data engineering, analytics/BI, testing/QA, mobile, computer science, networking and product terminology.

A technical catalog is not a dictionary used for postprocessing or a guarantee of transcription correctness. It is a set of **keyterm prompts** sent to Deepgram Nova-3 when creating an explicitly authorized cloud session.

## Limit and selection

- Nova-3 accepts up to **500 tokens of keyterms per request**, NOT unlimited terms. Deepgram recommends **20–50 carefully selected terms** for best performance.
- This implementation keeps an extensive local catalog and sends **up to 48 keyterms** chosen from a shared core and the interviewer's selected specialization. The fixed static catalog and explicit character/count bounds reduce the risk of breaching the provider token limit; we cannot guarantee provider token counts offline because Deepgram controls tokenization.
- One term is passed per `keyterm` URL query parameter; the implementation uses `urlencode(..., doseq=True)`. Nova-3 does **not** support legacy keyword weights.
- The category selection is deterministic, case-insensitive deduplicated, and allowlisted. No user-entered terms are interpolated into the Deepgram URL.
- The active profile is selected before capture. Changing profiles requires a new capture session. Both `en-US` and `es-MX` are supported; Spanish adds a handful of localized vocabulary hints.
- The current keyterm feature applies **only** to Deepgram Nova-3. Vosk and Faster-Whisper remain unaffected.
- The base app still needs explicit user consent before sending any system audio to Deepgram. No API key is sent to the desktop UI; terms do not contain personal data.

## Profiles

`general`, `frontend`, `backend`, `fullstack`, `ai-engineer`, `data-analyst`, `data-engineer`, `cloud-devops`, `security`, `qa`, `mobile`.

The complete catalog is not sent for every profile. For example, selecting `data-analyst` prioritizes Power BI, DAX, Tableau, SQL/BI and analysis tools; `ai-engineer` emphasizes LLM/ML, RAG and model/cloud terms. The general profile spreads a smaller selection across multiple specialties.

The first iteration uses deterministic priorities rather than a real-time AI term classifier. A future optional per-session context strategy can select different topics, but should not silently change provider data sent to the cloud.

## Testing

From the repository root, with the Python virtual environment active:

```bat
cd apps\api
python -m pytest -q tests/test_deepgram.py tests/test_stt.py
python -m pytest -q tests/test_live.py -k det002
```

In a second terminal, from the repository root:

```bat
node --test apps\desktop\audio-lab\transcribe.test.cjs
```

Then test **one** real session in the Electron audio lab with Deepgram, select the intended profile, and compare the final transcription to the question card. The vocabulary improves likely spelling of technical terms but **does not resolve the previously observed missing `suggestion` event**, which needs its own diagnosis.

Provider reference: https://developers.deepgram.com/docs/keyterm
