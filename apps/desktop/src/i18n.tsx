import {createContext, useContext, useEffect, useState, type ReactNode} from 'react';

export type UiLanguage = 'en' | 'es';
const STORAGE_KEY = 'copilot.ui-language';
export function readUiLanguage(storage?: Pick<Storage, 'getItem'>): UiLanguage {
  try { return storage?.getItem(STORAGE_KEY) === 'en' ? 'en' : 'es'; } catch { return 'es'; }
}
export function saveUiLanguage(storage: Pick<Storage, 'setItem'>, language: UiLanguage): boolean {
  try { storage.setItem(STORAGE_KEY, language); return true; } catch { return false; }
}
export function translate(language: UiLanguage, text: string): string {
  return window.copilotUi?.translate(language, text) ?? text;
}
const LanguageContext = createContext({language:'es' as UiLanguage, setLanguage:(_language: UiLanguage) => {}, saved:true});

/** Locale affects presentation only. Provider grants, session state and content stay unchanged. */
export function LanguageProvider({children}: {children: ReactNode}) {
  const [language, updateLanguage] = useState<UiLanguage>(() => {
    try { return readUiLanguage(window.localStorage); } catch { return 'es'; }
  });
  const [saved, setSaved] = useState(true);
  useEffect(() => {
    document.documentElement.lang = language;
    void window.copilotDesktop?.setUiLanguage(language).catch(() => { /* Browser/closing native shell. */ });
  }, [language]);
  const setLanguage = (next: UiLanguage) => {
    updateLanguage(next);
    try { setSaved(saveUiLanguage(window.localStorage, next)); } catch { setSaved(false); }
  };
  return <LanguageContext.Provider value={{language,setLanguage,saved}}>{children}</LanguageContext.Provider>;
}
export function useI18n() {
  const context = useContext(LanguageContext);
  return {...context, t:(text: string) => translate(context.language,text)};
}

declare global {
  interface Window { copilotUi?: {translate(language: UiLanguage, text: string): string} }
}
