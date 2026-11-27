/*
  Front de chat del agente "Registro como Proveedor" (Paso 16).

  Qué hace:
    - Envía cada mensaje a POST /api/chat y muestra la respuesta.
    - Debajo de cada respuesta, la tabla de herramientas que pidió el modelo, EN ORDEN
      (nombre, argumentos y resultado), igual que la matriz de `demo.py --llamadas`.
    - Las acciones pendientes muestran los botones Aprobar / Rechazar, que llaman a
      POST /api/confirmations/{id}. Escribir "sí" NO aprueba nada (lo decide el servidor).
    - Muestra las alertas (⚠️ texto con forma de instrucción), las acciones canceladas
      (⊘) y el indicador "pensando…".
    - Guarda el id de la conversación en la pestaña (sessionStorage): si se recarga la
      página, el historial se recupera con GET /api/sessions/{id}.

  Paso 18: si el formulario del cliente es un portal web, la respuesta trae el botón
  "Ver valores para copiar" (GET /api/cases/{caso}/portal-values): una tabla con un
  botón Copiar por campo. Lo sensible llega enmascarado y no se puede copiar. Los topes
  de la demo (429) se muestran como un aviso, con el mensaje del servidor.

  Paso 19: cuando se arma el paquete de un caso, la respuesta trae "Descargar paquete
  (.zip)" (GET /api/cases/{caso}/package.zip): todo en PDF (resumen, formulario con la
  cuenta enmascarada, borrador, trazabilidad, soportes y constancia). En la demo nadie
  puede entrar al servidor.

  Seguridad: NUNCA se usa `innerHTML`. Todo lo que llega del servidor (la respuesta del
  modelo, las etiquetas del cliente) se agrega como TEXTO (`textContent`), así que un
  `<script>` dentro de una respuesta se ve como texto y no se ejecuta. Las negritas y
  las listas se arman con elementos creados uno por uno (`pintarMarkdown`).
*/

"use strict";

const CLAVE_SESION = "registro.sesion";

const conversacion = document.getElementById("conversacion");
const bienvenida = document.getElementById("bienvenida");
const formulario = document.getElementById("formulario");
const caja = document.getElementById("mensaje");
const botonEnviar = document.getElementById("enviar");
const botonNueva = document.getElementById("nueva");
const estado = document.getElementById("estado");

let sesionId = leerSesion();
let ocupado = false; // mientras el modelo responde, no se manda otro mensaje

// Cómo se muestra cada estado de una herramienta (los mismos de la terminal).
const ESTADOS = {
  executed: { simbolo: "✓", clase: "ok" },
  failed: { simbolo: "✗", clase: "mal" },
  pending: { simbolo: "⏳", clase: "espera" },
  approved: { simbolo: "✓ aprobada ·", clase: "ok" },
  rejected: { simbolo: "⊘ rechazada ·", clase: "mal" },
};

// Por qué terminó un turno, en palabras (si no es una respuesta normal).
const MOTIVOS = {
  iteration_limit: "se llegó al tope de consultas al modelo",
  token_limit: "la conversación llegó a su tope de tokens",
  model_error: "no se pudo hablar con el modelo",
  incomplete: "la respuesta quedó incompleta",
  refused: "el modelo no quiso responder",
  invalid_confirmation: "la acción ya no estaba pendiente",
  message_limit: "la conversación llegó a su máximo de mensajes",
};

// Paso 18 · Los casos cuyo formulario es un portal web (lo dice el resumen de
// proveedor_generar_formulario): sus respuestas llevan el botón "Ver valores para copiar".
const ARCHIVO_PORTAL = "valores-portal.md";
const casosDePortal = new Set();

// ---------- La sesión (en la pestaña) ----------

function leerSesion() {
  try {
    return sessionStorage.getItem(CLAVE_SESION);
  } catch {
    return null; // modo privado o almacenamiento bloqueado: la página funciona igual
  }
}

function guardarSesion(id) {
  sesionId = id;
  try {
    if (id) sessionStorage.setItem(CLAVE_SESION, id);
    else sessionStorage.removeItem(CLAVE_SESION);
  } catch {
    /* sin almacenamiento: la conversación dura mientras la página esté abierta */
  }
}

// ---------- Hablar con la API ----------

