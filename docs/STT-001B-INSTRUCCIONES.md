# STT-001B — Deepgram Nova-3 en Live Mode

Este cambio integra Deepgram como **tercer proveedor opcional**. Vosk sigue siendo el predeterminado y Faster-Whisper se conserva. Solo el backend establece conexiones a Deepgram; el renderer no recibe la API Key.

## Aplicar en Windows

1. Desde la **raíz del repositorio**, crea la rama antes de reemplazar archivos:

   ```powershell
   git switch -c feature/stt-deepgram
   ```

2. Extrae `interview-copilot-deepgram-patch.zip` en esa misma raíz, conservando las rutas `apps/api/...` y `apps/desktop/...` y aceptando reemplazar los archivos incluidos. El parche NO incluye datos, modelos, dependencias, credenciales ni archivos ajenos a STT.

3. Instala la dependencia opcional, si fuera necesaria:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r apps\api\requirements-deepgram.txt
   ```

   Si la versión instalada ya es `websockets 17.4`, no es necesario reinstalarla para esta prueba.

4. En una PowerShell nueva, desde la raíz del repositorio, configura la clave **sin guardarla en archivos** e inicia el backend desde esa misma consola:

   ```powershell
   $secret = Read-Host 'Deepgram API Key' -AsSecureString
   $env:COPILOT_DEEPGRAM_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
   Remove-Variable secret
   .\dev-api.bat
   ```

   No copies la clave a `.env` versionados, al frontend, a la documentación ni a GitHub. Si el backend ya estaba abierto, debes reiniciarlo con la variable definida. La configuración de credenciales persistentes con Windows Credential Manager se deja para otra tarea.

5. Verifica `http://127.0.0.1:8765/live/status` y busca `providers.deepgram.available: true`. Este estado confirma configuración local, **no verifica el saldo o los permisos remotos**. El handshake cloud se comprueba al iniciar Live.

6. Abre la app de escritorio con el procedimiento normal (`cd apps\desktop; npm run dev`). En la ventana **Preparar captura Live**, elige `Deepgram Nova-3 (nube, de pago)` y un idioma. Lee y marca el consentimiento específico para Deepgram antes de iniciar. En inglés deberían aparecer `partial` y `final` en pantalla. Repite la prueba en español.

7. Al terminar, detén la captura y, cuando cierres el backend, elimina la variable de PowerShell si la sesión continúa abierta:

   ```powershell
   Remove-Item Env:\COPILOT_DEEPGRAM_API_KEY -ErrorAction SilentlyContinue
   ```

## Pruebas

```powershell
cd apps\api
python -m pytest -q tests\test_deepgram.py tests\test_stt.py
cd ..\desktop
npm run test:audio
npm run test:electron
npm run test:ui
npm run lint:electron
npm run build
```

La prueba real con Deepgram necesita conexión a Internet y consume los créditos o saldo de la cuenta. El endpoint `es-MX` de la UI se traduce a `language=es` en Deepgram. El audio se transmite únicamente si el usuario selecciona Deepgram y consiente el uso de la nube. **No hay fallback automático** a proveedores cloud/locales ni métricas de facturación dentro de la aplicación todavía.

## Contratos y límites

- PCM16 mono a 16 kHz y captura aislada de Windows sin cambios.
- Audio → FastAPI local → WebSocket Deepgram Nova-3, con `interim_results=true` y `endpointing=300`.
- `is_final=true` fija **un fragmento**, pero **solo `speech_final=true` completa la intervención** y activa detección de preguntas/RAG/Ollama. El valor 300 ms es inicial y requiere evaluación con voz humana.
- La clave nunca se transmite al renderer; se lee solamente del entorno del proceso API. Se usan host fijo, permisos existentes, cola de audio acotada y limpieza al detener/desconectar.
- La transcripción, segmentos no finalizados y audio no se escriben en la base de datos del proyecto. El procesamiento y la retención del proveedor cloud se rigen por la configuración/condiciones de Deepgram.
- No está implementado el histórico de consumo ni los costos por sesión. Evita dejar sesiones cloud abiertas sin necesidad; el límite de sesión existente es de una hora.
- Los tests automatizados y simuladores no sustituyen la validación real en Windows con cuentas y audio de usuario; por seguridad, **no envíes capturas con la API Key**.
