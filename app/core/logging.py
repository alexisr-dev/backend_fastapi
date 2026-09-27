import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_ctx.get()
        return True


def configurar_logging(debug: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIDFilter())
    if debug:
        handler.setFormatter(
            logging.Formatter("[%(levelname)s] %(name)s (%(request_id)s): %(message)s")
        )
    else:
        handler.setFormatter(
            JsonFormatter("%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
