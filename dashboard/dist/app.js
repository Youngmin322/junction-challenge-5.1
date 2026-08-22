const state = {
  key: sessionStorage.getItem('jellyguard-local-key') || '',
  bootstrap: null,
  run: null,
  intersection: null,
  explanation: null,
};

const $ = (selector) => document.querySelector(selector);
const keyInput = $('#access-key');
keyInput.value = state.key;

$('#connect-button').addEventListener('click', connect);
$('#run-button').addEventListener('click', runScenario);
$('#horizon-select').addEventListener('change', renderScenario);
$('#neighbor-select').addEventListener('change', renderScenario);

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      'content-type': 'application/json',
      'x-jellyguard-local-key': state.key,
      ...(options.headers || {}),
    },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function connect() {
  state.key = keyInput.value.trim();
  sessionStorage.setItem('jellyguard-local-key', state.key);
  setScreenState('LOADING', '자료 확인 중', '로컬 서비스의 공개 투영 정보를 불러오고 있습니다.');
  try {
    state.bootstrap = await request('/v1/dashboard/bootstrap');
    renderSources(state.bootstrap.data.sources || []);
    renderBasePlot();
    $('#run-button').disabled = false;
    $('#connection-message').textContent = '연결됨 · 조건부 시나리오를 실행할 수 있습니다.';
    setScreenState(state.bootstrap.status, '자료 준비 완료', '합성 시나리오 실행 전 상태입니다.');
  } catch (error) {
    setScreenState('ERROR', '로컬 서비스 응답 없음', error.message);
    $('#connection-message').textContent = '연결을 확인해 주세요.';
  }
}

async function runScenario() {
  $('#run-button').disabled = true;
  setScreenState('LOADING', '조건부 계산 중', '공개 감시격자와 이동 범위를 계산하고 있습니다.');
  try {
    const field = await request('/v1/hanul/field-status?allowed_modes=SYNTHETIC');
    const seed = state.bootstrap.data.scenario_seeds[0];
    state.run = await request('/v1/hanul/runs', {
      method: 'POST',
      body: JSON.stringify({
        seed_ids: [seed.seed_id],
        field_ref: field.data.selected_field_ref,
        horizons_h: [3, 6, 12],
        scenario_id: 'B2_current_only',
        allowed_modes: ['SYNTHETIC'],
      }),
    });
    const zoneIds = state.bootstrap.data.zones.map((zone) => zone.zone_id);
    state.intersection = await request(`/v1/hanul/runs/${state.run.run_id}/intersect`, {
      method: 'POST',
      body: JSON.stringify({ zone_ids: zoneIds, horizons_h: [3, 6, 12] }),
    });
    state.explanation = await request(`/v1/hanul/explain?run_id=${encodeURIComponent(state.run.run_id)}`);
    renderScenario();
    renderEvidence();
    setScreenState(state.run.status, '조건부 시나리오 준비 완료', '교차 member 수와 근거를 함께 확인하세요.');
  } catch (error) {
    setScreenState('BLOCKED', '계산을 완료하지 못했습니다', error.message);
  } finally {
    $('#run-button').disabled = false;
  }
}

function setScreenState(value, title, detail) {
  const normalized = ['READY', 'DEGRADED', 'STALE', 'BLOCKED'].includes(value) ? value : value === 'LOADING' ? 'LOADING' : 'ERROR';
  $('#overall-status').dataset.state = normalized;
  $('#overall-status').textContent = normalized;
  $('#state-banner').dataset.state = normalized;
  $('#state-title').textContent = title;
  $('#state-detail').textContent = detail;
}

function renderSources(sources) {
  $('#source-count').textContent = String(sources.length);
  $('#source-rows').innerHTML = sources.map((source) => {
    const stateName = source.public_reason_code || source.data_mode || 'UNAVAILABLE';
    const visual = source.freshness === 'synthetic' || source.freshness === 'fixture'
      ? 'synthetic'
      : source.data_mode === 'LIVE' || source.freshness === 'fresh'
        ? 'ready'
        : source.freshness === 'stale' || source.freshness === 'unknown'
          ? 'stale'
          : 'blocked';
    const timestamp = source.issued_at || source.fetched_at || '—';
    return `<tr><td><strong>${escapeHtml(labelForSource(source.source_id))}</strong><span>${escapeHtml(labelForClass(source.source_class))}</span></td><td><span class="source-state ${visual}">${escapeHtml(labelForState(stateName))}</span></td><td>${escapeHtml(shortTime(timestamp))}</td></tr>`;
  }).join('');
}

