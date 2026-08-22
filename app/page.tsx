'use client';

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';

type Language = 'ko' | 'en';
type Message = { role: 'assistant' | 'user'; content: string };
type CopilotState = 'checking' | 'ready' | 'auth' | 'offline';
type BackendState = 'checking' | 'ready' | 'offline';
type HealthResponse = { copilot?: string; jellyguard?: string };
type CopilotResponse = { answer?: string; code?: string; error?: string };

const copilotApiBase = process.env.NEXT_PUBLIC_COPILOT_API_BASE ?? 'http://localhost:3001';

const datasetDefinitions = [
  {
    id: 'jellyfish',
    name: { ko: '해파리 보고', en: 'Jellyfish reports' },
    source: { ko: '국립수산과학원', en: 'NIFS' },
    tone: 'coral',
  },
  {
    id: 'ocean_current',
    name: { ko: '해류 관측', en: 'Ocean currents' },
    source: { ko: 'KHOA 부이·HF-RADAR', en: 'KHOA buoys · HF radar' },
    tone: 'blue',
  },
  {
    id: 'marine_environment',
    name: { ko: '적조·해양환경', en: 'Marine environment' },
    source: { ko: 'NIFS 적조·정선해양', en: 'NIFS red tide · ocean survey' },
    tone: 'mint',
  },
  {
    id: 'risk_zone',
    name: { ko: '취수구 접근영역', en: 'Intake approach zone' },
    source: { ko: 'JellyGuard 조건부 계산', en: 'JellyGuard conditional model' },
    tone: 'violet',
  },
] as const;

const copy = {
  ko: {
    center: '경북 동해 데이터 센터',
    overviewNav: '데이터 현황',
    managerNav: 'AI 데이터 매니저',
    localMode: 'LOCAL MODE',
    localDescription: '데이터와 인증 정보는 로컬 서버 안에서만 처리됩니다.',
    region: 'GYEONGBUK EAST SEA',
    title: '해파리 데이터 관리 센터',
    subtitle: '해파리·해류·해양환경·취수구 접근영역을 하나의 흐름에서 점검하세요.',
    switchLanguage: '영어로 전환',
    switchLabel: 'English',
    schemaReady: '스키마 준비',
    datasetStatusRequest: '데이터 상태를 확인해줘',
    managerEyebrow: 'COPILOT DATA MANAGER',
    managerTitle: '데이터에 대해 무엇이든 물어보세요',
    welcome: '안녕하세요. 데이터 연결 상태와 품질 검사 항목을 확인해 드릴게요.',
    loading: '데이터 도구를 확인하고 있어요…',
    inputLabel: 'Copilot에게 질문',
    inputPlaceholder: '예: 취수구 접근영역 데이터 상태를 확인해줘',
    send: '보내기',
    statusEyebrow: 'LOCAL STATUS',
    statusTitle: '관리 상태',
    registeredData: '등록된 데이터',
    fourItems: '4개',
    writePermission: '쓰기 권한',
    blocked: '차단됨',
    backend: 'JellyGuard',
    authHelp: 'Copilot CLI 로그인 또는 COPILOT_GITHUB_TOKEN 설정이 필요합니다.',
    offlineHelp: '로컬 백엔드가 실행되지 않았습니다. 프로젝트에서 npm run dev를 실행하세요.',
    emptyError: '응답을 받지 못했습니다.',
    fallbackAnswer: '응답을 생성하지 못했습니다.',
    connectionError: '연결 오류가 발생했습니다.',
    connectionHelp: '서버와 Copilot 인증 상태를 확인해 주세요.',
    quickPrompts: [
      '관리 중인 데이터 목록을 보여줘',
      '해류 데이터 품질을 확인해줘',
      '취수구 접근영역의 현재 상태를 알려줘',
    ],
    status: {
      checking: '확인 중',
      ready: '연결됨',
      auth: '인증 필요',
      offline: '서버 꺼짐',
    },
  },
  en: {
    center: 'Gyeongbuk East Sea Data Center',
    overviewNav: 'Data overview',
    managerNav: 'AI data manager',
    localMode: 'LOCAL MODE',
    localDescription: 'Data and credentials are processed only by your local server.',
    region: 'GYEONGBUK EAST SEA',
    title: 'Jellyfish Data Center',
    subtitle: 'Review jellyfish, currents, marine conditions, and intake approach zones in one workflow.',
    switchLanguage: '한국어로 전환',
    switchLabel: '한국어',
    schemaReady: 'Schema ready',
    datasetStatusRequest: 'dataset status',
    managerEyebrow: 'COPILOT DATA MANAGER',
    managerTitle: 'Ask anything about your data',
    welcome: 'Hello! I can review your data connections and quality checks.',
    loading: 'Checking the data tools…',
    inputLabel: 'Ask Copilot',
    inputPlaceholder: 'Example: Check the intake approach zone status',
    send: 'Send',
    statusEyebrow: 'LOCAL STATUS',
    statusTitle: 'Management status',
    registeredData: 'Registered datasets',
    fourItems: '4',
    writePermission: 'Write access',
    blocked: 'Blocked',
    backend: 'JellyGuard',
    authHelp: 'Sign in to Copilot CLI or configure COPILOT_GITHUB_TOKEN.',
    offlineHelp: 'The local backend is not running. Run npm run dev in the project.',
    emptyError: 'No response was received.',
    fallbackAnswer: 'A response could not be generated.',
    connectionError: 'A connection error occurred.',
    connectionHelp: 'Check the server and Copilot authentication status.',
    quickPrompts: [
      'Show me the datasets being managed',
      'Check the quality of the ocean current dataset',
      'Show the current intake approach zone status',
    ],
    status: {
      checking: 'Checking',
      ready: 'Connected',
      auth: 'Sign-in needed',
      offline: 'Server offline',
    },
  },
} as const;