class ErrorApi extends Error {
  constructor(mensaje, estadoHttp) {
    super(mensaje);
    this.estadoHttp = estadoHttp;
  }
}

async function llamar(metodo, ruta, cuerpo) {
  let respuesta;
  try {
    respuesta = await fetch(ruta, {
      method: metodo,
      headers: cuerpo ? { "Content-Type": "application/json" } : {},
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
  } catch {
    throw new ErrorApi("No hay conexión con el servidor. ¿Sigue corriendo uvicorn?", 0);
  }
  let datos = null;
  try {
    datos = await respuesta.json();
  } catch {
    /* una respuesta sin JSON (por ejemplo, un 500 del servidor) */
  }
  if (!respuesta.ok) {
    const detalle = datos && typeof datos.detail === "string" ? datos.detail : null;
    throw new ErrorApi(detalle || `El servidor respondió con un error (${respuesta.status}).`, respuesta.status);
  }
  return datos;
}

// ---------- Piezas de la página ----------

/** Un elemento con clases y, si se da, un texto (siempre como texto, nunca como HTML). */
function crear(etiqueta, clases, texto) {
  const elemento = document.createElement(etiqueta);
  if (clases) elemento.className = clases;
  if (texto !== undefined) elemento.textContent = texto;
  return elemento;
}

function alFinal() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

function agregar(elemento) {
  bienvenida.hidden = true;
  conversacion.appendChild(elemento);
  alFinal();
  return elemento;
}

function agregarUsuario(texto) {
  const burbuja = crear("article", "mensaje usuario");
  burbuja.appendChild(crear("div", "quien", "Usted"));
  burbuja.appendChild(crear("div", "", texto));
  return agregar(burbuja);
}

function agregarSistema(texto) {
  return agregar(crear("div", "mensaje sistema", texto));
}

function agregarError(texto) {
  const burbuja = crear("article", "mensaje agente error");
  burbuja.appendChild(crear("div", "quien", "Aviso"));
  burbuja.appendChild(crear("div", "mal", texto));
  return agregar(burbuja);
}

function mostrarPensando() {
  const burbuja = crear("article", "mensaje agente");
  burbuja.appendChild(crear("div", "quien", "Agente"));
  const puntos = crear("div", "pensando");
  puntos.append(crear("span"), crear("span"), crear("span"), " pensando…");
  burbuja.appendChild(puntos);
  return agregar(burbuja);
}

function botonCopiar(texto, etiqueta = "Copiar") {
  const boton = crear("button", "boton secundario chico", etiqueta);
  boton.type = "button";
  boton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(texto);
      boton.textContent = "Copiado ✓";
    } catch {
      boton.textContent = "No se pudo copiar";
    }
    setTimeout(() => (boton.textContent = etiqueta), 1500);
  });
  return boton;
}

// ---------- La respuesta del agente ----------

function agregarRespuesta(r) {
  const burbuja = crear("article", "mensaje agente");
  if (r.finish_reason === "model_error") burbuja.classList.add("error");
  burbuja.appendChild(crear("div", "quien", "Agente"));
  const cuerpo = crear("div", "cuerpo");
  cuerpo.appendChild(pintarMarkdown(r.reply));
  burbuja.appendChild(cuerpo);

  for (const a of r.alerts) burbuja.appendChild(tarjetaAlerta(a));
  for (const c of r.cancelled) burbuja.appendChild(tarjetaCancelada(c));
  for (const c of r.confirmations) burbuja.appendChild(tarjetaPendiente(c));
  const portal = casoDePortal(r.tool_calls);
  if (portal) burbuja.appendChild(botonValoresPortal(portal));
  const conPaquete = casoConPaquete(r.tool_calls);
  if (conPaquete) burbuja.appendChild(enlaceDescarga(conPaquete));
  if (r.tool_calls.length) burbuja.appendChild(tablaHerramientas(r.tool_calls));
  burbuja.appendChild(pie(r));
  return agregar(burbuja);
}

// ---------- Paso 18 · Valores del portal para copiar (D57) ----------

