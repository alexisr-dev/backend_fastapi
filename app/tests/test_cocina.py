import uuid
from decimal import Decimal

from app.models import Insumo, Mesa


async def crear_pedido(cliente, datos, cabeceras, cantidad=1):
    respuesta = await cliente.post(
        "/api/v1/pedidos",
        json={
            "mesa_id": datos["mesa"].id,
            "idempotency_key": str(uuid.uuid4()),
            "lineas": [{"producto_id": datos["plato"].id, "cantidad": cantidad}],
        },
        headers=cabeceras,
    )
    assert respuesta.status_code == 201
    return respuesta.json()


async def test_el_tablero_agrupa_los_pedidos_por_estado(
    cliente, datos, cabeceras_mesero, cabeceras_cocina
):
    await crear_pedido(cliente, datos, cabeceras_mesero)

    respuesta = await cliente.get("/api/v1/cocina/tablero", headers=cabeceras_cocina)
    assert respuesta.status_code == 200
    tablero = respuesta.json()
    assert set(tablero) == {"pendiente", "preparando", "listo"}
    assert len(tablero["pendiente"]) >= 1


async def test_flujo_completo_de_estados(cliente, datos, cabeceras_mesero, cabeceras_cocina):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero)
    pedido_id = pedido["id"]

    preparando = await cliente.post(
        f"/api/v1/cocina/pedidos/{pedido_id}/preparar", headers=cabeceras_cocina
    )
    assert preparando.json()["estado"] == "preparando"

    listo = await cliente.post(
        f"/api/v1/cocina/pedidos/{pedido_id}/listo", headers=cabeceras_cocina
    )
    assert listo.json()["estado"] == "listo"

    entregado = await cliente.patch(
        f"/api/v1/pedidos/{pedido_id}/estado",
        json={"estado": "entregado"},
        headers=cabeceras_mesero,
    )
    assert entregado.json()["estado"] == "entregado"


async def test_una_transicion_invalida_se_rechaza(cliente, datos, cabeceras_mesero):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero)

    respuesta = await cliente.patch(
        f"/api/v1/pedidos/{pedido['id']}/estado",
        json={"estado": "entregado"},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["code"] == "transicion_invalida"


async def test_un_pedido_entregado_es_terminal(cliente, datos, cabeceras_mesero, cabeceras_cocina):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero)
    pedido_id = pedido["id"]

    await cliente.post(f"/api/v1/cocina/pedidos/{pedido_id}/preparar", headers=cabeceras_cocina)
    await cliente.post(f"/api/v1/cocina/pedidos/{pedido_id}/listo", headers=cabeceras_cocina)
    await cliente.patch(
        f"/api/v1/pedidos/{pedido_id}/estado",
        json={"estado": "entregado"},
        headers=cabeceras_mesero,
    )

    respuesta = await cliente.patch(
        f"/api/v1/pedidos/{pedido_id}/estado",
        json={"estado": "preparando"},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 400


async def test_entregar_no_libera_la_mesa(
    cliente, sesion, datos, cabeceras_mesero, cabeceras_cocina
):
    """Entregar la comida no vacia la mesa: los comensales siguen ahi y sin pagar.
    La mesa se libera despues, al cobrar (ver test_pagos)."""
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero)
    pedido_id = pedido["id"]

    await cliente.post(f"/api/v1/cocina/pedidos/{pedido_id}/preparar", headers=cabeceras_cocina)
    await cliente.post(f"/api/v1/cocina/pedidos/{pedido_id}/listo", headers=cabeceras_cocina)
    await cliente.patch(
        f"/api/v1/pedidos/{pedido_id}/estado",
        json={"estado": "entregado"},
        headers=cabeceras_mesero,
    )

    mesa = await sesion.get(Mesa, datos["mesa"].id)
    await sesion.refresh(mesa)
    assert mesa.estado == "ocupada"


async def test_cancelar_el_unico_pedido_libera_la_mesa(
    cliente, sesion, datos, cabeceras_mesero
):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero)

    await cliente.patch(
        f"/api/v1/pedidos/{pedido['id']}/estado",
        json={"estado": "cancelado"},
        headers=cabeceras_mesero,
    )

    mesa = await sesion.get(Mesa, datos["mesa"].id)
    await sesion.refresh(mesa)
    assert mesa.estado == "libre"


async def test_cancelar_repone_el_inventario(cliente, sesion, datos, cabeceras_mesero):
    stock_previo = datos["insumo_a"].stock_actual
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero, cantidad=2)

    insumo = await sesion.get(Insumo, datos["insumo_a"].id)
    await sesion.refresh(insumo)
    assert insumo.stock_actual == stock_previo - Decimal("1.000")

    respuesta = await cliente.patch(
        f"/api/v1/pedidos/{pedido['id']}/estado",
        json={"estado": "cancelado"},
        headers=cabeceras_mesero,
    )
    assert respuesta.json()["estado"] == "cancelado"

    await sesion.refresh(insumo)
    assert insumo.stock_actual == stock_previo


async def test_las_metricas_de_cocina_responden(cliente, datos, cabeceras_cocina):
    respuesta = await cliente.get("/api/v1/cocina/metricas", headers=cabeceras_cocina)
    assert respuesta.status_code == 200
    for campo in ("pendientes", "preparando", "listos", "items_pendientes"):
        assert campo in respuesta.json()


async def test_una_linea_en_preparacion_promueve_el_pedido(cliente, datos, cabeceras_cocina, cabeceras_mesero):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero)
    linea_id = pedido["lineas"][0]["id"]

    respuesta = await cliente.patch(
        f"/api/v1/pedidos/{pedido['id']}/lineas/{linea_id}",
        json={"estado": "preparando"},
        headers=cabeceras_cocina,
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "preparando"


async def test_la_mesa_no_se_libera_con_pedidos_abiertos(cliente, datos, cabeceras_mesero, cabeceras_admin):
    await crear_pedido(cliente, datos, cabeceras_mesero)

    respuesta = await cliente.patch(
        f"/api/v1/mesas/{datos['mesa'].id}",
        json={"estado": "libre"},
        headers=cabeceras_admin,
    )
    assert respuesta.status_code == 409
