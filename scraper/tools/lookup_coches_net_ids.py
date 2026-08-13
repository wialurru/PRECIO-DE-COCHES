"""Utilidad de mantenimiento: resuelve makeId/modelId reales de coches.net
para poder añadir modelos nuevos a scraper/config.py con datos correctos
en vez de adivinar slugs de URL (que en coches.net no existen como tales:
las búsquedas van por ID numérico interno).

Uso:
    python -m scraper.tools.lookup_coches_net_ids "SEAT" "Arona"
    python -m scraper.tools.lookup_coches_net_ids "BMW"          # lista todos los modelos de esa marca
"""
import json
import sys

import requests

from .. import config

ANY_MODEL_PAGE = "https://www.coches.net/segunda-mano/?makeId=9&modelId=592"  # Chevrolet Captiva
INITIAL_PROPS_MARKER = '__INITIAL_PROPS__ = JSON.parse("'


def _extract_initial_props(html: str) -> dict:
    i = html.find(INITIAL_PROPS_MARKER)
    i += len(INITIAL_PROPS_MARKER)
    j = i
    while not (html[j] == '"' and html[j - 1] != "\\"):
        j += 1
    raw = html[i:j]
    return json.loads(json.loads('"' + raw + '"'))


def load_catalog() -> dict:
    """Descarga el catálogo completo marca -> {modelo: modelId} que coches.net
    incrusta en cualquiera de sus páginas de listado."""
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})
    resp = session.get(ANY_MODEL_PAGE, timeout=20)
    resp.raise_for_status()
    data = _extract_initial_props(resp.text)
    options = data["listFiltersOptions"]["vehicles"]["options"]
    make_ids = {o["label"]: o["id"] for o in data["listFiltersOptions"]["makeId"]["options"]}
    catalog = {}
    for make in options:
        catalog[make["label"]] = {
            "make_id": make_ids.get(make["label"], make.get("id")),
            "models": {m["label"]: m["id"] for m in make["models"]},
        }
    return catalog


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    make_query = sys.argv[1].upper()
    model_query = sys.argv[2].upper() if len(sys.argv) > 2 else None

    catalog = load_catalog()
    matches = [m for m in catalog if make_query in m]
    if not matches:
        print(f"Marca no encontrada: {sys.argv[1]}")
        sys.exit(1)

    for make in matches:
        entry = catalog[make]
        print(f"{make}  (make_id={entry['make_id']})")
        for model_label, model_id in sorted(entry["models"].items()):
            if model_query and model_query not in model_label.upper():
                continue
            print(f"    {model_label!r:30} model_id={model_id}")


if __name__ == "__main__":
    main()
