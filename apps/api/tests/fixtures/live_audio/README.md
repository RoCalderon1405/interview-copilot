# Synthetic Live audio fixtures

These two WAV files are **local Windows SAPI text-to-speech output**, not human recordings and not user data. They contain only the synthetic interview questions below and are used by the backend Live transport tests.

| File | Spoken synthetic text | Format | SHA-256 |
|---|---|---|---|
| `en.wav` | "What is authentication?" | PCM signed 16-bit, mono, 16 kHz | `e010558ec8bc39f121579291d719d3f91df1be7480921cf568fc5af39479781b` |
| `es.wav` | "Como resuelves un conflicto en el equipo?" | PCM signed 16-bit, mono, 16 kHz | `132749a7cf1c3b9013bc53ca55475daffb3fa01ca8f24753c6ef226e84f0e976` |

No network call, upload or download is involved in these tests. The optional local Vosk runtime and models are still required; the integration tests skip only when those optional components are absent.

Generated for the Interview Copilot development vertical slice on 2026-11-14. The spoken answers used by the tests are invented test data.
