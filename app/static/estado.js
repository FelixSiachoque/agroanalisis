// Estado en tiempo real de los trabajos (sin recargar la página).
// Busca etiquetas <span data-trabajo="ID" data-estado="..."> y consulta /api/trabajos/ID cada 2 s
// mientras el trabajo esté pendiente o en ejecución. Si la página tiene data-recargar-al-terminar
// (detalle de un trabajo), se recarga una vez al terminar para mostrar los botones de descarga.
// Si el navegador no ejecuta JavaScript, las páginas usan <noscript><meta http-equiv="refresh"></noscript>.
(function () {
  "use strict";
  var TEXTOS = { pendiente: "Pendiente", en_ejecucion: "En ejecución", completado: "Completado", fallido: "Fallido" };
  var FINALES = { completado: true, fallido: true };
  var CADA_MS = 2000;
  var LIMITE_MS = 10 * 60 * 1000;   // deja de consultar después de 10 minutos
  var inicio = Date.now();
  var recargar = document.body.hasAttribute("data-recargar-al-terminar");

  function pintar(etiqueta, trabajo) {
    var estado = trabajo.estado;
    var integridad = estado === "fallido" && trabajo.error && trabajo.error.indexOf("integridad_comprometida") === 0;
    etiqueta.className = "estado " + (integridad ? "integridad" : estado);
    etiqueta.textContent = integridad ? "Integridad comprometida" : (TEXTOS[estado] || estado);
    etiqueta.setAttribute("data-estado", estado);
  }

  function consultar(etiqueta) {
    var id = etiqueta.getAttribute("data-trabajo");
    fetch("/api/trabajos/" + encodeURIComponent(id), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (trabajo) {
        if (!trabajo) { return; }
        var antes = etiqueta.getAttribute("data-estado");
        if (trabajo.estado !== antes) { pintar(etiqueta, trabajo); }
        if (FINALES[trabajo.estado]) {
          if (recargar && !FINALES[antes]) { window.location.reload(); }
        } else if (Date.now() - inicio < LIMITE_MS) {
          setTimeout(function () { consultar(etiqueta); }, CADA_MS);
        }
      })
      .catch(function () { setTimeout(function () { consultar(etiqueta); }, CADA_MS * 3); });
  }

  var etiquetas = document.querySelectorAll("[data-trabajo][data-estado]");
  for (var i = 0; i < etiquetas.length && i < 20; i++) {
    if (!FINALES[etiquetas[i].getAttribute("data-estado")]) {
      consultar(etiquetas[i]);
    }
  }
})();