function renderBasePlot() {
  drawAxes();
  drawZones();
  drawSeeds();
}

function renderScenario() {
  if (!state.bootstrap) return;
  drawAxes();
  drawZones();
  drawSeeds();
  drawEnvelope();
  $('#plot-empty').hidden = Boolean(state.run);
  if (state.intersection) renderIntersections();
}

function drawAxes() {
  const domain = state.bootstrap?.data.domain;
  if (!domain) return;
  const box = domain.bbox;
  const labels = [];
  for (let index = 0; index <= 4; index += 1) {
    const lon = box.lon_min + (box.lon_max - box.lon_min) * index / 4;
    const lat = box.lat_max - (box.lat_max - box.lat_min) * index / 4;
    labels.push(`<text class="axis-label" x="${72 + 720 * index / 4}" y="610" text-anchor="middle">${lon.toFixed(2)}E</text>`);
    labels.push(`<text class="axis-label" x="58" y="${46 + 540 * index / 4}" text-anchor="end">${lat.toFixed(2)}N</text>`);
  }
  $('#plot-labels').innerHTML = labels.join('');
}

function drawZones() {
  const zones = state.bootstrap?.data.zones || [];
  const mode = $('#neighbor-select').value;
  const cells = [];
  for (const zone of zones) {
    for (const cellId of neighbors(zone.cell_id, mode)) {
      const rect = cellRect(cellId);
      cells.push(`<rect class="zone-cell ${cellId === zone.cell_id ? '' : 'edge'}" x="${rect.x}" y="${rect.y}" width="${rect.width}" height="${rect.height}" rx="3" />`);
    }
    const point = project(zone.lon, zone.lat);
    cells.push(`<text class="point-label" x="${point.x + 8}" y="${point.y - 8}">${escapeHtml(zone.display_name)}</text>`);
  }
  $('#plot-zones').innerHTML = cells.join('');
}

function drawSeeds() {
  const seeds = state.bootstrap?.data.scenario_seeds || [];
  $('#plot-seeds').innerHTML = seeds.map((seed) => {
    const point = project(seed.geometry.coordinates[0], seed.geometry.coordinates[1]);
    return `<circle class="seed-glow" cx="${point.x}" cy="${point.y}" r="18"/><circle class="seed-point" cx="${point.x}" cy="${point.y}" r="5"/><text class="point-label" x="${point.x + 10}" y="${point.y + 18}">합성 관측 입력</text>`;
  }).join('');
}

function drawEnvelope() {
  if (!state.run) { $('#plot-envelope').innerHTML = ''; return; }
  const horizon = $('#horizon-select').value;
  const envelope = state.run.data.computed_metric.envelopes[horizon];
  $('#plot-envelope').innerHTML = (envelope?.occupied_cells || []).map((cellId) => {
    const rect = cellRect(cellId);
    return `<rect class="envelope-cell" x="${rect.x}" y="${rect.y}" width="${rect.width}" height="${rect.height}" rx="3" />`;
  }).join('');
}

function renderIntersections() {
  const horizon = Number($('#horizon-select').value);
  const mode = $('#neighbor-select').value;
  const zones = state.intersection.data.zones || [];
  $('#intersection-cards').innerHTML = zones.map((zone) => {
    const label = state.bootstrap.data.zones.find((item) => item.zone_id === zone.zone_id)?.display_name || zone.zone_id;
    const metric = zone.sensitivity[mode].by_horizon.find((item) => item.horizon_h === horizon);
    const window = zone.sensitivity[mode].first_intersection_window;
    const windowText = window && window.to_h <= horizon
      ? `${window.from_h}–${window.to_h}h 구간`
      : '선택 시간창 내 교차 없음';
    return `<article class="intersection-card"><h3>${escapeHtml(label)}</h3><div class="metric"><span>${horizon}h 교차 member</span><strong>${metric.members_intersected} of ${metric.members_total}</strong></div><div class="metric"><span>최초 교차</span><strong>${escapeHtml(windowText)}</strong></div></article>`;
  }).join('');
}

