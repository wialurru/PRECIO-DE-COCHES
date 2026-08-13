# PRECIO-DE-COCHES

Contexto para cualquier agente (Claude Code u otro) que trabaje en este repo.
Léelo entero antes de tocar nada: hay decisiones ya tomadas y varios
problemas reales ya diagnosticados que conviene no repetir.

## Qué es esto

Dos cosas conviven en el repo:

1. **Un informe de investigación puntual** (`chevrolet-captiva-2008-mercado-espana.md`):
   análisis manual del mercado español de un Chevrolet Captiva 2008 concreto
   del usuario (ficha técnica real: 2.0 VCDI 150cv 7 plazas, matrícula
   8704GJX, importado en 2008). No es parte del pipeline automático, es un
   documento de referencia de una tarea anterior.

2. **Una herramienta de escaneo continuo de "chollos"** (`scraper/`): vigila
   ~40 modelos de coche de alta rotación en el mercado español de segunda
   mano (coches.net, Milanuncios, y Wallapop en progreso) y detecta anuncios
   con precio muy por debajo de la mediana de su grupo (mismo modelo + año).
   **Esto es el foco actual del proyecto.**

## Objetivo del usuario

Quiere una base de datos de precios reales que se actualice sola (cron cada
6h) y le señale oportunidades ("chollos") entre los modelos que más rotan en
el mercado español, ordenadas/filtrables por estado según lo que dice el
propio vendedor en el anuncio. Cuantas más fuentes/marketplaces, mejor —
**no quiere que se descarte ningún marketplace**, aunque algunos sean más
difíciles de scrapear que otros (ver estado de Wallapop más abajo).

Siguiente cosa pendiente que el usuario quiere decidir: **cómo recibir
notificación de chollos nuevos** (email, Telegram...) — aún no implementado,
quedó aparcado para después de tener la recolección de datos funcionando.

## Arquitectura

```
scraper/
  config.py        # los ~40 modelos vigilados + parámetros (umbrales, delays...)
  db.py             # SQLite: tabla listings + scan_runs
  dealscore.py      # agrupa por (modelo, año), calcula mediana, marca "chollo"
  run.py            # pipeline AUTOMÁTICO: coches.net + Milanuncios -> genera chollos/*
  run_wallapop.py   # pipeline MANUAL (Playwright): Wallapop -> misma BD, mismo informe
  sources/
    coches_net.py   # requests + parseo del JSON embebido (__INITIAL_PROPS__)
    milanuncios.py  # requests + parseo del JSON embebido (__INITIAL_PROPS__)
    wallapop.py      # Playwright: intercepta las llamadas de red de la SPA (SIN PROBAR, ver abajo)
  tools/
    lookup_coches_net_ids.py   # resuelve makeId/modelId reales de coches.net para añadir modelos
    inspect_wallapop.py         # depuración: vuelca respuestas de red + HTML + screenshot de Wallapop
data/precios.db      # SQLite, se commitea al repo (así persiste entre runs de Actions)
chollos/latest.md    # informe legible, se regenera en cada run
chollos/latest.json  # mismo informe en JSON
.github/workflows/scan-chollos.yml   # cron cada 6h (ver limitaciones abajo)
requirements.txt            # solo lo que necesita el pipeline automático (requests)
requirements-wallapop.txt   # playwright, aparte porque es pesado y no lo usa el cron
```

### Cómo se obtienen los datos (importante, no reinventar)

`coches.net` y `Milanuncios` **no hace falta scrapearlos con BeautifulSoup ni
Playwright**: ambos renderizan en servidor y dejan el resultado de la
búsqueda como JSON completo en
`<script>window.__INITIAL_PROPS__ = JSON.parse("...")</script>`. Basta un
`requests.get` con User-Agent de navegador y parsear ese JSON (doble
JSON-encoded: es un string JS que a su vez contiene JSON). Ahí viene todo:
precio, km, año, **fecha real de publicación**, descripción del vendedor
(Milanuncios), tipo de vendedor, etc. Ver `sources/coches_net.py` y
`sources/milanuncios.py` para el patrón exacto de extracción.

