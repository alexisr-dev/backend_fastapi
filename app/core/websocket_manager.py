import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)

CANAL_COCINA = "cocina"
CANAL_SALON = "salon"
CANALES = (CANAL_COCINA, CANAL_SALON)


class WebSocketManager:
    def __init__(self):
        self._conexiones: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def conectar(self, websocket: WebSocket, canal: str) -> None:
        await websocket.accept()
        async with self._lock:
            self._conexiones[canal].add(websocket)
        logger.info("Cliente conectado al canal %s (total %s)", canal, self.total(canal))

    async def desconectar(self, websocket: WebSocket, canal: str) -> None:
        async with self._lock:
            self._conexiones[canal].discard(websocket)
        logger.info("Cliente desconectado del canal %s (total %s)", canal, self.total(canal))

    def total(self, canal: str) -> int:
        return len(self._conexiones.get(canal, ()))

    async def emitir(self, canal: str, evento: dict) -> None:
        async with self._lock:
            destinatarios = list(self._conexiones.get(canal, ()))

        if not destinatarios:
            return

        caidos = []
        for conexion in destinatarios:
            try:
                await conexion.send_json(evento)
            except Exception:
                caidos.append(conexion)

        if caidos:
            async with self._lock:
                for conexion in caidos:
                    self._conexiones[canal].discard(conexion)

    async def difundir(self, evento: dict, canales: tuple[str, ...] = CANALES) -> None:
        for canal in canales:
            await self.emitir(canal, evento)


manager = WebSocketManager()