function renderEvidence() {
  $('#run-id').textContent = state.run.run_id;
  $('#run-digest').textContent = state.run.deterministic_result_digest;
  $('#engine-version').textContent = state.run.data.engine_version;
  $('#as-of').textContent = state.run.as_of;
  $('#explanation').textContent = JSON.stringify(state.explanation.data.explanation, null, 2);
}

function project(lon, lat) {
  const box = state.bootstrap.data.domain.bbox;
  return {
    x: 72 + (lon - box.lon_min) / (box.lon_max - box.lon_min) * 720,
    y: 42 + (box.lat_max - lat) / (box.lat_max - box.lat_min) * 540,
  };
}

function cellRect(cellId) {
  const match = /^r(\d+)c(\d+)$/.exec(cellId);
  const row = Number(match[1]);
  const col = Number(match[2]);
  const box = state.bootstrap.data.domain.bbox;
  const spacing = state.bootstrap.data.domain.spacing_deg;
  const topLeft = project(box.lon_min + col * spacing, box.lat_min + (row + 1) * spacing);
  const bottomRight = project(box.lon_min + (col + 1) * spacing, box.lat_min + row * spacing);
  return { x: topLeft.x, y: topLeft.y, width: bottomRight.x - topLeft.x, height: bottomRight.y - topLeft.y };
}

function neighbors(cellId, mode) {
  const match = /^r(\d+)c(\d+)$/.exec(cellId);
  const row = Number(match[1]);
  const col = Number(match[2]);
  const offsets = [[0, 0]];
  if (mode === 'edge4' || mode === 'edge8') offsets.push([-1, 0], [1, 0], [0, -1], [0, 1]);
  if (mode === 'edge8') offsets.push([-1, -1], [-1, 1], [1, -1], [1, 1]);
  return offsets.map(([dr, dc]) => `r${String(row + dr).padStart(2, '0')}c${String(col + dc).padStart(2, '0')}`);
}

function shortTime(value) {
  if (value === '—') return value;
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 16);
}

function labelForSource(value) {
  return ({
    historical_observation_fixture: '과거 관측 재생',
    scenario_seed_synthetic: '합성 관측 입력',
    nifs_jelly_catalog: 'NIFS 해파리 보고',
    khoa_tw_recent_hanul: 'KHOA 한울 관측점',
    cached_field: '저장 유동장',
    synthetic_field: '합성 유동장',
    khoa_roms_blocked_fixture: 'ROMS 상태 재생',
    nifs_redtide_list: 'NIFS 해양 사건 맥락',
    nifs_soo_list: 'NIFS 해양 환경 맥락',
    khoa_hf_current_regression: 'HF 관측 회귀자료',
    khoa_roms_live: 'ROMS 면 자료',
    nifs_jelly_detail2_unverified: 'NIFS 상세 보고 후보',
  })[value] || value;
}

function labelForClass(value) {
  return ({
    observation: '관측 자료',
    scenario_seed: '시나리오 입력',
    report_catalog: '공식 보고 목록',
    point_context: '관측점 맥락',
    field: '유동장',
    event_context: '해양 사건 맥락',
    profile_context: '해양 환경 맥락',
    field_fixture: '검증용 유동장',
  })[value] || '보조 자료';
}

function labelForState(value) {
  return ({
    LIVE: '실시간 연결',
    CACHED: '저장 자료',
    SYNTHETIC: '합성 시나리오',
    NO_COVERAGE: '적용 자료 없음',
    LIVE_NOT_ENABLED: '실시간 미사용',
    UPSTREAM_AUTH_FAILED: '제공기관 미연결',
    UPSTREAM_UNAVAILABLE: '제공기관 응답 없음',
    SCHEMA_INVALID: '형식 확인 필요',
    STALE_DATA: '최신성 확인 필요',
    UNKNOWN_AGE: '자료시각 미상',
    FIXTURE_DATA: '고정 재생자료',
    NO_COMPATIBLE_SOURCE: '사용 가능한 자료 없음',
    MODE_NOT_ALLOWED: '현재 모드 제외',
  })[value] || value;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);
}

if (state.key) connect();
