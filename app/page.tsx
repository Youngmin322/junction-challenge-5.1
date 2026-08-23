'use client';

import Image from 'next/image';
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from 'react';

type Message = { role: 'assistant' | 'user'; content: string };
type ConnectionState = 'checking' | 'ready' | 'auth' | 'offline';
type HealthResponse = { copilot?: string; mops?: string; jellyguard?: string };
type CopilotResponse = { answer?: string; code?: string; error?: string };
type Horizon = 3 | 6 | 12;
type UnitFocus = 'north' | 'central' | 'south' | 'new';
type UnitView = { id: string; label: string; focus: UnitFocus };
type PlantOption = { id: string; label: string; units: readonly UnitView[]; connected: boolean };

const copilotApiBase = process.env.NEXT_PUBLIC_COPILOT_API_BASE ?? 'http://localhost:3001';

const plantOptions: readonly PlantOption[] = [
  {
    id: 'hanul', label: '한울', connected: true,
    units: [
      { id: 'hanul-12', label: '한울 1·2호기', focus: 'north' },
      { id: 'hanul-34', label: '한울 3·4호기', focus: 'central' },
      { id: 'hanul-56', label: '한울 5·6호기', focus: 'south' },
      { id: 'shin-hanul-12', label: '신한울 1·2호기', focus: 'new' },
    ],
  },
  {
    id: 'kori', label: '고리', connected: false,
    units: [
      { id: 'kori-2', label: '고리 2호기', focus: 'north' },
      { id: 'kori-34', label: '고리 3·4호기', focus: 'central' },
    ],
  },
  {
    id: 'saeul', label: '새울', connected: false,
    units: [
      { id: 'saeul-12', label: '새울 1·2호기', focus: 'north' },
      { id: 'saeul-34', label: '새울 3·4호기', focus: 'central' },
    ],
  },
  {
    id: 'wolsong', label: '월성', connected: false,
    units: [
      { id: 'wolsong-12', label: '월성 1·2호기', focus: 'north' },
      { id: 'wolsong-34', label: '월성 3·4호기', focus: 'central' },
      { id: 'shin-wolsong-12', label: '신월성 1·2호기', focus: 'south' },
    ],
  },
  {
    id: 'hanbit', label: '한빛', connected: false,
    units: [
      { id: 'hanbit-12', label: '한빛 1·2호기', focus: 'north' },
      { id: 'hanbit-34', label: '한빛 3·4호기', focus: 'central' },
      { id: 'hanbit-56', label: '한빛 5·6호기', focus: 'south' },
    ],
  },
] as const;

const assets = {
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
    code: 'OBS', title: '직접관측', status: 'READY · CACHED · 1건',
    lines: ['OBS · 2019-07-11', 'CACHED · 실시간 아님'], tone: 'violet',
  },
  {
    code: 'DOC', title: '보고서 catalog', status: 'READY · CACHED · context',
    lines: ['DOC · 좌표 없는 주간보고 맥락'], tone: 'blue',
  },
  {
    code: 'HB', title: '점 관측 · HB / HF', status: 'READY · CACHED · context',
    lines: ['HB 3 · HF 13 · HF ≠ 한울 field'], tone: 'cyan',
  },
  {
    code: 'SCN', title: '조건부 시나리오', status: 'READY · SYNTHETIC',
    lines: ['SCN · 나곡 6 of 25', '최초 교차 6–12h'], tone: 'orange',
  },
  {
    code: '!', title: 'ROMS field 상태', status: 'NO_FIELD · BLOCKED',
    lines: ['실측 면 field 없음'], tone: 'muted',
  },
] as const;

function Tag({ children, tone = 'default' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`mops-tag mops-tag--${tone}`}>{children}</span>;
}

