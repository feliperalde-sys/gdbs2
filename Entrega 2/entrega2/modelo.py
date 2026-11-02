"""Modelo MIP de lot-sizing capacitado multiproducto (Entrega 2).

El modelo se construye por bloques. Cada bloque corresponde a uno de los ocho
elementos mínimos del enunciado (sección 7.1) y puede inspeccionarse por separado
en el notebook de la Parte A.

Unidades: x en cajas brutas (antes de merma); I, B, u en cajas vendibles;
V en litros de jarabe; E y Em en horas; costos en CLP.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pulp as pl

from .parametros import RESULTADOS, SEMANA_FOCAL


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
def crear_variables(P: dict) -> dict:
    S, T, L, F = P["SKUS"], P["T"], P["LINEAS"], P["FAMILIAS"]
    IT = [(i, t) for i in S for t in T]
    LFT = [(l, f, t) for l in L for f in F for t in T if P["skus_lf"][(l, f)]]
    FS = [(f, s) for f in F for s in P["SEMANAS_MEZCLA"]]
    v = {
        "x": pl.LpVariable.dicts("x", IT, lowBound=0),             # producción bruta
        "I": pl.LpVariable.dicts("I", IT, lowBound=0),             # inventario final
        "B": pl.LpVariable.dicts("B", IT, lowBound=0),             # atraso final
        "u": pl.LpVariable.dicts("u", IT, lowBound=0),             # déficit de SS
        "y": pl.LpVariable.dicts("y", IT, cat="Binary"),           # preparación SKU
        "w": pl.LpVariable.dicts("w", LFT, cat="Binary"),          # campaña de familia en línea
        "fc": pl.LpVariable.dicts("fc", [(f, t) for f in F for t in T], lowBound=0),  # cambios de formato L2
        "E": pl.LpVariable.dicts("E", [(l, t) for l in L for t in T], lowBound=0),     # horas extra línea
        "V": pl.LpVariable.dicts("V", FS, lowBound=0),             # litros de jarabe mezclados en s
        "z": pl.LpVariable.dicts("z", FS, cat="Binary"),           # familia activa en mezcladora en s
        "Em": pl.LpVariable.dicts("Em", P["SEMANAS_MEZCLA"], lowBound=0),  # horas extra mezcla
    }
    v["IT"], v["LFT"], v["FS"] = IT, LFT, FS
    return v


# ---------------------------------------------------------------------------
# Bloques de restricciones (elementos 1 a 8 del enunciado)
# ---------------------------------------------------------------------------
def r1_balance(m, P, v):
    """(1) Balance de inventario con backlogging y rendimiento (1 - merma)."""
    x, I, B = v["x"], v["I"], v["B"]
    for i in P["SKUS"]:
        for t in P["T"]:
            I_prev = P["I0"][i] if t == 1 else I[(i, t - 1)]
            B_prev = P["B0"][i] if t == 1 else B[(i, t - 1)]
            m += (I[(i, t)] - B[(i, t)] == I_prev - B_prev + P["rend"][i] * x[(i, t)] - P["d"][(i, t)],
                  f"balance_{i}_{t}")


def r2_preparacion(m, P, v):
    """(2) Enlace x <= M*y con M justificada, y SKU activo => campaña de su familia."""
    x, y, w = v["x"], v["y"], v["w"]
    for i in P["SKUS"]:
        l, f = P["linea"][i], P["familia"][i]
        for t in P["T"]:
            m += (x[(i, t)] <= P["M"][(i, t)] * y[(i, t)], f"enlace_{i}_{t}")
            m += (y[(i, t)] <= w[(l, f, t)], f"campana_{i}_{t}")
    for (l, f, t) in v["LFT"]:
        m += (w[(l, f, t)] <= pl.lpSum(y[(i, t)] for i in P["skus_lf"][(l, f)]), f"campana_util_{l}_{f}_{t}")


def r3_capacidad(m, P, v):
    """(3) Capacidad de envasado por línea y de mezcla en litros (con sobrellenado y CIP)."""
    x, w, fc, E = v["x"], v["w"], v["fc"], v["E"]
    V, z, Em = v["V"], v["z"], v["Em"]
    for f in P["FAMILIAS"]:
        skus_l2 = P["skus_lf"][("L2", f)]
        for t in P["T"]:
            # cambios de formato dentro de la familia en L2 = SKU activos - 1 (si la campaña existe)
            m += (fc[(f, t)] >= pl.lpSum(v["y"][(i, t)] for i in skus_l2) - w[("L2", f, t)],
                  f"formato_{f}_{t}")
    for l in P["LINEAS"]:
        for t in P["T"]:
            horas_prod = pl.lpSum(x[(i, t)] * (1.0 / P["tasa"][i]) for i in P["skus_linea"][l])
            horas_cip = pl.lpSum(P["tau_cip"][f] * w[(l, f, t)] for f in P["FAMILIAS"]
                                 if P["skus_lf"][(l, f)])
            horas_fmt = (pl.lpSum(P["horas_formato"]["L2"] * fc[(f, t)] for f in P["FAMILIAS"])
                         if l == "L2" else 0)
            m += (horas_prod + horas_cip + horas_fmt <= P["H"][(l, t)] + E[(l, t)], f"cap_{l}_{t}")
    # Mezcla: el jarabe mezclado en s = t-1 se envasa en t (lead time de 1 semana).
    for f in P["FAMILIAS"]:
        for t in P["T"]:
            litros = pl.lpSum(P["litros_ef"][i] * x[(i, t)] for i in P["SKUS"] if P["familia"][i] == f)
            m += (litros == V[(f, t - 1)], f"jarabe_{f}_{t}")
    for s in P["SEMANAS_MEZCLA"]:
        tasa = P["tasa_mezcla"][s]
        U = tasa * (P["Hm"][s] + P["Emax_m"][s])
        m += (pl.lpSum(V[(f, s)] for f in P["FAMILIAS"]) * (1.0 / tasa)
              + P["cip_mezcla"][s] * pl.lpSum(z[(f, s)] for f in P["FAMILIAS"])
              <= P["Hm"][s] + Em[s], f"cap_mezcla_{s}")
        for f in P["FAMILIAS"]:
            m += (V[(f, s)] <= U * z[(f, s)], f"activa_mezcla_{f}_{s}")


def r4_stock_seguridad(m, P, v):
    """(4) Meta de stock de seguridad SS_it = ceil(z_alpha * sigma_ih), con déficit penalizado.

    Se mide sobre el inventario neto (I - B): una caja atrasada no protege a nadie.
    """
    for (i, t) in v["IT"]:
        m += (v["I"][(i, t)] - v["B"][(i, t)] + v["u"][(i, t)] >= P["SS"][(i, t)], f"ss_{i}_{t}")


def r5_horas_extra(m, P, v):
    """(5) Horas extra como variables acotadas."""
    for l in P["LINEAS"]:
        for t in P["T"]:
            m += (v["E"][(l, t)] <= P["Emax"][(l, t)], f"extra_max_{l}_{t}")
    for s in P["SEMANAS_MEZCLA"]:
        m += (v["Em"][s] <= P["Emax_m"][s], f"extra_max_mezcla_{s}")


def r6_lote_minimo(m, P, v):
    """(6) Lote mínimo por SKU (el lead time de jarabe está en el bloque 3)."""
    for (i, t) in v["IT"]:
        m += (v["x"][(i, t)] >= P["lote_min"][i] * v["y"][(i, t)], f"lote_min_{i}_{t}")


def r7_terminal(m, P, v):
    """(7) Reserva terminal sobre inventario neto: I_i13 - B_i13 >= SS_i13 + demanda esperada sem. 14.

    Con T_i = 0 (escenario sin restricción terminal) la condición se reduce a no dejar
    atrasos sin atender al cierre del horizonte, salvo que se cubran con inventario.
    """
    T = P["T"][-1]
    for i in P["SKUS"]:
        if P["escenario"].restriccion_terminal:
            m += (v["I"][(i, T)] - v["B"][(i, T)] >= P["T_terminal"][i], f"terminal_{i}")


def r8_pedidos_firme(m, P, v):
    """(8) La producción vendible de la semana 12 cubre la cartera en firme."""
    for i in P["SKUS"]:
        if P["C"][i] > 0:
            m += (P["rend"][i] * v["x"][(i, SEMANA_FOCAL)] >= P["C"][i], f"firme_{i}")


BLOQUES = [r1_balance, r2_preparacion, r3_capacidad, r4_stock_seguridad,
           r5_horas_extra, r6_lote_minimo, r7_terminal, r8_pedidos_firme]


# ---------------------------------------------------------------------------
# Función objetivo
# ---------------------------------------------------------------------------
def expresiones_costo(P: dict, v: dict) -> dict:
    x, I, B, u, w, fc, E, z, Em = (v[k] for k in ("x", "I", "B", "u", "w", "fc", "E", "z", "Em"))
    return {
        "Producción (costo variable)": pl.lpSum(P["costo_var"][i] * x[(i, t)] for (i, t) in v["IT"]),
        "Inventario": pl.lpSum(P["h"][i] * I[(i, t)] for (i, t) in v["IT"]),
        "Atraso": pl.lpSum(P["pi"][i] * B[(i, t)] for (i, t) in v["IT"]),
        "Déficit de SS": pl.lpSum(P["pi_ss"][i] * u[(i, t)] for (i, t) in v["IT"]),
        "CIP envasado": pl.lpSum(P["costo_cip_h"] * P["tau_cip"][f] * w[(l, f, t)] for (l, f, t) in v["LFT"]),
        "Cambio de formato": pl.lpSum(P["costo_formato"] * fc[k] for k in fc),
        "CIP mezcla": pl.lpSum(P["costo_cip_h"] * P["cip_mezcla"][s] * z[(f, s)] for (f, s) in v["FS"]),
        "Horas extra envasado": pl.lpSum(P["c_extra"][l] * E[(l, t)] for (l, t) in E),
        "Horas extra mezcla": pl.lpSum(P["c_extra_m"] * Em[s] for s in Em),
    }


def construir_modelo(P: dict, bloques=None) -> tuple[pl.LpProblem, dict]:
    m = pl.LpProblem("LotSizing_BdM_E2", pl.LpMinimize)
    v = crear_variables(P)
    for bloque in (bloques or BLOQUES):
        bloque(m, P, v)
    v["costos"] = expresiones_costo(P, v)
    m.setObjective(pl.lpSum(v["costos"].values()))
    return m, v


# ---------------------------------------------------------------------------
# Resolución
# ---------------------------------------------------------------------------
def _leer_log_cbc(ruta: Path) -> dict:
    texto = ruta.read_text(errors="ignore") if ruta.exists() else ""
    out = {}
    r = re.search(r"Continuous objective value is ([\-\d\.e\+]+)", texto)
    out["relajacion_lineal"] = float(r.group(1)) if r else None
    r = re.search(r"Result - (.+)", texto)
    out["estado_cbc"] = r.group(1).strip() if r else None
    r = re.search(r"Lower bound:\s+([\-\d\.e\+]+)", texto)
    out["cota_cbc"] = float(r.group(1)) if r else None
    r = re.search(r"Enumerated nodes:\s+(\d+)", texto)
    out["nodos"] = int(r.group(1)) if r else None
    return out


def resolver(m: pl.LpProblem, P: dict, nombre_log: str = "cbc_base.log", msg: bool = False) -> dict:
    esc = P["escenario"]
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    ruta_log = RESULTADOS / "logs" / nombre_log
    ruta_log.parent.mkdir(exist_ok=True)
    solver = pl.PULP_CBC_CMD(msg=msg, timeLimit=esc.limite_tiempo_s, gapRel=esc.gap_relativo,
                             logPath=str(ruta_log), threads=1)
    t0 = time.perf_counter()
    m.solve(solver)
    seg = time.perf_counter() - t0
    info = _leer_log_cbc(ruta_log)
    obj = pl.value(m.objective)
    # CBC informa "Lower bound" al terminar (óptimo, por tolerancia o por tiempo).
    cota = info.get("cota_cbc")
    if cota is None:
        cota = info.get("relajacion_lineal")
    if cota is not None and obj is not None:
        cota = min(cota, obj)
    gap = (obj - cota) / abs(obj) if (obj and cota is not None) else None
    return {
        "escenario": esc.nombre, "estado": pl.LpStatus[m.status], "estado_cbc": info.get("estado_cbc"),
        "valor_objetivo": obj, "cota_inferior": cota, "brecha": gap,
        "relajacion_lineal": info.get("relajacion_lineal"), "nodos": info.get("nodos"),
        "tiempo_s": seg, "variables": len(m.variables()), "restricciones": len(m.constraints),
        "binarias": sum(1 for x in m.variables() if x.cat == pl.LpInteger),
        "brecha_abs_MM": (obj - cota) / 1e6 if (obj and cota is not None) else None,
        "solver": f"CBC (incluido en PuLP {pl.__version__})",
    }


def extraer_solucion(P: dict, v: dict) -> dict:
    """Pasa la solución a diccionarios de floats (misma estructura que las heurísticas)."""
    val = lambda d: {k: (d[k].value() or 0.0) for k in d}
    sol = {k: val(v[k]) for k in ("x", "I", "B", "u", "y", "w", "fc", "E", "V", "z", "Em")}
    sol["y"] = {k: round(a) for k, a in sol["y"].items()}
    sol["w"] = {k: round(a) for k, a in sol["w"].items()}
    sol["z"] = {k: round(a) for k, a in sol["z"].items()}
    return sol


def precios_sombra_mezcla(P: dict, sol: dict) -> dict:
    """Fija las binarias del óptimo, resuelve el LP y devuelve los duales de capacidad.

    El dual de cap_mezcla_s es el valor (CLP) de una hora adicional de mezcla en la
    semana s, dado el patrón de preparaciones óptimo.
    """
    m, v = construir_modelo(P)
    for nombre in ("y", "w", "z"):
        for k, var in v[nombre].items():
            var.cat = pl.LpContinuous
            var.lowBound = var.upBound = sol[nombre][k]
    m.solve(pl.PULP_CBC_CMD(msg=False))
    duales = {}
    for s in P["SEMANAS_MEZCLA"]:
        duales[("mezcla", s)] = -m.constraints[f"cap_mezcla_{s}"].pi
    for l in P["LINEAS"]:
        for t in P["T"]:
            duales[(l, t)] = -m.constraints[f"cap_{l}_{t}"].pi
    return {"duales": duales, "objetivo_lp": pl.value(m.objective), "estado": pl.LpStatus[m.status]}
