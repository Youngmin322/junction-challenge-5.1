'use client';

import Image from 'next/image';
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type Message = { role: 'assistant' | 'user'; content: string };
type ConnectionState = 'checking' | 'ready' | 'auth' | 'offline';
type HealthResponse = { copilot?: string; mops?: string; jellyguard?: string };
type CopilotResponse = { answer?: string; code?: string; error?: string };

const copilotApiBase = process.env.NEXT_PUBLIC_COPILOT_API_BASE ?? 'http://localhost:3001';

const assets = {
  mark: '/design-assets/mops-mark.svg',
  basemap: '/design-assets/abstract-basemap.svg',
  domain: '/design-assets/synth-domain-hatched.svg',
  envelope3: '/design-assets/synthetic-envelope-3h.png',
  envelope6: '/design-assets/synthetic-envelope-6h.png',
  envelope12: '/design-assets/synthetic-envelope-12h.png',
  observationRing: '/design-assets/observation-ring.svg',
  observationDot: '/design-assets/observation-dot.svg',
  watchCellDot: '/design-assets/watch-cell-dot.svg',
  alert: '/design-assets/alert-icon.svg',
  history: '/design-assets/history-icon.svg',
} as const;

/**
 * MOPS API integration seam
 * -------------------------
 * This fixture mirrors the Figma review state. Replace each nested value with a
 * small adapter around these deterministic backend responses instead of binding
 * API payloads directly inside JSX:
 * - search_observations.data.latest_cluster -> observation
 * - bootstrap.data.current_vectors         -> romsField
 * - run_transport                          -> transport
 * - intersect_zone                         -> intersection
 * - explain_run                            -> provenance
 * Keeping one view-model prevents CACHED observations and SYNTHETIC results
 * from being accidentally merged into a single "risk" value.
 */
const dashboardFixture = {
  observation: {
    id: 'OBS-HANUL-HIST-001',
    observedAt: '2019-07-11',
    mode: 'CACHED',
    candidateCount: 1,
    returnedCount: 1,
    duplicateCount: 0,
  },
  transport: {
    runId: 'RUN-HANUL-DEMO-001',
    scenario: 'B2_current_only',
    engine: 'synthetic-rk4-v1',
    seedId: 'SEED-HANUL-DEMO-001',
    members: 25,
    horizons: [3, 6, 12] as const,
  },
  intersection: {
    // Legacy ID contains GATE, but intersect_zone treats this as a prototype
    // watch-cell polygon. Do not bind it to gate-line intersection output.
    watchCellId: 'DEMO_GATE_NAGOK_v1',
    members: 6,
    totalMembers: 25,
    firstWindow: '6–12h',
    sensitivity: 'core',
  },
  romsField: {
    status: 'NO_FIELD',
    vectorStatus: 'NO_FIELD',
    blockedVariant: 'DOMAIN_INSUFFICIENT',
  },
  provenance: {
    digest: '8f3a…',
    selectedSources: 2,
    excludedSources: 4,
    reasonCodes: 'NO_FIELD · LIVE_DISABLED · DIRECTION_UNVERIFIED',
    backendContract: 'feat/mcp-agent-orchestrator@b225a84',
    webContract: 'integration/all-features@b480e66',
  },
} as const;

const toolTrace = [
  { name: 'list_datasets', state: 'READY', detail: '데이터셋 목록' },
  { name: 'get_dataset_status', state: 'DEGRADED', detail: 'ROMS · NO_FIELD' },
  { name: 'check_dataset_quality', state: 'READY', detail: 'CACHED 경고' },
  { name: 'get_risk_overview', state: 'READY', detail: 'SYNTHETIC · 12h' },
] as const;

