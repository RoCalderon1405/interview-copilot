import type {LiveEvent} from '../../types';
import {useI18n} from '../../i18n';

export type LiveSuggestionEvent = Extract<LiveEvent, {type: 'suggestion' | 'generated_suggestion'}>;

/** Keep generated provenance structurally separate from documentary attribution. */
export function LiveSuggestion({item}: {item: LiveSuggestionEvent}) {
  const {t} = useI18n();
  if (item.type === 'generated_suggestion') return <article className="live-result live-result-generated">
    <h3>{item.question}</h3>
    <span className="live-result-label">{t('Sugerencia generada por IA — revisar')}</span>
    <p>{item.answer}</p>
    <div className="small-muted">{item.provider} · {item.model} · {t('Sin respaldo documental')}</div>
    <span className="live-result-warning">{t('No verificada. Puede contener errores o experiencia inventada.')}</span>
  </article>;
  return <article className={`live-result live-result-${item.status === 'found' ? item.match_type : 'no-evidence'}`}>
    <h3>{item.question}</h3>
    <span className={`live-result-label ${item.status === 'found' ? 'matched' : ''}`}>
      {t(item.match_type === 'exact_qa' ? 'Respuesta exacta del documento' : item.match_type === 'semantic_qa' ? 'Posible respuesta semántica — revisar' : 'Sin respuesta suficientemente relacionada')}
    </span>
    {item.match_type === 'semantic_qa' && item.matched_question && <span className="small-muted">{t('Pregunta guardada:')} {item.matched_question}</span>}
    {item.answer && <p>{item.answer}</p>}
    {item.status === 'no_evidence' && <p>{t('No hay una respuesta suficientemente relacionada en los documentos. Una sugerencia de IA, si llega, se muestra por separado.')}</p>}
    {item.source && <div className="small-muted">{t('Fuente:')} {item.source.document_name} · {item.source.location}</div>}
  </article>;
}
