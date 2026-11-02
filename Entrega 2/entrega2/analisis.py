"""Costos, indicadores del cuadro de mando y tablas de resultados.

``costos`` replica término a término la función objetivo del MIP, de modo que el
MIP y las heurísticas se evalúan con exactamente la misma regla.
"""

from __future__ import annotations

import pandas as pd

from .parametros import SEMANA_FOCAL

NOMBRES_COSTO = ["Producción (costo variable)", "Inventario", "Atraso", "Déficit de SS",
                 "CIP envasado", "Cambio de formato", "CIP mezcla",
                 "Horas extra envasado", "Horas extra mezcla"]


def costos(P: dict, sol: dict) -> dict:
    IT = [(i, t) for i in P["SKUS"] for t in P["T"]]
    c = {
        "Producción (costo variable)": sum(P["costo_var"][i] * sol["x"][(i, t)] for (i, t) in IT),
        "Inventario": sum(P["h"][i] * sol["I"][(i, t)] for (i, t) in IT),
        "Atraso": sum(P["pi"][i] * sol["B"][(i, t)] for (i, t) in IT),
        "Déficit de SS": sum(P["pi_ss"][i] * sol["u"][(i, t)] for (i, t) in IT),
        "CIP envasado": sum(P["costo_cip_h"] * P["tau_cip"][f] * a for (l, f, t), a in sol["w"].items()),
        "Cambio de formato": sum(P["costo_formato"] * a for a in sol["fc"].values()),
        "CIP mezcla": sum(P["costo_cip_h"] * P["cip_mezcla"][s] * a for (f, s), a in sol["z"].items()),
        "Horas extra envasado": sum(P["c_extra"][l] * a for (l, t), a in sol["E"].items()),
        "Horas extra mezcla": sum(P["c_extra_m"] * a for a in sol["Em"].values()),
    }
    c["Total"] = sum(c[k] for k in NOMBRES_COSTO)
    return c


def horas_por_recurso(P: dict, sol: dict) -> pd.DataFrame:
    """Horas usadas (producción + preparación) por recurso y semana de ejecución."""
    filas = []
    for t in P["T"]:
        for l in P["LINEAS"]:
            prod = sum(sol["x"][(i, t)] / P["tasa"][i] for i in P["skus_linea"][l])
            prep = sum(P["tau_cip"][f] * sol["w"].get((l, f, t), 0) for f in P["FAMILIAS"])
            if l == "L2":
                prep += sum(P["horas_formato"]["L2"] * sol["fc"][(f, t)] for f in P["FAMILIAS"])
            filas.append({"Semana": t, "Recurso": l, "Horas_produccion": prod, "Horas_preparacion": prep,
                          "Horas_regulares": P["H"][(l, t)], "Horas_extra": sol["E"][(l, t)]})
    for s in P["SEMANAS_MEZCLA"]:
        prod = sum(sol["V"][(f, s)] for f in P["FAMILIAS"]) / P["tasa_mezcla"][s]
        prep = P["cip_mezcla"][s] * sum(sol["z"][(f, s)] for f in P["FAMILIAS"])
        filas.append({"Semana": s, "Recurso": "Mezcla", "Horas_produccion": prod, "Horas_preparacion": prep,
                      "Horas_regulares": P["Hm"][s], "Horas_extra": sol["Em"][s]})
    df = pd.DataFrame(filas)
    df["Horas_usadas"] = df.Horas_produccion + df.Horas_preparacion
    df["Utilizacion_regular"] = df.Horas_usadas.clip(upper=df.Horas_regulares) / df.Horas_regulares
    df["Utilizacion_total"] = df.Horas_usadas / (df.Horas_regulares + df.Horas_extra.where(df.Horas_extra > 0, 0))
    return df


def indicadores(P: dict, sol: dict) -> dict:
    IT = [(i, t) for i in P["SKUS"] for t in P["T"]]
    demanda = sum(P["d"][k] for k in IT)
    inv_prom = sum(sol["I"][k] for k in IT) / len(P["T"])
    atraso_cs = sum(sol["B"][k] for k in IT)
    neto_ok = sum(1 for k in IT if sol["I"][k] - sol["B"][k] >= P["SS"][k] - 0.5)
    semanas_atraso = sum(1 for k in IT if sol["B"][k] > 0.5)
    h = horas_por_recurso(P, sol)
    c = costos(P, sol)
    term_ok = all(sol["I"][(i, 13)] - sol["B"][(i, 13)] >= P["T_terminal"][i] - 0.5 for i in P["SKUS"])
    firme_ok = all(P["rend"][i] * sol["x"][(i, SEMANA_FOCAL)] >= P["C"][i] - 0.5 for i in P["SKUS"])
    return {
        "Costo total (MM CLP)": c["Total"] / 1e6,
        "Costo sin costo variable (MM CLP)": (c["Total"] - c["Producción (costo variable)"]) / 1e6,
        "Fill rate (1 - cajas-semana atrasadas / demanda)": 1 - atraso_cs / demanda,
        "SKU-semana con atraso": semanas_atraso,
        "SKU-semana que cumplen SS (%)": 100 * neto_ok / len(IT),
        "Inventario promedio (cajas)": inv_prom,
        "Rotación (demanda 13 sem / inventario promedio)": demanda / inv_prom if inv_prom else float("inf"),
        "Cobertura promedio (semanas)": inv_prom / (demanda / len(P["T"])),
        "Horas extra L1": h.query("Recurso=='L1'").Horas_extra.sum(),
        "Horas extra L2": h.query("Recurso=='L2'").Horas_extra.sum(),
        "Horas extra mezcla": h.query("Recurso=='Mezcla'").Horas_extra.sum(),
        "Preparaciones SKU": int(sum(sol["y"].values())),
        "Cumple reserva terminal": term_ok,
        "Cumple cartera semana 12": firme_ok,
    }


def tabla(P: dict, sol: dict, clave: str) -> pd.DataFrame:
    return pd.DataFrame({t: {i: sol[clave][(i, t)] for i in P["SKUS"]} for t in P["T"]})


def guardar_solucion(sol: dict, ruta) -> None:
    """Guarda una solución en JSON (claves de tupla como texto 'a|b|c')."""
    import json
    datos = {k: {"|".join(map(str, kk if isinstance(kk, tuple) else (kk,))): vv for kk, vv in d.items()}
             for k, d in sol.items() if isinstance(d, dict)}
    ruta.write_text(json.dumps(datos, indent=0), encoding="utf-8")


def cargar_solucion(ruta) -> dict:
    import json

    def clave(s):
        partes = s.split("|")
        conv = [int(p) if p.lstrip("-").isdigit() else p for p in partes]
        return tuple(conv) if len(conv) > 1 else conv[0]
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return {k: {clave(kk): vv for kk, vv in d.items()} for k, d in datos.items()}
