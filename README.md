# Automatización de tarifas · Realidad 360

Actualiza todos los días, de forma automática y trazable, el **costo por hora facturable** del template de
presupuesto (pestaña `COSTOS X HORAS FACTURABLES`) a partir de escalas salariales y honorarios oficiales.
Cada valor que cambia queda documentado con su fuente, URL, período de vigencia y fecha de extracción.

```
 sources.json ──► extractores ──► conciliación ──► publicación ──────────► Google Sheets
 (SICA, SUP,      (PDF, OCR,      (mapeo de roles,  (columna C + nota      ├─ COSTOS X HORAS FACTURABLES
  CPCI, ...)       HTML, JS)       fórmula,          de auditoría,         └─ Fuentes_Tarifas
                                   validaciones)     pestaña de trazas)
                                                           │
                                                           └──► resumen + issue "alerta-tarifas" en GitHub
```

## Fuentes

| id | Entidad | Formato | Qué se toma |
|---|---|---|---|
| `sica_animacion_2d` / `_3d` | SICA-APMA | PDF con texto | Total básico **diario** por cargo y vigencia ("VIGENTES DESDE … HASTA …") |
| `sup_agencias` | SUP · CCT 57/89 | PDF **escaneado** (OCR) | Sueldo **mensual** del tramo vigente del acuerdo |
| `cpci_honorarios` | CPCI Córdoba | Tabla HTML (iframe) | Remuneración mensual y hora a demanda, fecha de actualización |
| `coderhouse_ai_automation_*` | Coderhouse | Texto de una nota | Rangos en USD por seniority (**solo referencia**) |
| `tarifario_servicios_3d` | Tarifario.ar | Datos dentro del JavaScript del sitio | Precios en USD por servicio 3D (**solo referencia**) |

Controles de calidad de cada extractor:
- **SICA**: la relación diario/mensual tiene que ser igual en todas las filas; si una fila no la cumple, se descarta.
- **SUP**: cada fila tiene que cumplir la cadena de aumentos publicada (Dic +4% → Feb +8% → Jul +8% → Nov +4%). Un dígito mal leído por el OCR rompe la cuenta y la fila se descarta. En la prueba inicial pasaron 94 de 95 filas.
- **Todas**: un mínimo de filas leídas. Si no se llega, la fuente se marca con error y **no se toca la planilla** con sus datos.

**Descubrimiento automático**: SICA publica un PDF nuevo por período. El extractor busca en
`https://www.sicacine.org.ar/` el enlace "Salarios Animación 2D …" y usa el más nuevo. Si no lo encuentra,
usa la URL de `sources.json`. Si una URL falla, prueba con la otra y, si las dos fallan, registra el error y
sigue con las demás fuentes.

## Fórmula (configurable en `config/calculo.json`)

```
costo_diario          = base_diaria × factor_rol × (1 + cargas_sociales) × factor_multiplicador
base_diaria           = diario | semanal ÷ 5 | mensual ÷ 21 | hora × 8
costo_hora_facturable = costo_diario × (1 + overhead) ÷ 8
```

- `costo_diario` se escribe en la columna **C**. La columna **S** de la planilla ya calcula la hora con
  `=C×(1+Factor_Overhead)/8`.
- El **overhead** se lee de la planilla (rango con nombre `Factor_Overhead`, pestaña `Parámetros!B2`), así hay
  una sola fuente de verdad. Dejar `cargas_sociales` en 0 mientras ese overhead incluya las cargas.
- `factor_rol` permite reglas como "CEO = Coordinador/a de Producción × 1,4" (ver `mapeo_roles.json`).

## Cuándo se aplica un cambio

| Estado | Qué pasa |
|---|---|
| **Aplicado** | El mapeo es `auto`, la fuente vino completa y la variación está entre **−2% y +40%** |
| **Pendiente de revisión** | Mapeo en modo `revision`, variación fuera de rango o celda sin valor previo |
| **Fuente con error** | La fuente no se pudo leer o vino incompleta (< 80% de las categorías): no se toca nada |
| **No encontrado** | El rol no está en la planilla o la categoría desapareció de la fuente |
| **Sin fuente configurada** | Rol que ninguna fuente cubre (Rodaje, Operadores, etc.): se mantiene a mano |

**Aprobar un pendiente**: en la pestaña `Fuentes_Tarifas`, marcar la casilla **Aprobar** de esa fila. En la
ejecución siguiente se aplica, siempre que el valor propuesto no haya cambiado.

## Trazabilidad

- **Nota en la celda C** (se ve al pasar el mouse): fuente, URL exacta, vigencia, categoría en la fuente,
  cálculo, valor anterior y fecha y hora de extracción.
- **Pestaña `Fuentes_Tarifas`**: se reescribe en cada corrida. Tiene una fila por rol con costo vigente,
  propuesto, variación, hora facturable, fuente, documento, URL, período de vigencia, cálculo, estado y motivo.
  Además lista **todo lo extraído de cada fuente con su área**: es el "listado por área" de cada sindicato,
  e incluye las categorías que todavía no están mapeadas y las referencias de mercado convertidas a pesos.
- El encabezado de la columna C indica que el valor se actualiza solo.

