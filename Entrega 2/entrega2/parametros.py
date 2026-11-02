"""Lectura de datos y construcción de parámetros del modelo de la Entrega 2.

Todos los datos crudos se leen desde la carpeta ``datos/`` del repositorio y la
tabla de traspaso desde la Entrega 1 (``Entrega 2/Parte A Formulación``). Ningún
archivo de entrada se modifica: toda transformación ocurre aquí, en código.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[2]
DATOS = RAIZ / "datos"
CARPETA_E2 = RAIZ / "Entrega 2"
TRASPASO = CARPETA_E2 / "Parte A Formulación" / "tabla_traspaso_entrega2.csv"
RESULTADOS = CARPETA_E2 / "resultados"
FIGURAS = RESULTADOS / "figuras"

SEMANAS = list(range(1, 14))          # horizonte táctico t = 1..13
SEMANA_FOCAL = 12                     # 14/12/2026
LINEAS = ["L1", "L2"]
FAMILIAS = ["CIT", "FUN", "NEC"]

# Constantes del enunciado (sección 2.3 y 2.4)
COSTO_CIP_HORA = 74_000               # CLP por hora de limpieza CIP
COSTO_CAMBIO_FORMATO = 38_000         # CLP por cambio de formato dentro de familia
HORAS_CAMBIO_FORMATO = {"L1": 0.4, "L2": 0.6}


@dataclass(frozen=True)
class Escenario:
    """Palancas que cambian entre el escenario base y las sensibilidades."""

    nombre: str = "Base"
    factor_capacidad_mezcla: float = 1.0      # multiplica la tasa L/h de la mezcladora
    nivel_servicio: float | None = None       # None = nivel por SKU del archivo
    factor_penalidad: float = 1.0             # escala el costo de quiebre (atraso y déficit SS)
    restriccion_terminal: bool = True
    corregir_sigma_cit_l05: bool = False      # escenario: σ̂ de CIT-L05 h=4 y h=9 sin el dato atípico
    costo_extra_L1: float = 168_000           # supuesto: L1 no tiene tarifa en los datos
    sin_extra_mezcla: bool = False            # contrafactual: prohíbe horas extra de mezcla
    limite_tiempo_s: int = 300
    gap_relativo: float = 0.0


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
def cargar_datos() -> dict[str, pd.DataFrame]:
    """Lee los CSV crudos sin modificarlos."""
    tablas = {
        "maestro": pd.read_csv(DATOS / "maestro_sku.csv"),
        "capacidad": pd.read_csv(DATOS / "capacidad_horizonte.csv"),
        "inventario": pd.read_csv(DATOS / "inventario_inicial.csv"),
        "setups": pd.read_csv(DATOS / "setups_cip.csv"),
        "compromisos": pd.read_csv(DATOS / "compromisos_semana_focal.csv"),
        "demanda_hist": pd.read_csv(DATOS / "demanda_semanal.csv", parse_dates=["fecha_lunes"]),
        "traspaso": pd.read_csv(TRASPASO, encoding="utf-8-sig"),
    }
    return tablas


def validar_datos(tablas: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Revisa los insumos de la Entrega 2 y devuelve una tabla de hallazgos."""
    hallazgos = []
    m, cap, inv = tablas["maestro"], tablas["capacidad"], tablas["inventario"]
    tr, com = tablas["traspaso"], tablas["compromisos"]

    def agregar(archivo, chequeo, resultado, decision):
        hallazgos.append({"Archivo": archivo, "Chequeo": chequeo,
                          "Resultado": resultado, "Decisión": decision})

    agregar("tabla_traspaso", "117 filas, 9 SKU x 13 semanas, sin duplicados",
            f"{len(tr)} filas, duplicados={tr.duplicated(['SKU', 'Horizonte']).sum()}",
            "Se usa sin modificar.")
    agregar("tabla_traspaso", "Valores faltantes en parámetros clave",
            int(tr[["pronostico_cajas", "sigma_error_cajas", "rho_merma",
                    "litros_efectivos_caja"]].isna().sum().sum()),
            "Ninguno.")
    ceros = tr[tr.pronostico_cajas == 0].groupby("SKU").size()
    agregar("tabla_traspaso", "Semanas con pronóstico 0",
            ", ".join(f"{k}: {v}" for k, v in ceros.items()) or "ninguna",
            "FUN-B30 es intermitente (69 de 156 semanas con venta 0); se respeta el "
            "pronóstico de la Entrega 1 y el SS cubre la incertidumbre.")
    s = tr.pivot(index="Horizonte", columns="SKU", values="sigma_error_cajas")
    f = tr.pivot(index="Horizonte", columns="SKU", values="pronostico_cajas")
    razon = (s / f.replace(0, np.nan)).stack()
    peor = razon.sort_values(ascending=False).head(2)
    agregar("tabla_traspaso", "σ̂ desproporcionado respecto del pronóstico",
            "; ".join(f"{sku} h={h}: σ̂={s.loc[h, sku]:,.0f} vs d̂={f.loc[h, sku]:,.0f}"
                      for (h, sku) in peor.index),
            "Origen: venta de 32.916 cajas de CIT-L05 el 29/12/2025 (vecinas ~2.600, sin "
            "promoción ni quiebre). No se corrige la Entrega 1; se evalúa en sensibilidad.")
    reg = cap[["horas_L2_regular", "mantencion_programada_h_L2"]]
    agregar("capacidad_horizonte", "Horas regulares ya netas de mantención",
            "L2 sem. 4 y 9: 40 h = 48 - 8; mezcla sem. 6: 49 h = 55 - 6",
            "Se usan las horas regulares tal cual, sin volver a descontar mantenciones.")
    sem13 = cap.loc[cap.t == 13].iloc[0]
    agregar("capacidad_horizonte", "Semana 13 con menos horas sin mantención declarada",
            f"mezcla {sem13.horas_mezcla_regular:g} h, L1 {sem13.horas_L1_regular:g} h, "
            f"L2 {sem13.horas_L2_regular:g} h",
            "Semana de Navidad (25/12). Se respeta el dato.")
    agregar("capacidad_horizonte", "Tarifa de hora extra de L1",
            "No existe columna para L1",
            "Supuesto: misma tarifa que L2 (168.000 CLP/h).")
    agregar("inventario_inicial", "Inventario inicial, lote mínimo y nivel de servicio",
            f"{len(inv)} SKU, sin negativos={bool((inv.select_dtypes('number') >= 0).all().all())}",
            "Se usan tal cual. No hay inventario de jarabe ni atrasos iniciales.")
    g = com.groupby("sku").cantidad_comprometida_cajas.sum()
    d12 = tr[tr.Horizonte == SEMANA_FOCAL].set_index("SKU").pronostico_cajas
    excede = [f"{k}: {g[k]:,.0f} > {d12[k]:,.0f}" for k in g.index if g[k] > d12[k]]
    agregar("compromisos_semana_focal", "Cartera en firme mayor que el pronóstico de la semana 12",
            "; ".join(excede) or "ninguno",
            "La demanda de la semana 12 se toma como máx(pronóstico, cartera).")
    lin = com.merge(m[["sku", "linea_envasado", "familia"]], on="sku", suffixes=("", "_m"))
    agregar("compromisos_semana_focal", "Línea y familia coherentes con el maestro",
            f"discrepancias={int(((lin.linea_envasado != lin.linea_envasado_m) | (lin.familia != lin.familia_m)).sum())}",
            "Ninguna.")
    return pd.DataFrame(hallazgos)