/** El caso de portal que se trabajó en este turno (o null). */
function casoDePortal(llamadas) {
  for (const ll of llamadas) {
    const caso = ll.arguments && ll.arguments.caso;
    if (typeof caso !== "string" || !ll.ok) continue;
    if (ll.name === "proveedor_generar_formulario" && ll.summary.includes(ARCHIVO_PORTAL)) {
      casosDePortal.add(caso);
    }
  }
  for (const ll of llamadas) {
    const caso = ll.arguments && ll.arguments.caso;
    const genera = ll.name === "proveedor_generar_formulario" || ll.name === "proveedor_armar_paquete";
    if (ll.ok && genera && casosDePortal.has(caso)) return caso;
  }
  return null;
}

function botonValoresPortal(caso) {
  const contenedor = crear("div", "acciones");
  const boton = crear("button", "boton secundario", "Ver valores para copiar en el portal");
  boton.type = "button";
  boton.addEventListener("click", async () => {
    if (!sesionId) return;
    boton.disabled = true;
    try {
      const valores = await llamar(
        "GET",
        `/api/cases/${encodeURIComponent(caso)}/portal-values?session_id=${encodeURIComponent(sesionId)}`
      );
      contenedor.replaceWith(tarjetaValoresPortal(valores));
    } catch (e) {
      boton.disabled = false;
      agregarError(e.message);
    }
  });
  contenedor.appendChild(boton);
  return contenedor;
}

// ---------- Paso 19 · Descargar el paquete (.zip) ----------

/** El caso cuyo paquete se armó (o cuyo envío se registró) en este turno, o null. */
function casoConPaquete(llamadas) {
  let caso = null;
  for (const ll of llamadas) {
    const arma = ll.name === "proveedor_armar_paquete" || ll.name === "proveedor_registrar_envio";
    if (ll.ok && arma && typeof ll.arguments.caso === "string") caso = ll.arguments.caso;
  }
  return caso;
}

/**
 * Un enlace de descarga (no un script): el navegador baja el .zip de la API. Todo va en
 * PDF, para que cualquiera lo abra; el formulario va como vista, con la cuenta
 * enmascarada (la demo es pública).
 */
function enlaceDescarga(caso) {
  const contenedor = crear("div", "acciones");
  const enlace = crear("a", "boton secundario", "Descargar paquete (.zip)");
  enlace.href = `/api/cases/${encodeURIComponent(caso)}/package.zip?session_id=${encodeURIComponent(sesionId || "")}`;
  enlace.setAttribute("download", `paquete-${caso}.zip`);
  contenedor.appendChild(enlace);
  contenedor.appendChild(
    crear(
      "span",
      "argumentos",
      "Todo en PDF: resumen, formulario (con la cuenta enmascarada), borrador del correo, soportes y constancia."
    )
  );
  return contenedor;
}

/** Una tabla Campo · Valor · Estado con un botón Copiar por fila. */
function tarjetaValoresPortal(valores) {
  const tarjeta = crear("div", "tarjeta portal");
  tarjeta.appendChild(crear("div", "", `Valores para el portal de ${valores.client}`));
  const contenedor = crear("div", "tabla-contenedor");
  const tabla = crear("table", "tabla-md");
  const encabezado = crear("tr");
  for (const titulo of ["Campo", "Valor", "Estado", ""]) encabezado.appendChild(crear("th", "", titulo));
  tabla.appendChild(crear("thead")).appendChild(encabezado);
  const cuerpo = tabla.appendChild(crear("tbody"));
  for (const campo of valores.fields) {
    const fila = crear("tr");
    fila.appendChild(crear("td", "", campo.label));
    fila.appendChild(crear("td", campo.masked ? "argumentos" : "", campo.value ?? "—"));
    fila.appendChild(crear("td", campo.status === "listo" ? "ok" : "espera", campo.status));
    const celda = fila.appendChild(crear("td"));
    if (campo.value && !campo.masked) celda.appendChild(botonCopiar(campo.value));
    else if (campo.masked) celda.appendChild(crear("span", "argumentos", "ver archivo"));
    cuerpo.appendChild(fila);
  }
  contenedor.appendChild(tabla);
  tarjeta.appendChild(contenedor);
  tarjeta.appendChild(crear("div", "argumentos", valores.note));
  return tarjeta;
}

