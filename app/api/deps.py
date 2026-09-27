from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import UsuarioAutenticado, decodificar_token

esquema_bearer = HTTPBearer(auto_error=False)

Sesion = Annotated[AsyncSession, Depends(get_session)]


async def usuario_actual(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(esquema_bearer)],
) -> UsuarioAutenticado:
    if credenciales is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Se requiere autenticacion.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decodificar_token(credenciales.credentials)


Usuario = Annotated[UsuarioAutenticado, Depends(usuario_actual)]


def requiere_rol(*roles: str) -> Callable:
    permitidos = set(roles) | {"admin"}

    async def verificar(usuario: Usuario) -> UsuarioAutenticado:
        if usuario.rol not in permitidos:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"El rol '{usuario.rol}' no tiene acceso a este recurso.",
            )
        return usuario

    return verificar


UsuarioMesero = Annotated[UsuarioAutenticado, Depends(requiere_rol("mesero"))]
UsuarioCocina = Annotated[UsuarioAutenticado, Depends(requiere_rol("cocina"))]
UsuarioSalon = Annotated[UsuarioAutenticado, Depends(requiere_rol("mesero", "cocina"))]
UsuarioGestion = Annotated[UsuarioAutenticado, Depends(requiere_rol("inventario"))]
