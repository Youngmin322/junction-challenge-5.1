import logging

import uvicorn

from jellyguard.api import create_app


def main() -> None:
    # httpx INFO records contain the full request URL, including provider keys
    # passed as query parameters. Keep operational logs without credential URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
