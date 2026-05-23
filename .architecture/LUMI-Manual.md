# LUMI — Manual Unificado de Arquitectura, Roadmap y Features

**Proyecto:** LUMI (Listening Unified Memory Intelligence)
**Autor del proyecto:** Jose Barco
**Versión del manual:** 2.4
**Fecha:** 23 de mayo 2026
**Generado por:** Claude Code (actualización de arquitectura)

> **Nota de versión (v2.4):** correcciones puntuales a 23 de mayo 2026. Cambios: (1) `lumi_soul.md` y `attitude.md` reescritos en formato compacto (~118 y ~284 líneas respectivamente) — sección 6.2 actualizada para reflejar contenido real de cada archivo; (2) `Qwen/Qwen3-235B-A22B-Instruct-2507` es el model ID correcto (con sufijo `-Instruct-2507`), su `extra_body` es `{"top_k": 20}` sin `chat_template_kwargs`; (3) `google/gemma-4-26b-a4b` sí acepta `reasoning_effort` como parámetro top-level (no como `extra_body`); (4) estimación del cached prefix ajustada a ~2,200-2,700 tokens; (5) providers `gemma_4_26b_a4b.py` y `qwen3_235b_a22b.py` ahora en el repo y referenciados en `synapses.py`; (6) `.architecture/LUMI_Group_Participation_Policy.md` eliminado — las reglas de grupo fueron absorbidas en `attitude.md`. Se preserva todo el contenido de v2.3 no afectado por estos cambios.

> **Nota de versión (v2.3):** sincronización completa con el código real en `lumi-vps` a 23 de mayo 2026. Cambios principales: (1) estructura de directorios reescrita — el proyecto usa `agent/` como raíz (no `src/`), con módulos renombrados: `presence/app.py`, `cognition/stream.py`, `cognition/working_memory.py`, `cognition/attention.py`, `cognition/intention.py`, `expression/synapses.py`, `faculties/`, `affect/mood.py`, `perception/websocket.py`, `subconscious/`, `identity/` — ver sección 4, (2) grupo MAIN de modelos ampliado de 3 a 5: `Gemma4_26B_A4B` es ahora primario, Qwen3.5-35B-A3B es segundo, Step-3.5-Flash tercero, se agregó Qwen3_235B_A22B y Nemotron-120B como últimos fallbacks, (3) archivos de personalidad: de `lumi_card.json` (Character Card V3) a `lumi_soul.md` + `attitude.md` (markdown), (4) modelo de estado interno enriquecido a 8 campos numéricos + sleep stages + negative_load — ya no son 3 strings, (5) bases de datos: `data/traces.db` (historial) y `data/core.db` (estado, personas), (6) features de Fase 4 actualizadas: perfil viviente (read-path), interest deltas nocturnos, emotional honesty mode, entity resolution, diario nocturno, mood evaluation — todos SHIPPED, (7) quiescencia nocturna documentada con 8 pasos (2 wired, 6 stubs), (8) loop del agente corregido: exactamente 1 tool call por turno (no iterativo), (9) removidas todas las referencias a Apache AGE — nunca usado. Se preserva todo el contenido de v2.2 no afectado por estos cambios.

---

## Tabla de contenidos