function MonitoringMap({ plant, unit, onSelectUnit }: {
  plant: PlantOption;
  unit: UnitView;
  onSelectUnit: (unitId: string) => void;
}) {
  const isHanul = plant.id === 'hanul';

  return (
    <section className="panel map-panel" aria-labelledby="map-title">
      <header className="panel-header map-header">
        <h2 className="sr-only" id="map-title">{plant.label} 취수구 감시 화면</h2>
        <div className="unit-tabs" aria-label={`${plant.label} 호기별 취수구 지도`}>
          {plant.units.map((candidate) => (
            <button
              aria-pressed={candidate.id === unit.id}
              className={candidate.id === unit.id ? 'is-active' : ''}
              key={candidate.id}
              onClick={() => onSelectUnit(candidate.id)}
              type="button"
            >
              {candidate.label}
            </button>
          ))}
        </div>
      </header>

      <div className={`map-canvas unit-view--${unit.focus} ${isHanul ? '' : 'is-unavailable'}`}>
        {isHanul ? (
          <>
            <iframe className="risk-zone-frame" src="http://localhost:5173/" title="한울원전 조건부 접근 우선순위 지도" />
          </>
        ) : (
          <Image alt={`${plant.label} 취수구 주변 프로토타입 지도`} className="map-basemap" fill priority sizes="(max-width: 980px) 100vw, 920px" src={assets.basemap} />
        )}
        {!isHanul && (
          <div className="unavailable-map-state" role="status">
            <span>DATA NOT CONNECTED</span>
            <strong>{unit.label} 취수구 지도</strong>
            <p>{plant.label} 원전 공개 관측·취수구 데이터는 아직 연결되지 않았습니다.<br />현재 MVP 계산과 관측 조회는 한울만 지원합니다.</p>
          </div>
        )}
      </div>

      {!isHanul && (
        <footer className="map-disclaimer">
          <Image alt="주의" height={16} src={assets.alert} width={16} />
          <p><strong>{plant.label} 자료 연결 전입니다.</strong> 데이터가 없다는 사실을 안전 또는 저위험으로 해석하지 않습니다.</p>
        </footer>
      )}
    </section>
  );
}

function CopilotPanel({ state, selectedHorizon, onSelectHorizon }: {
  state: ConnectionState;
  selectedHorizon: Horizon;
  onSelectHorizon: (horizon: Horizon) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: '2019-07-11 과거 관측을 최근 확보 관측으로 지정했습니다.\n합성 12h 시나리오는 READY이며 실제 예보가 아닙니다.' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const quickPrompts = ['직접관측 / 보고서 구분', '면 유동장 없는 이유', '감시격자 근거'];

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
        {messages.map((message, index) => <p className={`copilot-message copilot-message--${message.role}`} key={`${message.role}-${index}`}>{message.content}</p>)}
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
        <small>fixture · watch-cell core · 나곡 {dashboardFixture.intersection.members} of {dashboardFixture.intersection.totalMembers} · 최초 교차 {dashboardFixture.intersection.firstWindow} · 실제 예보 아님</small>
        <div className="run-summary-controls">
          <div className="horizon-pills" aria-label="합성 이동영역 시간 선택">
            {dashboardFixture.transport.horizons.map((horizon) => (
              <button aria-pressed={selectedHorizon === horizon} className={selectedHorizon === horizon ? 'is-active' : ''} key={horizon} onClick={() => onSelectHorizon(horizon)} type="button">{horizon}h</button>
            ))}
          </div>
          <button className="provenance-button" onClick={() => document.getElementById('provenance-title')?.scrollIntoView({ behavior: 'smooth', block: 'center' })} type="button">실행 근거 보기</button>
        </div>
      </section>
    </aside>
  );
}

