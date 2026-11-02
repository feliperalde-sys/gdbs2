"""Políticas de referencia (benchmark) para interpretar el resultado del MIP.

Ambas políticas deciden SKU por SKU sin optimizar en conjunto. Luego un simulador
común aplica las mismas restricciones físicas del MIP (capacidad de líneas y de
mezcla con lead time de una semana, horas extra hasta su máximo, lote mínimo y cartera
en firme). Si un plan excede la capacidad, se recorta proporcionalmente y lo no
producido se arrastra como requerimiento a la semana siguiente.
"""

from __future__ import annotations

import math

from .parametros import SEMANA_FOCAL


def _meta_neta(P, i, t):
    """Inventario neto deseado al cierre de t (SS; en t=13 también la reserva terminal)."""
    meta = P["SS"][(i, t)]
    if t == P["T"][-1]:
        meta = max(meta, P["T_terminal"][i])
    return meta


def lote_por_lote(P):
    """Lote por lote con stock de seguridad: cada semana produce lo justo para cerrar en SS."""
    def politica(t, estado, arrastre):
        plan = {}
        for i in P["SKUS"]:
            neto = estado["I"][i] - estado["B"][i]
            falta = P["d"][(i, t)] + _meta_neta(P, i, t) - neto
            plan[i] = max(0.0, falta) / P["rend"][i]
        return plan
    return politica


def costo_preparacion_sku(P, i):
    l, f = P["linea"][i], P["familia"][i]
    return P["costo_cip_h"] * P["tau_cip"][f] + (P["costo_formato"] if l == "L2" else 0.0)


def silver_meal(P):
    """Silver-Meal por SKU sobre requerimientos netos (incluye SS y reserva terminal)."""
    T = P["T"]
    plan = {}
    for i in P["SKUS"]:
        cubierto, neto = 0.0, {}
        acumulado = 0.0
        for t in T:
            acumulado += P["d"][(i, t)]
            req = acumulado + _meta_neta(P, i, t) - P["I0"][i]
            neto[t] = max(0.0, req - cubierto)
            cubierto += neto[t]
        K, h = costo_preparacion_sku(P, i), P["h"][i]
        t = T[0]
        lotes = {k: 0.0 for k in T}
        while t <= T[-1]:
            if neto[t] <= 0:
                t += 1
                continue
            mejor_k, mejor_prom, costo_h = t, K, 0.0
            for k in range(t + 1, T[-1] + 1):
                costo_h += h * neto[k] * (k - t)
                prom = (K + costo_h) / (k - t + 1)
                if prom > mejor_prom:
                    break
                mejor_k, mejor_prom = k, prom
            lotes[t] = sum(neto[k] for k in range(t, mejor_k + 1)) / P["rend"][i]
            t = mejor_k + 1
        plan[i] = lotes

    def politica(t, estado, arrastre):
        return {i: plan[i][t] + arrastre[i] for i in P["SKUS"]}
    return politica


def simular(P, politica):
    """Ejecuta una política semana a semana respetando la capacidad física."""
    S, F = P["SKUS"], P["FAMILIAS"]
    estado = {"I": dict(P["I0"]), "B": dict(P["B0"])}
    arrastre = {i: 0.0 for i in S}
    sol = {k: {} for k in ("x", "I", "B", "u", "y", "w", "fc", "E", "V", "z", "Em")}
    recortes = 0
    for t in P["T"]:
        deseado = politica(t, estado, arrastre)
        x = {}
        for i in S:
            q = deseado[i]
            if t == SEMANA_FOCAL:
                q = max(q, P["C"][i] / P["rend"][i])
            if 0 < q < P["lote_min"][i]:
                q = P["lote_min"][i]
            x[i] = q if q > 1e-6 else 0.0
        objetivo = dict(x)

        # Mezcla en s = t-1 (lead time de una semana).
        s = t - 1
        fams = [f for f in F if any(x[i] > 0 for i in S if P["familia"][i] == f)]
        litros = sum(P["litros_ef"][i] * x[i] for i in S)
        cip = P["cip_mezcla"][s] * len(fams)
        cap_m = P["Hm"][s] + P["Emax_m"][s]
        horas_m = litros / P["tasa_mezcla"][s] + cip
        if horas_m > cap_m + 1e-9:
            factor = max(0.0, (cap_m - cip) * P["tasa_mezcla"][s] / litros)
            x = {i: q * factor for i, q in x.items()}
            recortes += 1

        # Líneas de envasado.
        for l in P["LINEAS"]:
            skus = P["skus_linea"][l]
            prep = sum(P["tau_cip"][f] for f in F if any(x[i] > 0 for i in P["skus_lf"][(l, f)]))
            if l == "L2":
                prep += sum(P["horas_formato"]["L2"] * max(0, sum(1 for i in P["skus_lf"][(l, f)] if x[i] > 0) - 1)
                            for f in F)
            prod = sum(x[i] / P["tasa"][i] for i in skus)
            cap = P["H"][(l, t)] + P["Emax"][(l, t)]
            if prod + prep > cap + 1e-9:
                factor = max(0.0, (cap - prep) / prod)
                for i in skus:
                    x[i] *= factor
                recortes += 1

        # Registrar decisiones y costos asociados.
        for f in F:
            activos = [i for i in S if P["familia"][i] == f and x[i] > 1e-6]
            sol["V"][(f, s)] = sum(P["litros_ef"][i] * x[i] for i in activos)
            sol["z"][(f, s)] = 1 if activos else 0
            for l in P["LINEAS"]:
                if P["skus_lf"][(l, f)]:
                    sol["w"][(l, f, t)] = 1 if any(x[i] > 1e-6 for i in P["skus_lf"][(l, f)]) else 0
            sol["fc"][(f, t)] = max(0, sum(1 for i in P["skus_lf"][("L2", f)] if x[i] > 1e-6) - 1)
        horas_m = sum(sol["V"][(f, s)] for f in F) / P["tasa_mezcla"][s] + P["cip_mezcla"][s] * sum(
            sol["z"][(f, s)] for f in F)
        sol["Em"][s] = max(0.0, horas_m - P["Hm"][s])
        for l in P["LINEAS"]:
            prep = sum(P["tau_cip"][f] * sol["w"].get((l, f, t), 0) for f in F)
            if l == "L2":
                prep += sum(P["horas_formato"]["L2"] * sol["fc"][(f, t)] for f in F)
            horas = sum(x[i] / P["tasa"][i] for i in P["skus_linea"][l]) + prep
            sol["E"][(l, t)] = max(0.0, horas - P["H"][(l, t)])
        for i in S:
            sol["x"][(i, t)] = x[i]
            sol["y"][(i, t)] = 1 if x[i] > 1e-6 else 0
            arrastre[i] = max(0.0, objetivo[i] - x[i])
            neto = estado["I"][i] - estado["B"][i] + P["rend"][i] * x[i] - P["d"][(i, t)]
            estado["I"][i], estado["B"][i] = max(neto, 0.0), max(-neto, 0.0)
            sol["I"][(i, t)], sol["B"][(i, t)] = estado["I"][i], estado["B"][i]
            sol["u"][(i, t)] = max(0.0, P["SS"][(i, t)] - neto)
    # La mezcla de la semana 13 no alimenta el horizonte.
    sol["recortes_capacidad"] = recortes
    return sol
