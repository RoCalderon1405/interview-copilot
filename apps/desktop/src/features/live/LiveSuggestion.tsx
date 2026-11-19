import type {GenerationFailureCode, LiveEvent} from '../../types';
import {useI18n} from '../../i18n';

export type LiveSuggestionEvent = Extract<LiveEvent, {type: 'suggestion' | 'generated_suggestion'}>;
export type LiveGenerationState = 'unconfirmed' | 'replaced' | 'stopped' | 'interrupted';

const GENERATION_STATES: Record<LiveGenerationState, string> = {
  unconfirmed:'Sin sugerencia IA recibida. El inicio de la generación no está confirmado.',
  replaced:'Pregunta reemplazada por una más reciente; no se recibió una sugerencia IA.',
  stopped:'Detención de captura; sin sugerencia IA recibida para esta pregunta.',
  interrupted:'Sesión interrumpida o reiniciada; no se recibió una sugerencia IA para esta pregunta.',
};

const FAILURE_REASONS: Record<GenerationFailureCode, string> = {
  disabled:'Generación de IA desactivada en el backend.',
  not_configured:'Configuración de IA incompleta o inválida. Revisa el modelo y las variables del backend.',
  invalid_input:'La pregunta no cumple los límites de generación de IA.',
  unavailable:'Ollama no está disponible. Revisa el servicio y el modelo local.',
  timeout:'Se agotó el tiempo de generación de IA.',
  invalid_response:'La respuesta de IA se descartó por validación de formato o seguridad.',
  provider_error:'Ollama no pudo completar la generación. Revisa el servicio y el modelo configurado.',
};

/** One question card; documentary and unverified AI provenance remain distinct within it. */
export function LiveSuggestion({item, failure, showQuestion = true, generated, generationState}: {
  item: LiveSuggestionEvent; failure?: GenerationFailureCode; showQuestion?: boolean;
  generated?: Extract<LiveSuggestionEvent, {type:'generated_suggestion'}>; generationState?: LiveGenerationState;
}) {
  const {t} = useI18n();
  const ai = item.type === 'generated_suggestion' ? item : generated;
  return <article className={`live-result live-question-card live-result-${item.type === 'generated_suggestion' || ai ? 'generated'
    : item.status === 'found' ? item.match_type : 'no-evidence'}`} data-session-id={item.session_id} data-question-id={item.question_id}>
    {showQuestion && <h3 className="live-current-question">{item.question}</h3>}
    {item.type === 'suggestion' && <div className="live-documentary-result">
    <span className={`live-result-label ${item.status === 'found' ? 'matched' : ''}`}>
      {t(item.match_type === 'exact_qa' ? 'Respuesta exacta del documento' : item.match_type === 'semantic_qa' ? 'Posible respuesta semántica — revisar' : 'Sin respuesta suficientemente relacionada')}
    </span>
    {item.match_type === 'semantic_qa' && item.matched_question && <span className="small-muted">{t('Pregunta guardada:')} {item.matched_question}</span>}
    {item.answer && <p>{item.answer}</p>}
    {item.status === 'no_evidence' && (failure
      ? <p className="small-muted" role="status">{t(FAILURE_REASONS[failure])}</p>
      : !ai && !generationState && <p>{t('No hay una respuesta suficientemente relacionada en los documentos. La IA, si responde, se identifica como no verificada.')}</p>)}
    {item.source && <div className="small-muted">{t('Fuente:')} {item.source.document_name} · {item.source.location}</div>}
    </div>}
    {ai && <section className="live-ai-result" aria-label={t('Sugerencia generada por IA — revisar')}>
      <span className="live-result-label">{t('Sugerencia generada por IA — revisar')}</span>
      <p>{ai.answer}</p>
      <div className="small-muted">{ai.provider} · {ai.model} · {t('Sin respaldo documental')}</div>
      <span className="live-result-warning">{t('No verificada. Puede contener errores o experiencia inventada.')}</span>
    </section>}
    {!ai && !failure && generationState && <p className="small-muted" role="status">{t(GENERATION_STATES[generationState])}</p>}
  </article>;
}
