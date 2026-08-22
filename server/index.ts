import 'dotenv/config';
import crypto from 'node:crypto';
import cors from 'cors';
import express from 'express';
import { CopilotClient, defineTool } from '@github/copilot-sdk';

const port = Number(process.env.COPILOT_API_PORT ?? 3001);
const webOrigin = process.env.WEB_ORIGIN ?? 'http://localhost:3000';
const credentialStatus = Object.freeze({
  copilotTokenConfigured: Boolean(process.env.COPILOT_GITHUB_TOKEN?.trim()),
  nifsApiKeyConfigured: Boolean(process.env.NIFS_API_KEY?.trim()),
  dataGoKrServiceKeyConfigured: Boolean(process.env.DATA_GO_KR_SERVICE_KEY?.trim()),
});

const datasets = {
  jellyfish: {
    label: '해파리 출현',
    source: '국립수산과학원 해파리정보',
    cadence: '주간',
    status: 'API 연결 전',
    checks: ['출현 위치 표준화', '종명 확인', '미관측과 미출현 구분'],
  },
  water_temperature: {
    label: '수온',
    source: '국립수산과학원 KODC',
    cadence: '관측 주기별',
    status: 'API 연결 전',
    checks: ['섭씨 단위 확인', '표층·저층 분리', 'QC 플래그 확인'],
  },
  dissolved_oxygen: {
    label: '용존산소',
    source: '국립수산과학원 KODC',
    cadence: '관측 주기별',
    status: 'API 연결 전',
    checks: ['단위 확인', '관측 수심 확인', 'QC 플래그 확인'],
  },
  plankton: {
    label: '플랑크톤',
    source: '국가해양생태계종합조사',
    cadence: '조사 주기별',
    status: 'API 연결 전',
    checks: ['동물·식물플랑크톤 분리', '개체수 단위 확인', '채집 정점 확인'],
  },
} as const;

type DatasetName = keyof typeof datasets;

const listDatasets = defineTool('list_datasets', {
  description: '서비스가 관리하는 해파리 관련 데이터셋 목록과 현재 상태를 조회한다.',
  parameters: { type: 'object', properties: {} },
  handler: async () =>
    Object.entries(datasets).map(([id, dataset]) => ({ id, ...dataset })),
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
  handler: async ({ datasetName }: { datasetName: DatasetName }) => ({
    id: datasetName,
    ...datasets[datasetName],
  }),
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
    const dataset = datasets[datasetName];
    return {
      dataset: dataset.label,
      ready: false,
      reason: '원본 API 키와 실제 데이터가 아직 연결되지 않았습니다.',
      requiredChecks: dataset.checks,
      nextAction: `${dataset.source} API 키와 수집 함수를 연결하세요.`,
    };
  },
});

const readOnlyToolNames = new Set([
  'list_datasets',
  'get_dataset_status',
  'check_dataset_quality',
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
    await ensureCopilotStarted();
    res.json({
      ok: true,
      copilot: 'ready',
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
      sessionId: `jellywatch-${crypto.randomUUID()}`,
      model: 'auto',
      tools: [listDatasets, getDatasetStatus, checkDatasetQuality],
      hooks: {
        onPreToolUse: async (input) => {
          if (readOnlyToolNames.has(input.toolName)) {
            return { permissionDecision: 'allow' as const };
          }
          return {
            permissionDecision: 'deny' as const,
            permissionDecisionReason: 'Jellywatch는 등록된 읽기 전용 데이터 도구만 허용합니다.',
          };
        },
      },
      systemMessage: {
        content: [
          language === 'en'
            ? 'You are a jellyfish research data manager for the Gyeongbuk East Sea coast.'
            : '당신은 경상북도 동해안 해파리 연구 데이터 관리자입니다.',
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