`coches.net` además NO usa slugs de texto en la URL para buscar por modelo:
usa IDs numéricos internos (`?makeId=X&modelId=Y`). Esos IDs se resolvieron
contra el catálogo real que el propio coches.net expone en
`listFiltersOptions.vehicles` (no están inventados). Para añadir un modelo
nuevo, usar `python -m scraper.tools.lookup_coches_net_ids "MARCA" "modelo"`.

`Milanuncios` sí usa slugs de texto (`marca-modelo-de-segunda-mano`), pero
**no todos los modelos tienen página propia** (4 del top-40 dan 404: T-Roc,
Arona, C-HR, Niro — están marcados con slug `None` en `config.py` y el
pipeline los salta automáticamente solo en Milanuncios, coches.net sí los
cubre).

`Wallapop` es un caso aparte, ver siguiente sección.

## Wallapop: estado y qué falta

Wallapop bloquea con 403 (CloudFront) **cualquier petición HTTP directa**,
incluso pasando por un proxy lector (se probó con r.jina.ai y también lo
bloqueó). La única vía viable es un navegador real (Playwright) que ejecute
el JS del sitio y dispare sus propias llamadas a la API; `sources/wallapop.py`
intercepta esas respuestas de red en vez de volver a pedirlas a mano.

**Este código se escribió a ciegas y no se ha podido probar.** El sandbox
donde se escribió no tiene salida a red para procesos de navegador en
absoluto (se confirmó lanzando Chromium headless contra `example.com`, que
también falla con `ERR_CONNECTION_RESET` — no es Wallapop bloqueando, es una
limitación del entorno). Los nombres de campo del JSON de Wallapop
(`ID_KEYS`, `PRICE_KEYS`, `TITLE_KEYS`... en `sources/wallapop.py`) son
conjeturas razonables, no datos confirmados.

**Siguiente paso pendiente**, a hacer desde una máquina con red real (típicamente
la del usuario):
1. `pip install -r requirements-wallapop.txt && playwright install chromium`
2. `python -m scraper.tools.inspect_wallapop "https://es.wallapop.com/coches-segunda-mano/chevrolet-captiva" --headed`
   → mirar `scraper/tools/_wallapop_debug/screenshot.png` (¿pasa el muro
   anti-bot o no?) y `responses_index.json` (¿qué URL trae los anuncios de
   verdad?).
3. Ajustar `API_URL_HINTS` y las claves `*_KEYS` en `sources/wallapop.py`
   según lo que se vea en los JSON volcados.
4. `python -m scraper.run_wallapop` para el barrido real una vez ajustado.

No integrar Wallapop en `scraper/run.py` ni en el workflow de GitHub Actions
sin resolver antes el punto siguiente (IPs bloqueadas), o será tiempo de CI
tirado a la basura.

## Limitación seria ya descubierta: IPs de GitHub Actions bloqueadas

El primer barrido real vía GitHub Actions (workflow `scan-chollos.yml`)
reveló que **Milanuncios bloquea con 403 la IP de los runners de GitHub
Actions desde la primera petición**, y coches.net empieza a bloquear tras un
par de peticiones. Esto es habitual: son rangos de datacenter conocidos.

Esto en su momento causó un bug real (ya corregido, ver commits
`ac363df` y el histórico): el código trataba un fallo de red igual que "ya
no hay anuncios de este modelo" y marcaba como inactivos casi todos los
anuncios ya guardados, vaciando el informe. **Regla ya aplicada en el
código y que hay que mantener si se toca `run.py`/`run_wallapop.py`:**
`db.mark_inactive_not_seen_since(...)` **solo se llama si el fetch de esa
fuente para ese modelo respondió correctamente en este barrido.** Si falló,
se deja el dato tal cual estaba. Es preferible un dato desactualizado a
destruir el histórico por un bloqueo temporal.

Mitigaciones ya aplicadas (`config.py`: `MAX_RETRIES_PER_SOURCE`,
`RETRY_BACKOFF_SECONDS`, jitter en las pausas, "calentado" de sesión
visitando la home antes de pedir listados): ayudan pero no garantizan que el
cron de GitHub Actions traiga datos frescos en cada disparo. **El usuario ya
sabe esto** y de momento la vía fiable es correr `python -m scraper.run` a
mano desde una IP normal (su propio ordenador) y comitear el resultado; el
cron de Actions queda activo igualmente como intento best-effort.

