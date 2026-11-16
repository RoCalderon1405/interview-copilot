export type DocumentRecord = { id: string; name: string; extension: string; entry_count: number; imported_at: string };
export type Source = { document_id?: string; document_name: string; location: string };
export type AnswerResponse = { status: 'found' | 'no_evidence'; answer: string | null; source: Source | null; match_type: 'exact_qa' | 'similar_qa' | 'document_excerpt' | null; note?: string };
export type Session = { id: string; mode: 'live' | 'practice' };
export type PracticeQuestion = { id: number; question: string; document_name: string };
export type Feedback = { score: number; method: string; feedback: string; missing_concepts: string[]; expected_answer: string; source: Source };

export type LiveEvent =
  | {type: 'status'; text: string}
  | {type: 'error'; text: string}
  | {type: 'partial'; text: string}
  | {type: 'final'; text: string}
  | {type: 'metrics'; frames: number}
  | {type: 'suggestion'; question: string; status: 'found' | 'no_evidence';
      answer: string | null; match_type: 'exact_qa' | 'semantic_qa' | null;
      matched_question: string; source: Source | null};

declare global {
  interface Window {
    copilotDesktop?: {
      getWindowState(): Promise<{ available: boolean; protected: boolean; alwaysOnTop: boolean }>;
      setContentProtection(enabled: boolean): Promise<boolean>;
      setAlwaysOnTop(enabled: boolean): Promise<boolean>;
      openLiveCapture(): Promise<boolean>;
      closeLiveCapture(): Promise<boolean>;
      getLiveState(): Promise<{open: boolean; events: LiveEvent[]}>;
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
