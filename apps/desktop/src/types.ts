export type DocumentRecord = { id: string; name: string; extension: string; entry_count: number; imported_at: string };
export type Source = { document_id?: string; document_name: string; location: string };
export type AnswerResponse = { status: 'found' | 'no_evidence'; answer: string | null; source: Source | null; match_type: 'exact_qa' | 'similar_qa' | 'document_excerpt' | null; note?: string };
export type Session = { id: string; mode: 'live' | 'practice' };
export type PracticeQuestion = { id: number; question: string; document_name: string };
export type Feedback = { score: number; method: string; feedback: string; missing_concepts: string[]; expected_answer: string; source: Source };

export type GenerationFailureCode = 'disabled' | 'not_configured' | 'invalid_input' | 'unavailable' |
  'timeout' | 'invalid_response' | 'provider_error';
export type LiveWindowState = {available:boolean; protected:boolean; alwaysOnTop:boolean;
  mode:'compact' | 'expanded'; backgroundOpacity:number; transparencyAvailable:boolean; customFrame:boolean};
export type DeepgramKeyResult = {result:'status'|'configured'|'deleted'|'cancelled'|'conflict'|'busy'|'error'|'unsupported'|'timed_out'; stored:boolean|null};
export type DeepgramAvailability = {
  available?:boolean; runtime_installed?:boolean; configured?:boolean;
  credential_source?:string; configuration_error?:string|null;
};

export type LiveEvent =
  | {type: 'status'; text: string}
  | {type: 'error'; text: string}
  | {type: 'partial'; text: string}
  | {type: 'final'; text: string}
  | {type: 'metrics'; frames: number}
  | {type: 'generation_failed'; session_id: string; question_id: string; code: GenerationFailureCode}
  | {type: 'generated_suggestion'; kind: 'ai_generated'; session_id: string; question_id: string;
      question: string; language: 'en-US' | 'es-MX'; answer: string; provider: 'ollama'; model: string; source: null}
  | {type: 'suggestion'; question: string; status: 'found' | 'no_evidence';
      session_id?: string; question_id?: string;
      answer: string | null; match_type: 'exact_qa' | 'semantic_qa' | null;
      matched_question: string; source: Source | null};

declare global {
  interface Window {
    copilotDesktop?: {
      manageDeepgramKey(action:'status'|'configure'|'replace'|'delete'): Promise<DeepgramKeyResult>;
      cancelDeepgramKey(): Promise<boolean>;
      getWindowState(): Promise<LiveWindowState>;
      setLiveMode(mode: 'compact' | 'expanded'): Promise<LiveWindowState | false>;
      setLiveOpacity(opacity: number): Promise<LiveWindowState | false>;
      minimizeWindow(): Promise<boolean>;
      closeWindow(): Promise<boolean>;
      setContentProtection(enabled: boolean): Promise<boolean>;
      setAlwaysOnTop(enabled: boolean): Promise<boolean>;
      openLiveCapture(): Promise<boolean>;
      closeLiveCapture(): Promise<boolean>;
      getLiveState(): Promise<{open: boolean; events: LiveEvent[]}>;
      setUiLanguage(language: 'en' | 'es'): Promise<boolean>;
      onDeepgramSettings(callback: () => void): () => void;
      onLiveEvent(callback: (event: LiveEvent) => void): () => void;
    };
  }
}

export type SessionReport = {
  session_id: string;
  mode: 'live' | 'practice';
  finished: boolean;
  answered_questions: number;
  coverage_score: number | null;
  method: 'keyword_coverage_only' | 'not_scored';
  warning: string;
  areas_to_improve: string[];
  recommendations: string[];
  questions: {question: string; coverage_score: number; missing_concepts: string[]; source: Source}[];
};