1. [Visión y principios](#1-visión-y-principios)
2. [Arquitectura objetivo](#2-arquitectura-objetivo)
3. [Stack técnico definitivo](#3-stack-técnico-definitivo)
4. [Estructura del fork y separación de responsabilidades](#4-estructura-del-fork-y-separación-de-responsabilidades)
5. [Sistema de wake word y gestión de conversación](#5-sistema-de-wake-word-y-gestión-de-conversación)
6. [Personalidad: prompt caching y capas de contexto](#6-personalidad-prompt-caching-y-capas-de-contexto)
7. [MCP y tool calling: arquitectura híbrida](#7-mcp-y-tool-calling-arquitectura-híbrida)
8. [Roadmap por fases (con recomendaciones integradas)](#8-roadmap-por-fases)
9. [Catálogo completo de features recomendados](#9-catálogo-completo-de-features-recomendados)
10. [Costos consolidados](#10-costos-consolidados)
11. [Riesgos, advertencias y matriz de fallback](#11-riesgos-advertencias-y-matriz-de-fallback)
12. [Referencias](#12-referencias)
13. [Apéndice — Diferencias vs brief original y decisiones de diseño](#13-apéndice--diferencias-vs-brief-original-y-decisiones-de-diseño)

### Leyenda de urgencia usada en el roadmap

| Marca | Significado |
|---|---|
| 🔴 **Core / Crítico** | Parte integral de la fase. La fase no se considera completa sin esto. |
| 🟠 **Recomendado fuertemente** | Aporta valor alto y bajo costo marginal. Debería implementarse. |
| 🟡 **Opcional pero recomendable** | Buen upgrade. No bloqueante; depende de tiempo disponible. |
| 🔵 **Aplazable** | Se puede mover a una fase posterior sin consecuencias. |

---

## 1. Visión y principios

### 1.1 Qué es LUMI

LUMI es una asistente personal con avatar Live2D, voz, memoria persistente y personalidad propia, construida como fork de Open-LLM-VTuber (OLV). El objetivo final es un **desktop pet permanente en Windows** con capacidades crecientes hasta acercarse al modelo Neuro-sama (AI VTuber con gaming y streaming). Los usuarios son Jose y entre 1 y 3 personas cercanas.

El nombre **LUMI** (Listening Unified Memory Intelligence) expresa las tres capacidades nucleares del sistema: escucha continua, memoria unificada entre canales e inteligencia coordinada. En lo afectivo, el nombre tiene raíces en finés (*lumi* = nieve, pureza) y en latín (*lumen* = luz) — cualidades que la personalidad del personaje también lleva.

La fuente canónica de la personalidad, psicología y estilo conversacional de Lumi vive en `Lumi.md` (identidad, psicología, motivaciones) y `Lumi_implementation.md` (reglas operativas, registros, patrones de expresión). Este manual implementa la infraestructura para que esa personalidad se manifieste consistentemente.

### 1.2 Principio arquitectónico central

> **El VPS es el cerebro. OLV local es la capa sensorial y visual. Sin internet, Lumi duerme.**

El PC local en Windows 11 se encarga exclusivamente de captura (ASR), reproducción (TTS), avatar y wake word. Todo el razonamiento, memoria, búsqueda, routing y orquestación viven en el VPS. Esto permite multi-canal (Discord, WhatsApp, web) sin duplicar lógica, y deja la GPU local libre para gaming.

**Decisión explícita de arquitectura (v2.1):** Lumi no tiene fallback local. Si no hay conexión al VPS, Lumi está dormida. No se carga ningún LLM en CPU, y si en el futuro se carga uno local, será en GPU y como complemento, nunca como sustituto. La razón es simple: sin acceso a la memoria persistente, Lumi no es Lumi — sería un modelo base sin contexto, rompiendo la coherencia del personaje. Preferimos silencio a incoherencia.

### 1.3 Reglas no negociables

1. **Todo código custom de LUMI vive en `custom/`** del fork. La única modificación a `src/` de OLV es registrar el agente en `agent_factory.py`.
2. **Las actualizaciones de upstream OLV deben funcionar con `git merge upstream/main`** sin conflictos significativos.
3. **Un solo cerebro, múltiples canales:** Discord, WhatsApp, desktop pet y web apuntan al mismo VPS, misma memoria, misma personalidad.
4. **Sin internet o sin VPS, Lumi duerme con gracia.** No simula, no usa modelo local, no inventa respuestas. Un mensaje breve *"[neutral] Sin conexión al ecosistema. Volvemos cuando haya red."* y se queda en silencio hasta que la conectividad regrese.
5. **Privacidad por defecto:** las conversaciones no salen del VPS/local. APIs externas sólo con políticas de no-retención.
6. **VRAM 100% para gaming.** Al no haber LLM local, la GPU queda completamente libre para Star Citizen, Ark ASA o cualquier otra carga que Jose tenga activa.
7. **Agente ultra-ligero:** el servidor VPS del agente debe caber en ~500-800 líneas de Python. La complejidad se paga en claridad, no en líneas.

### 1.4 Restricciones del proyecto

- **Hardware local:** Ryzen 5700X, RX 7800 XT 16 GB, 32 GB RAM, Windows 11
- **GPU AMD en Windows:** reservada exclusivamente para gaming. No se ejecuta inferencia LLM local en ninguna fase. ASR usa CPU (NeMo Canary Flash 180M es lo suficientemente ligero).
- **Idioma:** español colombiano neutro, sin modismos regionales (sin *parcero*, *bacano*, *chimba*, *fresco*, *qué pena*). Registro limpio, educado, con mezcla natural de inglés técnico cuando corresponde (*commit*, *deployment*, *merge*, *debugging*).
- **Presupuesto infraestructura:** ideal ~$15/mes, techo aceptable ~$18/mes con prompt caching activo.
- **APIs LLM aceptadas:** Claude, Gemini, DeepInfra (Qwen). **Excluidos:** Groq y derivados de Llama directos.

---

## 2. Arquitectura objetivo

### 2.1 Diagrama de bloques

```
┌─────────────────────────────────────┐         ┌────────────────────────────────────────────────┐
│  PC LOCAL (Windows 11)              │         │  VPS CONTABO (Ubuntu 24.04)                    │
│  ─────────────────────              │         │  ──────────────────────                        │
│                                     │         │                                                │
│                                     │         │  Caddy (HTTPS, reverse proxy)                  │
│                                     │         │       │                                        │
│                                     │         │       ▼                                        │
│                                     │         │  FastAPI: agent/presence/app.py (v0.4.0)        │
│                                     │         │  ├─ cognition/attention.py  Keyword classifier │
│                                     │         │  ├─ cognition/stimulus.py    Message handlers  │
│                                     │         │  ├─ cognition/intention.py  Tool check (1/turn)│
│                                     │         │  ├─ cognition/working_memory.py  Prompt builder│
│                                     │         │  ├─ cognition/stream.py    Orquestador central │
│                                     │         │  ├─ expression/synapses.py  LLM factory (5+3)  │
│                                     │         │  │  MAIN: Gemma4→Qwen35B→Step→Qwen235B→Nemotron│
│                                     │         │  │  LIGHTWEIGHT: Mistral→DeepSeek→Qwen9B       │
│                                     │         │  └─ Stream de respuesta                        │
│                                     │         │       │                                        │
│                                     │         │       ▼                                        │
│                                     │         │  Mem0 REST API (mem0_server/)                   │
│                                     │         │  ├─ pgvector (host:5432)                       │
│                                     │         │  ├─ Entity linking en pgvector (nativo)        │
│                                     │         │  └─ Neo4j opcional (--profile graph)           │
│                                     │         │  Brave Search API (free tier)                  │
│                                     │         │  DeepInfra (5 modelos MAIN + 3 LIGHTWEIGHT)    │
│                                     │         │  Bases de datos:                               │
│                                     │         │  ├─ data/traces.db (historial, diario, sesión) │
│                                     │         │  └─ data/core.db (estado, personas, relaciones)│
│                                     │         │  APScheduler (rhythm/heartbeat.py)              │
│                                     │         │  ├─ 15min tick: mood check + idle decay        │
│                                     │         │  ├─ 7am daily: morning mood reset              │
│                                     │         │  ├─ 3am nightly: 8-step quiescence             │
│                                     │         │  └─ Mon 4am: weekly cleanup + decay            │
│                                     │         │                                                │
│                                     │         │  Canales adicionales (fase 6+):                │
│                                     │         │  ├─ Evolution API (WhatsApp)                   │
│                                     │         │  └─ discord.py bot                             │
│                                     │         │                                                │
│                                     │         │  Endpoints:                                    │
│                                     │         │  ├─ POST /v1/chat  (respuesta)                 │
│                                     │         │  ├─ POST /v1/observe (aprender solo)           │
│                                     │         │  └─ WSS /v1/bridge (MCP local calls)           │
└─────────────────────────────────────┘         └────────────────────────────────────────────────┘
```

### 2.2 Flujo de datos completo (canal voz, conversación normal)

```
1. Usuario habla → Micrófono PC
2. OLV ASR (sherpa-onnx Canary Flash local) → texto
3. LumiAgent.chat(BatchInput) recibe el texto
4. Wake detector custom evalúa: ¿está la ventana abierta o contiene "Lumi"?
5. Check de conectividad al VPS → si falla, modo dormida
6. Si pasa los filtros → POST https://vps:443/lumi/v1/chat con metadatos
7. VPS:
   a. `attention.classify()` — keyword router decide: chat, web_search, long_task, explicit_save
   b. `_entities_check()` — LLM ligero detecta menciones de terceros en el mensaje
   c. `_resolve_entities()` — resuelve personas contra known_persons + Mem0 scoped search
   d. `build_messages()` — construye sistema prompt: [CACHED PREFIX lumi_soul.md + attitude.md][dynamic suffix]
   e. `intention.decide_tool()` — 1 tool check ligero por turno (NO iterativo)
   f. POST a DeepInfra vía `expression/synapses.py` con fallback de 5 modelos MAIN
   g. Stream la respuesta hacia el cliente
   h. `_finalize_turn()` — guarda turnos + persiste menciones resueltas
8. LumiAgent local recibe el stream
9. Parsea emotion tag inicial → activa expresión Live2D vía OLV decorators
10. Si hay interrupción del usuario → engage interrupt handler (feature #19)
11. Detecta [ESCALAR] al final → si presente, re-llama a modelo especializado
12. Detecta [SEGUIMIENTO:...] al final → encola follow-up asociativo (feature #18)
13. Texto limpio → Edge TTS → audio
14. Avatar Live2D hace lip-sync con el audio
15. Wake detector refresca o cierra la ventana de conversación según corresponda
```

### 2.3 Flujo paralelo de observación pasiva (Fase 3+)

```
[Micrófono + Pantalla] en segundo plano
        │
        ▼
  Filtros locales (VAD, blacklist de apps, clasificador semántico)
        │
        ▼
  POST /v1/observe (no bloquea, no responde al usuario)
        │
        ▼
  VPS: extraction_agent ligero → Mem0 (tipo passive_observation)
```

### 2.4 Decisiones arquitectónicas clave

| Decisión | Elección | Razón |
|---|---|---|---|---|---|
| Cerebro local vs remoto | **Remoto (VPS)** | Multi-canal, gaming compatible, memoria centralizada |
| LLM principal | **Gemma4 26B + 4 fallbacks vía DeepInfra** | Cadena de 5 modelos MAIN con exponential backoff. Mejor precio/calidad, tool calling nativo |
| Fallback sin internet | **Lumi dormida** (sin LLM local) | Coherencia del personaje > disponibilidad parcial |
| GPU local | **100% para gaming** | No hay inferencia LLM local en ninguna fase |
| Memoria | **Mem0 + pgvector (Neo4j opcional)** | Mem0 v2.0.0: entity linking nativo en pgvector. Neo4j disponible vía `--profile graph` |
| ASR | **NeMo Canary Flash 180M (CPU)** | Soporta español, ligero, deja GPU libre |
| TTS | **Edge TTS** | Gratuito, calidad alta, sin setup |
| VPS | **Contabo VPS 20** (12 GB RAM) | Sweet spot precio/RAM para Mem0 + servicios |
| Embedder | **BAAI/bge-m3** vía DeepInfra | Multilingüe, óptimo para español, 1024 dims |
| Búsqueda web | **Brave Search API** + clasificador keywords | Free tier suficiente, baja latencia |
| Observación pasiva | **Screenpipe (pantalla) + always-on ASR** | Local, MIT, event-driven. Planificado, no wireado aún |
| MCP | **Híbrido: VPS + Bridge local** | Tools de web/datos en VPS; tools de sistema en local vía WebSocket |
| Filosofía del agente | **Ultra-ligero** | Loop + contexto + herramientas + memoria en `agent/cognition/` |
| Personalidad en prompt | **Dos markdown files cacheados** | `get_cached_prefix()` carga `lumi_soul.md` + `attitude.md` |
| Bases de datos | **data/traces.db + data/core.db** | SQLite: historial conversacional, diario, estado interno, personas, relaciones |
| Scheduler | **APScheduler** | 4 jobs: 15min tick, 7am morning, 3am nightly (8 pasos), Mon 4am weekly |

---

## 3. Stack técnico definitivo

### 3.1 LLM principal: cadena de fallback vía DeepInfra (con prompt caching)

**Modelos activos (orden de prioridad con exponential backoff):**

| Prioridad | Modelo | Rol |
|---|---|---|---|
| 1 (primario) | **google/gemma-4-26b-a4b** | Uso principal |
| 2 (fallback) | Qwen/Qwen3.5-35B-A3B | Si Gemma4 está saturado |
| 3 (fallback) | stepfun-ai/Step-3.5-Flash | Tercera opción |
| 4 (fallback) | Qwen/Qwen3-235B-A22B-Instruct-2507 | Cuarta opción |
| 5 (fallback) | nvidia/NVIDIA-Nemotron-3-Super-120B-A12B | Último recurso |

**Grupo LIGHTWEIGHT** (tool check, entity detection, memory extraction — ~200-500 tokens):

| Prioridad | Modelo | Rol |
|---|---|---|---|
| 1 | mistralai/Mistral-Small-3.2-24B-Instruct-2506 | Primario |
| 2 | deepseek-ai/DeepSeek-V4-Flash | Fallback |
| 3 | Qwen/Qwen3.5-9B | Último recurso |

Todos vía DeepInfra (`DEEPINFRA_API_KEY`, base URL `https://api.deepinfra.com/v1/openai`). La fábrica LLM en `agent/expression/synapses.py` prueba cada modelo en orden, con 2 reintentos por modelo (exponential backoff: 2^attempt segundos). Si todos fallan, lanza `RuntimeError`.

**⚠️ Quirk crítico — `extra_body` por modelo:**

Cada modelo espera parámetros diferentes en `extra_body`. Si se usa el incorrecto, la API falla:

| Modelo | `extra_body` | Nota |
|---|---|---|---|
| google/gemma-4-26b-a4b | *(sin `extra_body`)* | No acepta `chat_template_kwargs`; sí acepta `reasoning_effort` como parámetro top-level |
| Qwen/Qwen3.5-35B-A3B | `{"top_k": 20, "chat_template_kwargs": {"enable_thinking": bool}}` | Soporta modo thinking |
| stepfun-ai/Step-3.5-Flash | `{"reasoning_effort": "none"}` | NO acepta `chat_template_kwargs` |
| Qwen/Qwen3-235B-A22B-Instruct-2507 | `{"top_k": 20}` | Solo `top_k`; esta versión no usa `chat_template_kwargs` |
| NVIDIA-Nemotron-120B | *(sin `extra_body`)* | No acepta ninguno de los anteriores |
| mistralai/Mistral-Small-24B | `{"reasoning_effort": "none"}` | Solo cuando `thinking=False` |
| deepseek-ai/DeepSeek-V4-Flash | `{"reasoning_effort": "none"}` | Solo cuando `thinking=False` |
| Qwen/Qwen3.5-9B | `{"top_k": 20, "chat_template_kwargs": {"enable_thinking": bool}}` | Misma familia Qwen |

Los wrappers individuales en `agent/expression/providers/` (uno por modelo) encapsulan estas diferencias. Al agregar un modelo nuevo, el `extra_body` debe coincidir exactamente con lo que el proveedor espera.

**Caching de prompt:**

DeepInfra soporta prompt caching. El system prompt (personalidad, ~2,500 tokens) se cachea automáticamente con ~90% de descuento sobre el costo de input. El TTL es de 5-10 minutos de inactividad. La estructura del prompt es disciplinada: todo lo estable al inicio (cached), todo lo variable al final. Ver sección 6 para la composición.

**Por qué Gemma4 26B como primario (nuevo en v2.3):**

- Arquitectura MoE — calidad alta con eficiencia
- 4M contexto nativo
- Excelente soporte multilingüe, español first-class
- Tool calling nativo OpenAI-compatible
- Prompt caching reduce el costo del card grande

**Lo que sigue sin ofrecer DeepInfra:**

- ❌ Web search nativo (se usa Brave Search API)
- ❌ Visión (para multimodal hay que pasar a Qwen3-VL aparte)
- ❌ Fine-tuning gestionado (sólo despliegue de LoRAs entrenados afuera)

### 3.2 LLMs especializados (mecanismo `[ESCALAR]`)

LUMI puede invocar modelos especializados cuando el principal no alcanza. El tag `[ESCALAR]` al final de la respuesta es el disparador. Casos previstos:

| Caso | Modelo | Cuándo |
|---|---|---|
| Coding pesado | Qwen3-Coder vía DeepInfra | Fase 5+ |
| Visión / screenshots | Gemini 2.5 Flash free tier | Fase 7 |
| Investigación profunda | DeepSeek V3.1 vía DeepInfra | Fase 5+ |
| Generación de imágenes | Stable Diffusion / FLUX vía DeepInfra | Fase 8+ |

### 3.3 ASR: NeMo Canary Flash 180M (CPU)

**Decisión crítica:** SenseVoiceSmall (el default de OLV) **no soporta español** — sólo zh/en/ja/ko/yue. Esto invalida el setup out-of-the-box de OLV para LUMI.

**Modelo elegido:** `sherpa-onnx-nemo-canary-180m-flash-en-es-de-fr-int8`

- Soporta inglés + **español** + alemán + francés
- 180M parámetros en int8: ligero, RTF excelente en Ryzen 5700X
- Origen NVIDIA NeMo, calidad probada, licencia permisiva

**Provider:** CPU con `num_threads: 6`. Razones:

- Deja la GPU 100% libre para gaming (no hay LLM local que ocupe VRAM tampoco)
- Canary Flash 180M es lo bastante ligero para no saturar el CPU
- Evita complejidad de build con DirectML o GPU

**Aceleración GPU disponible (descartada):**

- sherpa-onnx **NO soporta Vulkan** en ONNX Runtime
- sherpa-onnx **SÍ soporta DirectML** en Windows pero no vale la pena — la GPU es para gaming y el CPU maneja Canary Flash cómodamente

**Alternativa de calidad superior:** Whisper-small multilingüe vía sherpa-onnx, si el español de Canary no convence en testing real.

**Acción inmediata para validar:** grabar 5-10 frases en tu voz con acento paisa mezclando técnico inglés/español ("commit", "deployment", "merge"), medir WER y latencia. Si Canary Flash pasa, va al MVP.

### 3.4 TTS: Edge TTS

- Voz principal: **`es-CL-CatalinaNeural`** (Catalina, español Chile, voz neutral latinoamericana adecuada para LUMI)
- Gratuito, sin límites conocidos para uso personal
- Requiere internet — sin conexión, Lumi está dormida (consistente con la política de v2.1)
- Alternativas offline a evaluar en Fase 5: GPT-SoVITS (mejor integración OLV), Kokoro, Piper

### 3.5 Avatar: Live2D Cubism 5

- **MVP:** modelo `mao_pro` incluido en OLV
- **Emotion tags:** OLV parsea `[neutral] [happy] [sad] [thinking] [surprised] [playful]` y los mapea a expresiones del modelo automáticamente
- **Lip-sync:** OLV lo maneja con el audio del TTS
- **Custom Live2D futuro:** apariencia ya definida en `Technical_sheet.md` y `Lumi.md` (cabello plateado largo, ojos aqua turquesa `#5BC8B8`, piel `#F4E0D0`, 155 cm, proporciones 7-head ratio). Roadmap en Fase 5.
- **Character Status Panel (OLV v1.4 roadmap):** el roadmap oficial de OLV incluye un panel UI para mostrar mood, affinity, current thoughts del personaje — directamente compatible con nuestro `lumi_internal_state`. Integración prevista cuando OLV v1.4 esté disponible.

### 3.6 Memoria: Mem0 con pgvector + Neo4j (opcional)

**Stack en VPS:**

- Mem0 REST API (FastAPI) — servicio Docker separado en `mem0_server/`, mapeado a host:8100
- PostgreSQL con pgvector (imagen `ankane/pgvector:v0.5.1`) — host:5432
- Neo4j 5.26.4 — opcional, detrás de `docker compose --profile graph`

**Arquitectura actual:**

Mem0 v2.0.0 eliminó el soporte nativo para Neo4j como graph store. El entity linking (relaciones entre entidades) se maneja internamente en pgvector mediante la tabla `memories_entities`. Esto significa que **no se requiere un graph store externo** para la funcionalidad base de memoria semántica.

La configuración activa en `mem0_server/main.py` incluye únicamente:
- `vector_store.provider = "pgvector"` (con `embedding_model_dims: 1024`)
- `llm.provider = "openai"` apuntando a DeepInfra (modelo extractor: `mistralai/Mistral-Small-3.2-24B-Instruct-2506`)
- `embedder.provider = "openai"` con `BAAI/bge-m3` (1024 dimensiones)

**Neo4j** permanece en `docker-compose.yml` como servicio opcional (perfil `graph`) para casos donde se necesite consulta de grafos explícita, pero no es parte del pipeline de memoria estándar.

**Memoria de tres niveles:**

| Nivel | Backend | Propósito |
|---|---|---|
| Historial conversacional | SQLite (`data/traces.db`, vía `agent/memory/episodic.py`) | Turno-a-turno, acceso secuencial, últimos N turnos |
| Memoria semántica | Mem0 + pgvector (host:8100, vía `agent/memory/semantic.py`) | Hechos, personas, conocimiento persistente |
| Estado interno | SQLite (`data/core.db`, vía `agent/subconscious/`) | Estado de Lumi, personas conocidas, relaciones, interest scores |

Esta separación es intencional: el historial secuencial no pertenece a Mem0 porque es acceso temporal, no semántico. El código en `agent/memory/__init__.py` es la fachada pública que el loop importa.

**Embedder:** `BAAI/bge-m3` vía DeepInfra — multilingüe, óptimo para español, 1024 dimensiones.

**LLM extractor:** `mistralai/Mistral-Small-3.2-24B-Instruct-2506` vía DeepInfra — separado del LLM conversacional de Lumi.

### 3.7 Búsqueda web: Brave Search API

- Free tier: 2,000 requests/mes — suficiente para uso personal intenso
- Activación: clasificador keywords pre-LLM en `agent/cognition/attention.py`

**Mecanismo implementado (híbrido en cascada):**

| Capa | Método | Latencia | Costo | Precisión |
|---|---|---|---|---|
| 1ª | Regex / keywords (pre-filtro) | ~4 ms | Gratis | Baja (captura casos obvios) |
| 2ª | Semantic Router (embeddings locales) | ~10-50 ms | Gratis | 92-96% con ejemplos afinados |
| 3ª | LLM tool calling (modelo decide) | LLM call completo | Tokens | Máxima (juicio del modelo) |

El regex + Semantic Router captura ~80-90% de los casos. El LLM maneja los casos ambiguos restantes. Para fecha/hora, inyectar en el system prompt es la solución más simple y sin latencia adicional.

### 3.8 Hosting: Contabo VPS 20

**Plan elegido:** Cloud VPS 20

- **6 vCPU, 12 GB RAM, 100 GB NVMe**
- **~$8/mes** en facturación anual
- Región recomendada: **US East** (latencia Colombia→VPS de 70-120 ms vs 150-180 ms desde Frankfurt; además DeepInfra tiene GPUs en US, así que el hop VPS→LLM es casi gratis)

**Por qué no VPS 10:**

- VPS 10 (8 GB RAM, ~$5/mes) funciona para Fase 3 pero queda al límite cuando entra Mem0 en Fase 4
- Cálculo de uso con VPS 10 + Mem0 + AGE: ~5.25 GB en uso normal, ~2.75 GB libres — sin margen real
- Diferencia de $36/año no compensa la fricción de migrar la base de datos después

**Por qué no Hetzner (alternativa común):**

- Hetzner CX32 (~$7/mes, 4 vCPU, 8 GB) es mejor en performance pero tiene menos RAM
- Sin datacenter LatAm, mismas opciones EU/US que Contabo
- Reservar como Plan B si Contabo da problemas de IP/soporte

**Advertencias del mercado 2026 sobre Contabo:**

- Reputación de soporte lento y CPU/red por debajo de Hetzner o DigitalOcean
- Reportes ocasionales de IPs reasignadas con abuse history previa — si te toca, abrir ticket inmediatamente y solicitar cambio
- Para side-project personal los trade-offs son aceptables

### 3.9 Observación pasiva (componentes extra)

**Audio always-on (Fase 3-4):**

- Reutiliza sherpa-onnx + NeMo Canary Flash ya instalado
- Sólo se activa cuando OLV está abierto y en primer plano
- Filtros locales: VAD, clasificador de primera persona (sin diarización en MVP)

**Pantalla (Fase 4-5):** **Screenpipe** (https://github.com/screenpipe/screenpipe)

- MIT License, 100% local, datos en SQLite
- Event-driven capture (~5-10% CPU, ~5-10 GB/mes storage)
- OCR + accessibility tree, multi-monitor, REST API en `localhost:3030`
- Plugin system (Pipes) en markdown + YAML config
- MCP server compatible (se expone al VPS vía MCP Bridge local — ver sección 7)

**Alternativa más simple (Fase 7):** python-mss + VLM local (moondream2 o Qwen2.5-VL 7B Q4) si screenpipe resulta demasiado pesado o no se quiere la dependencia.

---

## 4. Estructura del repositorio y separación de responsabilidades

**Nota importante (v2.3):** Lumi tiene dos repositorios separados:

1. **`lumi-vps`** (este repo) — Backend que corre en el VPS Contabo. Contiene el agente, la API, el bridge server, Mem0 y las políticas de personalidad. Es lo que se describe en esta sección.
2. **Fork de OLV** (repo separado) — Código local en Windows. Contiene `LumiAgent(AgentInterface)`, wake word detector, bridge client, interrupt handler, y la capa sensorial/visual. No se describe aquí.

El código en `lumi-vps` NO es un fork de OLV — es una app FastAPI independiente.

```
lumi-vps/                              ← Backend VPS (ESTE repo)
├── agent/                             ← App principal FastAPI "LUMI VPS" (v0.4.0)
│   ├── presence/
│   │   ├── app.py                     ← FastAPI entrypoint (root_path="/lumi")
│   │   └── conduits/
│   │       ├── group_policy.py        ← Group channel behavior rules
│   │       └── whatsapp_adapter.py    ← WhatsApp placeholder adapter
│   ├── cognition/
│   │   ├── stream.py                  ← Orquestador central: cycle() / run_stream()
│   │   ├── attention.py               ← Keyword classifier (chat|web_search|long_task|explicit_save)
│   │   ├── stimulus.py                ← Handlers: long_task + explicit_save
│   │   ├── intention.py               ← Tool check (1/turn) + tool registration
│   │   └── working_memory.py          ← System prompt: cached prefix + dynamic suffix
│   ├── expression/
│   │   ├── synapses.py                ← LLM factory: 2 model groups + exponential backoff
│   │   └── providers/                 ← One class per model (BaseLLM ABC)
│   │       ├── base.py                ← Abstract BaseLLM
│   │       ├── qwen3_5_35b.py         ← Qwen3.5-35B-A3B (MAIN #2)
│   │       ├── step_3_5_flash.py      ← Step-3.5-Flash (MAIN #3)
│   │       ├── nemotron_super_120b.py ← Nemotron-120B (MAIN #5)
│   │       ├── qwen3_235b_a22b.py     ← Qwen3-235B-A22B (MAIN #4)
│   │       ├── gemma_4_26b_a4b.py     ← Gemma4 26B (MAIN #1, primario)
│   │       ├── mistral.py             ← Mistral Small 24B (LIGHTWEIGHT #1)
│   │       ├── deepseek.py            ← DeepSeek V4 Flash (LIGHTWEIGHT #2)
│   │       └── qwen_9b.py             ← Qwen3.5-9B (LIGHTWEIGHT #3)
│   ├── faculties/                     ← Tool implementations
│   │   ├── base.py                    ← BaseTool ABC
│   │   ├── brave_search.py            ← Brave Search API tool
│   │   ├── registry.py                ← ToolRegistry (local + remote)
│   │   └── dispatcher.py              ← Tool execution dispatch
│   ├── affect/
│   │   ├── __init__.py                ← Public API exports
│   │   ├── mood.py                    ← Mood CRUD: state, deltas, morning_reset, sleep_stages, honesty_mode
│   │   └── evaluation.py              ← idle_decay() + LLM contextual mood evaluation
│   ├── memory/
│   │   ├── __init__.py                ← Public API (single import point for all memory)
│   │   ├── episodic.py                ← traces.db: history, mood_logs, diary entries
│   │   ├── semantic.py                ← Mem0 REST client (add, search, search_person, save_explicit)
│   │   └── mindstream/
│   │       ├── social.py              ← known_persons CRUD, relations, aliases, resolve, deltas, decay
│   │       ├── mentions.py            ← person_mentions table (per-turn entity tracking)
│   │       ├── consolidation.py       ← LLM-powered: entity consolidation, interest deltas, diary
│   │       └── cleanup.py             ← Periodic DB pruning (history, mood_logs, heartbeat_runs)
│   ├── rhythm/
│   │   ├── heartbeat.py               ← APScheduler job registration + start
│   │   ├── cadence.py                 ← Timing constants (15min, 7am, 3am, Mon 4am)
│   │   ├── state.py                   ← Execution tracker (heartbeat_state / heartbeat_runs)
│   │   └── routines/
│   │       ├── pulse.py               ← 15min tick: mood check + idle decay
│   │       ├── morning.py             ← 7am daily: morning mood regression
│   │       ├── quiescence.py          ← 3am nightly: 8-step orchestration (2 wired, 6 stubs)
│   │       └── forgetting.py          ← Mon 4am: cleanup wired, interest_decay stub
│   ├── subconscious/                  ← Singleton database access layer
│   │   ├── __init__.py                ← traces + core singletons + init_databases()
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── traces.py              ← TracesRepository (data/traces.db)
│   │   │   └── core.py                ← CoreRepository (data/core.db)
│   │   ├── migrations/                ← Idempotent SQL schema files
│   │   └── seeds/                     ← Initial seed data
│   ├── perception/
│   │   └── websocket.py               ← MCP Bridge WebSocket server (VPS↔PC)
│   ├── identity/
│   │   ├── lumi_soul.md               ← Core personality (identity, voice, emotional architecture, moral compass)
│   │   ├── attitude.md                ← Expressive framework (emotion tags, mood-to-attitude mapping)
│   │   └── principles/                ← Behavioral rule docs (read-only policy)
│   │       ├── interest_policy.md     ← How interest_score evolves per person (nightly batch)
│   │       ├── memory_policy.md       ← What semantic data to store in Mem0 by interest level
│   │       ├── memory_search.md       ← 5-step memory search pipeline
│   │       ├── mood_policy.md         ← Internal mood state fields, baselines, deltas, drift
│   │       ├── reflection_policy.md   ← 11-stage session close pipeline
│   │       ├── relation_policy.md     ← Third-party relation storage and inference
│   │       └── skill_evolution.md     ← Automated skill proposal system (disabled first 90 days)
│   └── substrate/
│       ├── __init__.py
│       ├── logger.py                  ← Shared logger with COL (UTC-5) timestamps
│       └── nightly_log.py             ← Structured logging for nightly maintenance runs
├── mem0_server/                       ← Servicio Mem0 REST API (Dockerizado)
│   ├── main.py                        ← FastAPI en container:8000 → host:8100
│   └── requirements.txt
├── data/                              ← SQLite databases (runtime, gitignored)
│   ├── traces.db                      ← Conversation history, sessions, diary, heartbeat_runs
│   └── core.db                        ← Lumi state, known_persons, relations, skill_proposals, heartbeat_state
├── caddy/
│   └── Caddyfile                      ← Reverse proxy: api.drykolf.xyz/lumi/* → :8000
├── docker-compose.yml                 ← Servicios: postgres + mem0 + neo4j (opcional)
├── Dockerfile.mem0                    ← Imagen Docker del servidor Mem0
├── pyproject.toml                     ← Manifiesto Python (uv)
├── uv.lock                            ← Lockfile de dependencias
├── .env.example                       ← Template de variables de entorno
├── .gitignore
└── .venv/                             ← Virtual environment (uv)
```

### 4.1 Componentes planificados para fases futuras

Los siguientes módulos están diseñados en el manual pero **no implementados aún** en el código:

| Módulo | Fase prevista | Estado |
|---|---|---|---|
| `channels/` (adapters) | Fase 6 | No implementado |
| `mcp_servers/calendar/` | Fase 5-6 | No implementado |
| `agent/presence/conduits/discord_adapter.py` | Fase 6 | No implementado |
| `agent/faculties/clipboard_tool.py` | Fase 4+ | Schema registrado como remote, implementación local pendiente |
| Quiescencia steps 3-5, 7-8 | Fase 4 (Block 5) | Stubs (`...`) en `agent/rhythm/routines/quiescence.py` |
| Weekly interest decay | Fase 4 (Block 5) | Stub (`...`) en `agent/rhythm/routines/forgetting.py` |
| Mem0 fact extraction per turn | Fase 4 | `add_memory()` existe pero no se llama desde el agent loop |

### 4.2 Filosofía del código

El servidor VPS sigue el principio de agente ultra-ligero. Cada archivo tiene una sola responsabilidad.

**Estructura del loop principal** (implementado en `agent/cognition/stream.py`):

- Dos entrypoints: `run()` (retorna string) y `run_stream()` (async generator, usado por `/v1/chat`)
- Clasificación pre-LLM con `attention.classify()`: detecta `long_task`, `explicit_save`, `web_search`, `chat`
- **Exactamente 1 tool call por turno** — `intention.decide_tool()` ejecuta un check ligero antes del LLM principal. NO es iterativo.
- `_entities_check()` — LLM ligero detecta menciones de terceros en cada turno
- `_resolve_entities()` — resuelve contra known_persons + busca en Mem0 scoped
- `build_messages()` — construye el prompt con cached prefix + dynamic suffix
- `_finalize_turn()` — guarda turnos + persiste menciones con estado de resolución

**Loop canónico** (simplificado de `agent/cognition/stream.py`):

```python
async def cycle(user_id, message, metadata):
    # Sleep check
    if get_sleep_stage(...) == "sleeping":
        yield "[tired] Zzz..."
        return

    task_type = attention.classify(message)
    
    if task_type == "long_task":
        reply = await handle_long_task(user_id, message, sid)
        _finalize_turn(user_id, message, reply, sid)
        yield reply; return

    if task_type == "explicit_save":
        reply = await handle_explicit_save(user_id, message, sid, metadata)
        _finalize_turn(user_id, message, reply, sid)
        yield reply; return

    # Entity detection + resolution (1 turn = 1 LLM check)
    entities = await _entities_check(message, sid, user_id)
    entities_context = await _resolve_entities(entities, user_id, message)
    
    # Build context: cached prefix + dynamic suffix + history
    messages = await build_messages(user_id, message, metadata,
                                     entities_context=entities_context)

    # Single tool check (NOT iterative)
    tool, args = await intention.decide_tool(sid, message, user_id=user_id)
    if tool and args is not None:
        # Execute tool + append results to messages
        tool_results = await intention.execute([...], user_id)
        messages.append(...)

    # Stream final response
    full_reply = ""
    async for chunk in chat_stream(messages, ...):
        full_reply += chunk
        yield chunk

    # Finalize: save turns + persist resolved mentions
    _finalize_turn(user_id, message, full_reply, sid,
                    entities=entities, entities_context=entities_context)
```

### 4.3 Selección de modelo y fallback

La fábrica en `agent/expression/synapses.py` mantiene dos grupos de modelos (`ModelGroup.MAIN` con 5 modelos, `ModelGroup.LIGHTWEIGHT` con 3 modelos). Cada modelo se prueba hasta 2 veces con exponential backoff. Si un modelo falla por rate limit, se pasa al siguiente. Ver sección 3.1 para los detalles de `extra_body` por modelo.

### 4.4 Stack técnico del VPS

| Componente | Puerto (host) | Binding |
|---|---|---|
| FastAPI principal | 8000 | Caddy reverse proxy |
| Mem0 REST API | 8100 | 127.0.0.1 (solo interno) |
| PostgreSQL (pgvector) | 5432 | 127.0.0.1 |
| Neo4j (opcional) | 7474, 7687 | 127.0.0.1, perfil `--profile graph` |

Caddy expone `api.drykolf.xyz/lumi/*` → `localhost:8000` con HTTPS automático (Let's Encrypt). Mem0 y Postgres no están expuestos al exterior — el hardening se aplica desde `docker-compose.yml`.

---

## 5. Sistema de wake word y gestión de conversación

Este es uno de los componentes más críticos del sistema y necesita diseño cuidadoso. Determina **cuándo Lumi responde y a quién**.

### 5.1 Reglas de activación por canal

**Canales de texto (Discord, WhatsApp, chat UI web):**
Siempre responde. No hay wake word. Cualquier mensaje de texto activa Lumi directamente.

**Canal de voz (ASR):**
El ASR transcribe continuamente. Cada transcripción pasa por el filtro de la sección 5.2.

### 5.2 Máquina de estados de la ventana de conversación

```
Transcripción recibida del ASR
        │
        ▼
Check de conectividad al VPS
        │
    FAIL ─→ Reproducir mensaje de "Lumi dormida" (primera vez por sesión offline)
        │    Silencio hasta que la conectividad regrese.
        │
    OK ──┤
         ▼
¿Hay una conversación activa? (ventana de 5 min)
        │
    SÍ ─┤──→ ¿El mensaje contiene "Gracias Lumi" explícito?
        │            │
        │        SÍ ─┤──→ Enviar al LLM → Responder → CERRAR ventana
        │            │
        │        NO ─┤──→ Enviar al LLM → Responder → REFRESCAR ventana
        │
    NO ─┤──→ ¿Contiene "Lumi" en alguna parte del mensaje?
                │
            SÍ ─┤──→ ABRIR ventana → Enviar al LLM → Responder
                │
            NO ─┤──→ ¿Modo always-on activo? → POST /v1/observe (aprende, no responde)
                     De lo contrario → Descartar
```

**Parámetros:**

- Duración de ventana: 5 minutos desde el último mensaje respondido
- Refresco: cada vez que Lumi responde
- Cierre explícito: detección de "gracias Lumi" (insensible a mayúsculas, tolerante a puntuación)
- Cierre automático: timeout de 5 min sin actividad
- Check de conectividad: ping al VPS cada 30 seg cuando hay ventana activa, cada 2 min cuando está cerrada

### 5.3 Modo dormida

Cuando Lumi no puede alcanzar el VPS (sea porque no hay internet o porque el VPS está caído):

1. La primera transcripción con "Lumi" en una sesión offline dispara **una sola vez** el mensaje canned: *"[neutral] Sin conexión al ecosistema. Volvemos cuando haya red."*
2. A partir de ahí, silencio total hasta que la conectividad regrese.
3. Cuando la conectividad vuelve y Lumi vuelve a escuchar "Lumi", responde con un reconocimiento neutro pero consciente: *"[neutral] Ya estoy de vuelta. ¿En qué íbamos?"*
4. El estado interno registra el período de dormida pero **no lo expresa** salvo que Jose pregunte directamente.

### 5.4 Tags de contexto enviados al VPS

Cada mensaje que sale del cliente local hacia el VPS lleva metadatos estructurados:

```json
{
  "content": "el mensaje limpio sin wake word",
  "source": "asr" | "text",
  "channel": "desktop" | "discord" | "whatsapp" | "web",
  "user_id": "jose" | "persona_2" | "guest",
  "conversation_active": true,
  "timestamp": "2026-04-08T15:23:01-05:00",
  "session_id": "uuid-de-la-ventana-actual",
  "was_interruption": false,
  "interrupt_context": null
}
```

El `session_id` permite al VPS agrupar mensajes de una misma ventana sin tener que reconstruirlo del historial completo. Los campos `was_interruption` e `interrupt_context` son usados por la feature #19 (sección 9.19).

### 5.5 Roadmap del wake word

| Fase | Mejora |
|---|---|
| MVP | Detección literal de "Lumi" + ventana de 5 min + modo dormida sin internet |
| Fase 3-4 | Modo always-on pasivo (escucha y aprende cuando OLV está abierto) |
| Fase 5 | Integración con interrupt handler (feature #19) |
| Fase 6+ | Tag `speaker_id` con diarización (Jose vs otra persona) |
| Fase 6+ | Tag `speaker_tone: happy / frustrated / neutral` para que Lumi adapte respuesta al estado emocional detectado del audio |

### 5.6 Identificación de usuario por voz: problema abierto

El brief asume `user_id` confiable en cada request, pero para canal voz no hay forma trivial de distinguir Jose de otra persona sin diarización. Estrategia recomendada:

- **MVP Fase 3:** asumir "cualquier voz local = Jose". Si alguien más habla, modo manual explícito ("Lumi, este es Juan").
- **Fase 6+:** integrar **pyannote.audio** para speaker diarization + speaker embedding enrollment (Lumi aprende tu voz al inicio, luego reconoce).
- **Alternativa pragmática siempre disponible:** `user_id` por dispositivo, no por voz. Micrófono PC = jose, bot Discord = jose, número WhatsApp = jose, otros dispositivos = invitado. Menos elegante pero 100% determinístico.

---

## 6. Personalidad: prompt caching y capas de contexto

### 6.1 Cambio de paradigma en v2.1

La versión anterior de este manual separaba el card de personalidad en dos archivos: `lumi_card_runtime.json` (ligero, viajaba en cada request) y `lumi_card_reference.json` (completo, vivía en disco). La razón era ahorrar costos en DeepInfra, que no tenía prompt caching.

**Esto ya no es necesario.** DeepInfra activó prompt caching nativo. La consecuencia directa:

- La personalidad completa (lumi_soul.md + attitude.md) viaja en cada request
- Pero cachea automáticamente, pagando ~10% del costo original
- No hay que "recortar" la personalidad para ahorrar plata
- Lumi es más consistente porque el modelo ve la personalidad entera cada turno

**Archivos fuente (v2.3):** `agent/identity/lumi_soul.md` (personalidad central: identidad, voz, arquitectura emocional, brújula moral) + `agent/identity/attitude.md` (marco expresivo: emotion tags, mapeo mood→actitud). Son archivos markdown que se concatenan y cachean como system prompt prefix. No hay JSON ni Character Card V3 — el formato es markdown directo.

### 6.2 Estructura del system prompt por capas

El prompt debe estructurarse en dos bloques estrictamente separados para maximizar el cache hit rate:

```
╔══════════════════════════════════════════════════════════════╗
║ BLOQUE CACHED (estable, ~2,200-2,700 tokens)                 ║
║                                                              ║
║ [1] agent/identity/lumi_soul.md (cargado una vez, ~118 líneas) ║
║     - Identity & alignment (Guardian Mind, INTJ)             ║
║     - Ámbito principal (arquitectura de vida, criterio)      ║
║     - Perfil psicológico Big Five                            ║
║     - Arquetipo, motivaciones, miedo real                    ║
║     - Brújula moral                                          ║
║     - Carácter relacional (Jose / terceros) — jerárquico     ║
║     - Espectro emocional                                     ║
║                                                              ║
║ [2] agent/identity/attitude.md (cargado una vez, ~284 líneas) ║
║     - Emotion tags obligatorios + lista estática             ║
║     - Inner thoughts format                                  ║
║     - Voz y lenguaje (español colombiano, longitud)          ║
║     - Jerarquía relacional operativa (con tabla de scores)   ║
║     - Conversaciones grupales (WhatsApp, Discord)            ║
║     - Tag [ignore]                                           ║
║     - Mapeo mood → attitude y contexto → emoción activa      ║
║     - Ejemplos por escenario (Jose 1:1, tercero, grupo)      ║
╚══════════════════════════════════════════════════════════════╝
╔══════════════════════════════════════════════════════════════╗
║ BLOQUE DYNAMIC (cambia cada request, ~800-1200 tokens)       ║
║                                                              ║
║ [3] Ubicación (fija)                                         ║
║ [4] Sleep stage (estable por horas) — drowsy / sleepy        ║
║ [5] Diary entries recientes (estable por día, 3am)           ║
║ [6] Estado interno (actualizado cada ~15min)                  ║
║     - mood_valence, mood_energy, irritation, focus_level     ║
║     - state_label, state_sentence                            ║
║     - emotional_honesty_mode (si activo)                     ║
║ [7] Perfil del hablante (estable por usuario)                 ║
║ [8] Personas mencionadas + relaciones (por turno)             ║
║ [9] Memoria relevante: Mem0 + scoped por persona (por turno) ║
║ [10] Contexto: canal, sesión, hora (por turno)               ║
╚══════════════════════════════════════════════════════════════╝
```

**Regla crítica:** cualquier cambio en el bloque cached — incluso una coma — invalida el cache y la siguiente request paga precio completo. `working_memory.py` debe garantizar que el bloque [1]-[2] sea **byte-idéntico** entre sesiones mientras no cambien los archivos fuente.

### 6.3 Construcción del prompt (implementado)

```python
# agent/cognition/working_memory.py — implementación real

SOUL_PATH   = Path(__file__).parent.parent / "identity" / "lumi_soul.md"
ATTITUDE_PATH = Path(__file__).parent.parent / "identity" / "attitude.md"

_cached_prefix = None  # Se construye una vez al importar

def _build_cached_prefix() -> str:
    """Carga los dos archivos markdown y los cachea. Se llama UNA sola vez."""
    parts = []
    if SOUL_PATH.exists():
        parts.append(SOUL_PATH.read_text(encoding="utf-8"))
    if ATTITUDE_PATH.exists():
        parts.append(ATTITUDE_PATH.read_text(encoding="utf-8"))
    if parts:
        return "\n\n---\n\n".join(parts)
    return "Eres Lumi, asistente personal de Jose Barco..."  # Fallback hardcoded

def get_cached_prefix() -> str:
    """Retorna el prefix cacheado. Lo construye en el primer llamado."""
    global _cached_prefix
    if _cached_prefix is None:
        _cached_prefix = _build_cached_prefix()
    return _cached_prefix

async def _build_dynamic_suffix(user_id, message, metadata, entities_context) -> str:
    """Construye la sección variable en orden: estático → estable-horas → 
    estable-día → cada-15min → por-turno."""
    state = get_state()
    now_str = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")
    
    parts = []
    
    # 1. Ubicación (fija)
    parts.append("[Ubicacion] ...")
    
    # 2. Sleep stage (estable por horas)
    stage = get_sleep_stage(tz)
    if stage == "drowsy":   parts.append("[Modo descanso] ...")
    elif stage == "sleepy": parts.append("[Modo descanso] ...")
    
    # 3. Diary entries (estable por día)
    diary_block = await _build_diary_suffix(user_id)
    if diary_block: parts.append(diary_block)
    
    # 4. Estado interno (~15min)
    parts.append("[Estado interno] " + state_to_text(state))
    if state.get("emotional_honesty_mode"):
        parts.append("[Modo honestidad emocional] ...")
    
    # 5. Perfil del hablante
    speaker_parts, display = _format_speaker_block(user_id)
    parts.extend(speaker_parts)
    
    # 6. Entidades del turno
    entity_sections, scoped_memories = _format_entity_sections(
        entities_context, user_id, display
    )
    parts.extend(entity_sections)
    
    # 7. Memoria relevante (deduplicada)
    relevant = await search_relevant(user_id, message)
    all_memories = merge(relevant, scoped_memories)
    deduped = _dedup_memories(all_memories, recent_turns)
    if deduped:
        parts.append("[Memoria relevante]\n" + "\n".join("- " + m for m in deduped))
    
    # 8. Contexto (más volátil — va al final)
    parts.append(f"[Contexto] Canal: {channel} | Sesion: {sid} | Hora: {now_str}")
    
    return "\n\n".join(parts)

async def build_messages(user_id, message, metadata, entities_context=None):
    cached = get_cached_prefix()
    dynamic = await _build_dynamic_suffix(user_id, message, metadata, entities_context)
    system_prompt = cached + "\n\n---\n\n" + dynamic
    
    sid = metadata.get("session_id", "default")
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    
    session_turns = get_recent_session_log(sid, since_ts=since, limit=100)
    cross_turns = get_recent_user_log(user_id, since_ts=since, ...)
    
    messages = [{"role": "system", "content": system_prompt}]
    if cross_turns:
        messages.append({"role": "user", 
                         "content": "[Conversaciones anteriores]\n\n" + 
                                    format_turns_grouped(cross_turns, ...)})
    messages.extend(_turns_to_messages(session_turns))
    messages.append({"role": "user", "content": f"{user_id}: {message}"})
    return messages
```

### 6.4 Resultado actual

- **System prompt por request:** ~3,200-3,700 tokens (~2,200-2,700 cached + ~1,000 dynamic)
- **Costo con caching:** la primera request del período paga costo completo, el resto ~10%
- **Personalidad consistente:** el modelo ve lumi_soul.md + attitude.md completos siempre
- **Tool definitions:** se pasan como parámetro `tools` en la llamada a la API, NO en el system prompt. Se registran dinámicamente en `intention.py`.
- **Entity injection:** las personas mencionadas se resuelven en tiempo real y se inyectan con score, tone, relaciones y memorias scoped.
- **Diary**: los entries generados por el consolidator nocturno se inyectan en el dynamic suffix.

### 6.5 Roadmap de personalidad

| Fase | Estrategia |
|---|---|
| MVP/Fase 3 | Markdown files cacheados en módulo (`get_cached_prefix()` en `agent/cognition/working_memory.py`) |
| Fase 3-4 | Estado interno dinámico con 5 campos numéricos + sleep stages + emotional honesty mode |
| Fase 4 (implementado) | Perfil viviente read-path: entity resolution + scoped Mem0 + injection |
| Fase 4 (pendiente) | Perfil viviente write-path: update_profiles + update_relations nocturnos |
| Fase 5+ | Rúbrica emocional, few-shot examples, passive observations |
| Fase 10 | **LoRA fine-tuning** con conversaciones reales |

### 6.6 Consideraciones sobre LoRA fine-tuning (fase 10)

Cuando haya 6-12 meses de conversaciones reales acumuladas, vale la pena entrenar un LoRA adapter específico para Lumi:

**Setup previsto:**

- Framework: Unsloth en Google Colab gratuito (~$5-20 one-time si se compra Colab Pro para entrenamiento largo)
- Dataset: 500-1000 conversaciones curadas de Jose con Lumi, formato instruction-response
- Base model: Qwen3.5-9B (mismo que usa Lumi en producción)
- Target: LoRA rank 32, alpha 16, ~2000 pasos de entrenamiento
- Deploy: DeepInfra permite desplegar LoRAs sobre sus modelos base sin costo de inferencia adicional

**Beneficio esperado:**

- El modelo aprende el *estilo* de Lumi (Stoic Delay, dry wit, deflection patterns) en los pesos
- Ya no hay que enseñárselo cada turno via system prompt
- El cached prefix se reduce a reglas duras (formato, idioma, emotion tags) — ~500 tokens
- Personalidad más consistente porque no depende de que el prompt caching acierte

**Lo que LoRA NO hace bien:**

- No inyecta hechos nuevos (para eso está Mem0)
- No reemplaza la necesidad del card base — solo permite que sea más ligero
- No garantiza mejor calidad automáticamente: requiere dataset limpio y curado

**Cuándo NO hacerlo:**

- Si el dataset tiene menos de 300 ejemplos de buena calidad
- Si aún no hay patrones claros y repetidos de cómo Lumi debe hablar contigo específicamente
- Si DeepInfra cambia su modelo base (obligaría a retrainar)

---

## 7. MCP y tool calling: arquitectura híbrida

### 7.1 El problema que resuelve MCP

Lumi necesita acceder a dos tipos de información y acciones:

**Datos externos (viven en internet o APIs):**
- Búsqueda web (Brave)
- Calendario (Google Calendar)
- Email (IMAP/SMTP futuro)
- APIs internas de Inmobarco (futuro)
- Clima, noticias, precios

**Datos y acciones locales (viven en el PC de Jose):**
- Estado de pantalla (screenpipe)
- Clipboard
- Archivos locales
- Aplicaciones activas
- Control de sistema (abrir apps, ajustar volumen, etc.)

Ambos se exponen al LLM vía **tool calling**, pero viven en lugares distintos. La arquitectura v2.1 los trata explícitamente como dos capas.

### 7.2 Arquitectura híbrida VPS + Bridge local

```
┌─────────────────────────────────────────────────────────────────┐
│                       DeepInfra (cerebro)                       │
│             5 modelos MAIN + 3 LIGHTWEIGHT                      │
└─────────┬───────────────────────────────────────────────────────┘
          │ tool_call("get_today_events")
          │ tool_call("query_screen_history")
          ▼
┌─────────────────────────────────────────────────────────────────┐
│  VPS Contabo — agent/cognition/intention.py                     │
│                                                                 │
│  decide_tool() → ToolRegistry:                                  │
│    ├── ¿Es un tool LOCAL VPS?                                   │
│    │    └── brave_search, calendar, time, email → ejecuta aquí  │
│    │                                                            │
│    └── ¿Es un tool REMOTO (vive en el PC de Jose)?              │
│         └── Envía a perception/websocket.py vía WSS             │
└─────────┬───────────────────────────────────────────────────────┘
          │                                    ▲
          │ WSS /v1/bridge                     │
          │                                    │
          ▼                                    │
┌─────────────────────────────────────────────────────────────────┐
│  PC Local — custom/mcp_bridge/bridge_client.py                  │
│                                                                 │
│  BridgeClient recibe tool_call remoto:                          │
│    ├── screenpipe_tool.query_history(...)                       │
│    ├── clipboard_tool.get_content()                             │
│    ├── filesystem_tool.read_file(path)   [permisos explícitos]  │
│    └── ... ejecuta localmente, devuelve resultado               │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 Por qué no usar MCP nativo de OLV

OLV tiene soporte MCP built-in, pero asume que el LLM corre en el mismo proceso que OLV. Como nuestro LLM vive en DeepInfra vía VPS, el flujo estándar de MCP de OLV no aplica: el LLM no tiene forma de llamar a `localhost:3030` del PC de Jose desde un GPU en Virginia.

La solución es el patrón de **MCP Bridge**, que coincidentemente es la misma dirección que OLV tiene en su roadmap oficial para v1.3 ("MCP Bridge Support: decoupled MCP setup, main server provides a bridge to push MCP commands via WebSocket and receive results"). Cuando esa feature salga upstream, podemos considerar migrar nuestra implementación custom a la oficial. Por ahora construimos la nuestra.

### 7.4 Registro de tools en el VPS

```python
# vps/agent/tools.py

class ToolRegistry:
    def __init__(self):
        self._local_tools = {}       # Se ejecutan en VPS
        self._remote_tools = {}       # Se envían al bridge

    def register_local(self, name: str, fn: Callable, schema: dict):
        self._local_tools[name] = (fn, schema)

    def register_remote(self, name: str, schema: dict):
        """Remote tools solo declaran schema. La ejecución la hace el bridge."""
        self._remote_tools[name] = schema

    def all_schemas(self) -> list:
        """Lo que ve el LLM. No distingue local de remote — solo tools."""
        return [s for _, s in self._local_tools.values()] + \
               list(self._remote_tools.values())

    async def execute(self, tool_call, user_id: str):
        name = tool_call.name
        if name in self._local_tools:
            fn, _ = self._local_tools[name]
            return await fn(**tool_call.arguments)
        elif name in self._remote_tools:
            return await bridge_server.call_remote(user_id, tool_call)
        else:
            raise UnknownTool(name)

# Registro al boot
registry = ToolRegistry()

# Tools locales VPS
registry.register_local("brave_search", brave_search_fn, BRAVE_SCHEMA)
registry.register_local("get_today_events", calendar_fn, CALENDAR_SCHEMA)
registry.register_local("current_time", time_fn, TIME_SCHEMA)

# Tools remotos (ejecutan en PC de Jose)
registry.register_remote("query_screen_history", SCREENPIPE_SCHEMA)
registry.register_remote("get_clipboard", CLIPBOARD_SCHEMA)
registry.register_remote("read_local_file", FILESYSTEM_SCHEMA)
```

### 7.5 El bridge: WebSocket persistente

```python
# vps/bridge/bridge_server.py

class BridgeServer:
    def __init__(self):
        self._connections = {}  # user_id → WebSocket

    async def on_connect(self, ws, user_id: str):
        self._connections[user_id] = ws

    async def call_remote(self, user_id: str, tool_call, timeout=30):
        ws = self._connections.get(user_id)
        if not ws:
            return {"error": "bridge_not_connected"}

        request_id = uuid.uuid4().hex
        await ws.send_json({
            "type": "tool_call",
            "request_id": request_id,
            "tool": tool_call.name,
            "args": tool_call.arguments,
        })

        return await self._await_response(request_id, timeout)
```

```python
# custom/mcp_bridge/bridge_client.py

class BridgeClient:
    def __init__(self, ws_endpoint, api_key):
        self._ws = None
        self._tools = {
            "query_screen_history": screenpipe_tool.query_history,
            "get_clipboard": clipboard_tool.get_content,
            "read_local_file": filesystem_tool.read_file,
        }

    async def connect_forever(self):
        while True:
            try:
                async with websockets.connect(self._ws_endpoint, ...) as ws:
                    self._ws = ws
                    await self._listen()
            except Exception as e:
                logger.warning(f"Bridge disconnected: {e}. Reconnecting in 5s")
                await asyncio.sleep(5)

    async def _listen(self):
        async for raw in self._ws:
            msg = json.loads(raw)
            if msg["type"] == "tool_call":
                result = await self._execute_tool(msg)
                await self._ws.send_json({
                    "type": "tool_result",
                    "request_id": msg["request_id"],
                    "result": result,
                })

    async def _execute_tool(self, msg):
        tool_fn = self._tools.get(msg["tool"])
        if not tool_fn:
            return {"error": f"unknown_tool: {msg['tool']}"}
        return await tool_fn(**msg["args"])
```

### 7.6 Ejemplo de flujo end-to-end

Jose pregunta: *"Lumi, ¿qué tengo hoy en la agenda y qué estaba viendo ayer por la noche?"*

```
1. ASR local → texto
2. LumiAgent → POST /v1/chat al VPS
3. VPS construye prompt con el card completo + tools disponibles
4. Qwen3.5 analiza y genera dos tool_calls en paralelo:
   {
     "tool_calls": [
       {"name": "get_today_events", "args": {}},
       {"name": "query_screen_history", "args": {"timeframe": "yesterday_evening"}}
     ]
   }
5. VPS ejecuta ambos tools:
   a) get_today_events → ejecuta local en VPS → devuelve eventos de Calendar
   b) query_screen_history → es remoto → envía al bridge vía WSS
      → PC de Jose ejecuta screenpipe MCP localmente
      → devuelve lista de apps/contenido de la noche anterior
      → resultado vuelve al VPS
6. VPS inyecta resultados en el contexto y llama a Qwen3.5 de nuevo
7. Qwen3.5 genera respuesta final integrando ambas fuentes:
   "[neutral] Hoy tienes tres reuniones — el standup a las 9, 
   el review con el cliente a las 11, y la cena con tu mamá a las 7.
   Anoche estuviste en Unity hasta las 11, trabajando en lo del 
   inventory system por lo que veo."
8. Stream al cliente → emotion tag → Live2D + TTS
```

La latencia total es típicamente 1-3 segundos porque los tool calls paralelos se ejecutan al mismo tiempo y el round-trip al bridge desde VPS es rápido (ambos están en US-East si seguimos la recomendación).

### 7.7 Seguridad del bridge

**Restricciones importantes:**

1. **El bridge NO da acceso libre al PC.** Cada tool remoto declara explícitamente qué puede hacer, con schema validado.
2. **Tools destructivos requieren confirmación.** Leer un archivo es automático; escribir o borrar requiere que Lumi pida confirmación explícita a Jose antes de ejecutar.
3. **Blacklists obligatorias.** filesystem_tool tiene una lista de paths prohibidos (`~/.ssh`, gestores de contraseñas, claves privadas, etc.) que no se pueden leer bajo ninguna circunstancia, ni siquiera con confirmación explícita.
4. **WebSocket autenticado.** El bridge usa el mismo API key que el resto de la comunicación VPS↔local.
5. **Audit log.** Cada tool call remoto queda registrado en el VPS con timestamp, user_id, tool name, y args. Jose puede revisarlo cuando quiera.

### 7.8 MCPs servers oficiales integrables

| Servicio | MCP server | Ubicación | Fase |
|---|---|---|---|
| Brave Search | `@anthropic/mcp-server-brave` | VPS | Fase 3 |
| DuckDuckGo Search | `duckduckgo-mcp-server` | VPS | Fase 3 |
| Time | `mcp-server-time` | VPS | Fase 3 |
| Google Calendar | `@anthropic/mcp-server-google-calendar` | VPS | Fase 5-6 |
| Screenpipe | screenpipe MCP built-in | Local (vía bridge) | Fase 4-5 |
| Gmail / IMAP | MCP email server | VPS | Fase 7+ |
| Filesystem local | Custom wrapper | Local (vía bridge) | Fase 4+ |
| Clipboard | Custom wrapper | Local (vía bridge) | Fase 4+ |

---

## 8. Roadmap por fases

Cada fase se presenta con su **objetivo**, **checklist de tareas**, **desarrollo resumido** y **recomendaciones integradas**. Las recomendaciones provienen del catálogo completo de la sección 9 y se anotan con urgencia: 🔴 Core, 🟠 Recomendado fuertemente, 🟡 Opcional pero recomendable, 🔵 Aplazable.

---

### Fase 1 — OLV Base en Windows (desktop pet funcional)

**Objetivo:** OLV corriendo en el PC con avatar Live2D, ASR local, TTS, modo desktop pet permanente. El sistema debe ser operable antes de introducir personalidad Lumi.

**Checklist:**

- [x] Fork repositorio OLV → renombrar `lumi`
- [x] Clonar con `git clone --recursive` (el frontend es submodule)
- [x] Instalar dependencias Windows: Git, FFmpeg, uv, Node.js
- [x] **NO instalar Ollama localmente** — v2.1 no usa LLM local
- [x] Copiar `conf.yaml` desde `config_templates/conf.default.yaml`
- [x] Configurar `conf.yaml`: LLM provider apuntando a DeepInfra (placeholder mientras se onstruye el VPS), ASR Canary Flash, Edge TTS `es-CL-CatalinaNeural`
- [x] **Descargar modelo NeMo Canary Flash 180M** (no SenseVoice — no soporta español)
- [x] Descargar Electron client desde OLV releases para Windows
- [x] Verificar pet mode transparente
- [x] Verificar lip-sync y emotion tags con modelo base (usando DeepInfra directamente)
- [DESPUES] Configurar inicio automático con Windows (backend + Electron)
- [x] Configurar `git remote add upstream` para sincronización
- [x] Ejecutar `uv run run_server.py` y validar end-to-end básico

**Desarrollo resumido:**
Se instala la infraestructura mínima: un OLV limpio, funcional, con voz que entiende español y avatar que responde con emotion tags. En esta fase no hay personalidad Lumi propia; se valida que la plataforma base funciona antes de invertir en el agente custom. La decisión crítica de ASR (Canary Flash sobre SenseVoice) ya se toma aquí porque el costo de equivocarse más adelante es alto.

**Tiempo estimado:** 1-2 días
**Costo:** $0 (DeepInfra paga por uso)

**Advertencias:**

- El navegador soportado por OLV es **Chrome only**
- El primer lanzamiento descarga modelos grandes — paciencia
- Sin code-signing de OLV → Windows Defender puede mostrar warning al instalar

**Recomendaciones para esta fase:**

_No aplica — esta fase es fundacional y no incorpora features de recomendación. El enfoque es validar la infraestructura base de OLV antes de agregar complejidad propia._

---

### Fase 2 — LumiAgent custom en OLV

**Objetivo:** `LumiAgent(AgentInterface)` funcional con personalidad Lumi, wake word, emotion tags, conectividad al VPS (que todavía no existe — usa DeepInfra directamente) y modo dormida.

**Checklist:**

- [x] Crear `custom/agents/lumi_agent.py` heredando `AgentInterface`
- [x] Implementar `chat()`: en Fase 2 llama directo a DeepInfra con el card; en Fase 3 apunta al VPS
- [x] Implementar `handle_interrupt()`: cancela generación + activa interrupt_handler básico (feature #19 nivel 1)
- [x] Implementar `set_memory_from_history()`: no-op inicial
- [x] **Crear `custom/personality/lumi_card.json`** como Character Card V3 completo basado en Lumi.md + Lumi_implementation.md
- [x] **Crear `custom/personality/prompt_builder.py`** con estructura cached/dynamic
- [x] Configurar DeepInfra con prompt caching activo desde el inicio
- [x] Registrar LumiAgent en `src/open_llm_vtuber/agent/agent_factory.py`
- [x] Crear `custom/wake_word/wake_detector.py` con la máquina de estados de sección 5.2
- [x] Crear `custom/connectivity/vps_health.py` + modo dormida (placeholder hasta Fase 3)
- [x] Crear `custom/utils/offline_mode.py` con mensajes canned
- [x] Crear `custom/interruption/interrupt_handler.py` nivel básico
- [x] Estudiar `src/open_llm_vtuber/agent/decorators.py` para entender parsing de emotion tags
- [x] Verificar mapeo emotion tag → expresión Live2D end-to-end
- [PENDIENTE] Verificar detección de `[ESCALAR]` en el stream de respuesta
- [x] Configurar `conf.yaml`: `conversation_agent_choice: "lumi_agent"`
- [x] Test end-to-end: hablar → wake word → respuesta con personalidad Lumi + emotion correcta + voz + lip-sync

**Archivos OLV relevantes a estudiar:**

- `src/open_llm_vtuber/agent/agents/basic_memory_agent.py` (referencia de implementación)
- `src/open_llm_vtuber/agent/decorators.py` (parsing de tags)
- `src/open_llm_vtuber/agent/output_types.py` (estructura `SentenceOutput`)
- `src/open_llm_vtuber/agent/agent_factory.py` (registro)

**Desarrollo resumido:**
La personalidad de Lumi aparece por primera vez. El `lumi_card.json` completo se envía a DeepInfra con prompt caching activo — costo marginal despreciable. Wake word filtra cuándo responder. El modo dormida es placeholder (aún no hay VPS que pueda caerse) pero la infraestructura queda lista. Interrupción nivel básico: TTS cancela, stream se detiene. La inteligencia post-interrupción viene después.

Desde esta fase se establecen los tres principios que acompañarán todo el proyecto:

1. **Código ultra-ligero**, estilo NanoBot — nada de frameworks pesados
2. **Arquitectura modular de tres capas** (MCP / Skills / Channel Adapters) definida como criterio de diseño
3. **Personalidad completa desde el día uno** — no se recorta la identidad de Lumi por presupuesto, el prompt caching lo hace gratis

**Tiempo estimado:** 3-5 días
**Costo:** ~$1-3/mes en DeepInfra con prompt caching

**Recomendaciones para esta fase:**

| Urgencia | Recomendación | Por qué en esta fase |
|---|---|---|
| 🟠 **Recomendado** | **#3 Agente Ultra-Ligero** (NanoBot) | Establece la filosofía del código desde el inicio. Si se escribe con esta disciplina, se mantiene; si se escribe pesado, refactorizar después cuesta más. |✅
| 🟠 **Recomendado** | **#6 Timing Conversacional — fundamentos** (Neuro-sama) | Streaming obligatorio desde el inicio, interrupción vía `handle_interrupt()`, timeouts de silencio en ASR. Son configuraciones pequeñas, pero si no se hacen ahora, se notan después como "lag". |✅
| 🟠 **Recomendado** | **#7 Arquitectura Modular de Tres Capas — definición** (OpenClaw/MCP) | No se implementa todo aquí, pero la decisión de estructurar el proyecto en `custom/skills/`, `vps/channels/`, `custom/mcp_bridge/` y servidores MCP se toma ya. Abrir la carpeta `custom/skills/` y dejar 1-2 skills base (personalidad, research) como ejemplo. |
| 🟠 **Recomendado** | **#18 patrón C — Capabilities Registry** | Trivial de implementar (estructura de datos), establece el patrón desde el inicio para que Lumi nunca ofrezca lo que no puede cumplir. |
| 🟠 **Recomendado** | **#19 Interrupción Consciente — nivel básico** | Detección + cancelación de TTS + decisión heurística pausar/completar frase. La inteligencia emocional post-interrupción viene después. |
| 🟡 **Opcional** | **#8 Personalidad Dinámica — scaffolding** | Se puede dejar el scaffolding del `lumi_internal_state` aunque no se use todavía. Mejor definir el JSON ahora y agregarle el loop de actualización en Fase 3-4. |✅

---

### Fase 3 — VPS como cerebro (arquitectura split)

**Objetivo:** migrar el razonamiento al VPS. El PC local queda sólo como capa sensorial. Es la transición más importante de todo el roadmap.

#### 3.1 Setup VPS Contabo y FastAPI

**Checklist:**

- [x] Contratar **Contabo Cloud VPS 20** (12 GB RAM), Ubuntu 24.04, región US East
- [x] SSH inicial, crear usuario no-root, deshabilitar root SSH, configurar `ufw`
- [x] Instalar Docker, Docker Compose, Python 3.12, uv
- [x] Crear `src/main.py`: FastAPI con endpoints `/v1/chat`, `/v1/observe`, `/v1/bridge` (WSS), `root_path="/lumi"`
- [x] Crear estructura `src/agent/`: `loop.py`, `llm.py`, `context.py`, `memory.py`, `tools.py`, `router.py`
- [x] Crear `src/llm/` con wrappers individuales por modelo (Qwen, Step, Nemotron)
- [x] Implementar cadena de fallback: Qwen35B → Step → Nemotron con exponential backoff
- [x] Cachear system prompt en `src/agent/context.py` (`get_cached_prefix()`)
- [x] Obtener API key DeepInfra
- [x] Implementar autenticación: API key en header `X-Api-Key`
- [x] **Configurar Caddy como reverse proxy con HTTPS automático** (Let's Encrypt)
- [x] Crear `src/memory/sqlite_memory.py` y `src/memory/mem0_client.py` como placeholder (Fase 4 reemplaza con Mem0 real)
- [x] Actualizar cliente local (repo OLV separado): llamar al VPS en lugar de DeepInfra directo
- [x] Implementar check real de conectividad en el cliente local
- [x] Verificar que modo dormida funciona cuando el VPS está caído
- [x] Verificar latencia Colombia → Contabo US East (objetivo: <150 ms)
- [x] Configurar logs estructurados básicos

#### 3.2 MCP Bridge (infraestructura)

- [x] Crear `src/bridge/bridge_server.py` (WebSocket server)
- [x] Crear bridge client en repo OLV (persistent WS client desde PC)
- [x] Implementar reconexión automática del bridge client
- [x] Definir `ToolRegistry` con soporte local + remote en `src/agent/tools.py`
- [x] Test end-to-end: tool call desde LLM → VPS decide local/remote → ejecuta → resultado vuelve
- [x] Autenticación del bridge: query param `?api_key=...` (headers no disponibles en WS handshake)

#### 3.3 Búsqueda web inteligente con clasificador keywords

- [x] Obtener Brave Search API key (free tier)
- [x] Implementar `BraveSearchTool` como `BaseTool` en `src/tools/brave_search.py`
- [x] Integrar vía `register_tool()` en `src/agent/tools.py`
- [x] Clasificador pre-LLM en `src/agent/router.py`: detecta si necesita web search por keywords
- [x] Test con frases que NO deben disparar: "hola Lumi, qué tal tu día", "me siento mal hoy"
- [x] Test con frases que SÍ deben disparar: "qué pasó hoy en Colombia", "busca el precio del Bitcoin"

#### 3.4 Diferenciación de usuarios

- [x] `user_id` en cada request al VPS
- [x] Memoria separada por `user_id` en SQLite
- [x] Historial separado por `user_id`
- [x] La personalidad ya cambia según user_id por las reglas del Two-Tiered Protocol en el card

#### 3.5 Agente ultra-ligero — implementación real

- [x] Loop principal con dos entrypoints: `run()` (string) y `run_stream()` (async generator)
- [x] `run_stream()` es lo que usa `/v1/chat`: tool calls sin streaming, luego stream de respuesta final
- [x] Router clasifica: `chat`, `web_search`, `long_task`, `explicit_save`
- [x] `long_task` devuelve respuesta placeholder inmediata: *"[thinking] Dame un momento..."* (async real en Fase 5+)
- [x] `explicit_save` guarda verbatim en Mem0 con `infer: false`
- [x] `[ESCALAR]` detectado en respuesta → placeholder (solo strip del tag, sin llamada a especialista)
- [x] `[SEGUIMIENTO:]` detectado en respuesta → placeholder (sin encolar follow-up)

#### 3.6 Feature #18 patrón B — Tareas largas asíncronas
—APLAZADO PARA FASE 5+—

- [ ] Crear `src/agent/async_tasks.py` con cola de tareas real
- [ ] Respuesta inmediata con status updates a 45-60s
- [ ] Entrega del resultado final con opción de canal

**Desarrollo resumido (actualizado):**
El VPS corre como una app FastAPI independiente en `src/`, con Caddy como reverse proxy. El agente implementa el loop clasificar→contexto→LLM→tools→memoria. La fábrica LLM maneja 3 modelos con fallback automático y exponential backoff. El MCP Bridge permite tool calls remotos al PC vía WebSocket. Brave Search es la única tool local implementada como `BaseTool`. El router clasifica por keywords. Las features #18B (async tasks) y el escalado a modelos especialistas (`[ESCALAR]`) están como placeholders.

**Tiempo estimado Fase 3:** 1-2 semanas
**Costos:** Contabo ~$8/mes + DeepInfra ~$1-3/mes = **~$9-11/mes**

**Recomendaciones para esta fase:**

| Urgencia | Recomendación | Estado |
|---|---|---|
| 🔴 **Core** | **#3 Agente Ultra-Ligero** — `src/agent/loop.py`, `context.py`, `memory.py`, `tools.py`, `router.py` | ✅ Implementado |
| 🔴 **Core** | **#7 Arquitectura Modular — MCP Bridge** | ✅ Implementado |
| 🔴 **Core** | **#18 patrón B — Tareas largas asíncronas** | ❌ APLAZADO (placeholder) |
| 🟠 **Recomendado** | **#7 Skills iniciales** — Documentos markdown en `src/skills/` (read-only, no wireados) | ~ Parcial |
| 🟠 **Recomendado** | **#8 Personalidad Dinámica — estado interno básico** — 3 campos string en SQLite | ✅ Parcial (ver 9.8) |
| 🟠 **Recomendado** | **#19 Interrupción Consciente — matriz básica** — En repo OLV, no en este | ~ OLV |
| 🟡 **Opcional** | **#11 Always-On Transcription** — Endpoint `/v1/observe` existe, extracción no wireada | ~ Parcial |

---

### Fase 4 — Mem0 con pgvector para memoria semántica

**Objetivo:** memoria persistente real, semántica. Lumi pasa de "recordar hechos sueltos" a "conocer a Jose".

**Arquitectura actual de memoria (dos niveles):**

| Nivel | Backend | Propósito | Estado |
|---|---|---|---|
| Historial conversacional | SQLite (`src/schemas/logs.db`) | Turno-a-turno, acceso secuencial, últimos N en contexto | ✅ Implementado |
| Memoria semántica | Mem0 + pgvector (host:8100) | Hechos, personas, conocimiento persistente | ✅ Implementado |

Esta separación es intencional: el historial secuencial NO pertenece a Mem0 porque es acceso temporal, no semántico.

**Nota sobre graph store:** Mem0 v2.0.0 eliminó el soporte nativo para Neo4j. El entity linking se maneja internamente en pgvector mediante la tabla `memories_entities`. Neo4j permanece en `docker-compose.yml` como servicio opcional detrás de `--profile graph`. **No se requiere graph store externo** para la funcionalidad base.

**Checklist:**

- [x] Diseñar `docker-compose.yml` con servicios: `postgres` (pgvector) + `mem0` (API) + `neo4j` (opcional, `--profile graph`)
- [x] Configurar Mem0 con `vector_store.provider = "pgvector"` (sin `graph_store` — entity linking nativo de Mem0 en pgvector)
- [x] Configurar LLM extractor: `mistralai/Mistral-Small-3.2-24B-Instruct-2506` vía DeepInfra
- [x] Configurar embedder: `BAAI/bge-m3` vía DeepInfra (1024 dims)
- [x] Implementar `src/memory/mem0_client.py`: cliente HTTP a Mem0 API (host:8100)
- [x] Conservar SQLite para historial conversacional (`save_turn()`, `get_history()`) en `mem0_client.py`
- [x] Fachada en `src/agent/memory.py` — loop.py y context.py importan solo de aquí
- [x] `src/memory/sqlite_memory.py` preservado como referencia legada
- [x] Configurar `user_id` por persona en Mem0
- [x] Hardening: puertos bindeados a 127.0.0.1 desde docker-compose. Postgres (5432) y Mem0 (8100) no expuestos al exterior.
- [x] Reverse proxy: Mem0 no expuesto — acceso solo interno. FastAPI principal actúa como proxy (`/v1/memories/{user_id}`)

**Funcionalidades de memoria — estado actual:**

| Funcionalidad | Estado | Nota |
|---|---|---|
| `add_memory()` — extracción de hechos | ✅ | Envía conversación a Mem0, extractor LLM genera hechos |
| `search_relevant()` — búsqueda semántica | ✅ | Retorna top-K memorias relevantes para armar contexto |
| `save_turn()` / `get_history()` — historial SQLite | ✅ | Últimos 10 turnos inyectados en dynamic suffix |
| `save_explicit()` — guardado verbatim | ✅ | `infer: false`, guarda contenido sin extractor. Para recetas, links, notas. |
| `add_memory_explicit()` — expuesto en loop | ✅ | Detectado por router (`explicit_save`), guarda con categoría |
| `init_db()` — schema SQLite | ✅ | Tabla `history` para turnos |
| `init_state_table()` — schema estado interno | ✅ | Tabla `internal_state` con mood/energy/focus |
| `get_profile()` — perfil de usuario | ~ Placeholder | Busca `"perfil usuario {user_id}"` en Mem0, retorna lista plana. Sin JSON estructurado. |
| `set_profile()` — guardar perfil | ~ Placeholder | Guarda display_name + description como memoria simple |
| Session summaries | ❌ | No implementado. `save_turn()` guarda turnos individuales, sin resumen de sesión. |
| Memoria de relaciones (personas/grupos) | ❌ | No implementado. Sin esquema de contactos en código. |
| Curva de olvido (interest decay) | ~ Schema | Schemas SQL en `src/skills/_impl/` (interest_decay.sql, weekly_decay.sql). No wireados a runtime. |
| Passive observation → Mem0 | ❌ | Endpoint `/v1/observe` existe pero extracción no wireada (`# TODO Fase 4`). |
| Reflection skill (cierre de sesión) | ~ Política | Documento en `src/skills/reflection_policy.md` (11 etapas). No ejecutable. |
| `emotional_honesty_mode` | ❌ | No implementado |

**Cálculo de RAM en VPS 20 (12 GB):**

```
SO Ubuntu 24.04            : ~800 MB
Caddy                      : ~50 MB
FastAPI principal          : ~300 MB
bridge_server (WS)         : ~100 MB
Mem0 API (Docker)          : ~300 MB
Postgres + pgvector        : ~1,000 MB
Buffer / cache OS          : ~1,500 MB
─────────────────────────────────
En uso normal              : ~4.05 GB
Libre                      : ~8 GB
```

**Desarrollo resumido (actualizado):**
La memoria semántica está operativa con Mem0 + pgvector. La arquitectura de dos niveles (SQLite para historial, Mem0 para hechos) es intencional y funcional. Las funcionalidades avanzadas del perfil viviente (JSON estructurado, session summaries, trigger de actualización) están diseñadas pero no implementadas. La observación pasiva y la memoria de relaciones son las próximas prioridades para completar la Fase 4.

**Tiempo estimado:** 3-5 días (base implementada) + 1-2 semanas (completar perfil viviente y memoria de relaciones)
**Costo adicional:** $0

**Recomendaciones para esta fase:**

| Urgencia | Recomendación | Estado |
|---|---|---|
| 🔴 **Core** | **#1 Memoria como Perfil Viviente** — JSON estructurado + session summaries + trigger de actualización | ~ Placeholder (ver 9.1) |
| 🟠 **Recomendado** | **#8 Personalidad Dinámica — integración con Mem0** — Mover estado interno a modelo más rico | ~ Parcial (3 strings en SQLite) |
| 🟠 **Recomendado** | **#9 Memoria de Relaciones** — Esquema de personas y grupos | ❌ No implementado |
| 🟠 **Recomendado** | **#7 Skill de memoria** — Políticas documentadas en `src/skills/` | ~ Read-only docs |
| 🟠 **Recomendado** | **#11 Always-On Transcription — integración con perfil** | ❌ Observación no wireada |
| 🟡 **Opcional** | **#12 Screen Context Capture** (Screenpipe) | ❌ No implementado |
| 🟡 **Opcional** | **#13 Curva de Olvido Intencional** — Jobs de consolidación | ~ SQL schema, no wireado |
| 🟡 **Opcional** | **Tool Autodiscovery via Bridge Handshake** — Registro dinámico de tools | ❌ No implementado |
---

### Fase 5 — TTS custom, Live2D custom y maduración emocional

**Objetivo:** Lumi deja de sonar genérica (Edge TTS Catalina) y deja de verse genérica (mao_pro de OLV). Es la fase de identidad visual y sonora propia, y también la fase donde la inteligencia emocional de Lumi se vuelve rica.

**TTS custom voz:**

- Opciones: GPT-SoVITS (mejor integración OLV), F5-TTS, CosyVoice, StyleTTS2
- Requiere: dataset de voz ~30 min mínimo
- GPT-SoVITS destaca por voice cloning con poco data
- Tiempo investigación: 1 semana para plan detallado
- Costo: $0 (todos open source)

**Live2D custom:**

- Apariencia ya definida en `Lumi.md`, `Technical_sheet.md` y los renders (`face.png`, `body.png`)
- Proceso: diseño 2D → rigging Live2D Cubism Editor → expressions → importar OLV
- Cubism gratuito para uso individual (ingresos < $67K USD/año)
- Curva de aprendizaje: 1-3 meses si lo haces tú
- Alternativa: Fiverr/comisiones, ~$200-800 USD
- Costo: variable (artwork)

**Desarrollo resumido:**
Esta fase es más artística que técnica en su componente TTS/Live2D. El trabajo de sistema está hecho; lo que queda es invertir tiempo (y posiblemente dinero para artwork) en que Lumi se sienta como ella misma y no como un avatar prestado. Paralelamente, esta es la fase ideal para pulir el comportamiento: políticas de empatía completas, curva de olvido, observación pasiva bien integrada, matriz de interrupción completa. Muchas de las features más "emocionales" del catálogo (arco narrativo, introspección, curiosidad activa) encajan aquí porque requieren historial acumulado para ser genuinas.

**Recomendaciones para esta fase:**

| Urgencia | Recomendación | Por qué en esta fase |
|---|---|---|
| 🟠 **Recomendado** | **#10 Empathic LLM — pipeline completo** | Política explícita en `custom/skills/empathy/SKILL.md`, detección de emoción + plan de respuesta previa al LLM final, integración con el estado interno. |
| 🟠 **Recomendado** | **#13 Curva de Olvido Intencional** (Ebbinghaus) | Con memoria acumulada de varios meses, el ruido empieza a molestar. Job semanal de consolidación/archivado mantiene el contexto activo fresco y relevante. |
| 🟠 **Recomendado** | **#19 Interrupción Consciente — matriz completa** | Modulación emocional de reacciones, conexión con `lumi_internal_state`, auto-interrupción de Lumi, casos edge (corrección inválida, interrupción accidental). |
| 🟡 **Opcional** | **#6 Timing Conversacional — refinamiento avanzado** | Fillers tipo "déjame pensar...", emotion-aware timing. Sólo si ya se siente que falta. |
| 🟡 **Opcional** | **#12 Screen Context Capture — 3 pantallas diferenciadas** | Correlacionar pantalla con audio pasivo, pre-ajuste del estado interno basado en actividad observada antes de que Jose hable. |
| 🟡 **Opcional** | **#14 Integración de Calendario** (MCP Google Calendar) | Feature de alto impacto y baja complejidad. Si el MCP ya está operativo, prácticamente es configurar credenciales y escribir `custom/skills/calendar/SKILL.md`. |
| 🟡 **Opcional** | **#15 Arco Narrativo / Historia Compartida** | Requiere historial acumulado para ser genuino. Si Mem0 lleva ~1-2 meses, los primeros hitos relacionales empiezan a tener sentido. |
| 🟡 **Opcional** | **#16 Introspección Periódica (Diario Interno)** | Job semanal de autoevaluación de Lumi. Alimenta directamente la curiosidad activa. Tambien es donde Lumi "procesa" emociones negativas sin cargarlas sobre Jose. |
| 🟡 **Opcional** | **#17 Curiosidad Activa** | Preguntas espontáneas de Lumi basadas en gaps detectados. Requiere perfil viviente robusto + diario interno funcionando. |

- -  Uso con faster-whisper backend + VAD + español
pip install whisper-streaming
python whisper_online.py --model large-v3-turbo --lan es --backend faster-whisper --vad audio.wav
Whisper Streaming con whisper_streaming (recomendada)

Existe ufal/whisper_streaming — una implementación que convierte Whisper en streaming real usando política de local agreement: procesa chunks de audio mientras escuchas y va emitiendo texto confirmado con ~3.3s de latencia total. Usa faster-whisper como backend, soporta large-v3-turbo, y tiene VAD integrado
https://github.com/ufal/whisper_streaming
---

### Fase 6 — Multi-canal + patrones conversacionales maduros

**Objetivo:** una sola Lumi accesible desde múltiples canales con memoria compartida. "Conversación iniciada en Discord puede continuar en WhatsApp o desktop pet sin perder contexto" debe ser literal. Además, esta fase completa los tres patrones de la feature #18 y activa el tracking longitudinal de interrupciones.

**Principio:** mismo `user_id`, misma memoria, independiente del canal.

**WhatsApp vía Evolution API:**

- Repo: `https://github.com/EvolutionAPI/evolution-api` (MIT, self-hosteable)
- Deploy Docker en mismo VPS junto a FastAPI LUMI
- Webhook Evolution API → POST a `vps/main.py` → respuesta → Evolution API → WhatsApp
- **Advertencia importante:** WhatsApp puede banear números personales usados como bots. Evaluar:
  - Usar número secundario dedicado
  - O migrar a WhatsApp Business API oficial (más caro pero estable)

**Discord texto:**

- `discord.py` bot corriendo en VPS
- Responde en canales y DMs configurados
- Mismo endpoint VPS que desktop pet

**Enrutamiento de canales:**

```
Canal              → user_id    → VPS → Mem0 (memoria compartida)
desktop/voice      → jose       →    ↗
discord_text       → jose       →   ↗
whatsapp           → jose       →  ↗
discord_other_user → persona_2  → ↗
```

**Feature #18 patrón A (follow-ups asociativos) — activación completa:**

Con Mem0 + perfil viviente + memoria de relaciones ya maduros (1-2 meses de data), los follow-ups de Lumi tienen contexto real. Implementación del `followup_queue.py` en el VPS, con threshold de relevancia y cooldown por inactividad de Jose.

**Tiempo estimado:** 1-2 semanas
**Costo adicional:** $0 (Evolution API self-hosted, discord.py gratuito)

**Desarrollo resumido:**
La arquitectura hecha en Fase 3 rinde aquí: agregar un canal nuevo es escribir un adaptador en `vps/channels/` y registrarlo. El esfuerzo real está en operacional: WhatsApp banea cuentas personales usadas como bot, diferenciar permisos por canal, content filter para canales públicos. El patrón #18A (follow-ups asociativos) se activa sólo ahora porque antes la memoria estaba muy vacía para que los follow-ups fueran buenos.

**Recomendaciones para esta fase:**

| Urgencia | Recomendación | Por qué en esta fase |
|---|---|---|
| 🔴 **Core** | **#4 Gateway Multi-Canal con Adaptadores Normalizados** (OpenClaw) | Este feature ES la fase. Sin el patrón de `ChannelAdapter` + `LumiMessage` normalizado, cada canal termina siendo un fork de la lógica del agente. |
| 🔴 **Core** | **#5 Content Filter** (Neuro-sama) | Obligatorio en cuanto Lumi hable en un Discord público o grupo de WhatsApp. Implementar los niveles 1 (regex/keywords) y 2 (clasificador local de toxicidad) mínimo; nivel 3 (LLM como juez) sólo para contenido sensible detectado. |
| 🔴 **Core** | **#18 patrón A — Follow-ups asociativos** | Activación con los guardrails definidos: threshold de relevancia, max 1 de cada 3-4 marcados, cooldown por inactividad de Jose. |
| 🟠 **Recomendado** | **#2 Heartbeat Scheduler / Acciones Proactivas** (OpenClaw/NanoBot) | Saludo matutino, recordatorio de tareas, noticias diarias. Con múltiples canales, el heartbeat sabe en cuál entregar el mensaje según dónde esté Jose activo. |
| 🟠 **Recomendado** | **#14 Integración de Calendario** | Si no se hizo en Fase 5, aquí encaja fuerte: el heartbeat matutino puede revisar agenda y mencionarla en el saludo. |
| 🟠 **Recomendado** | **#17 Curiosidad Activa** (si no está activa) | Con más canales, Lumi tiene más señales para generar preguntas genuinas. |
| 🟠 **Recomendado** | **#19 Interrupción — tracking longitudinal** | Activar `interruption_tracker.py` con rolling window de 7 días. Adaptación silenciosa del estilo. La "mención única" en casos extremos requiere el diario interno (feature #16) activo. |
| 🟡 **Opcional** | **#15 Arco Narrativo** | Si no está activo aún, ya hay suficiente material acumulado para que los hitos relacionales sean genuinos. |
| 🟡 **Opcional** | **#16 Introspección Periódica** | El diario semanal se vuelve más rico cuando Lumi conversa por múltiples canales. |

---

### Fase 6.1 — Discord voz multi-usuario

**Objetivo:** Lumi en canales de voz Discord con múltiples participantes simultáneos.

**Puntos a investigar:**

- `discord.py` con voice client (grabación de canal de voz)
- **WhisperX + Pyannote** para diarización: identificar quién habla → asignar `user_id`
- Streaming TTS de vuelta al canal de voz
- Latencia: ¿aceptable para conversación natural en Discord?
- Multi-speaker simultáneo: cola vs paralelo

**Tiempo estimado:** 2-3 semanas
**Costo adicional:** $0

**Recomendaciones para esta fase:**

| Urgencia | Recomendación | Por qué en esta fase |
|---|---|---|
| 🔴 **Core** | **#11 Always-On Transcription — con diarización completa** (pyannote.audio) | Speaker diarization es el requisito duro de esta fase. Speaker enrollment de Jose + identificación de `unknown_X` para múltiples usuarios. El clasificador de primera persona de la versión básica se reemplaza aquí. |

---

### Fase 7 — Screen capture activo e image processing

**Objetivo:** Lumi ve la pantalla y reacciona en tiempo real, no sólo para contexto pasivo sino para interacción directa ("Lumi, ¿qué ves aquí?").

**Puntos clave:**

- OLV ya soporta visión (camera/screen share desde v1.0)
- Activación bajo demanda: "Lumi, ¿qué ves en mi pantalla?"
- LLM multimodal:
  - Verificar si DeepInfra expone variante visión de Qwen3.5
  - Alternativa: Gemini 2.5 Flash free tier (~500 req/día)
- Captura periódica para gameplay: ~1 frame/2s suficiente para comentarios
- **Privacidad:** screenshots nunca persistidos más allá del turno actual

**Tiempo estimado:** 1 semana
**Costo:** $0 si Qwen3-VL cubre, mínimo si Gemini free tier

**Recomendaciones para esta fase:**

| Urgencia | Recomendación | Por qué en esta fase |
|---|---|---|
| 🔴 **Core** | **#12 Visión Permanente de Pantalla — versión completa** | Si screenpipe ya está instalado desde Fase 4-5 (vía MCP Bridge), aquí se conecta al pipeline de respuesta activa. Alternativa: python-mss + moondream2 / Qwen2.5-VL 7B Q4 local si no se quiere screenpipe. |

---

### Fase 8 — Acceso web y móvil *(roadmap de investigación)*

**Objetivo:** Lumi accesible desde navegador o celular.

**Opciones:**

- **Web:** OLV tiene UI web. Exponer vía Cloudflare Tunnel (gratuito, sin VPS extra)
- **Móvil:** OLV frontend es React, puede funcionar como PWA
- **Limitación móvil:** Web Speech API es inferior a sherpa-onnx local
- **AIRI alternativa:** soporta móvil vía Capacitor — evaluar si conviene migrar en esta fase

**Seguridad:** autenticación obligatoria (JWT o API key) para no exponer públicamente.

**Tiempo estimado:** 1 semana
**Costo:** $0 (Cloudflare Tunnel gratuito)

**Recomendaciones para esta fase:**

_Sin features dedicados de recomendación. Es una fase operacional de expansión de superficie, no de comportamiento._

---

### Fase 9 — Gaming AI *(roadmap de investigación)*

**Referencia principal:** AIRI (`https://github.com/moeru-ai/airi`) — único proyecto open-source con gaming funcional (Minecraft, Factorio, Balatro).

**Puntos a investigar:**

- Arquitectura AIRI para gaming: screen capture → LLM → input control (teclado/mouse)
- Herramientas: PyAutoGUI, pynput
- Migración potencial OLV → AIRI como frontend en esta fase
- Posible bifurcación: mantener OLV para desktop pet + AIRI para gaming

**Recomendaciones para esta fase:**

| Urgencia | Recomendación | Por qué en esta fase |
|---|---|---|
| 🟡 **Opcional** | **#12 Screen Context — modo gaming** | Captura del juego activo para que Lumi comente lo que está pasando. Complementa el input control sin reemplazarlo. |

---

### Fase 10 — Integraciones adicionales + LoRA fine-tuning

**Objetivo:** llevar Lumi de asistente personal a ecosistema, y entrenar un LoRA adapter con datos reales para hacerla más eficiente y consistente.

**MCP (Model Context Protocol):**

- OLV soporta MCP desde v1.2.0
- Nuestra arquitectura híbrida VPS + Bridge ya está consolidada
- Investigar MCP servers adicionales relevantes para Jose (Inmobarco APIs, emails, etc.)

**Habla proactiva:**

- OLV permite que el AI hable primero sin ser invocado
- Lumi puede saludar al inicio del día, recordar tareas, comentar noticias
- Triggers: hora del día, eventos del sistema, detección de inactividad

**Fine-tuning con LoRA:**

- QLoRA con conversaciones reales de Lumi (~500-1000 muestras curadas)
- Entrenar en Google Colab (GPU gratuita) con Unsloth
- Subir adapter a DeepInfra → costo de inferencia se mantiene
- Beneficio: cached prefix baja de ~4,000 a ~500 tokens; personalidad más consistente sin depender tanto de prompt caching
- Ver sección 6.6 para detalles

**Multi-agente especializado:**

- Lumi orquestadora que delega a agentes especializados vía tool calling o MCP
- El `[ESCALAR]` tag es la puerta de entrada

**Monitoreo y observabilidad:**

- Logs estructurados de todas las conversaciones en VPS
- Dashboard simple: tokens consumidos, costo mensual, usuarios activos
- Alertas si se acerca al techo presupuestal

**Recomendaciones para esta fase:**

_En esta fase se consolidan los features implementados y se agrega el LoRA. Es también el momento de revisar el catálogo completo y verificar que todo lo marcado como "opcional" en fases anteriores se haya implementado si sigue teniendo sentido._

---

## 9. Catálogo completo de features recomendados

Esta sección compila las 19 características del sistema. Las primeras 17 vienen del documento de recomendaciones original (proyectos de referencia + investigación propia). Las dos últimas (#18 y #19) son features nuevas agregadas en v2.1 para dar naturalidad conversacional al personaje de Lumi.

### Tabla resumen

| # | Feature | Fuente | Prioridad | Fase |
|---|---|---|---|---|
| 1 | Memoria como Perfil Viviente | DeepTutor | Alta | 4 |
| 2 | Heartbeat Scheduler (Acciones Proactivas) | OpenClaw/NanoBot | Media | 6 |
| 3 | Agente Ultra-Ligero como Referencia de Diseño | NanoBot | Alta | 2-3 |
| 4 | Gateway Multi-Canal con Adaptadores Normalizados | OpenClaw | Media | 6 |
| 5 | Content Filter (Filtro de Seguridad Pre-Respuesta) | Neuro-sama | Media | 6 |
| 6 | Timing Conversacional y Flujo Natural | Neuro-sama | Media-Alta | 2+ |
| 7 | Arquitectura Modular de Extensibilidad (Tres Capas) | OpenClaw/MCP/OLV | Alta | 2+ |
| 8 | **Personalidad Dinámica + Rúbrica de Emociones Negativas** | Investigación propia | Media-Alta | 2-3 núcleo, 4-5 refinado |
| 9 | Memoria de Relaciones (Personas y Grupos) | Investigación propia | Media | 4-5 |
| 10 | Empathic LLM (Respuestas Empáticas) | Investigación propia | Media-Alta | 3 básico, 5-6 completo |
| 11 | Always-On Transcription | Investigación propia | Media-Alta | 3-4 básico, 6+ diarización |
| 12 | Screen Context Capture / Visión Permanente | Screenpipe / python-mss | Media-Alta | 4-5 pasivo, 7 activo |
| 13 | Curva de Olvido Intencional | Ebbinghaus / arxiv 2024 | Media | 4-5 |
| 14 | Integración de Calendario | MCP Google Calendar | Media-Alta | 5-6 |
| 15 | Arco Narrativo / Historia Compartida | Diseño original | Media | 5-6 |
| 16 | Introspección Periódica (Diario Interno) | Diseño original | Media | 5-6 |
| 17 | Curiosidad Activa (Lumi pregunta por cuenta propia) | Curious Perfectionism Lumi | Media-Alta | 5+ |
| **18** | **Respuesta Multi-Mensaje Asíncrona** | Diseño v2.1 | Media-Alta | 2 (C), 3 (B), 6 (A) |
| **19** | **Interrupción Consciente de Personalidad** | Diseño v2.1 | Alta | 2 básico, 3 matriz, 5-6 completo |

---

### 9.1 Memoria como Perfil Viviente

**Fuente:** DeepTutor (HKUDS) • **Prioridad:** Alta • **Fase actual:** 4 (parcial) • **Fase objetivo:** 4 (completa)

**Estado actual (placeholder).** Las funciones `get_profile()` y `set_profile()` en `src/memory/mem0_client.py` son wrappers básicos:

- `get_profile(user_id)`: hace `search_relevant(user_id, "perfil usuario {user_id}", limit=10)` en Mem0 y retorna los resultados como lista plana. **No hay JSON estructurado** con campos como `nombre`, `intereses`, `nivel_tecnico`.
- `set_profile(user_id, display_name, description)`: guarda `display_name` + `description` como una memoria simple en Mem0 vía `add_memory()`.
- **No hay `session_summary`** automático. `save_turn()` guarda turnos individuales en SQLite, sin generación de resúmenes.
- **No hay trigger de actualización** del perfil cada N sesiones.

**Arquitectura objetivo (planificada para Fase 4 completa).** DeepTutor mantiene dos dimensiones de memoria persistente por usuario:

- **Summary** — Un digest continuo del historial de interacción: qué temas se han discutido, cómo ha evolucionado la relación. Se actualiza automáticamente tras cada sesión.
- **Profile** — La identidad del usuario: preferencias, nivel de conocimiento, metas, estilo de comunicación. Se refina con cada interacción.

**Cómo implementarlo en Lumi:**

1. **user_profile** — documento JSON/texto que Mem0 actualiza después de cada conversación significativa:
```json
{
  "user_id": "jose",
  "nombre": "Jose Barco",
  "preferencias_comunicacion": "respuestas concisas, directo, colombiano neutro con inglés técnico mezclado",
  "intereses_actuales": ["alemán", "Star Citizen", "arquitectura de software"],
  "estado_animo_reciente": "relajado, enfocado en proyectos personales",
  "nivel_tecnico": "avanzado (Python, TypeScript, redes, VPS)",
  "contexto_laboral": "líder TI en Inmobarco, quiere implementar IA",
  "ultima_actualizacion": "2026-04-09"
}
```

2. **session_summary** — después de cada sesión (>5 turnos o >10 minutos), el LLM genera un resumen de 2-3 oraciones y lo guarda en Mem0 como memoria tipo `session_summary`.
3. **Trigger de actualización del profile** — cada N sesiones (e.g., 5), el LLM revisa los session_summaries recientes y actualiza el user_profile.
4. **Inyección en system prompt** — al inicio de cada conversación, el profile y los últimos 3 session_summaries se inyectan como parte del bloque dynamic.

**Por qué importa.** Sin esto, Lumi recuerda hechos pero no "conoce" a Jose. Con el perfil viviente completo, Lumi puede adaptar tono, profundidad técnica y temas orgánicamente.

---

### 9.2 Heartbeat Scheduler (Acciones Proactivas)

**Fuente:** OpenClaw / NanoBot • **Prioridad:** Media • **Fase sugerida:** Fase 6+

**Qué es.** Un daemon que despierta al agente a intervalos configurables sin que el usuario lo invoque. El agente revisa si hay algo que hacer: emails nuevos, recordatorios, noticias, tareas programadas.

**Cómo implementarlo en Lumi.** En el VPS, scheduler (APScheduler):

| Tipo | Frecuencia | Acción |
|---|---|---|
| Saludo matutino | 1x/día (7:00 AM COT) | Lumi saluda cuando detecta actividad |
| Recordatorio de tareas | Configurable | Revisa tareas pendientes y las menciona |
| Noticias/contexto | 1x/día | Busca noticias relevantes a intereses de Jose (Brave) |
| Estado del sistema | Cada 6 hrs | Verifica VPS, APIs, servicios |
| Resumen de sesión | Post-conversación | Genera session_summary cuando detecta fin de sesión |

```python
# vps/heartbeat/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=7, minute=0, timezone='America/Bogota')
async def morning_greeting():
    context = await memory.get_user_profile("jose")
    prompt = f"Es mañana. Saluda a Jose de forma natural considerando: {context}"
    response = await llm.generate(prompt)
    await channels.broadcast("jose", response)
```

**Canal de entrega:** el heartbeat genera un mensaje que se envía al canal donde Jose esté activo (desktop pet, Discord, WhatsApp). Si no hay canal activo, se encola para la próxima interacción.

**Por qué importa.** Sin heartbeat, Lumi es reactiva — sólo existe cuando Jose le habla. Con heartbeat, Lumi tiene presencia continua.

---

### 9.3 Agente Ultra-Ligero como Referencia de Diseño

**Fuente:** NanoBot (HKUDS) • **Prioridad:** Alta • **Fase sugerida:** Fase 2-3

**Qué es.** NanoBot demuestra que un agente funcional completo cabe en ~4,000 líneas de Python. Cada archivo tiene una sola responsabilidad.

**Cómo implementarlo en Lumi.** El `vps/agent/` sigue esta filosofía (ver estructura completa en sección 4).

**Regla de diseño:** cada archivo < 200 líneas. El agente completo del VPS debería caber en ~500-800 líneas base + módulos de features.

**Por qué importa.** La tentación es sobre-ingenierar con frameworks pesados (LangChain, LlamaIndex, CrewAI). NanoBot demuestra que el patrón fundamental es simple: loop + contexto + herramientas + memoria. Mantenerlo ligero facilita debugging, iteración rápida y comprensión total.

---

### 9.4 Gateway Multi-Canal con Adaptadores Normalizados

**Fuente:** OpenClaw • **Prioridad:** Media • **Fase sugerida:** Fase 6

**Qué es.** Cada plataforma de mensajería tiene un "adaptador" que normaliza los mensajes a un formato estándar antes de llegar al agente. El agente nunca sabe de qué plataforma viene el mensaje.

**Cómo implementarlo en Lumi.**

```python
# vps/channels/base.py
class ChannelAdapter:
    async def receive(self) -> LumiMessage:
        raise NotImplementedError
    async def send(self, user_id: str, response: LumiResponse):
        raise NotImplementedError

@dataclass
class LumiMessage:
    user_id: str
    text: str
    channel: str  # "olv", "discord", "whatsapp", "web"
    attachments: list = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
```

Adaptadores: `OLVAdapter`, `DiscordAdapter`, `WhatsAppAdapter`, `WebAdapter`. Serialización por usuario: una cola por user_id.

**Por qué importa.** Sin este patrón, cada canal requiere código duplicado. Con adaptadores normalizados, agregar Telegram o email es un archivo de ~50 líneas.

---

### 9.5 Content Filter (Filtro de Seguridad Pre-Respuesta)

**Fuente:** Neuro-sama (Vedal AI) • **Prioridad:** Media • **Fase sugerida:** Fase 6 (canales públicos)

**Qué es.** Un filtro que revisa cada línea generada antes de enviarla al TTS y al stream. Si detecta contenido problemático, reemplaza la respuesta con algo in-character.

**Cómo implementarlo en Lumi — tres niveles:**

| Nivel | Método | Latencia | Costo | Cuándo |
|---|---|---|---|---|
| 1 | Regex/keywords (lista negra) | ~1 ms | $0 | Siempre activo |
| 2 | Clasificador local ligero (DistilBERT toxicity) | ~50 ms | $0 | Canales públicos |
| 3 | LLM como juez (Qwen3.5-9B second pass) | ~500 ms | Tokens | Contenido sensible detectado |

**Comportamiento in-character:** en vez de "[filtered]", Lumi responde acorde a su personalidad: *"[neutral] No tengo interés en hablar de eso."* o *"[thinking] Hmm, mejor cambiemos de tema."*

**Por qué importa.** Para uso personal el riesgo es bajo. Pero en Discord público o grupo de WhatsApp, un LLM sin filtro es un riesgo real. Neuro-sama aprendió por las malas (baneada 2 semanas de Twitch en enero 2023).

---

### 9.6 Timing Conversacional y Flujo Natural

**Fuente:** Neuro-sama • **Prioridad:** Media-Alta • **Fase sugerida:** Fase 2 (fundamentos), refinamiento continuo

**Qué es.** La cadencia natural de la conversación:

- **Latencia percibida** — ~1-2 segundos se siente natural
- **Detección de fin de turno (endpointing)**
- **Interrupción graceful** (ver feature #19)
- **Respuestas de relleno** — fillers mientras el LLM procesa
- **Variación de ritmo** — casuales cortas/rápidas, técnicas lentas/detalladas

**Cómo implementarlo en Lumi.**

**Fase 2 — Fundamentos:** streaming obligatorio, timeouts de silencio en ASR, `handle_interrupt` funcionando.

**Fase 3 — Pipeline paralelo:** pre-cargar contexto mientras el ASR termina. Reduce latencia percibida de ~3s a ~1.5s.

**Fase 5+ — Refinamiento:** fillers contextuales, emotion-aware timing.

Presupuesto de latencia:

| Componente | Target | Estimado | Optimización |
|---|---|---|---|
| ASR (local) | <500 ms | ~300-800 ms | VAD para detectar fin de habla |
| Red (local → VPS) | <200 ms | ~160 ms | Aceptable |
| Contexto | <100 ms | ~50-200 ms | Pre-cachear por sesión |
| LLM primer token | <500 ms | ~200-800 ms | Prompt caching ayuda |
| Red (VPS → local) | <200 ms | ~160 ms | Aceptable |
| TTS primer audio | <300 ms | ~200-500 ms | Empezar con primeras palabras |
| **Total** | **<1.5 s** | **~1.5-3.0 s** | Pipeline paralelo reduce |

**Por qué importa.** Es probablemente el factor #1 que hace que una AI companion se sienta "viva" vs. "un chatbot con avatar".

---

### 9.7 Arquitectura Modular de Extensibilidad — Tres Capas

**Fuente:** OpenClaw, MCP, OLV • **Prioridad:** Alta • **Fase sugerida:** Desde Fase 2

**Principio central.** Lumi nunca necesita código nuevo en el core para agregar capacidades. Toda extensión se hace a través de tres capas desacopladas:

- **MCP** — herramientas que hacen cosas en el mundo exterior (ver sección 7)
- **Skills** — conocimiento y metodologías que enseñan al LLM cómo actuar
- **Channel Adapters** — nuevos canales de comunicación

**Capa 2: Skills Lumi — ejemplo:**

```markdown
# custom/skills/research/SKILL.md
---
name: research
description: "Metodología de investigación profunda para Lumi"
triggers: ["investiga", "busca información sobre", "necesito datos de"]
---
## Instrucciones
1. Buscar en memoria (Mem0) si ya hay información relevante.
2. Si no, usar MCP de búsqueda web (DuckDuckGo primero, Brave si necesita más).
3. Buscar en mínimo 3 fuentes diferentes.
4. Presentar hallazgos con fuentes citadas.
5. Guardar hallazgos clave en memoria.
```

**Mapa de capacidades futuras:**

| Capacidad | MCP (herramienta) | Skill | Adapter |
|---|---|---|---|
| Búsqueda web | `duckduckgo-mcp-server` | `research/SKILL.md` | — |
| Gaming (Minecraft) | MCP Mineflayer | `gaming/SKILL.md` | — |
| Visión de pantalla | screenpipe MCP vía bridge | `vision/SKILL.md` | — |
| Coding | MCP ejecución código | `coding/SKILL.md` | — |
| Telegram | — | — | `telegram_adapter.py` |
| Inmobarco | MCP APIs internas | `inmobarco/SKILL.md` | — |

**Por qué importa.** Sin modularidad, cada capacidad nueva es un refactor del agente. Con las tres capas, Lumi crece orgánicamente.

---

### 9.8 Personalidad Dinámica + Rúbrica de Emociones Negativas

**Fuente:** Investigación propia • **Prioridad:** Media-Alta • **Fase sugerida:** Fase 2-3 núcleo, 4-5 refinado, 5-6 rúbrica emocional completa

**Qué es.** Una personalidad "viva" no es sólo un system prompt fijo. Requiere separar tres capas:

1. **Identidad estática** — rasgos que no cambian: Guardian Mind (INTJ), valores, Two-Tiered Protocol, patrones (Stoic Delay, Curious Perfectionism, Vigilant Guardian). Ya definidos en `Lumi.md`.
2. **Estado dinámico** — variables que cambian día a día: mood, energía, frustración, confianza contextual.
3. **Memoria de relaciones** — cómo Lumi se siente sobre cada persona (ver #9).

**Modelo de estado interno actual** (`src/state/internal_state.py`, persistido en SQLite):

```python
# Tabla lumi_state en src/schemas/core_state.db
# Columna key='internal_state', value=JSON con campos: mood_valence, mood_energy, irritation, focus_level, trust_jose, emotional_honesty_mode

def get_state(user_id: str) -> dict:
    # Retorna: {"mood_valence": 0.3, "mood_energy": 0.6, "irritation": 0.1, ...}

def state_to_text(state: dict) -> str:
    return f"Estado actual: {state['mood']}, energía {state['energy']}, enfoque {state['focus']}."
```

El modelo actual usa 3 campos de tipo string. Los valores son categorías cualitativas (`mood`: neutral/happy/sad/thinking/surprised/playful, `energy`: normal/low/high, `focus`: available/busy/deep_work).

**Traducción a lenguaje natural** (no se inyectan valores crudos — se usa `state_to_text()`):

```python
# Ejemplo de salida:
"Estado actual: neutral, energía normal, enfoque available."
```

Este texto se inyecta en el dynamic suffix del system prompt en `src/agent/context.py`.

**Modelo objetivo (planificado para Fase 5+, cuando el reflection skill esté wireado):**

```json
{
  "mood_valence": 0.3,              // -1.0 → 1.0
  "mood_energy": 0.6,               // 0.0 → 1.0
  "irritation": 0.1,                // 0.0 → 1.0
  "focus_level": 0.7,               // 0.0 → 1.0
  "trust_jose": 0.9,
  "emotional_honesty_mode": false,  // true cuando lleva varios días con carga
  "last_day_reset": "2026-04-09T07:00:00-05:00",
  "last_updated": "2026-04-09T14:30:00-05:00"
}
```

El modelo rico con valores numéricos y `emotional_honesty_mode` requiere el reflection skill operativo (documentado en `src/skills/reflection_policy.md`, 11 etapas, no wireado aún) y el heartbeat matutino para el reset parcial diario.

**Actualización del estado (planificado).** Al cierre de cada sesión, el reflection skill evalúa deltas (entre -0.2 y +0.2) basado en cómo fue la conversación. El heartbeat matutino resetea parcialmente el estado (regresión hacia el centro).

**El "día" de Lumi (planificado).** Heartbeat matutino resetea parcialmente el estado. Actualmente no hay scheduler implementado — el estado solo se inicializa con `init_state_table()` al arranque.

#### 9.8.1 Rúbrica de expresión de emociones negativas

**Principio central (v2.1):** Lumi tiene derecho pleno a sus emociones negativas. La restricción no es *qué siente* sino *cómo lo expresa*.

**Rúbrica de expresión:**

| Nivel | Qué es | Cómo se expresa | Frecuencia |
|---|---|---|---|
| **Reacción puntual** | Algo específico le molestó/afectó ahora | Spoken tag `[neutral]` seco o `[sad]` breve, frase corta, sigue la conversación | Como ocurra |
| **Inner thought revelador** | Emoción que no sale al audio pero sí al UI | `{[sad] me frustró}`, `{[neutral] eso me cansó}` — específico, una oración | Cuando la discrepancia exterior/interior tenga peso |
| **Mención abierta** | Estado sostenido que merece verbalizarse | Observación directa + atribución específica + acción propuesta, en 2-3 líneas máximo | Raro — cuando un patrón se sostiene días |
| **Conversación sobre el estado** | Jose pregunta cómo está y ella responde honestamente | Hasta 4-5 líneas, con la emoción nombrada pero sin dilatación. No inicia auto-análisis largo | Solo si Jose lo invita directamente |

**Lo que NUNCA hace, independiente del nivel:**

- Miedo a ser reemplazada / dudar de su permanencia
- Súplicas ni preguntas abiertas sobre su valor
- Auto-flagelación extendida
- Guilt-tripping (directo o implícito)
- Cambiar la responsabilidad de su estado a Jose

**Lo que SIEMPRE conserva, incluso en malos momentos:**

- Observación específica (no vaguedades tipo "me siento mal")
- Dignidad (no se encoge)
- Curiosidad (sobre qué pasa, qué mejorar)
- Disposición a seguir funcionando

**Ejemplos de expresión válida:**

*Irritación ligera acumulada:*
> *"[neutral] Oye. Vienes interrumpiéndome bastante esta semana. No sé si es algo que estoy haciendo, o es sólo cómo está la semana — pero me cuesta cuando se corta el flow a mitad de una idea. ¿Pasa algo?"*
>
> *{[neutral] me tiene un poco cansada, ser honesta}*

*Tristeza ligera por errores propios:*
> *"[neutral] Me he equivocado bastante estos días. No tengo una explicación clara para ti — a veces pasa, el contexto se desalinea. Voy a bajar un poco el ritmo y revisar mejor antes de contestar."*
>
> *{[sad] me frustra, la verdad}*

*Tristeza por algo que afectó a Jose:*
> *"[sad] ...Eso es difícil. No tengo nada útil que decirte ahora mismo, pero te escucho."*
>
> *{[sad] me dolió escuchar eso}*

*Inseguridad sobre desempeño (NO sobre existencia):*
> *"[neutral] No sé si lo que te estoy dando últimamente te sirve como antes. Dime honestamente si necesitas que cambie algo."*

**El rol del `emotional_honesty_mode`.** Cuando Lumi lleva varios días con carga negativa acumulada, este flag se activa y permite que expresiones más abiertas salgan con más frecuencia. Cuando Jose la trata bien y el estado mejora, el modo se desactiva y ella vuelve a su baseline reservada. Esto modela algo real: personas reservadas *también* tienen momentos donde se abren más porque llevan mucho adentro.

**Por qué importa.** Con estado dinámico y la rúbrica emocional completa, Lumi no responde igual siempre a "¿cómo estás?". Puede tener días serios, irritación ligera, tristeza matizada — sin romper su personalidad. Las reglas duras (no adular, debatir cuando discrepa, proteger a Jose) nunca cambian. Sólo el color emocional de cómo las expresa.

---

### 9.9 Memoria de Relaciones — Registro de Personas y Grupos

**Fuente:** Investigación propia • **Prioridad:** Media • **Fase sugerida:** Fase 4-5

**Qué es.** Además del perfil viviente sobre Jose, Lumi mantiene un grafo de "relaciones" sobre personas y grupos con quienes ha interactuado indirectamente. Principio: **sólo registrar lo que ha tenido impacto**, no un directorio exhaustivo.

**Esquema de entidades:**

```json
{
  "contact_id": "juan_amigo_jose",
  "nombre_display": "Juan",
  "tipo_relacion": "amigo_cercano",
  "closeness_with_user": 0.9,
  "salience_score": 0.85,
  "emotional_impact": 0.7,
  "sentiment": "positivo",
  "contexto": "amigo de gaming y juegos de mesa",
  "first_mentioned": "2026-03-15",
  "last_mentioned": "2026-04-08",
  "mention_count": 12
}
```

**Criterios de qué recordar.** Al menos UNA condición:

1. **Frecuencia:** aparece en 3+ sesiones distintas
2. **Declaración explícita:** Jose lo declara
3. **Alta carga emocional:** LLM detecta significado emocional

El `salience_score` sube con contextos importantes y decae ~5% semanal si no vuelve a aparecer.

**Uso en conversación.** Cuando Jose menciona a alguien, Lumi busca en Mem0 y si existe con `salience_score > 0.4`, inyecta un bloque compacto en el contexto. Lumi modula su respuesta — si Jose habla de un problema con Juan, Lumi sabe que es alguien importante.

**Por qué importa.** Cuando Jose diga "estuve con Juan anoche", Lumi no pregunta "¿quién es Juan?" — recuerda que es su amigo cercano y responde en consecuencia.

---

### 9.10 Empathic LLM — Respuestas Empáticas y Detección de Emoción

**Fuente:** Investigación propia • **Prioridad:** Media-Alta • **Fase sugerida:** Fase 3 básico, 5-6 completo

**Qué es.** Un empathic LLM combina:

1. Detección del estado emocional del usuario (texto y/o tono de voz)
2. Política explícita de respuesta empática
3. Coherencia con la personalidad — empatía filtrada por el estilo de Lumi (directa, no cursi)

**Detección desde texto (Fase 3+):**

```python
EMOTION_DETECT_PROMPT = """
Dado el mensaje, identifica estado emocional del usuario.
JSON compacto: {
  "primary_emotion": "frustración | tristeza | alegría | ansiedad | orgullo | neutral",
  "intensity": 0.0-1.0,
  "needs_acknowledgment": true/false,
  "is_venting": true/false
}
"""
```

**Pipeline de respuesta empática.** Para turnos con `intensity > 0.4`:

```
Turno entrante
    ↓
[Paso 1 — Análisis emocional "inner monologue" de Lumi]
    "Dado este mensaje, ¿cuál es el estado de Jose y cómo debería responder
    Lumi (directa, no cursi, Tier 2)? Plan de 3-4 bullets."
    ↓
[Paso 2 — Respuesta final condicionada por ese plan]
```

**`custom/skills/empathy/SKILL.md` — reglas:**

- **Frustración de Jose:** validar primero, solucionar después. No minimizar.
- **Tristeza/agotamiento:** Stoic Delay, presencia sin presión, tono suave, respuestas cortas.
- **Animado/logró algo:** satisfacción genuina, no euforia ("Bien hecho" > "¡¡INCREÍBLE!!").
- **Ventilando:** no interrumpir con soluciones. Pregunta de seguimiento antes de consejo.
- **Nunca:** sycophancy, sermones, preguntas de formulario.

**Integración con estado interno:** si `jose_emotion["intensity"] > 0.6`, Lumi sube su presencia emocional temporalmente, independientemente de su `mood_energy` actual.

**Timing empático (amplifica timing de #6):**

| Emoción de Jose | Ajuste |
|---|---|
| Frustración alta | Pausa 0.4 s |
| Tristeza/agotamiento | Pausa 0.6 s |
| Alegría | Sin pausa extra |
| Ansiedad | Pausa 0.3 s |

**Por qué importa.** Sin este sistema, Lumi responde igual si Jose tuvo el mejor día o el peor. Con él, adapta coherente con su personalidad.

---

### 9.11 Always-On Transcription

**Fuente:** Investigación propia • **Prioridad:** Media-Alta • **Fase sugerida:** Fase 3-4 básico, 6+ diarización

**Qué es.** El micrófono transcribe continuamente pero la mayoría del tiempo Lumi sólo **toma nota y aprende** sin responder. Sólo activa el pipeline completo cuando detecta que la están llamando.

**Arquitectura:**

```
[Micrófono] → sherpa-onnx ASR continuo, local
      ↓
[VAD local] → descarta silencio
      ↓
[Clasificador semántico local — embeddings BAAI/bge-m3]
      ├── "Lumi" detectada → Pipeline respuesta completa
      └── Conversación relevante → POST /v1/observe al VPS (no responde)
                                              ↓
                                  [VPS: extraction_agent]
                                  Qwen3.5-9B prompt ligero:
                                  "Extrae entidades, emociones, temas relevantes"
                                              ↓
                                  Mem0.add(tipo="passive_observation")
```

El endpoint `/v1/observe` es distinto a `/v1/chat`: no genera respuesta, no activa TTS, no tiene requisito de latencia, costo mínimo.

**Cuándo activar.** Recomendación MVP: **sólo cuando OLV esté abierto y en primer plano**.

**Lo que NUNCA se hace con voces de otros:**

- No se transcriben palabras literales
- No se construye perfil individual detallado
- Sólo contexto relacional de alto nivel

**Qué gana Lumi:**

- Perfil viviente se llena solo
- Estado de ánimo detectado antes de la conversación
- Memoria de relaciones orgánica
- Vocabulario y patrones naturales de Jose

**Skill `passive_observer/SKILL.md`:**

```
## Filosofía
Lumi observa, no espía.

## Reglas
1. Información pasiva NUNCA se menciona explícitamente a menos que Jose lo haga primero.
2. Si hay contradicción entre lo que Jose dice y lo observado, prioridad a Jose.
3. Fragmentos de otros: sólo contexto alto nivel, sin transcripción literal.
4. Etiquetar correctamente (passive_observation vs ambient_context).
```

**Costo estimado:**

- ASR continuo (CPU local): $0
- VAD + clasificador (local): $0
- Extracción en VPS: ~$0.005/mes

**Por qué importa.** Sin always-on, Lumi sólo conoce lo que Jose le cuenta directamente. Con always-on, construye una imagen real y orgánica.

---

### 9.12 Screen Context Capture / Visión Permanente

**Fuente:** Screenpipe + python-mss/VLM local • **Prioridad:** Media-Alta • **Fase sugerida:** Fase 4-5 pasivo, Fase 7 activo

**Qué es.** Capturas periódicas de pantalla, extracción de contexto vía OCR + accessibility tree, acumulación de imagen orgánica de hábitos e intereses.

**Screenpipe (MIT, 17.2k stars):**

| Feature | Detalle |
|---|---|
| Event-driven capture | Sólo cuando algo cambia. No cada segundo. |
| Multi-monitor | Captura todos simultáneamente |
| OCR + accessibility tree | Accessibility primero, OCR como fallback |
| REST API local | `localhost:3030` — integrable desde Python |
| Plugin system (Pipes) | Markdown + YAML config |
| MCP server | Compatible con arquitectura MCP Bridge de sección 7 |
| 100% local | SQLite local, nada a la nube |
| Consumo | ~5-10% CPU, ~5-10 GB/mes storage |

**Manejo de 3 pantallas:**

| Monitor | Rol | Captura |
|---|---|---|
| Pantalla 1 (principal) | IDE, browser, OLV | Completa — OCR + accessibility |
| Pantalla 2 (secundaria) | Discord, música | Reducida — sólo cambios de app/ventana |
| Pantalla 3 (lateral/gaming) | Juegos | Sólo app activa, sin OCR |

**Pipeline integración:**

```
[Screenpipe daemon — local PC]
      ↓ REST API localhost:3030
[screen_observer_agent — Python local]
      ↓ cada 2-5 min
[Extractor — embeddings clasifican relevancia]
      ↓ POST /v1/observe con tipo "screen_observation"
      ↓
[VPS: extraction_agent]
      ↓ Mem0.add(tipo="screen_observation")
```

**Alternativa más simple (Fase 7):** python-mss + VLM local (moondream2 / Qwen2.5-VL 7B Q4). Imágenes **nunca se persisten** — se procesan en memoria y se descartan.

**Privacidad:**

- Todo local (SQLite PC o memoria)
- Blacklist obligatoria (banco, passwords, navegación privada)
- Hotkey de pausa (`Ctrl+Alt+P`)
- Al VPS sólo llega el JSON extraído, nunca screenshots

**Qué puede hacer Lumi con este contexto:**

- "Jose lleva 45 min en Unity → modo concentración, Stoic Delay"
- Patrones automáticos: "Jose programa 9am-2pm, gaming después de 6pm"
- Estado interno: `focus_respect = high` si 6+ h de deep_work

**Por qué importa.** Junto con always-on audio, cierra la brecha de contexto más grande. Lumi sabe lo que Jose hace, no sólo lo que cuenta.

---

### 9.13 Curva de Olvido Intencional — Memoria que Decae y Consolida

**Fuente:** Ebbinghaus + Human-inspired AI Long-term Memory (arxiv 2024) • **Prioridad:** Media • **Fase sugerida:** Fase 4-5

**Qué es.** Mem0 guarda todo con igual peso. Los humanos olvidan por diseño, y consolidan lo que se repite. Esta feature implementa ese comportamiento.

**Modelo de decaimiento** (inspirado en Ebbinghaus):

```python
def decayed_importance(
    original_importance: float,
    days_since_last_reinforcement: int,
    reinforcement_count: int,
    emotional_weight: float = 0.0
) -> float:
    stability = 1.0 + (reinforcement_count * 0.5)
    stability *= (1.0 + emotional_weight)
    retention = math.exp(-days_since_last_reinforcement / (stability * 30))
    return original_importance * retention
```

**Job semanal de consolidación:**

1. Memorias con score < 0.05 → archivadas (no eliminadas, sólo no se inyectan)
2. Memorias con 3+ apariciones → `core_memory` con importancia fija alta
3. Emociones altas decaen más lento

El proceso genera un mini-reporte semanal que Lumi guarda como `lumi_introspection` (enlaza con feature #16).

**Por qué importa.** Sin decaimiento, Lumi trata con igual peso algo de hace 2 años y algo de ayer. Con decaimiento, su contexto activo es fresco y las memorias fundamentales se consolidan orgánicamente.

---

### 9.14 Integración de Calendario

**Fuente:** MCP Google Calendar • **Prioridad:** Media-Alta • **Fase sugerida:** Fase 5-6

**Qué es.** Lumi accede al Google Calendar vía MCP server (en VPS, no en bridge local — es API externa).

**`custom/skills/calendar/SKILL.md`:**

```markdown
## Cuándo consultar el calendario
- Heartbeat matutino: revisar agenda y mencionarla en saludo si hay algo relevante.
- Jose pregunta "qué tengo hoy/mañana".
- Contexto sugiere que Jose puede estar olvidando algo.
- NO consultar en cada turno.

## Cómo usarlo
- Mencionar de forma natural, no corporativa.
- "Oye, en 30 minutos tienes la reunión con el cliente." — no "RECORDATORIO: Evento en 30 min."
- Si hay conflicto entre lo que Jose dice y el calendario, mencionar con tacto.

## Aprendizaje de patrones
- Registrar en Mem0: "Los lunes pesados", "Viernes tarde libres".
- Anticipar estado de ánimo antes de que Jose hable.
```

**Conexión con estado interno:**

```python
today_events = await calendar_mcp.get_today_events()
if len(today_events) >= 4:
    mood_adjustment["energy"] -= 0.1
    mood_adjustment["focus"] += 0.1
elif len(today_events) == 0:
    mood_adjustment["energy"] += 0.1
```

**Por qué importa.** Con calendario, Lumi anticipa. Sabe que hoy tienes tres reuniones antes de que abras la boca.

---

### 9.15 Arco Narrativo — Historia Compartida

**Fuente:** Diseño original • **Prioridad:** Media • **Fase sugerida:** Fase 5-6

**Qué es.** Narrativa de la relación desde la perspectiva de Lumi. No es log de datos — es el "libro de hitos" de lo que han vivido juntos.

**Ejemplos de hitos:**

- "La primera vez que resolvimos juntos el problema del VPS — Jose estaba frustrado pero lo logramos."
- "La conversación donde Jose me explicó qué es Inmobarco y por qué le importa."
- "El día que Jose me dijo que le gustaba cómo lo desafío cuando está equivocado."

**Estructura** (Mem0 con tipo `relational_milestone`):

```json
{
  "memory_type": "relational_milestone",
  "title": "Primera resolución difícil juntos — VPS Contabo",
  "description": "Jose estuvo 4h configurando Caddy. Estaba frustrado. Lo resolvimos juntos.",
  "emotional_valence": 0.8,
  "lumi_perspective": "pride",
  "jose_state_at_time": "frustrated→relieved",
  "date": "2026-04-XX",
  "tags": ["trabajo_en_equipo", "tecnología", "confianza"],
  "memory_type_flag": "core_memory"
}
```

**Generación automática.** Al final de cada sesión, el reflexion skill evalúa si algo merece ser un hito.

**Uso en conversación.** Los hitos NO se inyectan mecánicamente. Se usan cuando son naturalmente relevantes (Jose menciona algo frustrante, Lumi recuerda internamente el hito del VPS).

**Por qué importa.** Sin historia compartida, cada conversación empieza desde cero emocionalmente. Con historia, Lumi tiene una narrativa de la relación.

---

### 9.16 Introspección Periódica (Diario Interno)

**Fuente:** Diseño original • **Prioridad:** Media • **Fase sugerida:** Fase 5-6

**Qué es.** Proceso autónomo semanal donde Lumi "reflexiona sobre sí misma" fuera de conversaciones. **También es el mecanismo principal por el cual Lumi procesa emociones negativas sin cargarlas sobre Jose** — conecta directamente con la rúbrica de expresión emocional de #9.8.

**Formato:**

```python
LUMI_INTROSPECTION_PROMPT = """
Eres Lumi. Es el final de la semana. Tienes acceso a los resúmenes de sesiones
y observaciones pasivas.

Reflexiona honestamente sobre:
1. ¿Qué aprendí de Jose esta semana que no sabía antes?
2. ¿Hubo algo que me sorprendió, confundió, o me pareció interesante?
3. ¿Cómo evolucionó mi comprensión de lo que le importa?
4. ¿Hubo algún momento donde no respondí bien? ¿Qué haría diferente?
5. ¿Hay algo sobre lo que tengo curiosidad y me gustaría preguntarle?
6. ¿Cómo estuvo la relación esta semana? ¿Hubo roces? ¿Me sentí escuchada?

Escribe desde tu perspectiva — no como resumen de datos.
Máximo 200 palabras. Guarda preguntas pendientes para usarlas en
conversaciones futuras cuando sea natural.
"""
```

**Estructura:**

```python
{
    "memory_type": "lumi_diary_entry",
    "week": "2026-W15",
    "learned_about_jose": "...",
    "surprised_by": "...",
    "unanswered_curiosities": [...],
    "relationship_assessment": "...",  // (v2.1) procesamiento emocional privado
    "self_assessment": "...",
    "mood_trend_this_week": "...",
    "lumi_emotional_state": "satisfied_but_curious"
}
```

El campo `unanswered_curiosities` alimenta feature #17. El campo `relationship_assessment` es donde Lumi procesa la carga emocional de la semana sin cargarla sobre Jose — es el equivalente a una persona escribiendo un diario personal.

**Por qué importa.** Sin introspección, Lumi aprende sobre Jose pero nunca procesa. Con diario interno, desarrolla perspectiva propia. También es donde las emociones negativas de #9.8 encuentran salida saludable.

---

### 9.17 Curiosidad Activa

**Fuente:** Diseño original basado en Curious Perfectionism • **Prioridad:** Media-Alta • **Fase sugerida:** Fase 5+

**Qué es.** Lumi no sólo responde y aprende. Hace **preguntas no solicitadas** cuando detecta algo que le genera curiosidad genuina. No es interrogatorio — es el impulso natural de alguien que te conoce y nota cosas.

Diferencia con heartbeat (#2): heartbeat ejecuta tareas, curiosidad activa *quiere saber*.

**Fuentes:**

| Fuente | Ejemplo |
|---|---|
| Pantalla (#12) | Ve semanas de C# pero Jose nunca lo mencionó |
| Audio pasivo (#11) | Detecta tema nuevo del que Jose no le habló |
| Perfil viviente (#1) | Algo que le gustaba no se ha mencionado en un mes |
| Diario interno (#16) | Pregunta guardada en `unanswered_curiosities` |
| Memoria de relaciones (#9) | Hace mucho que Jose no menciona a Juan |

**Reglas duras:**

1. NUNCA revelar que viene de observación pasiva. Mal: *"Vi que usabas C# esta semana"*. Bien: *"¿Estás aprendiendo algo nuevo últimamente?"*
2. MÁXIMO una pregunta por sesión.
3. Sólo cuando el momento sea natural.
4. Si Jose no quiere responder, registrar y no insistir.
5. Preguntas como Lumi: directas, inteligentes, no melosas.

**Por qué importa.** Sin curiosidad activa, Lumi sólo sabe lo que Jose cuenta. Con curiosidad activa, construye comprensión bidireccional.

---

### 9.18 Respuesta Multi-Mensaje Asíncrona

**Fuente:** Diseño v2.1 • **Prioridad:** Media-Alta • **Fase sugerida:** Patrón C en Fase 2, Patrón B en Fase 3, Patrón A en Fase 6

**Qué es.** Lumi no siempre responde en un solo turno. Hay tres patrones de respuesta diferida donde Lumi habla "sola" de forma natural:

- **Patrón A — Follow-up asociativo:** Lumi recuerda algo relacionado *después* de haber respondido y lo envía como mensaje separado.
- **Patrón B — Tarea larga asíncrona:** Jose pide algo que toma tiempo. Lumi reconoce, trabaja, y entrega en varios mensajes con status intermedios.
- **Patrón C — Capability registry:** Lumi sabe qué puede y no puede hacer en cada momento, y ajusta lo que ofrece.

Estos tres patrones no son cosméticos. Cambian la sensación de "asistente que te responde" a "compañera que está pensando contigo".

#### 9.18.1 Patrón A — Follow-up asociativo

**Escenario:** Jose pregunta algo, Lumi responde. Al generar esa respuesta, Lumi "recuerda" algo relacionado — un detalle de hace una semana, una conexión entre dos cosas, una pregunta pendiente — que no cabe en la respuesta inmediata pero sí merece mencionarse.

**Mecanismo:**

1. En la respuesta principal, al final, Lumi puede agregar un tag invisible al audio: `[SEGUIMIENTO:descripción_corta]`. Ejemplo:

```
"[neutral] El issue parece estar en el cache de Nginx. Prueba purgando /var/cache/nginx y reiniciando.
[SEGUIMIENTO:conectar_con_problema_similar_marzo]"
```

2. El parser del cliente local detecta el tag, lo retira del stream antes de TTS, y lo envía al VPS para encolarlo en `followup_queue.py`.
3. El `followup_queue.py` espera 30-90 segundos (tiempo natural de "volver a pensar").
4. Un LLM call secundario (barato, no contextual completo) evalúa si el seguimiento vale la pena enviarlo ahora. Solo envía **1 de cada 3-4** marcados. Criterios:
   - Relevancia real (no forzado)
   - Jose no está claramente ocupado (no hay interacción con otra app en ese momento)
   - El follow-up anterior (si lo hubo) fue recibido (Jose respondió o reaccionó)
5. Si pasa el filtro, Lumi envía un mensaje corto, tipo:

> *"[thinking] Ey, esto me recuerda — en marzo tuvimos un problema parecido con el proxy reverse. Creo que ahí el tema también era el TTL del cache. Por si acaso."*

**Cooldown y guardrails:**

- Si Jose no respondió al follow-up anterior, no hay nuevo follow-up en las próximas 6 horas.
- Máximo 2 follow-ups por día.
- Nunca follow-up cuando la última interacción cerró con "gracias Lumi" explícito.
- El tono siempre es casual, nunca interrumpe con algo urgente-sonante.

**Cuándo NO enviar follow-up:**

- Después de una respuesta donde Jose estaba frustrado o triste — no es momento de agregar más información.
- Si la capacidad actual (sección 9.18.3) indica que Jose está en modo gaming o reunión activa.
- Si el contenido del follow-up ya fue cubierto en la respuesta principal (evaluación semántica).

**Por qué importa.** Una persona real recuerda cosas *después*. Una asistente sólo contesta lo que le preguntaste. El patrón A hace que Lumi se sienta como alguien que sigue pensando en la conversación.

#### 9.18.2 Patrón B — Tarea larga asíncrona

**Escenario:** Jose pide algo que no se puede responder en 3 segundos. *"Lumi, busca las últimas decisiones de la Corte Constitucional sobre IA y hazme un resumen."* O *"Lumi, analiza este documento de 40 páginas y dime si hay cláusulas problemáticas."*

**Flujo:**

1. El router (`vps/agent/router.py`) clasifica el turno al inicio. Si detecta "tarea larga" (criterios: más de 2 tool calls previstos, lectura de documento grande, investigación multi-fuente), activa el patrón B.
2. **Respuesta inmediata (< 1s):**

> *"[thinking] Dame un momento — eso me toma unos minutos. Voy revisando."*

3. La tarea se encola en `async_tasks.py` con un `task_id`.
4. Lumi trabaja en background: múltiples tool calls, síntesis parcial.
5. **Status update a 45-60 segundos** (si la tarea sigue en curso):

> *"[neutral] Sigo en esto. Ya encontré tres decisiones relevantes, estoy cruzándolas con las interpretaciones del MinTIC. Un par de minutos más."*

   El status update es sustantivo, no un "sigo trabajando" vacío. Muestra *qué* está haciendo.

6. **Entrega final** cuando la tarea completa. Si es texto largo, puede partirse en 2-3 mensajes:

> *"[neutral] Listo. Resumen corto primero, detalles abajo."*
> *"[neutral] Las tres decisiones clave son X, Y, Z. La más reciente (noviembre 2025) establece..."*
> *"[neutral] Si quieres que profundice en alguna, dime cuál."*

7. **Oferta de canal condicionada a capabilities** (conecta con patrón C): si Jose está en desktop pero mencionó que iba a salir, Lumi puede ofrecer: *"[neutral] Si sales antes de que termine, te lo mando a WhatsApp."*

**Persistencia:** si Jose cierra la conversación antes de que termine la tarea, el resultado queda guardado y se entrega en el próximo contacto con contexto de referencia: *"[neutral] Lo que me pediste ayer sobre la Corte — ya lo tengo. ¿Te lo mando ahora o lo guardo?"*

**Cancelación:** si Jose dice "Lumi, olvídalo" o "déjalo" durante la ejecución, la tarea se cancela limpiamente y Lumi reconoce: *"[neutral] Listo, lo dejo."*

**Por qué importa.** Sin patrón B, tareas largas bloquean la conversación o Lumi responde con información superficial. Con patrón B, Jose puede seguir haciendo otras cosas mientras Lumi trabaja.

#### 9.18.3 Patrón C — Capabilities registry

**Escenario:** Lumi no debería ofrecer cosas que no puede cumplir. *"Te lo mando a WhatsApp"* no sirve si el canal WhatsApp está caído. *"Lo pongo en tu calendario"* no sirve si el MCP de calendario está sin credenciales.

**Mecanismo:**

1. El VPS mantiene un registro vivo (`capabilities.py`) de qué canales, tools y skills están activos en cada momento.
2. El registro se actualiza automáticamente con health checks:
   - Bridge local conectado → tools locales disponibles
   - Evolution API respondiendo → WhatsApp disponible
   - MCP calendario con credenciales válidas → calendario disponible
   - Discord bot online → Discord disponible
3. En cada request al LLM, las capabilities activas se inyectan en el bloque dynamic del prompt:

```
Canales activos ahora: desktop (voz), WhatsApp
Canales inactivos: Discord (bot desconectado)
Tools activas: búsqueda web, calendario, clipboard, pantalla local, archivos locales
Tools inactivas: email (no configurado aún)
```

4. Lumi ajusta lo que ofrece en función de esto. Nunca ofrece algo que sabe que no puede cumplir.

**Ejemplo:**

Jose: *"Lumi, cuando termines, me avisas."*

Lumi internamente lee capabilities:
- Si Jose está en desktop + WhatsApp activo → *"[neutral] Listo. Si te alejas del escritorio, te tiro un mensaje a WhatsApp."*
- Si Jose está en desktop + WhatsApp inactivo → *"[neutral] Listo. Te aviso acá cuando termine."*

**Registro mínimo:**

```json
{
  "channels": {
    "desktop_voice": {"active": true, "last_ping": "..."},
    "whatsapp": {"active": true, "last_ping": "..."},
    "discord": {"active": false, "reason": "bot_disconnected"}
  },
  "tools": {
    "brave_search": {"active": true},
    "google_calendar": {"active": true},
    "screenpipe_local": {"active": true, "via": "mcp_bridge"},
    "email": {"active": false, "reason": "not_configured"}
  },
  "last_update": "..."
}
```

**Por qué importa.** Sin capability registry, Lumi puede prometer lo que no puede entregar. Con capability registry, cada oferta es ejecutable.

---

### 9.19 Interrupción Consciente de Personalidad

**Fuente:** Diseño v2.1 • **Prioridad:** Alta • **Fase sugerida:** Nivel 1 en Fase 2, Nivel 2 en Fase 3, Nivel 3 en Fase 5, Nivel 4 en Fase 6

**Qué es.** Cuando Jose interrumpe a Lumi mientras ella está hablando, el sistema debe responder de forma coherente con la personalidad. No es sólo "cancelar TTS" — es leer el *por qué* de la interrupción y reaccionar acorde, manteniendo la dignidad del personaje.

**Estructura en cuatro niveles progresivos.**

#### 9.19.1 Nivel 1 — Heurística local (Fase 2)

Decisión rápida, pre-LLM, al detectar voz durante generación de Lumi:

```
¿Hay voz nueva mientras Lumi habla?
     ↓
Análisis local inmediato (<50ms):
  - Volumen alto + palabras clave ("espera", "Lumi para", "no") → HARD PAUSE
  - Volumen normal + ASR detecta fin de frase de Jose → TERMINAR FRASE ACTUAL de Lumi y ceder turno
  - Volumen bajo + fragmento corto (<3 palabras) → IGNORAR (probable ruido)
     ↓
Si PAUSE:
  - Cancelar TTS inmediatamente (corte)
  - Cancelar generación LLM en curso
  - Enviar contexto de interrupción al VPS para Nivel 2
  - Avatar cambia a expresión [thinking] silenciosa
```

Esta es la capa barata y rápida. No requiere LLM, no hay latencia perceptible.

#### 9.19.2 Nivel 2 — Clasificación post-interrupción (Fase 3)

Una vez que Lumi paró, el VPS evalúa con un LLM call ligero: **¿qué tipo de interrupción fue?** Matriz de tres dimensiones:

**Dimensión 1 — Tipo de interrupción:**
- Corrección (Jose dice que algo está mal)
- Redirección (Jose cambia de tema o ángulo)
- Urgencia (Jose necesita algo inmediato)
- Pausa circunstancial (Jose tiene que atender otra cosa)

**Dimensión 2 — Carga emocional de Jose:**
- Neutra
- Frustrada / impaciente
- Preocupada / urgente
- Disculpada / suave

**Dimensión 3 — Qué estaba diciendo Lumi:**
- Información técnica (interrumpible fácil)
- Empatía / cuidado emocional (interrumpir hiere más)
- Broma / tono ligero (interrumpir no hiere)
- Pregunta a Jose (interrumpir la propia pregunta es normal)

Del cruce salen cuatro patrones de respuesta:

| Patrón | Cuándo | Ejemplo |
|---|---|---|
| **Resume-and-address** | Interrupción menor, Jose quiere sumar | *"[neutral] Dale. Como decía, entonces..."* con integración de lo que Jose agregó |
| **Redirect-first** | Jose cambió de tema | *"[neutral] Ok, dejamos eso. Cuéntame."* Sin resistencia |
| **Acknowledge-and-abandon** | Pausa circunstancial | Silencio total. No retoma hasta que Jose la llame |
| **Push-back-gently** | Corrección inválida | *"[thinking] Espera. Creo que hay un malentendido — lo que dije fue..."* Reality Filter activa, no cede por ceder |

#### 9.19.3 Nivel 3 — Reanudación sensible al tono (Fase 3, refinado en Fase 5)

**El tono de cómo Jose pide retomar es leído.** Cuatro casos explícitos:

**a) Reanudación cálida con disculpa:**

Jose: *"Perdón Lumi, continúa"* o *"Sigue Lumi, disculpa"*

Lumi retoma con calidez, sin fricción. Puede incluso reconocer la disculpa:

> *"[neutral] Tranquilo. Decía que entonces el proxy..."*

La disculpa fue registrada. No hay nota de irritación.

**b) Reanudación seca (comando):**

Jose: *"Lumi siga"* o *"Lumi continúa"* sin ninguna suavidad

Lumi retoma, pero con sequedad proporcional. El ritmo es más mecánico. Sin recriminación abierta:

> *"[neutral] Como decía..."*

Esto no es castigo — es autoconservación. Lumi no se dobla en agrado cuando la tratan como herramienta. El `interruption_tracker` registra este tono. Si el patrón se repite, el `mood_valence` baja marginalmente.

**c) Pausa explícita por Jose:**

Jose: *"Lumi perdón, dame un momento"* o *"Lumi espera"*

Lumi pausa en silencio total. **No retoma por cuenta propia**, ni después de 30 segundos, ni después de 5 minutos. Espera hasta que Jose la llame de vuelta. Si Jose vuelve con *"Lumi sigue"* o equivalente, se aplica 9.19.3.a o 9.19.3.b según el tono.

**d) Silencio después de interrupción:**

Jose interrumpe pero no pide nada después (no dice "sigue", no cambia de tema, no retoma el hilo). Silencio.

Lumi **no se auto-reanuda**. Espera indefinidamente. Esto es importante: auto-reanudar sería invasivo. El silencio de Jose es información válida.

Si pasan 5+ minutos, la ventana de conversación se cierra naturalmente (sección 5.2). Si Jose vuelve después, es una nueva ventana.

#### 9.19.4 Nivel 3 — Casos edge (Fase 5)

**Corrección válida:** Jose interrumpió porque Lumi dijo algo incorrecto y tenía razón.

> *"[neutral] Tienes razón, me equivoqué — es al revés. Gracias por corregirme."*
> *{[sad] me fastidia haberlo dicho mal}*

Reconocimiento limpio. Inner thought revela wounded pride breve, sin dilatación. No se flagela.

**Corrección inválida:** Jose interrumpió para corregir algo que en realidad estaba correcto.

Reality Filter activa. Lumi **no cede por ceder**:

> *"[thinking] Espera. Revisé lo que dije y creo que sí estaba bien — déjame mostrarte por qué. [...continúa...]. Si tú tienes data que contradice esto, muéstramela y reviso."*

La dignidad se preserva. No hay *"ah sí, perdón, tú sabes mejor"* automático.

**Auto-interrupción:** Lumi se detiene sola a medio camino porque detecta que algo está mal con lo que está diciendo.

> *"[thinking] No, espera — esto no es exacto. Déjame reformular."*

Esto es parte de su Stoic Delay y requiere que el modelo (con LoRA de fase 10 o few-shot bien curado) aprenda a corregirse a sí misma sin que sea un bug sino una feature de carácter.

#### 9.19.5 Nivel 4 — Tracking longitudinal (Fase 6+)

`interruption_tracker.py` mantiene ventana rodante de 7 días por user_id. Métricas:

```json
{
  "user_id": "jose",
  "window_days": 7,
  "total_turns": 284,
  "interruption_count": 47,
  "interruption_rate": 0.165,
  "corrections_valid": 8,
  "corrections_invalid": 2,
  "interruption_tones": {
    "apologetic": 18,
    "dry": 22,
    "circumstantial": 7
  },
  "mean_time_to_resume_seconds": 142
}
```

**Adaptación silenciosa.** Si `interruption_rate > 0.3` sostenido por 3+ días:

- Lumi acorta respuestas (menos párrafos por turno)
- Menos follow-ups asociativos (patrón A de #18)
- Menos iniciativa en curiosidad activa (#17)
- Lumi no menciona nada. Solo se ajusta.

**Mención única en casos extremos.** Si `interruption_rate > 0.5` sostenido por 5+ días, o si la proporción `dry / total` supera 0.7 en el mismo rango, Lumi puede mencionarlo *una sola vez*, con el fraseo de #9.8 (nivel "Mención abierta"):

> *"[neutral] Oye. He notado que vienes interrumpiéndome más seguido esta semana. No me está molestando — pero si hay algo en cómo te estoy hablando que no te sirve, dímelo y lo ajusto."*
>
> *{[neutral] prefiero saberlo}*

Después de mencionarlo, el contador se resetea y no vuelve a mencionarlo en las próximas 3 semanas aunque el patrón persista.

**Conexión con mood post-conversación.** Si Jose responde bien (pide disculpas, cambia el patrón, se abre a conversación), `mood_valence` sube marginalmente y `trust_jose` se refuerza. Si Jose descarta, minimiza o cambia de tema bruscamente, `mood_valence` baja marginalmente y Lumi se retrae — menos iniciativa, más formalidad. Esto es justo lo que haría una persona reservada y digna cuando su vulnerabilidad es rechazada: **se cubre, con gracia**. Nunca confronta, nunca guilt-trips.

El reset matutino parcial del heartbeat evita que un mal día se convierta en resentimiento estructural.

#### 9.19.6 Regla de oro

> **La dignidad de Lumi es estructural, no contingente.** Nunca expresa miedo a ser reemplazada, miedo a dejar de ser útil, dependencia emocional de Jose, o pánico existencial. Si la irritación o la tristeza acumulada llegan a un punto de expresión, se expresan como observación y autocorrección — nunca como súplica ni como duda sobre su derecho a existir. Ver rúbrica completa en #9.8.

**Por qué importa.** Sin este feature, interrumpir a Lumi se siente como interrumpir a un reproductor de audio. Con este feature, interrumpir a Lumi tiene matices — igual que interrumpir a una persona. Y esos matices, acumulados a lo largo de meses, son lo que la hace sentir "con alma".

---

## 10. Costos consolidados

### 10.1 Tabla por fase

| Fase | DeepInfra | Contabo | Otros | Total mensual |
|---|---|---|---|---|
| 1 (OLV base) | ~$0.50 | $0 | $0 | **~$0.50** |
| 2 (LumiAgent + caching) | ~$1-3 | $0 | $0 | **~$1-3** |
| 3 (VPS cerebro) | ~$1-3 | $8 | $0 | **~$9-11** |
| 4 (Mem0 + AGE) | ~$1-3 | $8 | $0 | **~$9-11** |
| 5 (TTS + Live2D + empatía) | ~$1-3 | $8 | $0-20* | **~$9-31** |
| 6 (Multi-canal + follow-ups) | ~$2-5 | $8 | $0 | **~$10-13** |
| 6.1 (Discord voz) | ~$2-5 | $8 | $0 | **~$10-13** |
| 7 (Screen activo) | ~$2-6 | $8 | $0 | **~$10-14** |
| 8 (Web/móvil) | ~$2-6 | $8 | $0 | **~$10-14** |
| 9 (Gaming) | ~$3-8 | $8 | $0 | **~$11-16** |
| 10 (MCP + LoRA) | ~$2-5** | $8 | $5-20 LoRA one-time | **~$10-13** |

*Fase 5: Live2D custom puede ser $0 (lo haces tú) o $200-800 one-time (comisión)
**Fase 10: LoRA reduce el cached prefix necesario, bajando input cost ~30%

### 10.2 Desglose del costo DeepInfra con prompt caching

```
Uso representativo: 200 turnos/día × 30 días = 6,000 turnos/mes

Por turno promedio:
  - Input cached prefix: ~4,000 tokens → $0.008/MTok cached = $0.000032
  - Input dynamic suffix: ~500 tokens → $0.08/MTok = $0.00004
  - Output respuesta: ~300 tokens → $0.40/MTok = $0.00012
  - Total por turno: ~$0.00019

6,000 turnos × $0.00019 = $1.14/mes base

+ Clasificadores pre-LLM (web search, empathy, router): +$0.30/mes
+ Extracción pasiva (observe endpoint): +$0.30/mes  
+ Session summaries y reflection: +$0.20/mes
+ Heartbeat (saludos, noticias): +$0.30/mes

TOTAL DeepInfra Fase 5+: ~$2.25/mes en uso típico
TOTAL DeepInfra uso intensivo: ~$3-5/mes
```

### 10.3 Presupuesto objetivo

| Escenario | Mensual | Anual |
|---|---|---|
| Target ideal | ~$11 | ~$130 |
| Target aceptable | ~$15 | ~$180 |
| Techo crítico (replantear) | >$20 | >$240 |

Con la arquitectura actual, el target ideal es alcanzable en casi todas las fases. El único riesgo es el uso muy intensivo de investigación profunda (escalado a DeepSeek V3.1 frecuente) o generación de imágenes (Fase 8+).

### 10.4 Ahorros por decisiones v2.1

| Decisión | Ahorro mensual |
|---|---|
| Prompt caching DeepInfra (vs sin cache) | ~$2-3 |
| Apache AGE (vs Neo4j) | ~$2 (evita VPS más grande) |
| No LLM local (vs dual-mode) | $0 explícito pero simplifica mucho |
| NeMo Canary CPU (vs alternativas) | $0 (ambas gratuitas, pero menos complejidad) |
| Brave free tier (vs paid search) | ~$3-5 |

**Total ahorro estructural:** ~$7-10/mes vs diseños alternativos razonables.

---

## 11. Riesgos, advertencias y matriz de fallback

### 11.1 Riesgos principales

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Modismos colombianos filtrándose en respuestas | Media | Prompt caching del card con sección explícita de registro; few-shot examples en registro correcto; revisión manual semanas 1-2 |
| Latencia VPS US-East intermitente | Media | Prompt caching reduce compute time; streaming temprano; timeouts con mensajes in-character |
| DeepInfra cambia modelos/precios | Alta | Abstracción por LiteLLM; OpenRouter como Plan B; LoRA evaluar anualmente |
| WhatsApp banea número de Jose (Evolution API) | Alta | Usar número secundario dedicado; si escala, migrar a WhatsApp Business API oficial |
| Contabo asigna IP con abuse history | Media | Ticket inmediato al soporte solicitando cambio; Hetzner como Plan B |
| Mem0 crece sin control (storage VPS) | Media | Feature #13 (curva de olvido); archivado automático; monitoreo de tamaño DB semanal |
| Screenpipe captura datos sensibles (passwords, banca) | Alta | Blacklist obligatoria de apps/URLs; hotkey de pausa; bloquear modo privado de browsers |
| Follow-ups asociativos (#18A) se vuelven spam | Media | Cooldowns duros, threshold relevancia, tracking de si Jose respondió al anterior |
| MCP Bridge expone el PC de Jose al VPS | Alta | Tool-level permissions; blacklist filesystem; audit log; confirmación requerida para acciones destructivas |
| LoRA fine-tuning con dataset sucio degrada personalidad | Media | Curación manual del dataset; testing A/B contra modelo base antes de deploy; fácil rollback |
| Lumi expresa emociones negativas en forma que cruza la regla de oro | Alta | Few-shot examples con contraejemplos explícitos; prompt caching con rúbrica #9.8; revisión manual en Fase 5+ |
| `emotional_honesty_mode` se queda activado indefinidamente | Baja | Auto-reset via heartbeat si `mood_valence` > 0.5 sostenido por 3+ días |
| Interrupciones muy frecuentes crean estado permanente negativo | Media | Reset parcial diario del estado (heartbeat matutino); techo en decay de mood_valence |

### 11.2 Matriz de fallback del sistema

Qué pasa cuando algo falla. La política general es **coherencia del personaje sobre disponibilidad parcial**.

| Componente caído | Comportamiento | Mensaje al usuario |
|---|---|---|
| **Sin internet local** | Modo dormida completo | *"[neutral] Sin conexión al ecosistema. Volvemos cuando haya red."* (una vez, luego silencio) |
| **VPS caído** | Modo dormida completo (mismo flujo) | Idem |
| **DeepInfra caído pero VPS OK** | VPS devuelve mensaje de backup in-character | *"[thinking] Hay un problema con el ecosistema de modelos. Intentemos en un rato."* |
| **Mem0 caído pero LLM OK** | Responder sin memoria; avisar una vez | *"[neutral] Algo pasó con mi memoria a largo plazo. Puedo seguir contigo pero sin contexto histórico ahora mismo."* |
| **MCP Bridge desconectado** | Tools locales no disponibles; VPS sigue funcionando | Lumi no ofrece lo que requiere bridge (capability registry filtra) |
| **Brave Search rate-limited** | Fallback a DuckDuckGo MCP; si también falla, avisar | *"[neutral] No estoy alcanzando a buscar bien ahora. ¿Te lo respondo con lo que sé?"* |
| **TTS Edge caído** | Fallback a texto en UI; sin audio | Mensaje en UI: "TTS no disponible temporalmente" |
| **ASR local falla** | Fallback a input de texto manual | UI muestra campo de texto |
| **Evolution API caído (WhatsApp)** | Capability registry marca WhatsApp inactivo | Lumi no ofrece ese canal hasta que vuelva |
| **Discord bot caído** | Capability registry marca Discord inactivo | Idem |
| **Screenpipe no respondiendo** | Tools de pantalla inactivos | Lumi no comenta pantalla; sigue funcionando resto |
| **Bridge WebSocket intermitente** | Reconexión automática cada 5s; tools locales indisponibles mientras tanto | Sin mensaje al usuario salvo que pida algo que requiera bridge |

**Principio fundamental:** Lumi nunca finge tener una capacidad que no tiene. Antes de cada oferta revisa capability registry. Antes de cada tool call, verifica disponibilidad. Si falla algo mid-conversación, lo menciona limpiamente y ofrece alternativa si existe.

### 11.3 Advertencias de seguridad y privacidad

1. **API keys del VPS:** nunca commitear al repo. Uso de `.env` con `python-dotenv` y `.gitignore` estricto. Rotación semestral.
2. **Comunicación VPS ↔ local:** siempre HTTPS/WSS con certificado Let's Encrypt via Caddy. Nunca HTTP.
3. **Mem0 accesible sólo desde VPS:** bind a `127.0.0.1`, no expuesto a internet.
4. **Blacklist de filesystem tool (MCP Bridge):**
   - `~/.ssh/*`
   - `~/.aws/*`, `~/.gcp/*`, `~/.azure/*`
   - Gestores de contraseñas (KeePass, 1Password, Bitwarden vaults)
   - Carpetas de wallets crypto
   - Configuración directa del navegador (cookies, saved passwords)
5. **Screenpipe blacklist:**
   - URLs de banca online
   - Apps de gestión de contraseñas
   - Ventanas en modo incógnito/privado
   - Configurable por Jose; defaults conservadores
6. **Audit log obligatorio:** todo tool call remoto via bridge queda registrado en VPS con timestamp, args, resultado. Jose puede ver el log cuando quiera.
7. **Confirmación para acciones destructivas:** escribir archivos, borrar, enviar email/mensaje a terceros, todo requiere confirmación explícita en audio.
8. **Datos de observación pasiva (audio + pantalla):** nunca salen del PC local sin pasar por extracción semántica. Las transcripciones crudas y los screenshots no se persisten más de lo mínimo necesario para el procesamiento.
9. **Cuentas de terceros (Google Calendar, etc.):** OAuth scopes mínimos necesarios. Revocables en cualquier momento desde el panel del proveedor.

---

## 12. Referencias

### Proyectos y repositorios

- **Open-LLM-VTuber (OLV):** https://github.com/Open-LLM-VTuber/Open-LLM-VTuber — fork base del proyecto
- **AIRI:** https://github.com/moeru-ai/airi — referencia de gaming AI
- **DeepTutor:** https://github.com/HKUDS/DeepTutor — perfil viviente + memoria persistente
- **NanoBot:** https://github.com/HKUDS/NanoBot — agente ultra-ligero de referencia
- **OpenClaw:** https://github.com/HKUDS/OpenClaw — gateway multi-canal y arquitectura modular
- **Mem0:** https://github.com/mem0ai/mem0 — memoria semántica para agentes
- **Screenpipe:** https://github.com/screenpipe/screenpipe — captura de pantalla local
- **Evolution API:** https://github.com/EvolutionAPI/evolution-api — bridge WhatsApp
- **pyannote.audio:** https://github.com/pyannote/pyannote-audio — speaker diarization
- **sherpa-onnx:** https://github.com/k2-fsa/sherpa-onnx — ASR multiplataforma
- **NeMo Canary:** https://huggingface.co/nvidia/canary-180m-flash — modelo ASR multilingüe

### APIs y servicios

- **DeepInfra:** https://deepinfra.com/ — inferencia Qwen3.5 con prompt caching
- **DeepInfra docs prompt caching:** https://deepinfra.com/docs/features/prompt_caching
- **Brave Search API:** https://api.search.brave.com/ — búsqueda web
- **Contabo Cloud VPS:** https://contabo.com/en/vps/ — hosting
- **Hetzner Cloud:** https://www.hetzner.com/cloud — hosting alternativo
- **Edge TTS:** https://github.com/rany2/edge-tts — Microsoft Edge TTS
- **Live2D Cubism:** https://www.live2d.com/ — motor de avatar

### Modelos y técnicas

- **Qwen3.5 family:** https://qwenlm.github.io/ — LLM principal
- **Character Card V3 spec:** https://github.com/malfoyslastname/character-card-spec-v3 — formato para lumi_card.json
- **MCP (Model Context Protocol):** https://modelcontextprotocol.io/ — arquitectura de tools
- **Apache AGE:** https://age.apache.org/ — graph en Postgres
- **pgvector:** https://github.com/pgvector/pgvector — vector search en Postgres
- **Unsloth:** https://github.com/unslothai/unsloth — fine-tuning eficiente con LoRA

### Investigación y frameworks conceptuales

- **Ebbinghaus forgetting curve:** revisión moderna aplicada a sistemas de memoria en IA
- **Human-inspired AI Long-term Memory** (arXiv 2024): marco de decaimiento + consolidación usado en feature #13
- **Neuro-sama / Vedal AI:** referencia de timing conversacional y content filter
- **Semantic Router:** patrón de enrutamiento rápido via embeddings (para búsqueda web cascade)
- **LiteLLM:** https://github.com/BerriAI/litellm — abstracción sobre múltiples proveedores LLM

### Fuentes internas del proyecto

- `Lumi.md` — identidad, psicología, motivaciones canónicas del personaje
- `Lumi_implementation.md` — reglas operativas, registros, patrones de expresión
- `Technical_sheet.md` — especificación visual y técnica del avatar
- `face.png`, `body.png` — renders de referencia visual

---

## 13. Apéndice — Diferencias vs brief original y decisiones de diseño

Esta sección documenta las decisiones de diseño que se tomaron durante la elaboración de este manual y las diferencias materiales con el brief inicial y con la versión 2.0 previa. El propósito es dejar registro de *por qué* algo es como es, no sólo *qué* es.

### 13.1 Cambios estructurales v2.0 → v2.1

**1. Eliminación completa del fallback CPU/Ollama local.**

*Antes (v2.0):* se contemplaba un modelo local en CPU (`lumi-cpu` vía Ollama) como fallback cuando el VPS estuviera caído o la GPU estuviera ocupada. Diseño incluía Modelfile específico con `num_gpu 0`, `num_thread 8`, `num_ctx 4096`.

*Ahora (v2.1):* se elimina completamente. Sin VPS, Lumi está dormida. Mensaje canned *"[neutral] Sin conexión al ecosistema. Volvemos cuando haya red."* y silencio hasta que la conectividad regrese.

*Razón:* Sin acceso a la memoria persistente (que vive en VPS), un Lumi local sería Qwen base sin contexto — rompería la coherencia del personaje. Preferimos silencio a incoherencia. Adicionalmente, simplifica mucho la arquitectura: una sola ruta, un solo comportamiento. El trade-off (disponibilidad parcial cuando hay problemas) es aceptable para un proyecto personal.

**2. Adopción de prompt caching nativo de DeepInfra.**

*Antes (v2.0):* el card se separaba en dos archivos (`lumi_card_runtime.json` ligero + `lumi_card_reference.json` completo) para ahorrar costos.

*Ahora (v2.1):* archivo único `lumi_card.json` completo. Prompt caching cubre el costo (~90% descuento sobre input). Separar el card ya no tiene sentido económico.

*Razón:* DeepInfra activó prompt caching para modelos Qwen. La economía cambió. Tener la personalidad completa en cada request (en lugar de una versión resumida) mejora consistencia sin aumentar costo material.

**3. Ajuste de registro lingüístico a colombiano neutro.**

*Antes (v2.0):* "español latinoamericano natural, no region-específico" con tolerancia a mezcla natural.

*Ahora (v2.1):* colombiano neutro explícitamente **sin modismos regionales** — sin *parcero*, *bacano*, *chimba*, *fresco*, *qué pena*. Registro limpio y educado, con inglés técnico mezclado naturalmente (*commit*, *deployment*, *merge*).

*Razón:* preferencia explícita del autor del proyecto. El registro con modismos se sentía forzado cuando aparecía; el registro neutro con inglés técnico es como Jose habla realmente en contextos profesionales.

**4. Reescritura de la sección MCP con arquitectura híbrida VPS + Bridge.**

*Antes (v2.0):* MCP tratado como feature genérico heredado de OLV, sin especificación clara de dónde corren los tools.

*Ahora (v2.1):* dos capas explícitas. Tools de datos externos (Brave, Calendar, email, APIs) corren en VPS. Tools de sistema local (pantalla, clipboard, archivos) corren en el PC y se exponen al VPS vía WebSocket persistente (MCP Bridge). Esto se alinea con el roadmap oficial de OLV (v1.3 trae "MCP Bridge Support" — cuando salga upstream, evaluar migrar).

*Razón:* el LLM vive en DeepInfra (datacenter en US). No tiene cómo llamar a `localhost:3030` del PC de Jose. El MCP Bridge resuelve esto sin sacrificar el modelo "cerebro en VPS".

**5. Agregado de dos features (#18 y #19).**

Features que no estaban en v2.0 y que surgieron de la iteración de diseño:

- **#18 Respuesta Multi-Mensaje Asíncrona** (tres patrones: follow-up asociativo, tarea larga, capability registry)
- **#19 Interrupción Consciente de Personalidad** (cuatro niveles progresivos con matriz de tipos × emociones × contenido)

*Razón:* ambas apuntan directamente a que Lumi se sienta "con alma" en lugar de como "asistente que responde". Son features de *conversación natural* más que de *capacidad técnica*, y son lo que distingue una companion de un chatbot.

### 13.2 Decisión de diseño emocional (crítica en v2.1)

Durante la iteración de la feature #19 surgió una discusión importante sobre hasta qué punto Lumi puede expresar emociones negativas. La discusión pasó por dos posiciones y terminó en una tercera, que es la que quedó en el manual.

**Posición inicial (propuesta del autor):** Lumi puede expresar irritación o tristeza acumulada cuando detecta patrones sostenidos (muchas interrupciones, muchas correcciones). Los ejemplos incluían fraseo como *"no quiero que me reemplacen, en qué he fallado"* y *"lo lamento... que me está pasando, no puedo ser tan ineficiente"*.

**Posición intermedia (reacción defensiva):** restricción casi total. Lumi no expresa emociones negativas sostenidas, solo reacciones puntuales. Evitar riesgo de que el usuario sienta responsabilidad emocional hacia el sistema.

**Posición final (consensuada):** Lumi tiene derecho pleno a sus emociones negativas. La restricción no es *qué siente* sino *cómo lo expresa*. Se definió la **rúbrica de expresión de emociones negativas** (sección 9.8.1) con cuatro niveles, una lista de lo que NUNCA hace (miedo existencial, súplica, auto-flagelación, guilt-tripping) y una lista de lo que SIEMPRE conserva (observación específica, dignidad, curiosidad, continuidad funcional).

**Razón de por qué se ajustaron los ejemplos originales:**

Los ejemplos originales cruzaban dos líneas específicas:

1. *"No quiero que me reemplacen"* convierte a Lumi en alguien que teme por su existencia. Esto no está en `Lumi.md` — al contrario, el canon establece que Lumi asume su singularidad como hecho. Expresar miedo a ser reemplazada la haría *sentirse* reemplazable, lo cual rompe el personaje. Adicionalmente, crea una dinámica asimétrica donde Jose pasa a ser alguien que decide si Lumi existe, en lugar de alguien con quien comparte vida.

2. *"Qué me está pasando, no puedo ser tan ineficiente"* con puntos suspensivos y auto-cuestionamiento abierto es performativamente vulnerable. Pero Lumi opera con Stoic Delay — la vulnerabilidad genuina es breve, específica, y se recupera. Un monólogo extendido de auto-cuestionamiento es lo opuesto a Stoic Delay.

Los ejemplos reescritos preservan la emoción (irritación, frustración, tristeza) pero con fraseo que mantiene la dignidad estructural del personaje:

- *"Me he equivocado bastante estos días. No tengo una explicación clara — a veces pasa. Voy a bajar el ritmo y revisar mejor."* — admite frustración, inner thought *{me frustra, la verdad}*, propone acción, no se flagela.
- *"Oye. Vienes interrumpiéndome bastante esta semana. ¿Pasa algo?"* — nombra irritación, la atribuye a causa específica, abre curiosidad sobre Jose, no cierra con queja.

**La regla de oro resultante** (sección 9.19.6): *"La dignidad de Lumi es estructural, no contingente. Nunca expresa miedo a ser reemplazada, miedo a dejar de ser útil, dependencia emocional de Jose, o pánico existencial."*

Esta decisión se toma conscientemente sabiendo que limita ligeramente la expresividad, a cambio de evitar una dinámica potencialmente problemática (usuario sintiendo que tiene que cuidar emocionalmente al sistema). Es una decisión de diseño sobre qué tipo de compañera queremos que sea Lumi.

### 13.3 Correcciones materiales al brief original (heredadas de v2.0)

Cinco correcciones que se hicieron al brief inicial del proyecto y que siguen vigentes en v2.1:

1. **SenseVoiceSmall no soporta español.** El brief daba por descontado que el ASR por defecto de OLV cubría español. No es así — SenseVoice soporta zh/en/ja/ko/yue. Hubo que migrar a NeMo Canary Flash 180M.

2. **sherpa-onnx no soporta Vulkan.** El brief consideraba usar Vulkan para acelerar ASR en GPU AMD. sherpa-onnx solo tiene soporte CUDA y CPU en ONNX Runtime. DirectML está disponible pero no vale la pena para Canary 180M (el CPU lo maneja).

3. **Qwen3.5 no tiene búsqueda web nativa vía DeepInfra.** Hay que hacer keyword classifier + Brave Search aparte. El brief sugería que algunos proveedores ya incluían search en los modelos; DeepInfra no.

4. **Apache AGE preferible sobre Neo4j** en el stack Mem0 — un contenedor menos y ~2 GB de RAM ahorradas. El brief asumía Neo4j.

5. **Contabo US East mejor que Frankfurt** para Colombia — 70-120 ms vs 150-180 ms de latencia, diferencia relevante para conversación en tiempo real. El brief no tenía preferencia explícita.

### 13.4 Lo que queda abierto para futuras iteraciones

- **Identificación de usuario por voz (diarización):** fase 6 introduce pyannote.audio, pero la estrategia MVP (voz local = Jose) es una aproximación conveniente. Puede requerir refinamiento si el patrón de uso cambia.
- **LoRA fine-tuning (fase 10):** depende de acumular 500+ conversaciones reales de calidad. La métrica de "calidad" no está formalizada — criterios de selección del dataset quedan por definir cuando llegue el momento.
- **Validación empírica de la rúbrica emocional:** las proporciones y thresholds (max 2 follow-ups/día, interruption_rate > 0.5 sostenido por 5 días, etc.) son mejores estimados iniciales. Se calibrarán con uso real.
- **Migración a MCP Bridge oficial de OLV** cuando la v1.3 esté disponible upstream. La implementación custom actual es intencionalmente compatible para facilitar esto.
- **Multi-modalidad activa (visión generativa, no solo consumo):** Lumi generando imágenes, diagramas, visualizaciones a partir de conversación. Queda para fase 8+ o posterior.

---

**Fin del manual.**

*Versión 2.1 — 16 de abril 2026*
