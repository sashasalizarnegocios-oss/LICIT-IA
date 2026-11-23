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