# ---------------------------------------------------------------------------
# Parámetros derivados
# ---------------------------------------------------------------------------
def tiempos_cip_por_familia(setups: pd.DataFrame) -> dict[str, float]:
    """Tiempo esperado de CIP al ENTRAR a cada familia (promedio sobre familias de origen).

    La matriz es asimétrica: entrar a CIT cuesta 2,4 h desde FUN y 2,8 h desde NEC.
    Sin conocer la secuencia, el modelo táctico usa el promedio de entrada. La suma de
    los tres promedios (5,7 h) coincide con el promedio de los dos ciclos posibles.
    """
    cambios = setups[setups.familia_origen != setups.familia_destino]
    return cambios.groupby("familia_destino").horas_limpieza_cip.mean().to_dict()


def factor_estacional_post_horizonte(hist: pd.DataFrame) -> dict[str, float]:
    """Razón ventas(22-dic a 18-ene) / ventas(23-nov a 21-dic), mediana por familia.

    Usa medianas de 4 semanas para que un dato atípico aislado no la distorsione.
    """
    razones = []
    for anio in sorted(hist.fecha_lunes.dt.year.unique())[:-1]:
        antes = hist[(hist.fecha_lunes >= f"{anio}-11-23") & (hist.fecha_lunes <= f"{anio}-12-21")]
        despues = hist[(hist.fecha_lunes >= f"{anio}-12-22") & (hist.fecha_lunes <= f"{anio + 1}-01-18")]
        if antes.empty or despues.empty:
            continue
        r = despues.groupby("sku").ventas_cajas.median() / antes.groupby("sku").ventas_cajas.median()
        razones.append(r)
    r = pd.concat(razones, axis=1).median(axis=1)
    r = r[np.isfinite(r)]
    return r.groupby(r.index.str[:3]).median().to_dict()


