"""
기존 3개 오픈API 수집기(collectors/)를 MCP 툴로 그대로 노출하는 서버.

collectors/ 안의 파이썬 코드는 손대지 않는다. 이 파일은 각 build_dataset()을
MCP tool 함수 하나로 감싸고, Streamable HTTP로 /mcp에 노출할 뿐이다.

노출 툴 3개
  get_ocean_current      해류데이터_통합.build_dataset()
  get_jellyfish_reports  해파리정보_수집.build_dataset()
  get_marine_environment 적조_정선해양_수집.build_dataset()

실행:
  python3 mcp_server.py

docs/04-copilot-studio-local-mcp-connection.md의 로컬 서버 전제(FastAPI, port 8000,
POST /mcp)와 맞추기 위해 host=0.0.0.0, port=8000, path=/mcp로 고정한다.
그 문서의 6개 도구(search_observations 등)는 이 저장소의 별도 domain 구현이 필요한
상위 설계이며, 이 서버는 그 설계와 무관하게 "기존 수집기를 MCP화"하는 요청만 처리한다.
"""

import importlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

ROOT = Path(__file__).resolve().parent
COLLECTORS_DIR = ROOT / "collectors"

# 루트 .env를 먼저 읽어 os.environ에 채운다.
# collectors/*.py의 load_env()는 os.environ.setdefault를 쓰므로,
# 여기서 먼저 채워두면 "collectors/.env만 읽는" 원래 버그를 건드리지 않고도
# 루트 .env 값이 우선 적용된다.
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(COLLECTORS_DIR))

MCP_CLIENT_KEY = os.environ.get("JELLYGUARD_MCP_CLIENT_KEY")

mcp = MCPServer(
    name="Hanul Jellyfish Data Collectors",
    description="한울 프로젝트의 기존 오픈API 수집기(해류/해파리/적조·정선해양)를 그대로 호출하는 MCP 도구 모음",
)


def _import_collector(module_name):
    """collectors/ 안의 모듈을 지연 임포트한다.

    해류데이터_통합.py는 KHOA_SERVICE_KEY가 없으면 import 시점에 SystemExit을
    던지므로, 서버 기동 자체가 죽지 않도록 도구 호출 시점에만 임포트한다.
    """
    return importlib.import_module(module_name)


@mcp.tool()
def get_ocean_current(
    date: str | None = None,
    hours: int = 24,
    tolerance_min: int = 60,
    include_series: bool = True,
    include_extra: bool = True,
) -> dict:
    """전국 해역 해양관측부이(twRecent)+HF-RADAR(hfCurrent) 통합 해류 데이터를 반환한다.

    date: 'YYYYMMDD' 특정 날짜 하루치. 미지정 시 최근 hours시간.
    include_series=False로 부이 원해상도 시계열을 빼면 응답 크기가 줄어든다.
    KHOA_SERVICE_KEY가 없으면 계산 대신 오류 dict를 반환한다.
    """
    try:
        mod = _import_collector("해류데이터_통합")
        return mod.build_dataset(
            date=date,
            hours=hours,
            tolerance_min=tolerance_min,
            include_series=include_series,
            include_extra=include_extra,
            verbose=False,
        )
    except SystemExit as exc:
        return {"error": "KHOA_SERVICE_KEY_MISSING", "detail": str(exc)}


@mcp.tool()
def get_jellyfish_reports(
    sdate: str | None = None,
    edate: str | None = None,
    days: int = 30,
) -> dict:
    """NIFS 해파리 주간보고 게시물 목록을 반환한다.

    관측 수치가 아니라 게시물 목록이다 (board_idx, board_subject, inpt_date 등).
    sdate/edate 'YYYYMMDD'. 미지정 시 최근 days일.
    NIFS_JELLY_KEY가 없으면 오류 dict를 반환한다.
    """
    try:
        mod = _import_collector("해파리정보_수집")
        return mod.build_dataset(sdate=sdate, edate=edate, days=days, verbose=False)
    except SystemExit as exc:
        # build_dataset()이 키 없을 때 SystemExit을 던진다. 이 예외는
        # BaseException이라 잡지 않으면 MCP 서버 프로세스 전체가 죽는다.
        return {"error": "NIFS_JELLY_KEY_MISSING", "detail": str(exc)}


@mcp.tool()
def get_marine_environment(
    sdate: str | None = None,
    edate: str | None = None,
    redtide_days: int = 30,
    soo_days: int = 365,
) -> dict:
    """적조정보(redtideList)+정선해양관측정보(sooList)를 하나의 dict로 반환한다.

    두 데이터셋을 연산 없이 나란히 담기만 한다.
    sdate/edate를 주면 두 데이터셋에 같은 기간을 적용하고,
    미지정 시 적조는 최근 redtide_days일, 정선해양은 최근 soo_days일을 각각 적용한다.
    NIFS_REDTIDE_KEY / NIFS_SOO_KEY가 없으면 meta.warnings에 사유가 남는다.
    """
    try:
        mod = _import_collector("적조_정선해양_수집")
        return mod.build_dataset(
            sdate=sdate,
            edate=edate,
            redtide_days=redtide_days,
            soo_days=soo_days,
            verbose=False,
        )
    except SystemExit as exc:
        return {"error": "NIFS_KEY_MISSING", "detail": str(exc)}


class ClientKeyMiddleware(BaseHTTPMiddleware):
    """MCP client key 인증. JELLYGUARD_MCP_CLIENT_KEY 미설정 시 인증을 건너뛴다(로컬 개발용)."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if MCP_CLIENT_KEY:
            supplied = request.headers.get("x-mcp-client-key")
            if supplied != MCP_CLIENT_KEY:
                return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)
        return await call_next(request)


def build_app():
    app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True)
    app.add_middleware(ClientKeyMiddleware)

    async def health(request: Request):
        return PlainTextResponse("ok")

    app.router.routes.insert(0, __import__("starlette.routing", fromlist=["Route"]).Route("/health", health))
    return app


if __name__ == "__main__":
    if not MCP_CLIENT_KEY:
        print(
            "경고: JELLYGUARD_MCP_CLIENT_KEY가 없다. /mcp가 인증 없이 열려 있다. "
            "Dev Tunnel로 외부에 노출하기 전에 .env에 값을 설정할 것.",
            file=sys.stderr,
        )

    import uvicorn

    uvicorn.run(build_app(), host="0.0.0.0", port=8000)