const evidenceCards = [
  {
    code: 'OBS', title: '직접관측 · 데모 기준', claim: 'direct_observation',
    lines: ['1건 · 2019-07-11', 'latest_cluster 지정'], footer: 'CACHED · 실시간 아님',
    invariant: '후보 1 · 반환 1 · 중복 0', tone: 'violet', state: 'READY',
  },
  {
    code: 'DOC', title: '보고서 catalog', claim: 'context/report_catalog',
    lines: ['좌표 없는 주간보고 맥락'], footer: 'CACHED · context only', tone: 'blue', state: 'READY',
  },
  {
    code: 'HB', title: '점 관측 · HB / HF', claim: 'context / distant_reference',
    lines: ['HB 3 · 근해 context', 'HF 13 · 원거리 reference'], footer: 'HF ≠ 한울 field', tone: 'cyan', state: 'READY',
  },
  {
    code: 'SCN', title: '조건부 시나리오', claim: 'conditional_scenario',
    lines: ['B2 · 3/6/12h', '나곡 6 of 25'], footer: 'SYNTHETIC · fixture', tone: 'orange', state: 'READY',
  },
  {
    code: '!', title: 'ROMS field 상태', claim: 'diagnostic',
    lines: ['현재 · NO_FIELD', 'BLOCKED · DOMAIN_INSUFFICIENT'], footer: '표시할 실측 면 field 없음', tone: 'muted', state: 'NO_FIELD',
  },
] as const;

function Tag({ children, tone = 'default' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`mops-tag mops-tag--${tone}`}>{children}</span>;
}

function MonitoringMap() {
  return (
    <section className="panel map-panel" aria-labelledby="map-title">
      <header className="panel-header map-header">
        <div><h2 id="map-title">한울원전 조건부 접근 우선순위 지도</h2><p>해파리 밀집 관측과 Risk Zone 상세 지도</p></div>
        <div className="layer-legend" aria-label="지도 레이어 범례">
          <span><i className="legend-dot violet" />해파리 밀집</span>
          <span><i className="legend-square orange" />Risk Zone</span>
          <span><i className="legend-dot cyan" />감시격자</span>
          <span><i className="legend-square rose" />감시선</span>
        </div>
      </header>

      <div className="map-canvas">
        <iframe className="risk-zone-frame" src="http://localhost:5173/" title="한울원전 조건부 접근 우선순위 지도" />
      </div>

      <footer className="map-disclaimer">
        <p><strong>Risk Zone은 해파리 밀집 관측과 같은 좌표계에 표시한 조건부 접근영역입니다.</strong> 실제 막힘 확률이나 시설 위험도를 뜻하지 않습니다.<br />관측은 CACHED, 이동영역은 SYNTHETIC 시나리오입니다.</p>
      </footer>
    </section>
  );
}

