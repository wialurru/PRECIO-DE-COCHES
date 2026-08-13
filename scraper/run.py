"""Orquestador: recorre el top de modelos vigilados, descarga anuncios de
coches.net y Milanuncios, los guarda en SQLite y genera el informe de
chollos (chollos/latest.md y chollos/latest.json).

Uso: python -m scraper.run
"""
import json
import sys
import time
import traceback
from datetime import datetime, timezone

import requests

from . import config, db, dealscore
from .sources import coches_net, milanuncios


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.USER_AGENT,
        "Accept-Language": "es-ES,es;q=0.9",
    })
    return s


def scan_model(conn, session, display_model, cn_make_id, cn_model_id, ma_make_slug, ma_model_slug, stats):
    seen_ids_by_source = {"coches_net": set(), "milanuncios": set()}
    now = now_iso()

    try:
        cn_listings = coches_net.fetch_listings(display_model, cn_make_id, cn_model_id, session)
    except Exception as exc:
        print(f"  [coches.net] ERROR en {display_model}: {exc}", file=sys.stderr)
        cn_listings = []
        stats["errors"] += 1
    time.sleep(config.REQUEST_DELAY_SECONDS)

    if ma_make_slug and ma_model_slug:
        try:
            ma_listings = milanuncios.fetch_listings(display_model, ma_make_slug, ma_model_slug, session)
        except Exception as exc:
            print(f"  [milanuncios] ERROR en {display_model}: {exc}", file=sys.stderr)
            ma_listings = []
            stats["errors"] += 1
        time.sleep(config.REQUEST_DELAY_SECONDS)
    else:
        ma_listings = []  # sin página propia en Milanuncios para este modelo

    for listing in cn_listings + ma_listings:
        seen_ids_by_source[listing["source"]].add(listing["source_id"])
        is_new = db.upsert_listing(conn, listing, now)
        stats["listings_seen"] += 1
        if is_new:
            stats["new_listings"] += 1

    for source in ("coches_net", "milanuncios"):
        db.mark_inactive_not_seen_since(conn, source, display_model, seen_ids_by_source[source], now)

    print(f"  {display_model}: coches.net={len(cn_listings)} milanuncios={len(ma_listings)}")


def generate_report(conn, all_models):
    now = datetime.now(timezone.utc)
    report_models = []
    all_deals = []

    for display_model, *_ in all_models:
        listings = db.active_listings_for_model(conn, display_model)
        deals, group_stats = dealscore.compute_deals(listings, now)
        recent = [
            dict(row) | {"age_days": dealscore.days_since(row["publish_date"], now),
                          "condition": dealscore.classify_condition(row)}
            for row in listings
            if dealscore.days_since(row["publish_date"], now) <= config.MAX_AGE_DAYS
        ]
        report_models.append({
            "model": display_model,
            "active_listings": len(listings),
            "recent_listings": len(recent),
            "deals": deals,
            "group_stats": group_stats,
        })
        all_deals.extend(deals)

    all_deals.sort(key=lambda d: d["discount_ratio"])
    return report_models, all_deals, now


CONDITION_ORDER = [
    "Buen estado / revisado / con garantía",
    "Estado no especificado por el vendedor",
    "Necesita reparación / revisión pendiente",
    "Para piezas / no arranca / accidentado",
]


def write_markdown(report_models, all_deals, now, path):
    lines = []
    lines.append("# Chollos detectados — coches de segunda mano (España)")
    lines.append("")
    lines.append(f"Última actualización: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(
        f"Se vigilan {len(report_models)} modelos (top de rotación + modelos extra) en coches.net y "
        "Milanuncios. Se considera **chollo** un anuncio activo, publicado hace "
        f"{config.MAX_AGE_DAYS} días o menos, con precio igual o inferior al "
        f"{int(config.CHOLLO_DISCOUNT_RATIO * 100)}% de la mediana de precios de su grupo "
        "(mismo modelo vigilado + año), exigiendo al menos "
        f"{config.CHOLLO_MIN_GROUP_SIZE} anuncios comparables en ese grupo."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## Chollos activos ({len(all_deals)})")
    lines.append("")

    if not all_deals:
        lines.append("No se han detectado chollos que cumplan el criterio en este barrido.")
    else:
        by_condition = {}
        for deal in all_deals:
            by_condition.setdefault(deal["condition"], []).append(deal)

        for condition in CONDITION_ORDER:
            deals = by_condition.get(condition, [])
            if not deals:
                continue
            lines.append(f"### {condition}")
            lines.append("")
            lines.append("| Modelo | Año | Precio | Mediana grupo | Descuento | Km | Ubicación | Fuente | Publicado hace | Enlace |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|")
            for d in deals:
                pct_off = int(round((1 - d["discount_ratio"]) * 100))
                km = f"{d['km']:,} km".replace(",", ".") if d["km"] else "—"
                age = f"{d['age_days']:.1f} d" if d["age_days"] != float("inf") else "—"
                lines.append(
                    f"| {d['display_model']} | {d['year'] or '—'} | {d['price']:,.0f} € | "
                    f"{d['group_median']:,.0f} € | -{pct_off}% | {km} | "
                    f"{d.get('city') or d.get('province') or '—'} | {d['source']} | {age} | "
                    f"[Ver anuncio]({d['url']}) |"
                )
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Resumen por modelo vigilado")
    lines.append("")
    lines.append("| Modelo | Anuncios activos | Publicados en <15 días | Chollos |")
    lines.append("|---|---|---|---|")
    for m in sorted(report_models, key=lambda x: -x["recent_listings"]):
        lines.append(f"| {m['model']} | {m['active_listings']} | {m['recent_listings']} | {len(m['deals'])} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_Generado automáticamente por el escáner de `scraper/run.py`. Los precios y la disponibilidad "
        "cambian constantemente: verificar siempre el anuncio original antes de decidir._"
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_json(report_models, all_deals, now, path):
    payload = {
        "generated_at": now.isoformat(),
        "max_age_days": config.MAX_AGE_DAYS,
        "discount_ratio": config.CHOLLO_DISCOUNT_RATIO,
        "deals": all_deals,
        "models": [
            {"model": m["model"], "active_listings": m["active_listings"],
             "recent_listings": m["recent_listings"], "deal_count": len(m["deals"])}
            for m in report_models
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def main():
    started_at = now_iso()
    stats = {"listings_seen": 0, "new_listings": 0, "errors": 0}
    all_models = config.ALL_MODELS

    session = build_session()
    with db.connect(config.DB_PATH) as conn:
        print(f"Escaneando {len(all_models)} modelos...")
        for display_model, cn_make_id, cn_model_id, ma_make_slug, ma_model_slug in all_models:
            try:
                scan_model(conn, session, display_model, cn_make_id, cn_model_id,
                           ma_make_slug, ma_model_slug, stats)
                conn.commit()
            except Exception:
                stats["errors"] += 1
                print(f"  ERROR inesperado escaneando {display_model}:", file=sys.stderr)
                traceback.print_exc()

        report_models, all_deals, now = generate_report(conn, all_models)
        write_markdown(report_models, all_deals, now, config.CHOLLOS_MD_PATH)
        write_json(report_models, all_deals, now, config.CHOLLOS_JSON_PATH)

        db.record_scan_run(conn, started_at, now_iso(), len(all_models),
                            stats["listings_seen"], stats["new_listings"], stats["errors"])

    print(f"Hecho. Anuncios vistos={stats['listings_seen']} nuevos={stats['new_listings']} "
          f"errores={stats['errors']} chollos={len(all_deals)}")


if __name__ == "__main__":
    main()
