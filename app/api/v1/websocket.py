import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.security import decodificar_token
from app.core.websocket_manager import CANALES, manager
from app.schemas.ws_events import TipoEvento, evento

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{canal}")
async def canal_tiempo_real(websocket: WebSocket, canal: str, token: str = Query(...)):
    if canal not in CANALES:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Canal desconocido")
        return

    try:
        usuario = decodificar_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Token invalido")
        return

    await manager.conectar(websocket, canal)
    await websocket.send_json(
        evento(TipoEvento.CONEXION, canal=canal, usuario=usuario.nombre, rol=usuario.rol)
    )

    try:
        while True:
            mensaje = await websocket.receive_text()
            if mensaje == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Error en el canal %s", canal)
    finally:
        await manager.desconectar(websocket, canal)
