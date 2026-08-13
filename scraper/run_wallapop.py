"""Escaneo de Wallapop con Playwright. Va aparte del pipeline automático
(scraper/run.py, que corre en GitHub Actions) porque necesita un
navegador real -- pesado de instalar en un runner y, sobre todo, aún sin
probar/depurar contra el sitio real (ver scraper/sources/wallapop.py).
Pensado para ejecutarse en local.

Uso:
    pip install -r requirements-wallapop.txt
    playwright install chromium
    python -m scraper.run_wallapop
    python -m scraper.run_wallapop --models "Chevrolet Captiva" "Volkswagen Golf"
    python -m scraper.run_wallapop --headed --debug-dir scraper/tools/_wallapop_debug

Escribe en la misma base de datos que scraper/run.py (data/precios.db,
source="wallapop") y regenera chollos/latest.md y chollos/latest.json
combinando las tres fuentes.
"""
import argparse
import sys
import time
from datetime import datetime, timezone

from . import config, db
from .run import generate_report, write_json, write_markdown
from .sources import wallapop

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Falta playwright. Instala con: pip install -r requirements-wallapop.txt && playwright install chromium",
          file=sys.stderr)
    sys.exit(1)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headed", action="store_true",
                         help="Abrir el navegador visible (útil para ver a ojo si hay bloqueo/captcha)")
    parser.add_argument("--debug-dir", default=None,
                         help="Volcar ahí las respuestas de red capturadas de cada modelo, para depurar el parseo")
    parser.add_argument("--models", nargs="*", default=None,
                         help="Limitar a estos modelos (nombre mostrado exacto, ej. 'Chevrolet Captiva'). "
                              "Por defecto, todos los de scraper/config.py")
    args = parser.parse_args()

    models = config.ALL_MODELS
    if args.models:
        wanted = set(args.models)
        models = [m for m in models if m[0] in wanted]
        missing = wanted - {m[0] for m in models}
        if missing:
            print(f"Aviso: no encontrados en config.ALL_MODELS: {missing}", file=sys.stderr)

    stats = {"listings_seen": 0, "new_listings": 0, "errors": 0}
    started_at = now_iso()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(user_agent=config.USER_AGENT, locale="es-ES")
        page = context.new_page()

        with db.connect(config.DB_PATH) as conn:
            print(f"Escaneando {len(models)} modelos en Wallapop...")
            for display_model, *_ in models:
                now = now_iso()
                try:
                    listings = wallapop.fetch_listings(display_model, page, debug_dir=args.debug_dir)
                except Exception as exc:
                    print(f"  [wallapop] ERROR en {display_model}: {exc}", file=sys.stderr)
                    stats["errors"] += 1
                    time.sleep(config.REQUEST_DELAY_SECONDS)
                    continue

                # Las islas quedan fuera del todo, igual que en run.py.
                listings = [l for l in listings if l.get("province") not in config.EXCLUDED_PROVINCES]

                seen_ids = set()
                for listing in listings:
                    seen_ids.add(listing["source_id"])
                    is_new = db.upsert_listing(conn, listing, now)
                    stats["listings_seen"] += 1
                    if is_new:
                        stats["new_listings"] += 1
                # Solo se marca inactivo lo no visto si el fetch fue bien
                # (mismo criterio que en run.py: un fallo no debe borrar histórico).
                db.mark_inactive_not_seen_since(conn, "wallapop", display_model, seen_ids, now)
                conn.commit()
                print(f"  [OK] {display_model}: wallapop={len(listings)}")
                time.sleep(config.REQUEST_DELAY_SECONDS)

            report_models, all_deals, now = generate_report(conn, config.ALL_MODELS)
            write_markdown(report_models, all_deals, now, config.CHOLLOS_MD_PATH)
            write_json(report_models, all_deals, now, config.CHOLLOS_JSON_PATH)
            db.record_scan_run(conn, started_at, now_iso(), len(models),
                                stats["listings_seen"], stats["new_listings"], stats["errors"])

        browser.close()

    print(f"\nHecho. Anuncios vistos={stats['listings_seen']} nuevos={stats['new_listings']} "
          f"errores={stats['errors']} chollos={len(all_deals)}")
    if stats["errors"]:
        print("Si hubo errores en todos los modelos, prueba primero con:")
        print("  python -m scraper.tools.inspect_wallapop \"https://es.wallapop.com/coches-segunda-mano/chevrolet-captiva\" --headed")


if __name__ == "__main__":
    main()