Si en el futuro se quiere resolver de raíz: la opción discutida con el
usuario fue contratar un proxy de scraping (residencial/rotativo) y usarlo
desde el Action — no implementado, decisión pendiente del usuario si hace
falta.

## Rama y CI

El repo estaba vacío; el primer push de este proyecto creó la rama
`claude/precios-coches-espana-recientes-2ahl9b`, que **GitHub la fijó sola
como rama por defecto** (no hay `main`). El cron de
`.github/workflows/scan-chollos.yml` funciona porque GitHub Actions solo
dispara `schedule` desde la rama por defecto — si en algún momento se crea
una rama `main` y se cambia el default ahí, hay que mover el workflow o el
cron dejará de dispararse en silencio.

## Modelo de datos

SQLite en `data/precios.db` (se commitea al repo tal cual, binario, para que
persista entre ejecuciones del Action sin depender de un servicio externo).

Tabla `listings`: `source` (coches_net/milanuncios/wallapop) + `source_id`
como clave primaria compuesta; `is_active` marca si el anuncio se vio en el
último barrido de esa fuente+modelo. Tabla `scan_runs`: histórico de
ejecuciones (para poder ver si el cron está trayendo datos o fallando en
silencio, mirar `SELECT * FROM scan_runs ORDER BY id DESC`).

## Lógica de "chollo" (`dealscore.py`)

Agrupa anuncios activos por `(display_model, year)`. Si el grupo tiene al
menos `CHOLLO_MIN_GROUP_SIZE` (4) anuncios con precio válido, calcula la
mediana. **El precio de referencia se ajusta por kilometraje** cuando el
grupo tiene suficientes anuncios con km conocido (`KM_REGRESSION_MIN_SAMPLES`,
6): se ajusta una regresión lineal simple precio~km (`statistics.linear_regression`,
sin dependencias extra) y se compara cada anuncio contra el precio esperado
para SU kilometraje, no contra la mediana bruta del grupo — así un coche con
300.000 km no compite en igualdad con uno de 50.000 km. Si la pendiente sale
positiva (no tiene sentido) o no hay grupo suficiente, cae de vuelta a la
mediana simple. Un anuncio es chollo si `precio <= precio_esperado *
CHOLLO_DISCOUNT_RATIO` (0.75, 25% o más por debajo) **y** se publicó hace
`MAX_AGE_DAYS` (15) días o menos. Se clasifica por "estado" con palabras
clave simples sobre título+descripción (buen estado/garantía, necesita
reparación, para piezas, sin especificar) — ver `CONDITION_RULES`.

## Comandos útiles

```bash
# Pipeline automático (coches.net + Milanuncios), lo mismo que corre el cron
pip install -r requirements.txt
python -m scraper.run

# Wallapop (aparte, necesita navegador real, ver sección de arriba)
pip install -r requirements-wallapop.txt && playwright install chromium
python -m scraper.tools.inspect_wallapop "<url>" --headed   # depurar primero
python -m scraper.run_wallapop

# Añadir un modelo nuevo al top vigilado
python -m scraper.tools.lookup_coches_net_ids "SEAT" "Arona"   # sacar make_id/model_id reales
# luego añadir la tupla a TOP_MODELS en scraper/config.py y verificar el slug
# de Milanuncios visitando https://www.milanuncios.com/<marca>-<modelo>-de-segunda-mano/
```

## Pendiente / próximos pasos

- [ ] Depurar y validar `scraper/sources/wallapop.py` contra el sitio real (ver arriba).
- [ ] Decidir vía de entrega de chollos nuevos (email / Telegram / otro) — el usuario lo pidió, no implementado.
- [ ] Decidir si merece la pena un proxy de pago para que el cron de GitHub Actions no dependa de correr a mano.
- [ ] Revisar de vez en cuando si coches.net/Milanuncios cambiaron su HTML/JSON embebido (romperían `_extract_initial_props`).
