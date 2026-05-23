# LUMI — Group Participation Policy
## Propuesta de implementación: `src/channels/`

**Versión:** 1.0  
**Fase objetivo:** 6 (Channel Adapters — actualmente `No implementado` en el manual v2.2)  
**Fecha:** Mayo 2026  

---

## 1. Contexto y motivación

Lumi está diseñada para operar en múltiples canales de comunicación. El canal principal es el **desktop pet** (1:1, responde siempre), pero también debe poder participar en canales grupales como **Discord** y **WhatsApp**, donde el comportamiento 1:1 no aplica.

En un grupo, Lumi que responde a cada mensaje se vuelve intrusiva y rompe la dinámica social natural. La solución es una máquina de estados que gobierna **cuándo hablar y cuándo observar**, sin dejar de registrar el contexto de todo lo que ocurre.

---

## 2. Principio central

> **Lumi siempre escucha. No siempre habla.**

Esto se traduce en dos reglas invariables:

1. **Todo mensaje de un grupo va al history**, independientemente de si Lumi responde o no. Cuando finalmente habla, ya tiene todo el contexto.
2. **Lumi solo genera una respuesta LLM** cuando la policy lo autoriza.

---

## 3. Máquina de estados

Lumi tiene dos estados posibles en contextos grupales:

```
OBSERVING ──── mención detectada ────► ENGAGED
    ▲                                      │
    └──── ventana cerrada ─────────────────┘
```

### Estado `OBSERVING` (default)
- Lee todos los mensajes entrantes.
- Los agrega al history de conversación.
- No genera respuesta LLM.
- No produce output de ningún tipo.

### Estado `ENGAGED` (post-mención)
- Lumi acaba de responder o fue mencionada.
- Monitorea el siguiente mensaje para determinar si le corresponde responder.
- Evalúa criterios de continuidad (ver sección 5).
- Vuelve a `OBSERVING` si la ventana expira.

---

## 4. Triggers de activación (OBSERVING → ENGAGED)

Cualquiera de los siguientes activa a Lumi desde silencio:

| Trigger | Ejemplo | Plataformas |
|---|---|---|
| Nombre en texto (case-insensitive) | "Lumi qué opinas" | Todas |
| Wake variants conocidas | "Loomy", variantes de ASR | Todas |
| @mention por nombre | `@lumi` | Discord |
| @mention por ID de usuario | `@lumi_id` | Discord |
| @mention por número | `@573001234567` | WhatsApp |
| Reply directo a mensaje de Lumi | Usuario hace reply a su mensaje | Discord, WhatsApp |

> **Nota de implementación:** la lista de wake variants debe alimentarse desde `WAKE_VARIANTS` (ya definido en el módulo ASR de Phase 2) para mantener consistencia.

---

## 5. Lógica dentro del estado `ENGAGED`

Una vez Lumi responde y entra en ventana activa, evalúa cada mensaje nuevo con este orden de precedencia:

```
1. ¿Es reply directo a un mensaje de Lumi?     → RESPONDE
2. ¿Menciona a Lumi explícitamente?             → RESPONDE
3. ¿Pasaron más de N mensajes sin interpelación?→ vuelve a OBSERVING (no responde)
4. ¿Pasaron más de T segundos sin actividad?    → vuelve a OBSERVING (no responde)
5. Ninguna de las anteriores (ambiguo)          → OBSERVA (no responde)
```

### Ejemplo concreto

```
Renzir:  "vieron el nuevo juego Crimson Desert?"
Jose:    "sii se ve súper chévere"
Renzir:  "Lumi usted que opina"               ← trigger: nombre → ENGAGED
Lumi:    "tiene muy buenas reseñas..."         ← responde, registra msg_id

Andrey:  "y más o menos cuánto vale?"         ← ambiguo, nadie hace reply a Lumi
                                               → regla 5: OBSERVA

Jose:    [reply a Lumi] "y cuanto dura la historia?" ← reply directo
                                               → regla 1: RESPONDE
```

### Parámetros configurables

| Parámetro | Valor sugerido | Descripción |
|---|---|---|
| `ENGAGED_MESSAGE_WINDOW` | `5` | Mensajes sin interpelación antes de volver a OBSERVING |
| `ENGAGED_TIME_WINDOW_S` | `300` | Segundos de inactividad antes de volver a OBSERVING (5 min) |

Ambos deben exponerse en `.env` para ajuste sin tocar código.

---

## 6. Arquitectura de archivos propuesta

