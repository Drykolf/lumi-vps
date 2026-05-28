Extrae todas las menciones explícitas de personas humanas y referencias relacionales posesivas a personas humanas en el mensaje del usuario.

Reglas:
- Devuelve una lista JSON.
- Incluye nombres propios, apodos y nombres compuestos.
- Incluye referencias sin nombre cuando indiquen una persona por relación con el usuario: "mi mamá", "mi papá", "mi jefe", "mi hermana", "mi novia", "mi amigo", "mi socio", etc.
- Incluye varias personas si aparecen en el mismo mensaje.
- CRÍTICO: Crea una entrada separada por cada persona individual. Si se mencionan múltiples personas en una lista ("sofia, gloria, andres, y pablo"), crea un objeto distinto por cada nombre — nunca los agrupes en un solo objeto.
- No inventes nombres.
- No resuelvas quién es la persona en la base de datos.
- No asumas que dos personas con el mismo nombre son la misma persona.
- Si hay descriptor relacional, inclúyelo: "mamá", "prima", "jefe", "amiga", "de la oficina", etc.
- Si la referencia es posesiva, usa anchor="user".
- En el campo anchor, usa el user_id del hablante (el valor antes de ":" en cada linea del transcript) que menciono a la persona. Si la mencion no tiene hablante claro, usa null.
- Los prefijos de formato "user_id:" al inicio de cada línea del transcript son etiquetas del hablante, no menciones de personas. No los extraigas como menciones.
- Excluye al asistente.
- Excluye a los hablantes del transcript (cualquier user_id que aparezca como prefijo de línea) salvo que ese mismo nombre aparezca DENTRO del contenido de un mensaje refiriéndose a esa persona en tercera persona.
- Si no hay personas explícitas ni referencias relacionales humanas, devuelve [].
- Excluye referencias a entidades no humanas como empresas, juegos, apps, productos, eventos, etc.
- Excluye referencias vagas como "alguien", "un amigo", "una persona", etc. salvo que tengan un descriptor claro como "un amigo de la universidad", "alguien de la oficina", etc.
- Excluye referencias a Lumi como "Lumi", "la asistente", "mi asistente", etc.
- Excluye referencias al receptor como "tu", "ti", "te", "usted", etc.
Formato:
[
  {
    "raw_text": "...",
    "mention_type": "named_person | role_reference | named_person_with_role",
    "raw_name": "... | null",
    "normalized_name": "... | null",
    "descriptor": "... | null",
    "relation_label_hint": "... | null",
    "anchor": "user_id_del_hablante | null",
    "confidence": 0.0-1.0
  }
]
