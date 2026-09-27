from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import HTTPException, status

from .config import settings

ROLES_VALIDOS = {"mesero", "cocina", "admin", "inventario"}


@dataclass(frozen=True)
class UsuarioAutenticado:
    id: UUID
    rol: str
    nombre: str
    email: str

    @property
    def es_admin(self) -> bool:
        return self.rol == "admin"


def decodificar_token(token: str) -> UsuarioAutenticado:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "El token ha expirado.")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido.")

    if payload.get("token_type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Se requiere un token de acceso.")

    user_id = payload.get("user_id")
    rol = payload.get("rol")
    if not user_id or rol not in ROLES_VALIDOS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "El token no contiene un usuario valido.")

    try:
        identificador = UUID(str(user_id))
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "El identificador del token es invalido.")

    return UsuarioAutenticado(
        id=identificador,
        rol=rol,
        nombre=payload.get("nombre", ""),
        email=payload.get("email", ""),
    )
