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

const costos = document.querySelector("#costos");
if (costos) {
  costos.addEventListener("submit", event => {
    event.preventDefault();
    const valores = new FormData(costos);
    const numero = campo => Number(valores.get(campo));
    const costo = numero("meses") * (numero("personal") + numero("operacion")) + numero("equipos");
    const margen = numero("oferta") - costo;
    const soles = new Intl.NumberFormat("es-PE", {style:"currency", currency:"PEN"});
    document.querySelector("#margen").textContent =
      "Costo total: " + soles.format(costo) + " · Margen: " + soles.format(margen) +
      " (" + (100 * margen / numero("oferta")).toFixed(1) + " %)";
  });
}
const guardar = document.querySelector("#guardar-alerta");
if (guardar) {
  const clave = "licitia.busquedas.v1";
  const estado = document.querySelector("#estado-alerta");
  const lista = document.querySelector("#mis-alertas");
  let alertas = [];
  try {
    const datos = JSON.parse(localStorage.getItem(clave) || "[]");
    if (Array.isArray(datos)) alertas = datos.filter(item => typeof item === "string");
  } catch { estado.textContent = "El almacenamiento del navegador está restringido."; }
  const formulario = document.querySelector(".filters");
  function guardarCambios() {
    try { localStorage.setItem(clave, JSON.stringify(alertas)); }
    catch { estado.textContent = "La búsqueda se conservará solo durante esta visita."; }
  }
  function mostrarAlertas() {
    lista.replaceChildren();
    for (const filtro of alertas) {
      const params = new URLSearchParams(filtro);
      const criterio = Array.from(params).filter(([k,v]) => k !== "origen" && v).map(([,v]) => v).join(" · ");
      const item = document.createElement("li");
      const enlace = document.createElement("a");
      enlace.href = formulario.action.split("?")[0] + "?" + filtro;
      enlace.textContent = criterio || "Todas las convocatorias";
      const quitar = document.createElement("button");
      quitar.type = "button";
      quitar.textContent = "Quitar";
      quitar.addEventListener("click", () => {
        alertas = alertas.filter(value => value !== filtro);
        guardarCambios(); mostrarAlertas();
      });
      item.append(enlace," ",quitar); lista.append(item);
    }
  }
  guardar.addEventListener("click", () => {
    const filtro = new URLSearchParams(new FormData(formulario)).toString();
    if (!alertas.includes(filtro)) alertas.push(filtro);
    estado.textContent = "Búsqueda guardada.";
    guardarCambios(); mostrarAlertas();
  });
  mostrarAlertas();
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
