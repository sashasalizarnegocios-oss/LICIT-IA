const formulario = document.querySelector("[data-ollama-form]");

if (formulario) {
  const boton = formulario.querySelector('button[type="submit"]');
  const estado = formulario.querySelector("[data-ollama-status]");

  formulario.addEventListener("submit", (evento) => {
    if (boton.disabled) {
      evento.preventDefault();
      return;
    }
    estado.textContent = "Consultando a Ollama…";
    boton.disabled = true;
  });

  window.addEventListener("pageshow", () => {
    estado.textContent = "";
    boton.disabled = false;
  });
}

const evidencia = document.querySelector("#evidencia");
if (evidencia) {
  const clave = "licitia.evidencia." + evidencia.dataset.expediente;
  const lista = document.querySelector("#requisitos");
  let requisitos = [];
  try {
    const valor = JSON.parse(localStorage.getItem(clave) || "[]");
    if (Array.isArray(valor)) requisitos = valor.filter(item => item && typeof item.requisito === "string");
  } catch { /* El formulario también permite una revisión en memoria. */ }
  function persistir() {
    try { localStorage.setItem(clave, JSON.stringify(requisitos)); }
    catch { document.querySelector("#aviso-evidencia").textContent = "Revisión disponible solo durante esta visita."; }
  }
  function mostrar() {
    lista.replaceChildren();
    requisitos.forEach((item, i) => {
      const li = document.createElement("li");
      const quitar = document.createElement("button");
      quitar.type = "button";
      quitar.textContent = "Quitar";
      quitar.addEventListener("click", () => {
        requisitos.splice(i,1); persistir(); mostrar();
      });
      li.append(item.requisito + " · " + (item.documento || "Pendiente de acreditar") + " ", quitar);
      lista.append(li);
    });
  }
  evidencia.addEventListener("submit", event => {
    event.preventDefault();
    const campos = new FormData(evidencia);
    const requisito = campos.get("requisito").trim();
    if (!requisito) return;
    requisitos.push({requisito, documento:campos.get("documento").trim()});
    persistir(); mostrar(); evidencia.reset();
  });
  mostrar();
}

const aviso = document.querySelector("#avisos-cierre");
if (aviso) {
  const hoy = new Intl.DateTimeFormat("sv-SE",{timeZone:"America/Lima"}).format(new Date());
  const inicio = Date.parse(hoy + "T00:00:00Z");
  for (const tarjeta of document.querySelectorAll(".card[data-activo='active']")) {
    const dias = (Date.parse(tarjeta.dataset.cierre.slice(0,10) + "T00:00:00Z") - inicio) / 86400000;
    if (dias >= 0 && dias <= 7) {
      const enlace = tarjeta.querySelector("h3 a").cloneNode(true);
      const linea = document.createElement("p");
      linea.append("Alerta de plazo · " + (dias === 0 ? "Cierra hoy" : "Cierra en " + dias + " días") + ": ", enlace);
      aviso.append(linea);
    }
  }
}

for (const form of document.querySelectorAll("[data-alerta]")) {
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const estado = document.querySelector("#estado-alerta");
    const datos = new FormData(form);
    if (datos.get("accion") === "crear") {
      for (const [k,v] of new FormData(document.querySelector(".filters"))) datos.set(k,v);
    }
    const boton = form.querySelector("button");
    boton.disabled = true;
    try {
      const res = await fetch(form.action,{method:"POST",body:datos});
      const info = await res.json();
      estado.textContent = info.mensaje || info.error;
      if (res.ok && datos.get("accion") === "crear") document.querySelector("#alertas details").open = true;
    } catch { estado.textContent = "No se pudo contactar con el servidor."; }
    finally { boton.disabled = false; }
  });
}

const chat = document.querySelector("#chat");
if (chat) {
  const docs = [...document.querySelectorAll(".documento")];
  const enlaces = document.querySelectorAll(".ver-doc");
  const lista = document.querySelector("#mensajes");
  const estado = document.querySelector("#estado-chat");
  const boton = chat.querySelector("button");
  const campo = chat.elements.pregunta;
  let historial = [];
  function seleccionar(){
    historial = [];
    lista.replaceChildren();
    docs.forEach((doc,i) => {
      enlaces[i].hidden = !doc.value;
      if(doc.value) enlaces[i].href = doc.selectedOptions[0].dataset.url;
    });
    boton.disabled = !docs.every(d=>d.value) || docs[0].value === docs[1].value;
    estado.textContent = boton.disabled ? "Elige dos expedientes distintos para empezar." : "¿Qué quieres comparar?";
  }
  function mostrar(rol,texto){
    const p = document.createElement("p");
    p.className = rol;
    p.textContent = texto;
    lista.append(p); lista.scrollTop = lista.scrollHeight;
    return p;
  }
  docs.forEach(d=>d.addEventListener("change",seleccionar));
  seleccionar();
  chat.addEventListener("submit",async event=>{
    event.preventDefault();
    const pregunta = campo.value.trim();
    if(boton.disabled || !pregunta) return;
    const turno = {role:"user",content:pregunta};
    const mensaje = mostrar("usuario",pregunta);
    boton.disabled = true; campo.disabled = true;
    docs.forEach(d=>d.disabled=true);
    estado.textContent = "Ollama está revisando ambos expedientes…";
    try {
      const res = await fetch(chat.action,{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({documentos:docs.map(d=>d.value),historial:[...historial.slice(-8),turno]})});
      const datos = await res.json();
      if(!res.ok) throw new Error(datos.error || "No se pudo completar la consulta.");
      mostrar("asistente",datos.respuesta);
      historial.push(turno,{role:"assistant",content:datos.respuesta.slice(0,4000)});
      campo.value=""; estado.textContent="";
    } catch(error) { mensaje.remove(); estado.textContent=error.message; }
    finally { boton.disabled=false; campo.disabled=false; docs.forEach(d=>d.disabled=false); campo.focus(); }
  });
}