> La pestaña `LISTADO DE ÁREAS` **no se modifica automáticamente**: sus nombres son las claves de los
> menús desplegables y de las búsquedas, y renombrarlos rompería presupuestos ya cargados. Las categorías
> nuevas aparecen en `Fuentes_Tarifas` como "Categoría sin mapear" para incorporarlas a mano.

## Configuración

| Archivo | Para qué |
|---|---|
| `config/sources.json` | Fuentes: URL, extractor, descubrimiento, patrón de vigencia, opciones |
| `config/mapeo_roles.json` | Rol del template → categoría de una fuente, unidad, factor y modo (`auto`/`revision`) |
| `config/calculo.json` | Horas por jornada, días por mes, cargas, multiplicador, umbrales de validación |
| `config/plantilla.json` | Nombres de pestañas y columnas del template |

### Agregar una fuente

1. Copiar un bloque en `sources.json`, con un `id` nuevo y un `extractor` existente (`sica_pdf`,
   `sup_pdf_ocr`, `cpci_html`, `coderhouse_html` o `tarifario_js`).
2. Probarla: `python -m tarifas extraer --solo <id>`.
3. Mapear los roles en `mapeo_roles.json`, empezando en modo `revision`.
4. Si el formato es nuevo, crear un módulo en `tarifas/extractores/` con una función
   `extraer(fuente, url, cliente, ctx) -> ResultadoFuente` y registrarlo en `tarifas/extractores/__init__.py`.

Hay un ejemplo deshabilitado (`sica_publicidad`) que probablemente cubre Rodaje y Sonido.

## Puesta en marcha

### 1. Cuenta de servicio de Google (una sola vez)
1. En [console.cloud.google.com](https://console.cloud.google.com) crear un proyecto y habilitar la
   **Google Sheets API**.
2. En *IAM y administración › Cuentas de servicio*, crear una cuenta (por ejemplo `tarifas-r360`) y
   generar una **clave JSON**. Guardarla fuera del repositorio.
3. Abrir la planilla, **Compartir** y agregar el e-mail de la cuenta de servicio
   (`…@….iam.gserviceaccount.com`) como **Editor**.

### 2. Secretos en GitHub
En el repositorio, *Settings › Secrets and variables › Actions › New repository secret*:
- `GOOGLE_SERVICE_ACCOUNT_JSON`: el contenido completo del archivo JSON de la clave.
- `TARIFAS_SHEET_ID`: el ID de la planilla, que es la parte de la URL entre `/d/` y `/edit`.

### 3. Primera corrida
*Actions › Actualizar tarifas › Run workflow*, con **Simulación** marcada: calcula todo y no escribe.
Revisar el resumen de la corrida. Después correrla sin simulación. A partir de ahí se ejecuta sola
todos los días a las **08:00 (Argentina)**.

### Ejecución local
```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # en Linux/Mac: .venv/bin/pip
python -m tarifas validar-config
python -m tarifas extraer --solo sica_animacion_2d
# Probar contra un export .xlsx de la planilla (escribe en otra copia, nunca en el original):
python -m tarifas actualizar --backend xlsx --xlsx-entrada plantilla.xlsx --xlsx-salida salida/plantilla.xlsx --mostrar-montos
# Contra la planilla real (credenciales en variables de entorno):
GOOGLE_APPLICATION_CREDENTIALS=clave.json TARIFAS_SHEET_ID=... python -m tarifas actualizar --simulacion
pytest
```

## Alertas
- Cada corrida publica un **resumen** en la pestaña *Summary* de GitHub Actions.
- Si hay fuentes con error, pendientes o roles no encontrados, se abre (o se actualiza) un **issue** con la
  etiqueta `alerta-tarifas`. Cuando todo vuelve a estar en orden, se cierra solo.
- Los avisos de cada fuente (URL nueva detectada, escala vencida, filas descartadas) quedan en el log.

## Seguridad
- **El repositorio es público**: los logs de GitHub Actions y los issues son visibles para cualquiera. Por
  eso no muestran montos, solo nombres de fuentes, roles y estados; los montos quedan en la planilla. Se
  recomienda hacer el repositorio **privado** (el plan gratuito incluye minutos suficientes para una corrida diaria).
- Las claves nunca se suben: van como secretos de GitHub (`.gitignore` excluye `*.json.key`, `credenciales/`, `.env`).
- `www.ceni.com.ar` (tabla del CPCI) no envía su certificado intermedio. Se agrega solo ese intermedio público
  de GoDaddy (`config/certificados/godaddy_secure_ca_g2.pem`, vence en 2031). La verificación TLS sigue activa.

## Limitaciones conocidas
- **SUP**: no tiene página índice para descubrir el acuerdo siguiente. Cuando se publique el nuevo
  (después de nov-2026), actualizar `url` y `tramos_respaldo` en `sources.json`. El job avisa cuando el
  acuerdo vigente terminó.
- **Coderhouse y Tarifario** son páginas comerciales: si cambian el texto o la estructura, la fuente queda en
  error (con alerta) y el resto sigue funcionando.
- GitHub **pausa los workflows programados** de repositorios públicos sin actividad durante 60 días. Si pasa,
  se reactivan desde la pestaña *Actions*.
