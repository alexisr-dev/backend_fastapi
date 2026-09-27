import asyncio
import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.models import Insumo, Pedido


def carga(datos, clave=None, cantidad=1):
    return {
        "mesa_id": datos["mesa"].id,
        "idempotency_key": str(clave or uuid.uuid4()),
        "lineas": [{"producto_id": datos["plato"].id, "cantidad": cantidad}],
    }


async def test_reenviar_la_misma_clave_no_duplica_el_pedido(
    cliente, sesion, datos, cabeceras_mesero
):
    cuerpo = carga(datos)

    primera = await cliente.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras_mesero)
    segunda = await cliente.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras_mesero)

    assert primera.status_code == 201
    assert segunda.status_code == 200
    assert primera.json()["id"] == segunda.json()["id"]

    total = await sesion.execute(
        select(func.count()).select_from(Pedido).where(Pedido.mesa_id == datos["mesa"].id)
    )
    assert total.scalar_one() == 1


async def test_el_reenvio_no_vuelve_a_descontar_stock(cliente, sesion, datos, cabeceras_mesero):
    cuerpo = carga(datos, cantidad=2)
    stock_previo = datos["insumo_a"].stock_actual

    await cliente.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras_mesero)
    await cliente.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras_mesero)
    await cliente.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras_mesero)

    insumo = await sesion.get(Insumo, datos["insumo_a"].id)
    await sesion.refresh(insumo)
    assert insumo.stock_actual == stock_previo - Decimal("1.000")


async def test_claves_distintas_crean_pedidos_distintos(cliente, sesion, datos, cabeceras_mesero):
    primera = await cliente.post("/api/v1/pedidos", json=carga(datos), headers=cabeceras_mesero)
    segunda = await cliente.post("/api/v1/pedidos", json=carga(datos), headers=cabeceras_mesero)

    assert primera.status_code == 201
    assert segunda.status_code == 201
    assert primera.json()["id"] != segunda.json()["id"]

    total = await sesion.execute(
        select(func.count()).select_from(Pedido).where(Pedido.mesa_id == datos["mesa"].id)
    )
    assert total.scalar_one() == 2


async def test_doble_clic_simultaneo_crea_un_solo_pedido(cliente, sesion, datos, cabeceras_mesero):
    cuerpo = carga(datos)

    respuestas = await asyncio.gather(
        cliente.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras_mesero),
        cliente.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras_mesero),
    )

    assert {r.status_code for r in respuestas} <= {200, 201}
    assert len({r.json()["id"] for r in respuestas}) == 1

    total = await sesion.execute(
        select(func.count()).select_from(Pedido).where(Pedido.mesa_id == datos["mesa"].id)
    )
    assert total.scalar_one() == 1


async def test_una_clave_mal_formada_es_rechazada(cliente, datos, cabeceras_mesero):
    respuesta = await cliente.post(
        "/api/v1/pedidos",
        json={
            "mesa_id": datos["mesa"].id,
            "idempotency_key": "no-es-un-uuid",
            "lineas": [{"producto_id": datos["plato"].id, "cantidad": 1}],
        },
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 422
