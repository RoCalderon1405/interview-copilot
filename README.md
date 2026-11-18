# Interview Copilot

A Windows desktop workspace for technical interview preparation and consent-based Live assistance in English and Spanish.

Live Mode transcribes system audio, detects interview questions and retrieves answers from your documents. Optional Ollama suggestions are separate, unverified and disabled by default. **Development preview:** integrated Windows acceptance is incomplete; packaged audio capture is disabled.

## Features

- **Live workspace:** newest-first transcripts, replaceable interim text, independently scrollable answers and clear session states.
- **Document-backed answers:** exact Q&A first, optional semantic candidates for review, and explicit no-evidence results.
- **Selectable STT:** Vosk by default; optional local Faster-Whisper or Deepgram Nova-3 cloud streaming. No automatic provider switching.
- **Knowledge Base:** import XLSX, DOCX, PDF, TXT and Markdown; search manually and manage local documents.
- **Basic Practice:** document questions, keyword-based feedback and session reports—not an AI assessment of technical correctness.

## Tech stack

Electron 39 · React 19 · TypeScript · Vite · Python/FastAPI · SQLite/FTS5 · Vosk. Optional integrations: Faster-Whisper, FastEmbed, Deepgram and local Ollama. No vector database service is required.

## Windows setup (CMD)

Prerequisites: Windows, Python, Node.js/npm and local Vosk models. **Existing users:** reuse your working `.venv`, database, documents and model caches. Do not reinstall or reindex just to validate a change.

For a first installation, from the repository root:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r apps\api\requirements-live.txt
cd apps\desktop
npm install
```

Dependencies and models are not bundled. Place the English and Spanish Vosk models in `local-data\models`, or set `COPILOT_MODELS_DIR`. See [configuration and optional providers](docs/setup.md) for model folder names, storage paths, semantic indexing, Whisper, Deepgram and Ollama. The backend reads process environment variables; it does **not** automatically load `.env`.

Start the backend from the repository root:

```bat
dev-api.bat
```

In a second terminal, also from the repository root:

```bat
cd apps\desktop
npm run dev
```

The API runs at `http://127.0.0.1:8765` and the development UI at `http://127.0.0.1:5173`. Check `/health` and `/live/status` if startup fails. Do not start a second backend or leave the standalone transcription lab using the same ports.

## Usage

1. Import interview Q&A documents in **Knowledge Base**. Semantic indexing is optional and explicit.
2. Open **Live Interview → Preparar captura**.
3. In the isolated audio window, select a provider/language, review consent and click **Iniciar transcripción**. Cloud STT requires separate consent.
4. Review transcript and answer panels. Exact answers retain their sources; semantic and LLM suggestions require review. **Consulta manual** searches documents without invoking Ollama.
5. Use **Mostrar controles** to return to the audio window or **Detener y cerrar** to stop and close it.

Use **Practice Interview** for the existing question-and-keyword-feedback workflow. See the [Live acceptance guide](docs/live-mode.md) for detailed checks.

## Important limitations

- Capture includes **all Windows output**, not just one application. The main renderer cannot capture media; authorization must happen inside the isolated audio window. Respect participants' consent and organizational policies.
- The application does not persist Live audio or transcripts. Documents and basic Practice answers are stored locally. Deepgram sends audio off-device, may incur charges, and has its own processing/retention policies. Credentials stay in the backend environment.
- Main-window screen-sharing exclusion is **best effort**. The auxiliary audio window is not protected. Teams, Zoom and Google Meet exclusion remains unverified.
- STT and question detection can miss or combine speech. Complete Spanish, latency, interruption and restart acceptance is pending.
- Ollama can invent experience, metrics or technical claims. Its conservative checks can also reject valid answers. **AI-001C is not accepted for quality**; human review remains necessary.
- Live histories are bounded and memory-only, not a complete session archive. A successful build does not create a Windows installer.

### Documents and retrieval

Importing a supported file does not guarantee extracted Q&A. Scanned PDFs require OCR, which is not implemented; PDF fragments are not automatic Live answer candidates. Manual search uses exact/lexical retrieval, while automatic Live uses exact Q&A followed by optional semantic Q&A. See [format details](docs/setup.md#documents-and-retrieval).

## Development checks

Use the existing environment. Run focused tests first, then the relevant regressions described in [AGENTS.md](AGENTS.md). Do not run real-model benchmarks for documentation or test cleanup. Models, private data, credentials and dependency/cache folders must stay out of Git.

## Documentation

- [Configuration and optional integrations](docs/setup.md)
- [Architecture and security boundaries](docs/architecture.md)
- [Visual design reference](DESIGN.md)
- [Live validation evidence and known limitations](docs/live-mode.md)
- [Roadmap](docs/roadmap.md) · [Technical vocabulary profiles](docs/technical-vocabulary.md)
- [Audio lab](docs/audio-lab.md) · [Transcription lab](docs/transcription-lab.md)