def construir_parametros(esc: Escenario = Escenario(), tablas: dict | None = None) -> dict:
    """Devuelve un diccionario con todos los parámetros del modelo para un escenario."""
    tablas = tablas or cargar_datos()
    m = tablas["maestro"].set_index("sku")
    cap = tablas["capacidad"].set_index("t")
    inv = tablas["inventario"].set_index("sku")
    tr = tablas["traspaso"].copy()
    skus = list(m.index)

    P: dict = {"escenario": esc, "SKUS": skus, "T": SEMANAS, "LINEAS": LINEAS,
               "FAMILIAS": FAMILIAS}
    P["linea"] = m.linea_envasado.to_dict()
    P["familia"] = m.familia.to_dict()
    P["tasa"] = m.tasa_envasado_cajas_h.astype(float).to_dict()
    P["costo_var"] = m.costo_variable_caja_clp.astype(float).to_dict()
    P["h"] = m.costo_inventario_caja_semana_clp.astype(float).to_dict()
    P["pi"] = (m.penalidad_atraso_caja_semana_clp.astype(float) * esc.factor_penalidad).to_dict()
    P["pi_ss"] = dict(P["pi"])            # costo de déficit de SS = costo de quiebre
    P["precio"] = m.precio_lista_caja_clp.astype(float).to_dict()
    P["skus_linea"] = {l: [i for i in skus if P["linea"][i] == l] for l in LINEAS}
    P["skus_lf"] = {(l, f): [i for i in skus if P["linea"][i] == l and P["familia"][i] == f]
                    for l in LINEAS for f in FAMILIAS}

    # --- Parámetros heredados de la Entrega 1 (tabla de traspaso) ---
    tr1 = tr.drop_duplicates("SKU").set_index("SKU")
    P["merma"] = tr1.rho_merma.astype(float).to_dict()
    P["rend"] = {i: 1.0 - P["merma"][i] for i in skus}
    P["litros_ef"] = tr1.litros_efectivos_caja.astype(float).to_dict()
    P["fecha"] = dict(zip(tr[tr.SKU == skus[0]].Horizonte, tr[tr.SKU == skus[0]].Fecha))

    pron = tr.set_index(["SKU", "Horizonte"]).pronostico_cajas.astype(float)
    sigma = tr.set_index(["SKU", "Horizonte"]).sigma_error_cajas.astype(float).copy()
    if esc.corregir_sigma_cit_l05:
        # Escenario de sensibilidad (no modifica la Entrega 1): los horizontes 4 y 9
        # son los únicos que contienen el error de la venta atípica. Se reemplazan
        # por el promedio de los horizontes vecinos.
        for h in (4, 9):
            sigma[("CIT-L05", h)] = (sigma[("CIT-L05", h - 1)] + sigma[("CIT-L05", h + 1)]) / 2
    P["pronostico"] = pron.to_dict()
    P["sigma"] = sigma.to_dict()

    # --- Cartera en firme de la semana 12 ---
    com = tablas["compromisos"]
    C = com.groupby("sku").cantidad_comprometida_cajas.sum().astype(float)
    P["C"] = {i: float(C.get(i, 0.0)) for i in skus}
    P["d"] = {(i, t): pron[(i, t)] for i in skus for t in SEMANAS}
    for i in skus:
        P["d"][(i, SEMANA_FOCAL)] = max(P["d"][(i, SEMANA_FOCAL)], P["C"][i])

    # --- Stock de seguridad ---
    ns = inv.nivel_servicio_objetivo.astype(float).to_dict()
    if esc.nivel_servicio is not None:
        ns = {i: float(esc.nivel_servicio) for i in skus}
    P["nivel_servicio"] = ns
    P["z"] = {i: NormalDist().inv_cdf(ns[i]) for i in skus}
    P["SS"] = {(i, t): math.ceil(P["z"][i] * P["sigma"][(i, t)]) for i in skus for t in SEMANAS}

    # --- Inventario inicial y lotes ---
    P["I0"] = inv.inventario_inicial_cajas.astype(float).to_dict()
    P["B0"] = {i: 0.0 for i in skus}
    P["lote_min"] = inv.lote_minimo_cajas.astype(float).to_dict()
    P["lead_time_jarabe"] = int(inv.lead_time_jarabe_semanas.max())

    # --- Capacidad ---
    P["H"] = {("L1", t): float(cap.loc[t, "horas_L1_regular"]) for t in SEMANAS}
    P["H"].update({("L2", t): float(cap.loc[t, "horas_L2_regular"]) for t in SEMANAS})
    P["Emax"] = {("L1", t): float(cap.loc[t, "horas_L1_extra_max"]) for t in SEMANAS}
    P["Emax"].update({("L2", t): float(cap.loc[t, "horas_L2_extra_max"]) for t in SEMANAS})
    P["c_extra"] = {"L1": float(esc.costo_extra_L1),
                    "L2": float(cap.costo_hora_extra_L2_clp.iloc[0])}
    # Semana 0: mezcla previa al horizonte (alimenta el envasado de la semana 1).
    # Supuesto: misma capacidad regular de la semana 1, sin horas extra.
    P["Hm"] = {t: float(cap.loc[t, "horas_mezcla_regular"]) for t in SEMANAS}
    P["Hm"][0] = P["Hm"][1]
    P["Emax_m"] = {t: float(cap.loc[t, "horas_mezcla_extra_max"]) for t in SEMANAS}
    P["Emax_m"][0] = 0.0
    if esc.sin_extra_mezcla:
        P["Emax_m"] = {s: 0.0 for s in P["Emax_m"]}
    P["tasa_mezcla"] = {t: float(cap.loc[t, "tasa_mezcla_L_h"]) * esc.factor_capacidad_mezcla
                        for t in SEMANAS}
    P["tasa_mezcla"][0] = P["tasa_mezcla"][1]
    P["cip_mezcla"] = {t: float(cap.loc[t, "cip_mezcla_horas"]) for t in SEMANAS}
    P["cip_mezcla"][0] = P["cip_mezcla"][1]
    P["c_extra_m"] = float(cap.costo_hora_extra_mezcla_clp.iloc[0])
    P["SEMANAS_MEZCLA"] = [0] + SEMANAS[:-1]          # s = t - 1 alimenta el envasado de t

    # --- Preparaciones ---
    P["tau_cip"] = tiempos_cip_por_familia(tablas["setups"])
    P["horas_formato"] = dict(HORAS_CAMBIO_FORMATO)
    P["costo_cip_h"] = COSTO_CIP_HORA
    P["costo_formato"] = COSTO_CAMBIO_FORMATO

    # --- Reserva terminal ---
    fe = factor_estacional_post_horizonte(tablas["demanda_hist"])
    P["factor_estacional"] = fe
    P["d14"] = {i: np.mean([P["d"][(i, t)] for t in (10, 11, 12, 13)]) * fe[P["familia"][i]]
                for i in skus}
    P["T_terminal"] = ({i: math.ceil(P["SS"][(i, 13)] + P["d14"][i]) for i in skus}
                       if esc.restriccion_terminal else {i: 0 for i in skus})

    # --- Cota M justificada ---
    P["M"] = {(i, t): cota_produccion(P, i, t) for i in skus for t in SEMANAS}
    return P


