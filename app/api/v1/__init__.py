from fastapi import APIRouter

from . import cocina, mesas, pedidos, websocket

api_router = APIRouter()
api_router.include_router(mesas.router)
api_router.include_router(pedidos.router)
api_router.include_router(cocina.router)
api_router.include_router(websocket.router)
