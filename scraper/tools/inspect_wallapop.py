"""Herramienta de depuración para scraper/sources/wallapop.py.

Abre una URL de Wallapop con un navegador real, vuelca TODAS las
respuestas de red que parezcan JSON (para localizar el endpoint real de
búsqueda) más el HTML final y una captura de pantalla, y avisa si el
sitio está sirviendo un bloqueo anti-bot en vez de contenido real.

Uso:
    pip install -r requirements-wallapop.txt
    playwright install chromium
    python -m scraper.tools.inspect_wallapop "https://es.wallapop.com/coches-segunda-mano/chevrolet-captiva"

Salida: carpeta scraper/tools/_wallapop_debug/ con:
    - responses_index.json  (url, status, content-type, tamaño de cada respuesta)
    - resp_XXX.json         (cuerpo de cada respuesta JSON capturada)
    - page.html             (HTML final renderizado)
    - screenshot.png        (captura visual, para ver a ojo si hay un muro anti-bot)
"""
import json
import os
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Falta playwright. Instala con: pip install -r requirements-wallapop.txt && playwright install chromium",
          file=sys.stderr)
    sys.exit(1)

from .. import config

OUT_DIR = os.path.join(os.path.dirname(__file__), "_wallapop_debug")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1]
    headed = "--headed" in sys.argv

    os.makedirs(OUT_DIR, exist_ok=True)
    responses_index = []
    json_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(user_agent=config.USER_AGENT, locale="es-ES")
        page = context.new_page()

        def on_response(response):
            nonlocal json_count
            ctype = response.headers.get("content-type", "")
            entry = {"url": response.url, "status": response.status, "content_type": ctype}
            if "json" in ctype:
                try:
                    body = response.json()
                    json_count += 1
                    fname = f"resp_{json_count:03d}.json"
                    with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as f:
                        json.dump(body, f, ensure_ascii=False, indent=2, default=str)
                    entry["saved_as"] = fname
                except Exception as exc:
                    entry["json_parse_error"] = str(exc)
            responses_index.append(entry)

        page.on("response", on_response)

        print(f"Navegando a {url} ...")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        for _ in range(4):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1200)

        with open(os.path.join(OUT_DIR, "page.html"), "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path=os.path.join(OUT_DIR, "screenshot.png"), full_page=True)

        with open(os.path.join(OUT_DIR, "responses_index.json"), "w", encoding="utf-8") as f:
            json.dump(responses_index, f, ensure_ascii=False, indent=2)

        title = page.title()
        body_preview = page.inner_text("body")[:300].replace("\n", " ")
        browser.close()

    print(f"\nTítulo de la página: {title!r}")
    print(f"Primeras palabras del body: {body_preview!r}")
    print(f"\nRespuestas JSON capturadas: {json_count}")
    print(f"Todo volcado en: {OUT_DIR}")
    print("\nSiguiente paso: mirar screenshot.png (¿es la web real o un muro anti-bot/captcha?) "
          "y responses_index.json (¿qué URL trae los anuncios?) para ajustar API_URL_HINTS y las "
          "claves de campo en scraper/sources/wallapop.py")


if __name__ == "__main__":
    main()