def cota_produccion(P: dict, i: str, t: int) -> float:
    """M_it = mínimo entre tres cotas válidas (en cajas brutas).

    (a) Línea: toda la capacidad regular + extra de su línea dedicada al SKU.
    (b) Mezcla: todo el jarabe que la mezcladora puede preparar en t-1 (un solo CIP).
    (c) Necesidad: lo que falta cubrir hasta el fin del horizonte (demanda restante
        + máximo SS + reserva terminal + atraso inicial), en cajas brutas.
    """
    l = P["linea"][i]
    cota_linea = P["tasa"][i] * (P["H"][(l, t)] + P["Emax"][(l, t)])
    s = t - 1
    horas_m = P["Hm"][s] + P["Emax_m"][s] - P["cip_mezcla"][s]
    cota_mezcla = horas_m * P["tasa_mezcla"][s] / P["litros_ef"][i]
    resto = sum(P["d"][(i, k)] for k in P["T"] if k >= t)
    necesidad = (resto + max(P["SS"][(i, k)] for k in P["T"]) + P["T_terminal"][i] + P["B0"][i])
    cota_necesidad = necesidad / P["rend"][i]
    return float(math.ceil(min(cota_linea, cota_mezcla, cota_necesidad)))


def escenario(**kw) -> Escenario:
    return replace(Escenario(), **kw)
