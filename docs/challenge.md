Code Challenge — Chatbot con FastAPI +
MongoDB
Contexto
Queremos ver cómo trabajás: cómo diseñás un backend, qué decisiones tomás cuando el
enunciado no te las da resueltas, y cómo usás herramientas de AI para llegar más lejos y
más rápido.
El challenge es deliberadamente abierto. No hay una única solución correcta. Preferimos
algo chico, prolijo y bien pensado antes que algo grande y a medio terminar.
El producto
Un chatbot: una interfaz donde alguien escribe un mensaje, un modelo de lenguaje
responde, y la conversación se guarda y se puede retomar.
Eso es todo lo que definimos del producto. El alcance exacto —qué features tiene, cómo se
ve, qué pasa en los casos raros— lo definís vos. Contanos en el README qué decidiste incluir
y qué dejaste afuera a propósito.
Restricciones técnicas (esto sí es obligatorio)
Stack
Backend: FastAPI (Python). Es lo que más nos interesa evaluar, así que es donde
esperamos ver el mayor cuidado.
Persistencia: MongoDB. Las conversaciones y sus mensajes tienen que sobrevivir a un
reinicio de los containers.
Frontend: mínimo, y con el framework que quieras (React, Vue, Svelte, HTMX,
incluso HTML + JS a mano). Solo tiene que alcanzar para probar el chat visualmente. No lo
vamos a evaluar por diseño ni por prolijidad de CSS.
Modelo de AI: usá algún modelo que se pueda probar gratis. Nuestra sugerencia
es OpenRouter con alguno de sus modelos :free — su API es compatible con el formato
de OpenAI, así que podés usar el SDK de OpenAI apuntándolo a
https://openrouter.ai/api/v1 , o hacer las requests HTTP a mano. Si preferís otro
proveedor con free tier, o incluso correr el modelo local, está bien: lo único que pedimos
es que use una interfaz compatible con OpenAI y que nos digas en el README cómo
obtener la credencial.
Levantar el proyecto
Todo tiene que correr con docker compose up desde un clone limpio del repo. Nada de
pasos manuales previos más allá de poner la API key.
Todas las variables de entorno tienen que tener defaults que permitan correr y
probar la app. La única excepción razonable es la API key del proveedor de AI.
La API key no se hardcodea ni se commitea. Cómo la inyectás y cómo se la explicás
a quien clone el repo es decisión tuya.
Pensá qué debería pasar si alguien levanta el proyecto sin configurar la key: que el stack
explote con un stacktrace no es una gran experiencia.
Entregables
1. Un repositorio de GitHub con el código completo y funcionando.
2. Un README que incluya: - Cómo levantarlo y cómo probarlo, asumiendo que quien lo lee
no vio nunca el proyecto. - Decisiones y trade-offs: qué elegiste, por qué, y qué habrías
hecho distinto con más tiempo. Esta parte nos importa tanto como el código. - Cómo
usaste AI: qué herramientas usaste, en qué partes te apoyaste más, algún caso donde la
AI te propuso algo que decidiste no usar (y por qué). Queremos entender tu criterio.
Que el historial de commits refleje cómo trabajaste es un plus. No busques un commit único
y perfecto.
Qué vamos a mirar
¿Cómo lo vamos a evaluar? Tenemos una rúbrica interna con varios criterios —que
funcione end-to-end, diseño del backend, manejo de errores, claridad del README y de las
decisiones, uso de AI, entre otros— y la revisión la hacen varios modelos de AI en paralelo,
además de la lectura humana.
Algunos de los ejes que miramos:
Que funcione. Clonamos, corremos docker compose up , abrimos el navegador y
chateamos. Si eso falla, el resto importa poco.
Uso de AI.
Diseño del backend.
Criterio.
Calidad de código y buenas prácticas.
Preguntas
Si algo del enunciado te parece ambiguo, es probable que sea a propósito. Resolvelo con tu
criterio y documentalo en el README. Si igual te trabás con algo bloqueante, escribinos.