import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.logging import configurar_logging, request_id_ctx
from app.services.inventario_client import StockInsuficienteError
from app.services.pedido_service import RecursoNoEncontradoError, ReglaNegocioError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    configurar_logging(settings.debug)
    async with engine.connect() as conexion:
        await conexion.execute(text("SELECT 1"))
    logger.info("Conexion a PostgreSQL verificada: %s", settings.db_name)
    yield
    await engine.dispose()
    logger.info("Conexiones cerradas")


app = FastAPI(
    title="Restaurante — API operativa",
    description=(
        "Servicio de alta frecuencia: mesas, pedidos, tablero de cocina y eventos en tiempo real. "
        "El catalogo, el inventario y los reportes viven en backend_restaurante (Django)."
    ),
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlacionar_peticion(request: Request, call_next):
    identificador = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_ctx.set(identificador)
    respuesta = await call_next(request)
    respuesta.headers["X-Request-ID"] = identificador
    return respuesta


@app.exception_handler(ReglaNegocioError)
async def manejar_regla_negocio(request: Request, exc: ReglaNegocioError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": exc.mensaje, "code": exc.codigo},
    )


@app.exception_handler(RecursoNoEncontradoError)
async def manejar_no_encontrado(request: Request, exc: RecursoNoEncontradoError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc), "code": "no_encontrado"},
    )


@app.exception_handler(StockInsuficienteError)
async def manejar_stock(request: Request, exc: StockInsuficienteError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": str(exc),
            "code": "stock_insuficiente",
            "insumo": exc.insumo,
            "disponible": str(exc.disponible),
            "requerido": str(exc.requerido),
        },
    )


@app.get("/health", tags=["salud"])
async def salud():
    async with engine.connect() as conexion:
        await conexion.execute(text("SELECT 1"))
    return {"status": "ok", "service": settings.app_name}


app.include_router(api_router, prefix="/api/v1")