function EvidenceGrid() {
  return (
    <section className="panel evidence-panel" aria-labelledby="evidence-title">
      <header className="evidence-heading"><h2 id="evidence-title">이어보기 · 증거층 탐색</h2></header>
      <div className="evidence-grid">
        {evidenceCards.map((card) => (
          <article className={`evidence-card evidence-card--${card.tone}`} key={card.code}>
            <div className="evidence-cover">
              <span aria-hidden="true">{card.code}</span>
            </div>
            <div className="evidence-progress" aria-hidden="true" />
            <div className="evidence-body">
              <h3>{card.title}</h3><strong>{card.status}</strong>
              <p>{card.lines.map((line) => <span key={line}>{line}</span>)}</p>
            </div>
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
  const [selectedHorizon, setSelectedHorizon] = useState<Horizon>(12);
  const [selectedPlantId, setSelectedPlantId] = useState('hanul');
  const [selectedUnitId, setSelectedUnitId] = useState('hanul-12');
  const [plantMenuOpen, setPlantMenuOpen] = useState(false);
  const [copilotState, setCopilotState] = useState<ConnectionState>('checking');
  const [backendState, setBackendState] = useState<ConnectionState>('checking');
  const [healthCheck, setHealthCheck] = useState(0);
  const provenanceRef = useRef<HTMLElement>(null);
  const plantPickerRef = useRef<HTMLDivElement>(null);
  const selectedPlant = plantOptions.find((plant) => plant.id === selectedPlantId) ?? plantOptions[0];
  const selectedUnit = selectedPlant.units.find((unit) => unit.id === selectedUnitId) ?? selectedPlant.units[0];

  useEffect(() => {
    function closePlantMenu(event: MouseEvent) {
      if (!plantPickerRef.current?.contains(event.target as Node)) setPlantMenuOpen(false);
    }
    function closePlantMenuOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') setPlantMenuOpen(false);
    }
    document.addEventListener('pointerdown', closePlantMenu);
    document.addEventListener('keydown', closePlantMenuOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closePlantMenu);
      document.removeEventListener('keydown', closePlantMenuOnEscape);
    };
  }, []);

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
  }, [healthCheck]);

  function selectPlant(plantId: string) {
    const plant = plantOptions.find((candidate) => candidate.id === plantId);
    if (!plant) return;
    setSelectedPlantId(plant.id);
    setSelectedUnitId(plant.units[0].id);
    setPlantMenuOpen(false);
  }

  return (
    <main className="mops-app">
      <div className="dashboard-shell">
        <header className="global-header">
          <div className="brand"><div><h1>원전 주변 해양 생물 이동 경로 예측 시스템</h1><p>MOPS_PUBLIC_DEMO · 조회 실행 2026.08.23 14:32 KST</p></div></div>
          <Tag tone="local">SDK · LOCAL</Tag>
          <div className="header-meta">
            <div className="plant-picker" ref={plantPickerRef}>
              <button aria-expanded={plantMenuOpen} aria-haspopup="menu" aria-label={`대상 원전: ${selectedPlant.label}`} className="plant-selector" onClick={() => setPlantMenuOpen((open) => !open)} type="button">
                {selectedPlant.label}<span aria-hidden="true" className={plantMenuOpen ? 'is-open' : ''}>⌄</span>
              </button>
              {plantMenuOpen && (
                <div className="plant-menu" role="menu" aria-label="원전 선택">
                  {plantOptions.map((plant) => (
                    <button aria-checked={plant.id === selectedPlant.id} className={plant.id === selectedPlant.id ? 'is-selected' : ''} key={plant.id} onClick={() => selectPlant(plant.id)} role="menuitemradio" type="button">
                      <span>{plant.label}</span><small>{plant.connected ? 'MVP 연결' : '자료 연결 전'}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button className="refresh-button" onClick={() => setHealthCheck((value) => value + 1)} type="button">상태 다시 확인</button>
          </div>
        </header>

        <section className="status-bar" aria-label="대시보드 상태 요약">
          <div className="status-summary"><span className="status-light" /><strong>{selectedPlant.label} 감시 화면</strong><p>{selectedPlant.connected ? '실측 ROMS · NO_FIELD — 표시할 면 field 없음 · 합성 결과와 분리' : '현재 MVP 자료 연결 전 · 탐색 구조만 제공'}</p></div>
          <div className="status-actions"><Tag tone="cached">{selectedPlant.connected ? 'CACHED 사용' : 'CACHED 미연결'}</Tag><Tag tone="live">{selectedPlant.connected ? 'LIVE 조건부 · GATE' : 'LIVE 미연결'}</Tag><Tag tone="synthetic">{selectedPlant.connected ? 'SYNTHETIC 사용' : 'SYNTHETIC 미허용'}</Tag></div>
        </section>

        <div className="primary-grid"><MonitoringMap onSelectUnit={setSelectedUnitId} plant={selectedPlant} unit={selectedUnit} /><CopilotPanel onSelectHorizon={setSelectedHorizon} selectedHorizon={selectedHorizon} state={copilotState} /></div>
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