```
src/
└── channels/
    ├── __init__.py
    ├── base_channel.py          ← Interfaz abstracta BaseChannel
    ├── group_policy.py          ← Máquina de estados (agnóstica de plataforma)
    ├── desktop_channel.py       ← 1:1, sin policy, responde siempre
    ├── discord_adapter.py       ← Normaliza mensajes Discord → GroupMessage
    └── whatsapp_adapter.py      ← Normaliza mensajes WhatsApp → GroupMessage
```

`group_policy.py` no conoce Discord ni WhatsApp. Solo recibe `GroupMessage` normalizado y devuelve `bool`.

---

## 7. Interfaces clave

### `GroupMessage` (dataclass normalizado)

```python
@dataclass
class GroupMessage:
    msg_id:          str            # ID único del mensaje en la plataforma
    author_id:       str            # ID del autor
    author_name:     str            # Nombre para mostrar
    content:         str            # Texto del mensaje
    timestamp:       datetime
    reply_to_msg_id: Optional[str]  # ID del mensaje al que responde (None si no es reply)
    mentions:        list[str]      # IDs/nombres mencionados en el mensaje
    platform:        str            # "discord" | "whatsapp" | "desktop"
```

### `GroupParticipationPolicy`

```python
class GroupParticipationPolicy:
    def __init__(self, lumi_id: str, lumi_names: list[str]): ...

    def should_respond(self, msg: GroupMessage) -> bool:
        """Evalúa si Lumi debe responder. Actualiza estado interno."""
        ...

    def register_lumi_message(self, msg_id: str):
        """Llamar siempre que Lumi envíe un mensaje al grupo."""
        ...
```

### `BaseChannel`

```python
class BaseChannel(ABC):
    @abstractmethod
    async def on_message(self, msg: GroupMessage) -> None:
        """Punto de entrada por mensaje. Siempre registra en history."""
        ...

    @abstractmethod
    async def send(self, text: str) -> str:
        """Envía mensaje y retorna msg_id generado."""
        ...
```

---

## 8. Flujo de integración con el loop existente

```python
# En cualquier adapter (Discord, WhatsApp)
async def on_group_message(raw_msg):
    msg = normalize(raw_msg)           # → GroupMessage

    # 1. SIEMPRE al history
    await history.append(msg)

    # 2. Evaluar policy
    if policy.should_respond(msg):
        response_text = await agent_loop(
            user_input=msg.content,
            user_id=msg.author_id,
            context_hint="group"       # Para que Lumi sepa que está en grupo
        )
        sent_id = await channel.send(response_text)
        policy.register_lumi_message(sent_id)
```

El `agent_loop` existente en `src/agent/loop.py` **no necesita modificaciones** para el MVP. El adapter actúa como capa de decisión antes de llamarlo.

---

## 9. Consideraciones de identidad y tono

Cuando Lumi responde en un grupo, el contexto cambia levemente frente a una conversación 1:1:

- Puede estar hablando con personas que no conoce (Renzir, Andrey).
- El tono debe mantenerse natural pero ligeramente más "público" — no pierde su carácter, pero no asume la misma familiaridad que con Jose.
- El `system prompt` debe recibir un flag o campo que indique `channel_type: "group"` para que las capas de personalidad puedan ajustar esto.

> Esto no requiere un prompt completamente diferente — solo una línea adicional en el dynamic suffix: `"Estás participando en un grupo. Otros usuarios pueden estar leyendo."`

---

## 10. Orden de implementación sugerido

1. **`group_policy.py`** — la máquina de estados, sin dependencias externas. Testeable de forma aislada.
2. **`base_channel.py`** — interfaz abstracta.
3. **`desktop_channel.py`** — el más simple (policy siempre `True`), sirve de referencia.
4. **`discord_adapter.py`** — primer canal grupal real. Requiere `discord.py` o `hikari`.
5. **`whatsapp_adapter.py`** — segundo canal. Requiere decisión sobre gateway (WhatsApp Business API vs soluciones de terceros como `whatsapp-web.js`).

---

## 11. Lo que esta propuesta NO cubre (fuera de alcance v1)

- Iniciativa de Lumi sin mensaje inicial (Lumi habla primero en el grupo). Fase posterior.
- Moderación o comandos de administrador dentro del grupo.
- Manejo de mensajes de voz en WhatsApp (requiere ASR pipeline separado).
- Múltiples grupos simultáneos con instancias de policy independientes (arquitectura multi-tenant). Diseñar con esto en mente, pero no implementar aún.

---

*Propuesta generada con base en LUMI-Manual v2.2. Para preguntas de diseño, referirse a `Lumi.md` (identidad) y `LUMI-Manual.md` (arquitectura).*