function CopilotPanel({ state }: { state: ConnectionState }) {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: '2019-07-11 과거 관측을 최근 확보 관측으로 지정했습니다.\n합성 12h 시나리오는 READY이며 실제 예보가 아닙니다.' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const quickPrompts = ['최근 확보 관측 근거', 'ROMS vector 없는 이유', '수송 엔진 차이'];

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, loading]);

  async function sendMessage(value: string) {
    const question = value.trim();
    if (!question || loading) return;
    setMessages((current) => [...current, { role: 'user', content: question }]);
    setInput('');
    setLoading(true);

    try {
      const response = await fetch(`${copilotApiBase}/api/copilot`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: question, language: 'ko' }),
      });
      const body = (await response.json()) as CopilotResponse;
      if (!response.ok) throw new Error(body.error ?? 'Copilot 응답을 받지 못했습니다.');
      setMessages((current) => [...current, { role: 'assistant', content: body.answer ?? '응답이 비어 있습니다.' }]);
    } catch (error) {
      setMessages((current) => [...current, {
        role: 'assistant',
        content: `${error instanceof Error ? error.message : '연결 오류가 발생했습니다.'}\nLOCAL 서버와 Copilot 인증 상태를 확인해 주세요.`,
      }]);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); void sendMessage(input); }
  function handleInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter' || event.nativeEvent.isComposing) return;
    event.preventDefault(); void sendMessage(input);
  }

  return (
    <aside className="panel copilot-panel" aria-labelledby="copilot-title">
      <header className="copilot-heading"><h2 id="copilot-title">감시 Copilot</h2><Tag tone={state === 'ready' ? 'brand' : 'muted'}>GitHub Copilot SDK · LOCAL</Tag></header>

      <form className="copilot-input" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="copilot-question">Copilot 질문</label>
        <input id="copilot-question" onChange={(event) => setInput(event.target.value)} onKeyDown={handleInputKeyDown} placeholder="가장 최근 확보 관측과 12h 이동영역을 설명해줘" value={input} />
        <button disabled={loading || !input.trim()} type="submit" aria-label="질문 전송">↑</button>
      </form>

      <div className="quick-prompts">{quickPrompts.map((prompt) => <button key={prompt} onClick={() => void sendMessage(prompt)} type="button">{prompt}</button>)}</div>

      <div className="copilot-messages" ref={scrollRef} aria-live="polite">
        {messages.map((message, index) => (
          <div className={`copilot-message copilot-message--${message.role}`} key={`${message.role}-${index}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        ))}
        {loading && <p className="copilot-message is-loading">MOPS 데이터 도구를 확인하고 있습니다…</p>}
      </div>

      <section className="tool-trace" aria-labelledby="tool-trace-title">
        <header><h3 id="tool-trace-title">Copilot 도구 호출 근거</h3><span>입력 · REST 근거 · 경고</span></header>
        <ol>
          {toolTrace.map((tool, index) => (
            <li key={tool.name}><span>{index + 1}</span><code>{tool.name}</code><strong className={tool.state === 'DEGRADED' ? 'is-degraded' : ''}>{tool.state}</strong><small>{tool.detail}</small></li>
          ))}
          <li className="mops-tool-row"><span>—</span><code>MOPS MCP surface</code><strong>DYNAMIC</strong><small>{'{tool_count}'} tools</small></li>
        </ol>
      </section>

      <section className="run-summary">
        <header><strong>표층조건부 이동 · SYNTHETIC READY</strong><span>READY</span></header>
        <p>{dashboardFixture.transport.scenario} · 3/6/12h · {dashboardFixture.transport.members} members</p>
        <small>fixture · watch-cell core · 나곡 {dashboardFixture.intersection.members} of {dashboardFixture.intersection.totalMembers}<br />최초 교차 {dashboardFixture.intersection.firstWindow} · 실제 예보 아님</small>
        <code>engine · {dashboardFixture.transport.engine} · {dashboardFixture.transport.seedId}</code>
      </section>
    </aside>
  );
}

function EvidenceGrid() {
  return (
    <section className="panel evidence-panel" aria-labelledby="evidence-title">
      <header className="evidence-heading"><h2 id="evidence-title">증거층과 계산상태를 섞지 않고 조회</h2><p>과거 관측 ≠ 합성 시나리오 ≠ ROMS field</p></header>
      <div className="evidence-grid">
        {evidenceCards.map((card) => (
          <article className={`evidence-card evidence-card--${card.tone}`} key={card.code}>
            <header><span>{card.code}</span><strong>{card.state}</strong></header>
            <h3>{card.title}</h3><code>{card.claim}</code>
            <p>{card.lines.map((line) => <span key={line}>{line}</span>)}</p>
            <small>{card.footer}</small>{'invariant' in card && <em>{card.invariant}</em>}
          </article>
        ))}
      </div>
    </section>
  );
}

function ProvenancePanel({ panelRef }: { panelRef: React.RefObject<HTMLElement | null> }) {
  const fixture = dashboardFixture;
  return (
    <section className="panel provenance-panel" ref={panelRef} aria-labelledby="provenance-title" tabIndex={-1}>
      <header><h2 id="provenance-title">출처 · 실행 근거</h2><span>TARGET · 2 BRANCHES</span></header>
      <dl>
        <div><dt>tool_surface</dt><dd>Copilot 4 · MOPS MCP {'{tool_count}'}</dd></div>
        <div><dt>tool_name</dt><dd>run_transport</dd></div>
        <div><dt>claim_type</dt><dd>conditional_scenario</dd></div>
        <div><dt>run_id</dt><dd>{fixture.transport.runId}</dd></div>
        <div><dt>engine · digest</dt><dd>{fixture.transport.engine} · {fixture.provenance.digest}</dd></div>
      </dl>
      <div className="source-counts"><strong>선택 소스 {fixture.provenance.selectedSources}</strong><b>제외 소스 {fixture.provenance.excludedSources}</b><span>{fixture.provenance.reasonCodes}</span></div>
      <div className="selection-invariant"><code>demo_current_cluster</code><span>true · {fixture.observation.id} · 중복 0</span></div>
      <div className="history-warning"><Image alt="" height={16} src={assets.history} width={16} /><p>{fixture.observation.observedAt} 과거 관측 · 실시간 아님 · SYNTHETIC 실제 예보 아님</p></div>
      <footer><span>contract refs · {fixture.provenance.backendContract}</span><span>{fixture.provenance.webContract} · 결합 미구현 · 공식 유향 문서 일치 여부 별도 추적</span></footer>
    </section>
  );
}

export default function Home() {
  const [copilotState, setCopilotState] = useState<ConnectionState>('checking');
  const [backendState, setBackendState] = useState<ConnectionState>('checking');
  const provenanceRef = useRef<HTMLElement>(null);

  useEffect(() => {
    fetch(`${copilotApiBase}/api/health`)
      .then(async (response) => {
        const body = (await response.json()) as HealthResponse;
        setCopilotState(body.copilot === 'ready' ? 'ready' : 'auth');
        // Accept the legacy health field while backend packages and environment
        // variables migrate from JellyGuard to the public MOPS product name.
        setBackendState((body.mops ?? body.jellyguard) === 'ready' ? 'ready' : 'offline');
      })
      .catch(() => { setCopilotState('offline'); setBackendState('offline'); });
  }, []);

  function showContractDetails() {
    provenanceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    provenanceRef.current?.focus({ preventScroll: true });
  }

  return (
    <main className="mops-app">
      <div className="dashboard-shell">
        <header className="global-header">
          <div className="brand"><Image alt="MOPS" height={32} priority src={assets.mark} width={32} /><div><h1>한울 주변 대량 해파리 군집 감시</h1><p>공개데이터 기반 조건부 이동·근거 조회</p></div></div>
          <div className="header-meta"><span>HANUL DEMO</span><i /><strong>FIXTURE PREVIEW · 단일 브랜치 실행 아님</strong><Tag tone="local">SDK · LOCAL</Tag></div>
        </header>

        <section className="status-bar" aria-label="대시보드 상태 요약">
          <div className="status-summary"><span className="status-light" /><strong>관측 READY · 합성 시나리오 READY</strong><p>실측 ROMS · NO_FIELD — 표시할 면 field 없음 · 합성 결과와 분리</p></div>
          <div className="status-actions"><Tag tone="cached">CACHED 관측</Tag><Tag tone="live">LIVE 조건부 · Gate</Tag><Tag tone="synthetic">SYNTHETIC 사용</Tag><button onClick={showContractDetails} type="button">계약 상태 보기</button></div>
        </section>

        <div className="primary-grid"><MonitoringMap /><CopilotPanel state={copilotState} /></div>
        <div className="secondary-grid"><EvidenceGrid /><ProvenancePanel panelRef={provenanceRef} /></div>

        <footer className="runtime-footer">
          <span>Copilot · <b data-state={copilotState}>{copilotState}</b></span>
          <span>MOPS backend · <b data-state={backendState}>{backendState}</b></span>
          <span>MOPS · Marine Organism Path Prediction System for Nuclear Power Plant Intake Clogging Risk</span>
        </footer>
      </div>
    </main>
  );
}