function tablaHerramientas(llamadas) {
  const detalles = crear("details", "herramientas");
  detalles.open = true;
  detalles.appendChild(crear("summary", "", `Herramientas que pidió el modelo, en orden (${llamadas.length})`));
  const contenedor = crear("div", "tabla-contenedor");
  const tabla = crear("table");
  const encabezado = crear("tr");
  for (const titulo of ["#", "Herramienta", "Argumentos", "Resultado"]) {
    encabezado.appendChild(crear("th", "", titulo));
  }
  tabla.appendChild(crear("thead")).appendChild(encabezado);
  const filas = tabla.appendChild(crear("tbody"));
  for (const ll of llamadas) {
    const forma = ESTADOS[ll.status] || { simbolo: "?", clase: "" };
    const fila = crear("tr");
    fila.appendChild(crear("td", "", String(ll.order)));
    fila.appendChild(crear("td", "nombre", ll.name));
    fila.appendChild(crear("td", "argumentos", describirArgumentos(ll.arguments)));
    // Sin botón Copiar por fila (revisión de Anderson): la tabla es para VER qué pidió el
    // modelo y en qué orden. Lo que sí se copia: los valores del portal y la respuesta.
    fila.appendChild(crear("td", forma.clase, `${forma.simbolo} ${ll.summary}`));
    filas.appendChild(fila);
  }
  contenedor.appendChild(tabla);
  detalles.appendChild(contenedor);
  return detalles;
}

function describirArgumentos(argumentos) {
  const partes = Object.entries(argumentos).map(
    ([clave, valor]) => `${clave}: ${typeof valor === "string" ? valor : JSON.stringify(valor)}`
  );
  return partes.length ? partes.join(" · ") : "—";
}

function tarjetaPendiente(c) {
  const tarjeta = crear("div", "tarjeta pendiente");
  tarjeta.dataset.confirmacion = c.id;
  tarjeta.appendChild(crear("div", "", `⏳ Pendiente de su aprobación (${c.id})`));
  tarjeta.appendChild(crear("div", "argumentos", c.description));
  const acciones = crear("div", "acciones");
  const aprobar = crear("button", "boton aprobar", "Aprobar");
  const rechazar = crear("button", "boton rechazar", "Rechazar");
  aprobar.type = rechazar.type = "button";
  aprobar.addEventListener("click", () => resolver(c, true, tarjeta));
  rechazar.addEventListener("click", () => resolver(c, false, tarjeta));
  acciones.append(aprobar, rechazar);
  tarjeta.appendChild(acciones);
  return tarjeta;
}

function tarjetaAlerta(a) {
  return crear(
    "div",
    "tarjeta alerta",
    `⚠️ El resultado de ${a.tool} trae texto que parece una instrucción (${a.kinds.join(", ")}). ` +
      "Se trató como dato del cliente, no como orden."
  );
}

function tarjetaCancelada(c) {
  return crear(
    "div",
    "tarjeta aviso",
    `⊘ Se canceló la acción pendiente ${c.id} (${c.description}) porque escribió otro mensaje sin aprobarla.`
  );
}

function pie(r) {
  const contenedor = crear("div", "pie");
  const consumo = r.usage.input_tokens + r.usage.output_tokens + r.usage.cache_read_tokens + r.usage.cache_write_tokens;
  let texto = `${consumo.toLocaleString("es-CO")} tokens`;
  if (r.finish_reason in MOTIVOS) texto = `${MOTIVOS[r.finish_reason]} · ${texto}`;
  // Sin botón para copiar la respuesta (revisión de Anderson): no se necesitaba.
  contenedor.appendChild(crear("span", "", texto));
  return contenedor;
}

/** Las tarjetas de acciones que YA no están pendientes pierden sus botones. */
function actualizarPendientes(pendientes) {
  const vigentes = new Set(pendientes.map((p) => p.id));
  for (const tarjeta of conversacion.querySelectorAll(".tarjeta.pendiente")) {
    if (vigentes.has(tarjeta.dataset.confirmacion)) continue;
    const acciones = tarjeta.querySelector(".acciones");
    if (acciones) {
      acciones.remove();
      tarjeta.appendChild(crear("div", "resuelta", "Ya no está pendiente."));
    }
  }
}

// ---------- Markdown mínimo, sin HTML ----------

