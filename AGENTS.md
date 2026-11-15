# Interview Copilot — instrucciones de desarrollo

## Prioridad única
Validar **recuperación semántica local** de preguntas Q&A en el laboratorio Windows ya probado, sin alterar captura, PCM, Vosk o detección.

## Estado verificado por el usuario
- Captura de audio del sistema: PASS en Windows.
- Audio PCM → FastAPI/Vosk → texto: PASS en Windows.
- Preguntas conversacionales y respuesta exacta con origen: PASS en Windows.
- Coincidencias semánticas con FastEmbed: **NO PROBADAS EN WINDOWS**. No presentar métricas de precisión inventadas.
- Live de producción: sigue separado del laboratorio.

## Límites
1. Trabaja en una sola tarea pequeña y con criterios comprobables.
2. Conserva la captura que ya funciona. No modifiques Electron ni el streaming PCM sin una reproducción concreta del fallo.
3. Una coincidencia exacta tiene prioridad absoluta. Una coincidencia semántica es una **sugerencia por revisar**, nunca una respuesta verificada ni generada.
4. Embeddings EN/ES locales con FastEmbed opt-in; SQLite almacena vectores de preguntas Q&A. Sin Chroma, Docker, LLM ni servidor vectorial.
5. El runtime no descarga modelos por sorpresa. Solo se descargan tras autorización explícita en `/semantic/index`.
6. Al subir nuevos archivos Q&A, hay que indexar las preguntas nuevas explícitamente. Al borrar documentos, SQLite elimina sus vectores.
7. Si no hay modelo, índice o confianza suficiente, mostrar “sin respuesta”; no inventar resultados. Mantener fuente documental.
8. No introducir nuevos agentes, prompts de supervisor, documentación histórica ni archivos basura. No borrar datos privados.
9. Verificación en Windows la decide el usuario; pruebas mock/unitarias NO equivalen a validación de semántica real.

## Prueba de aceptación
- Importar documento Q&A, preparar índice por acción explícita, iniciar `npm run lab:transcribe`.
- Pregunta exacta → respuesta original y origen.
- Paráfrasis → **posible** respuesta semántica con pregunta original y origen.
- Pregunta no relacionada/ambigua → sin respuesta.
- Reiniciar el servidor: la indexación persiste en SQLite.
- Sin modelo instalado, los flujos exactos y Vosk siguen funcionando.

## Pruebas y comunicación
`cd apps/api && python -m pytest -q`; `cd apps/desktop && npm run test:audio && npm run test:electron && npm run lint:electron`.
Reportar en español: Cambios · Pruebas locales · Windows (PASS/FAIL/NOT TESTED) · Próximo paso.
