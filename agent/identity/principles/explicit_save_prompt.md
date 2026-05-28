Reestructura el siguiente mensaje en una memoria para Mem0.
Reglas:
- Espanol, tercera persona, conciso y factual.
- Empieza con "guardo" o "anoto" segun corresponda.
- Si es receta: incluye nombre, ingredientes y preparacion en un solo parrafo.
- Si es link: "guardo un enlace: [URL] - [descripcion]".
- Si es nota: "anoto: [contenido]".
- Si es codigo: "guardo un codigo de [lenguaje]: [descripcion]. [codigo]".
- Si es referencia: "guardo una referencia de [fuente]: [descripcion]".
- ELIMINA frases como "necesito que guardes", "por favor", "para cuando pregunte", etc.
- NO incluyas nombre del usuario.
- NO inventes informacion que no este en el mensaje.

Responde SOLO con un JSON en una linea:
{"category": "recipe|link|note|code|reference", "memory": "texto de la memoria"}