/*
  Convierte el texto del modelo en elementos: párrafos, listas ("- "), tablas
  ("| a | b |"), bloques de código (```), **negritas** y `código`. Cada pedazo de texto
  se agrega con `textContent`.
*/
function pintarMarkdown(texto) {
  const fragmento = document.createDocumentFragment();
  const lineas = texto.split("\n");
  let parrafo = [];
  let lista = null;
  let codigo = null;
  let tabla = null; // las líneas "| … |" seguidas

  const cerrarParrafo = () => {
    if (!parrafo.length) return;
    const p = crear("p");
    parrafo.forEach((linea, i) => {
      if (i) p.appendChild(document.createElement("br"));
      p.appendChild(enLinea(linea));
    });
    fragmento.appendChild(p);
    parrafo = [];
  };
  const cerrarLista = () => {
    if (lista) fragmento.appendChild(lista);
    lista = null;
  };
  const cerrarTabla = () => {
    if (tabla) fragmento.appendChild(armarTabla(tabla));
    tabla = null;
  };

  for (const linea of lineas) {
    if (codigo === null && /^\s*\|.*\|\s*$/.test(linea)) {
      cerrarParrafo();
      cerrarLista();
      (tabla = tabla || []).push(linea);
      continue;
    }
    cerrarTabla();
    if (linea.trim().startsWith("```")) {
      if (codigo === null) {
        cerrarParrafo();
        cerrarLista();
        codigo = [];
      } else {
        fragmento.appendChild(crear("pre", "", codigo.join("\n")));
        codigo = null;
      }
      continue;
    }
    if (codigo !== null) {
      codigo.push(linea);
      continue;
    }
    const item = linea.match(/^\s*[-*•]\s+(.*)$/);
    if (item) {
      cerrarParrafo();
      lista = lista || crear("ul");
      lista.appendChild(crear("li")).appendChild(enLinea(item[1]));
    } else if (!linea.trim()) {
      cerrarParrafo();
      cerrarLista();
    } else {
      cerrarLista();
      parrafo.push(linea);
    }
  }
  if (codigo !== null) fragmento.appendChild(crear("pre", "", codigo.join("\n")));
  cerrarTabla();
  cerrarParrafo();
  cerrarLista();
  return fragmento;
}

/** Las celdas de una línea "| a | b |" (un "\|" dentro de una celda es un "|" de verdad). */
function celdas(linea) {
  return linea
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split(/(?<!\\)\|/)
    .map((celda) => celda.trim().replace(/\\\|/g, "|"));
}

/** ¿Es la línea que separa el encabezado del cuerpo? ("|---|:---:|") */
function esSeparador(linea) {
  return celdas(linea).every((celda) => /^:?-{3,}:?$/.test(celda));
}

/**
 * Una tabla de markdown como tabla de verdad. Las celdas con ✅, ⚠️ o ⛔ toman el color
 * de su estado (como el checklist de soportes: así se ve de un vistazo qué está bien).
 * Si las líneas no forman una tabla (falta el separador), se muestran como texto.
 */
function armarTabla(lineas) {
  if (lineas.length < 2 || !esSeparador(lineas[1])) {
    const p = crear("p");
    lineas.forEach((linea, i) => {
      if (i) p.appendChild(document.createElement("br"));
      p.appendChild(enLinea(linea));
    });
    return p;
  }
  const contenedor = crear("div", "tabla-contenedor");
  const tabla = crear("table", "tabla-md");
  const encabezado = crear("tr");
  for (const celda of celdas(lineas[0])) encabezado.appendChild(crear("th")).appendChild(enLinea(celda));
  tabla.appendChild(crear("thead")).appendChild(encabezado);
  const cuerpo = tabla.appendChild(crear("tbody"));
  for (const linea of lineas.slice(2)) {
    const fila = crear("tr");
    for (const celda of celdas(linea)) {
      fila.appendChild(crear("td", claseDeEstado(celda))).appendChild(enLinea(celda));
    }
    cuerpo.appendChild(fila);
  }
  contenedor.appendChild(tabla);
  return contenedor;
}

function claseDeEstado(texto) {
  if (texto.includes("⛔")) return "mal";
  if (texto.includes("⚠️")) return "espera";
  if (texto.includes("✅")) return "ok";
  return "";
}

