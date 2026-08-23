import 'dotenv/config';
import crypto from 'node:crypto';
import cors from 'cors';
import express from 'express';
import { CopilotClient, defineTool } from '@github/copilot-sdk';

const port = Number(process.env.COPILOT_API_PORT ?? 3001);
const webOrigin = process.env.WEB_ORIGIN ?? 'http://localhost:3100';
// Compatibility: the Python package and deployed environment variables still
// use the JellyGuard prefix. Keep those wire names until the backend migration,
// while all new product-facing copy and health output use MOPS.
const mopsApiBase = (process.env.JELLYGUARD_API_BASE ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const mopsRestKey = process.env.JELLYGUARD_LOCAL_REST_KEY?.trim() ?? '';
const credentialStatus = Object.freeze({
  copilotTokenConfigured: Boolean(process.env.COPILOT_GITHUB_TOKEN?.trim()),
  mopsRestKeyConfigured: Boolean(mopsRestKey),
  nifsJellyKeyConfigured: Boolean(process.env.JELLYGUARD_NIFS_JELLY_KEY?.trim()),
  khoaKeyConfigured: Boolean(process.env.JELLYGUARD_KHOA_KEY?.trim()),
});

const datasets = {
  jellyfish: {
    label: '해파리 보고',
    source: '국립수산과학원 해파리정보',
    cadence: '주간',
    connection: 'fixture',
    checks: ['보고서와 위치 관측 구분', '게시일 최신성 확인', '미관측과 미출현 구분'],
  },
  ocean_current: {
    label: '해류 관측',
    source: 'KHOA 해양관측부이·HF-RADAR',
    cadence: '시간별 통합',
    connection: 'fixture',
    checks: ['유향 정의 확인', 'u/v 단위 확인', '레이더·부이 시간 정렬'],
  },
  marine_environment: {
    label: '적조·해양환경',
    source: '국립수산과학원 적조·정선해양관측',
    cadence: '자료원별',
    connection: 'fixture',
    checks: ['수온·용존산소 단위 확인', '관측 수심 확인', 'QC·결측값 확인'],
  },
  risk_zone: {
    label: '취수구 접근영역',
    source: 'MOPS 조건부 연결 계산',
    cadence: '시나리오 실행 시',
    connection: 'synthetic_ready',
    checks: ['합성·실자료 표시', '해류·수심 coverage 확인', '조건부 연결로 표기'],
  },
} as const;

type DatasetName = keyof typeof datasets;

async function mopsBackendGet(path: string) {
  if (!mopsRestKey) throw new Error('MOPS backend REST key is not configured');
  const response = await fetch(`${mopsApiBase}${path}`, {
    headers: { 'x-jellyguard-local-key': mopsRestKey },
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`MOPS backend responded with ${response.status}`);
  return response.json();
}

const listDatasets = defineTool('list_datasets', {
  description: '서비스가 관리하는 해파리 관련 데이터셋 목록과 현재 상태를 조회한다.',
  parameters: { type: 'object', properties: {} },
  handler: async () => {
    try {
      return await mopsBackendGet('/v1/datasets');
    } catch {
      return {
        backend: 'offline',
        datasets: Object.entries(datasets).map(([id, dataset]) => ({ id, ...dataset })),
      };
    }
  },
});

const getDatasetStatus = defineTool('get_dataset_status', {
  description: '선택한 데이터셋의 출처, 갱신 주기, 연결 상태와 검사 항목을 확인한다.',
  parameters: {
    type: 'object',
    properties: {
      datasetName: {
        type: 'string',
        enum: Object.keys(datasets),
        description: '확인할 데이터셋 ID',
      },
    },
    required: ['datasetName'],
  },
  handler: async ({ datasetName }: { datasetName: DatasetName }) => {
    try {
      return await mopsBackendGet(`/v1/datasets/${datasetName}/status`);
    } catch {
      return { id: datasetName, backend: 'offline', ...datasets[datasetName] };
    }
  },
});

const checkDatasetQuality = defineTool('check_dataset_quality', {
  description: '선택한 데이터셋에 필요한 품질 검사 항목과 현재 준비 상태를 알려준다.',
  parameters: {
    type: 'object',
    properties: {
      datasetName: {
        type: 'string',
        enum: Object.keys(datasets),
        description: '검사할 데이터셋 ID',
      },
    },
    required: ['datasetName'],
  },
  handler: async ({ datasetName }: { datasetName: DatasetName }) => {
    try {
      return await mopsBackendGet(`/v1/datasets/${datasetName}/quality`);
    } catch {
      const dataset = datasets[datasetName];
      return {
        dataset: dataset.label,
        ready: datasetName === 'risk_zone',
        backend: 'offline',
        reason: 'MOPS 백엔드에 연결되지 않아 로컬 스키마만 확인했습니다.',
        requiredChecks: dataset.checks,
        nextAction: 'MOPS 백엔드를 실행하고 연결 상태를 다시 확인하세요.',
      };
    }
  },
});

const getRiskOverview = defineTool('get_risk_overview', {
  description: '한울 공개 데모의 조건부 이동영역, 감시격자, 자료 모드와 주의사항을 조회한다.',
  parameters: { type: 'object', properties: {} },
  handler: async () => {
    try {
      return await mopsBackendGet('/v1/dashboard/bootstrap');
    } catch {
      return {
        status: 'offline',
        message: 'MOPS 백엔드가 실행 중일 때 합성 이동영역과 감시격자를 조회할 수 있습니다.',
      };
    }
  },
});

const readOnlyToolNames = new Set([
  'list_datasets',
  'get_dataset_status',
  'check_dataset_quality',
  'get_risk_overview',
]);

const copilot = new CopilotClient({ logLevel: 'warning' });
let copilotStarted = false;

async function ensureCopilotStarted() {
  if (!copilotStarted) {
    await copilot.start();
    copilotStarted = true;
  }
}

const app = express();
app.disable('x-powered-by');
app.use(cors({ origin: webOrigin }));
app.use(express.json({ limit: '64kb' }));

app.get('/api/health', async (_req, res) => {
  try {
    const [, mops] = await Promise.all([
      ensureCopilotStarted(),
      mopsBackendGet('/v1/datasets').then(() => 'ready').catch(() => 'offline'),
    ]);
    res.json({
      ok: true,
      copilot: 'ready',
      mops,
      // Remove after older clients stop reading this compatibility field.
      jellyguard: mops,
      datasets: Object.keys(datasets).length,
      credentials: credentialStatus,
    });
  } catch {
    res.status(503).json({
      ok: false,
      copilot: 'authentication_required',
      message: 'Copilot CLI 로그인 또는 COPILOT_GITHUB_TOKEN 설정이 필요합니다.',
      credentials: credentialStatus,
    });
  }
});

app.post('/api/copilot', async (req, res) => {
  const message = String(req.body?.message ?? '').trim();
  const language = req.body?.language === 'en' ? 'en' : 'ko';
  if (!message) {
    res.status(400).json({
      error: language === 'en' ? 'Please enter a question.' : '질문을 입력해 주세요.',
    });
    return;
  }

  try {
    await ensureCopilotStarted();
    const session = await copilot.createSession({
      sessionId: `mops-${crypto.randomUUID()}`,
      model: 'auto',
      tools: [listDatasets, getDatasetStatus, checkDatasetQuality, getRiskOverview],
      hooks: {
        onPreToolUse: async (input) => {
          if (readOnlyToolNames.has(input.toolName)) {
            return { permissionDecision: 'allow' as const };
          }
          return {
            permissionDecision: 'deny' as const,
            permissionDecisionReason: 'MOPS는 등록된 읽기 전용 데이터 도구만 허용합니다.',
          };
        },
      },
      systemMessage: {
        content: [
          language === 'en'
            ? 'You are the MOPS marine-organism path monitoring assistant for the Hanul public-data demo.'
            : '당신은 한울 공개데이터 데모를 설명하는 MOPS 해양생물 이동 감시 도우미입니다.',
          language === 'en'
            ? 'Answer only with information available through the registered data tools.'
            : '등록된 데이터 도구로 확인할 수 있는 내용만 답하세요.',
          language === 'en'
            ? 'Distinguish missing observations from confirmed absence and never guess values.'
            : '미관측과 미출현을 구분하고 값을 추측하지 마세요.',
          language === 'en'
            ? 'The tools are read-only. Never claim that you modified or deleted data.'
            : '현재 도구는 읽기 전용입니다. 수정이나 삭제를 했다고 말하지 마세요.',
          language === 'en'
            ? 'A direct observation may be historical CACHED data. Always state its observation date and that it is not real-time.'
            : '직접관측은 과거 CACHED 자료일 수 있습니다. 관측일과 실시간 자료가 아님을 항상 함께 밝히세요.',
          language === 'en'
            ? 'SYNTHETIC transport is a conditional scenario, not a forecast. Never turn M of N into probability, ETA, risk score, or plant-operation advice.'
            : 'SYNTHETIC 수송은 조건부 시나리오이며 실제 예보가 아닙니다. M of N을 확률·ETA·위험점수·원전 운전 권고로 바꾸지 마세요.',
          language === 'en'
            ? 'Reply in concise English, translate tool output naturally, and suggest one next action.'
            : '답변은 한국어로 간결하게 작성하고 다음 작업을 한 가지 제안하세요.',
        ].join('\n'),
      },
    });

    const result = await session.sendAndWait({ prompt: message });
    await session.disconnect();
    res.json({
      answer:
        result?.data.content ??
        (language === 'en' ? 'A response could not be generated.' : '응답을 생성하지 못했습니다.'),
    });
  } catch {
    res.status(503).json({
      error:
        language === 'en'
          ? 'Could not connect to Copilot.'
          : 'Copilot에 연결하지 못했습니다.',
      code: 'COPILOT_AUTH_REQUIRED',
    });
  }
});

app.listen(port, '127.0.0.1', () => {
  console.log(`Copilot API: http://localhost:${port}`);
});

async function shutdown() {
  if (copilotStarted) await copilot.stop();
  process.exit(0);
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
