# STT-001B — Deepgram Nova-3 en Live Mode

La integración ya está en el proyecto. Las antiguas instrucciones para crear una rama y sobrescribir archivos desde un ZIP quedan obsoletas; no las uses sobre el trabajo local.

- [Inicio de la aplicación en Windows](../README.md#windows-setup-cmd).
- [Configuración opcional de Deepgram](setup.md#optional-deepgram-nova-3): dependencias, clave solo en el entorno del backend, consentimiento cloud y limpieza de credenciales.
- [Contratos y límites de arquitectura](architecture.md#deepgram-nova-3-streaming-extension-stt-001b).
- [Evidencia y aceptación pendiente en Windows](live-mode.md#stt-001b--initial-deepgram-windows-observation-2026-11-16).

Vosk sigue como proveedor predeterminado. Deepgram requiere selección explícita y consentimiento separado para transmitir toda la salida de audio de Windows. No hay fallback automático ni métricas de facturación implementadas. La disponibilidad local no demuestra acceso remoto, saldo ni precisión. Las pruebas reales pueden consumir créditos y no sustituyen la aceptación EN/ES, de red y de ciclo de vida pendiente.