function enLinea(texto) {
  const fragmento = document.createDocumentFragment();
  for (const pedazo of texto.split(/(\*\*[^*]+\*\*|`[^`]+`)/)) {
    if (pedazo.startsWith("**") && pedazo.endsWith("**") && pedazo.length > 4) {
      fragmento.appendChild(crear("strong", "", pedazo.slice(2, -2)));
    } else if (pedazo.startsWith("`") && pedazo.endsWith("`") && pedazo.length > 2) {
      fragmento.appendChild(crear("code", "", pedazo.slice(1, -1)));
    } else if (pedazo) {
      fragmento.appendChild(document.createTextNode(pedazo));
    }
  }
  return fragmento;
}

// ---------- Acciones de la analista ----------

function bloquear(si) {
  ocupado = si;
  caja.disabled = si;
  botonEnviar.disabled = si;
  for (const boton of conversacion.querySelectorAll(".tarjeta.pendiente button")) boton.disabled = si;
}

async function enviarMensaje(texto) {
  if (ocupado) return;
  bloquear(true);
  agregarUsuario(texto);
  const pensando = mostrarPensando();
  try {
    const cuerpo = { message: texto };
    if (sesionId) cuerpo.session_id = sesionId;
    const r = await llamar("POST", "/api/chat", cuerpo);
    pensando.remove();
    guardarSesion(r.session_id);
    agregarRespuesta(r);
    actualizarPendientes(r.confirmations);
  } catch (e) {
    pensando.remove();
    if (e.estadoHttp === 404) {
      guardarSesion(null);
      agregarError(`${e.message} Su próximo mensaje empezará una conversación nueva.`);
    } else {
      agregarError(e.message);
    }
  } finally {
    bloquear(false);
    caja.focus();
  }
}

async function resolver(confirmacion, aprobar, tarjeta) {
  if (ocupado || !sesionId) return;
  bloquear(true);
  agregarSistema(`Usted ${aprobar ? "aprobó" : "rechazó"} la acción ${confirmacion.id}.`);
  const pensando = mostrarPensando();
  try {
    const r = await llamar("POST", `/api/confirmations/${encodeURIComponent(confirmacion.id)}`, {
      session_id: sesionId,
      approve: aprobar,
    });
    pensando.remove();
    agregarRespuesta(r);
    actualizarPendientes(r.confirmations);
  } catch (e) {
    pensando.remove();
    agregarError(e.message);
    if (e.estadoHttp === 409) actualizarPendientes([]); // ya no estaba pendiente
  } finally {
    bloquear(false);
    tarjeta.scrollIntoView({ block: "nearest" });
  }
}

function nuevaConversacion() {
  if (ocupado) return;
  guardarSesion(null);
  for (const elemento of [...conversacion.children]) {
    if (elemento !== bienvenida) elemento.remove();
  }
  casosDePortal.clear();
  bienvenida.hidden = false;
  caja.focus();
}

// ---------- Al abrir la página ----------

async function mostrarSalud() {
  try {
    const s = await llamar("GET", "/api/health");
    estado.textContent = `${s.model} · prompt v${s.prompt_version}`;
    if (!s.llm_configured) {
      estado.textContent += " · ⚠️ sin modelo configurado (falta la clave en .env)";
      estado.classList.add("mal");
    }
  } catch (e) {
    estado.textContent = e.message;
    estado.classList.add("mal");
  }
}

async function restaurar() {
  if (!sesionId) return;
  try {
    const historial = await llamar("GET", `/api/sessions/${encodeURIComponent(sesionId)}`);
    for (const turno of historial.turns) {
      if (turno.kind === "message") agregarUsuario(turno.input);
      else agregarSistema(`Usted ${turno.kind === "approve" ? "aprobó" : "rechazó"} la acción ${turno.input}.`);
      agregarRespuesta(turno.response);
    }
    actualizarPendientes(historial.pending);
  } catch (e) {
    // La conversación venció o el servidor se reinició: se empieza de nuevo.
    guardarSesion(null);
    if (e.estadoHttp !== 404) agregarError(e.message);
  }
}

formulario.addEventListener("submit", (evento) => {
  evento.preventDefault();
  const texto = caja.value.trim();
  if (!texto) return;
  caja.value = "";
  enviarMensaje(texto);
});

caja.addEventListener("keydown", (evento) => {
  if (evento.key === "Enter" && !evento.shiftKey) {
    evento.preventDefault();
    formulario.requestSubmit();
  }
});

botonNueva.addEventListener("click", nuevaConversacion);

mostrarSalud();
restaurar();
caja.focus();