const statusClassNames: Record<CopilotState, string> = {
  checking: 'text-[#7b6c4c]',
  ready: 'text-[#2f7d69]',
  auth: 'text-[#be6b4c]',
  offline: 'text-[#a14f55]',
};

export default function Home() {
  const [language, setLanguage] = useState<Language>('ko');
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: copy.ko.welcome },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [copilotState, setCopilotState] = useState<CopilotState>('checking');
  const [backendState, setBackendState] = useState<BackendState>('checking');
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const t = copy[language];

  useEffect(() => {
    const savedLanguage = window.localStorage.getItem('jellywatch-language');
    if (savedLanguage === 'ko' || savedLanguage === 'en') {
      setLanguage(savedLanguage);
      setMessages([{ role: 'assistant', content: copy[savedLanguage].welcome }]);
      document.documentElement.lang = savedLanguage;
    }
  }, []);

  useEffect(() => {
    fetch(`${copilotApiBase}/api/health`)
      .then(async (response) => {
        const body = (await response.json()) as HealthResponse;
        setCopilotState(body.copilot === 'ready' ? 'ready' : 'auth');
        setBackendState(body.jellyguard === 'ready' ? 'ready' : 'offline');
      })
      .catch(() => {
        setCopilotState('offline');
        setBackendState('offline');
      });
  }, []);

  useEffect(() => {
    const chatScroll = chatScrollRef.current;
    if (!chatScroll) return;

    const frame = window.requestAnimationFrame(() => {
      chatScroll.scrollTo({ top: chatScroll.scrollHeight, behavior: 'smooth' });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [messages, loading]);

  function toggleLanguage() {
    const nextLanguage: Language = language === 'ko' ? 'en' : 'ko';
    setLanguage(nextLanguage);
    window.localStorage.setItem('jellywatch-language', nextLanguage);
    document.documentElement.lang = nextLanguage;
    setMessages((current) =>
      current.length === 1 && current[0].role === 'assistant'
        ? [{ role: 'assistant', content: copy[nextLanguage].welcome }]
        : current,
    );
  }

  async function sendMessage(message: string) {
    const question = message.trim();
    if (!question || loading) return;

    setMessages((current) => [...current, { role: 'user', content: question }]);
    setInput('');
    setLoading(true);

    try {
      const response = await fetch(`${copilotApiBase}/api/copilot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: question, language }),
      });
      const body = (await response.json()) as CopilotResponse;

      if (!response.ok) {
        setCopilotState(body.code === 'COPILOT_AUTH_REQUIRED' ? 'auth' : 'offline');
        throw new Error(body.error ?? t.emptyError);
      }

      setCopilotState('ready');
      setMessages((current) => [
        ...current,
        { role: 'assistant', content: body.answer ?? t.fallbackAnswer },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: `${error instanceof Error ? error.message : t.connectionError} ${t.connectionHelp}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(input);
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter' || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void sendMessage(input);
  }

  return (
    <main className="min-h-screen bg-[#f3f7f8] text-[#13272d]">
      <div className="mx-auto grid min-h-screen max-w-[1480px] grid-cols-[240px_minmax(0,1fr)] px-4 py-4 max-lg:grid-cols-1">
        <aside className="rounded-[28px] bg-[#103b46] px-6 py-7 text-white max-lg:mb-4">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-[#b9f1dc] text-2xl text-[#103b46]">◌</div>
            <div>
              <p className="text-lg font-bold tracking-tight">Jellywatch</p>
              <p className="text-xs text-white/55">{t.center}</p>
            </div>
          </div>

          <nav className="mt-12 space-y-2 text-sm">
            <a className="block rounded-xl bg-white/12 px-4 py-3 font-semibold" href="#overview">{t.overviewNav}</a>
            <a className="block rounded-xl px-4 py-3 text-white/60 transition hover:bg-white/8 hover:text-white" href="#assistant">{t.managerNav}</a>
          </nav>

          <div className="mt-12 rounded-2xl border border-white/10 bg-white/5 p-4">
            <p className="text-xs font-semibold text-[#b9f1dc]">{t.localMode}</p>
            <p className="mt-2 text-sm leading-6 text-white/65">{t.localDescription}</p>
          </div>
        </aside>

        <section className="px-5 py-4 sm:px-9 sm:py-7">
          <header className="flex items-start justify-between gap-5">
            <div>
              <p className="text-sm font-semibold text-[#38717b]">{t.region}</p>
              <h1 className="mt-2 text-3xl font-bold tracking-[-0.04em] sm:text-4xl">{t.title}</h1>
              <p className="mt-3 text-sm text-[#61757a]">{t.subtitle}</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                aria-label={t.switchLanguage}
                className="flex items-center gap-2 rounded-full border border-[#cbdcdf] bg-white p-1.5 pr-3 text-xs font-bold text-[#315f68] shadow-[0_8px_24px_rgba(33,70,78,.07)] transition hover:border-[#80aaa2] hover:bg-[#f7fbfa]"
                onClick={toggleLanguage}
                title={t.switchLanguage}
                type="button"
              >
                <span className="grid h-7 min-w-8 place-items-center rounded-full bg-[#103b46] px-2 text-[11px] text-white">
                  {language === 'ko' ? 'KO' : 'EN'}
                </span>
                <span>{t.switchLabel}</span>
              </button>
              <div className="hidden rounded-full border border-[#d7e3e5] bg-white px-4 py-2 text-sm text-[#567078] sm:block">LOCALHOST</div>
            </div>
          </header>

          <div id="overview" className="mt-9 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {datasetDefinitions.map((dataset) => (
              <button
                key={dataset.id}
                className={`dataset-card ${dataset.tone} text-left`}
                onClick={() =>
                  void sendMessage(
                    language === 'ko'
                      ? `${dataset.name.ko} ${t.datasetStatusRequest}`
                      : `Check the ${dataset.name.en} ${t.datasetStatusRequest}`,
                  )
                }
                type="button"
              >
                <div className="flex items-center justify-between">
                  <span className="status-dot" />
                  <span className="rounded-full bg-white/65 px-2.5 py-1 text-[11px] font-semibold text-[#667a7e]">{t.schemaReady}</span>
                </div>
                <h2 className="mt-7 text-xl font-bold">{dataset.name[language]}</h2>
                <p className="mt-1 text-xs text-[#5f7478]">{dataset.source[language]}</p>
              </button>
            ))}
          </div>

          <section id="assistant" className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,.65fr)]">
            <div className="rounded-[26px] border border-[#dce7e9] bg-white p-6 shadow-[0_18px_50px_rgba(33,70,78,.06)]">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-bold tracking-[0.12em] text-[#31806d]">{t.managerEyebrow}</p>
                  <h2 className="mt-2 text-2xl font-bold tracking-tight">{t.managerTitle}</h2>
                </div>
                <span className={`connection-light ${copilotState}`} aria-label={`Copilot ${t.status[copilotState]}`} />
              </div>

              <div
                ref={chatScrollRef}
                className="chat-scroll mt-7 space-y-3 overflow-y-auto pr-1"
                aria-live="polite"
              >
                {messages.map((message, index) => (
                  <div key={`${message.role}-${index}`} className={`message ${message.role}`}>
                    {message.content}
                  </div>
                ))}
                {loading && <div className="message assistant animate-pulse">{t.loading}</div>}
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {t.quickPrompts.map((prompt) => (
                  <button key={prompt} type="button" className="quick-prompt" onClick={() => void sendMessage(prompt)}>
                    {prompt}
                  </button>
                ))}
              </div>

              <form className="mt-5 flex gap-3 rounded-2xl border border-[#d8e4e6] bg-[#fafcfc] p-2 focus-within:border-[#76a79d]" onSubmit={handleSubmit}>
                <input
                  aria-label={t.inputLabel}
                  className="min-w-0 flex-1 bg-transparent px-3 text-sm outline-none"
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={handleInputKeyDown}
                  placeholder={t.inputPlaceholder}
                  value={input}
                />
                <button disabled={loading || !input.trim()} className="rounded-xl bg-[#103b46] px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-45" type="submit">
                  {t.send}
                </button>
              </form>
            </div>

            <aside className="rounded-[26px] bg-[#e7f0f2] p-6">
              <p className="text-xs font-bold tracking-[0.12em] text-[#55757c]">{t.statusEyebrow}</p>
              <h2 className="mt-2 text-xl font-bold">{t.statusTitle}</h2>
              <div className="mt-8 space-y-5 text-sm">
                <div className="flex justify-between border-b border-[#cfdee1] pb-4"><span className="text-[#60777c]">{t.registeredData}</span><strong>{t.fourItems}</strong></div>
                <div className="flex justify-between border-b border-[#cfdee1] pb-4"><span className="text-[#60777c]">{t.writePermission}</span><strong>{t.blocked}</strong></div>
                <div className="flex justify-between border-b border-[#cfdee1] pb-4"><span className="text-[#60777c]">Copilot</span><strong className={statusClassNames[copilotState]}>{t.status[copilotState]}</strong></div>
                <div className="flex justify-between"><span className="text-[#60777c]">{t.backend}</span><strong className={statusClassNames[backendState]}>{t.status[backendState]}</strong></div>
              </div>

              {copilotState === 'auth' && (
                <div className="mt-8 rounded-2xl bg-white/70 p-4 text-xs leading-6 text-[#5f7478]">
                  {t.authHelp}
                </div>
              )}
              {copilotState === 'offline' && (
                <div className="mt-8 rounded-2xl bg-white/70 p-4 text-xs leading-6 text-[#5f7478]">
                  {t.offlineHelp}
                </div>
              )}
            </aside>
          </section>
        </section>
      </div>
    </main>
  );
}
