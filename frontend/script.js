/* DATARA · frontend conectado a la API de SmartSearch
   - URL de la API: config.js (local: http://localhost:8000 · AWS/CloudFront: /api)
   - index.html:      temas populares (/categories) y artículos destacados (/articles)
   - resultados.html: búsqueda (?q=), similares (?similar=<url>) o exploración paginada
   - Cada tarjeta: "Generar resumen" llama al modelo de teasers (/articles/{url}/teaser) */
(function () {
  "use strict";

  var API = (window.APP_CONFIG && window.APP_CONFIG.API_URL) || "http://localhost:8000";

  /* ---------- Tema claro / oscuro ---------- */
  var root = document.documentElement;
  var STORAGE_KEY = "datara-theme";

  try {
    var saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (e) { /* almacenamiento no disponible */ }

  var themeBtn = document.getElementById("themeToggle");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var current = root.getAttribute("data-theme") ||
        (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      var next = current === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem(STORAGE_KEY, next); } catch (e) {}
    });
  }

  /* ---------- Utilidades ---------- */
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // FastAPI envía el motivo del error en "detail"
  function request(path, options) {
    return fetch(API + path, options).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) throw new Error((data && data.detail) || ("Error " + res.status));
        return data;
      });
    });
  }
  function getJSON(path) { return request(path); }
  function postJSON(path, body) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }

  function sourceOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return "Fuente"; }
  }

  function shuffle(list) {
    var a = list.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  function stateHTML(kind, title, text) {
    if (kind === "loading") {
      return '<div class="state"><span class="spinner" aria-hidden="true"></span><p>' + esc(title) + "</p></div>";
    }
    return '<div class="state' + (kind === "error" ? " state--error" : "") + '">' +
      "<h3>" + esc(title) + "</h3>" + (text ? "<p>" + esc(text) + "</p>" : "") + "</div>";
  }

  function backendError(err) {
    return stateHTML("error", "No se pudo conectar con el servidor",
      (err && err.message ? err.message.replace(/\.+$/, "") + ". " : "") + "Comprueba que la API esté en marcha (" + API + ").");
  }

  var ICON = {
    sparkle: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M10 2l1.8 5.2L17 9l-5.2 1.8L10 16l-1.8-5.2L3 9l5.2-1.8zM18 13l.9 2.1L21 16l-2.1.9L18 19l-.9-2.1L15 16l2.1-.9z"/></svg>',
    sparkleLine: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M10 2l1.8 5.2L17 9l-5.2 1.8L10 16l-1.8-5.2L3 9l5.2-1.8zM18 13l.9 2.1L21 16l-2.1.9L18 19l-.9-2.1L15 16l2.1-.9z"/></svg>',
    link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg>',
    external: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>'
  };

  /* ---------- Tarjeta de artículo ----------
     La API devuelve title, url (identificador del artículo) y category_name. */
  function cardHTML(article, row) {
    var url = article.url || "";
    var title = article.title || "Sin título";
    var source = sourceOf(url);
    var similarHref = "resultados.html?similar=" + encodeURIComponent(url) + "&title=" + encodeURIComponent(title);

    return '<article class="article-card' + (row ? " article-card--row" : "") + '" data-url="' + esc(url) + '">' +
      '<div class="article-card__meta">' +
        '<span class="source"><span class="source__mark">' + esc(source.charAt(0).toUpperCase()) + "</span>" + esc(source) + "</span>" +
      "</div>" +
      '<h3 class="article-card__title"><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(title) + "</a></h3>" +
      (article.category_name
        ? '<div class="tags"><a class="tag" href="resultados.html?q=' + encodeURIComponent(article.category_name) + '">' + esc(article.category_name) + "</a></div>"
        : "") +
      '<div class="summary" hidden aria-live="polite">' +
        '<span class="summary__label">' + ICON.sparkle + "Resumen generado por IA</span>" +
        '<p class="summary__text"></p>' +
      "</div>" +
      '<div class="article-card__actions">' +
        '<button class="btn btn--soft js-summary" type="button" aria-expanded="false">' + ICON.sparkleLine + "Generar resumen</button>" +
        '<a class="btn btn--outline" href="' + esc(similarHref) + '">' + ICON.link + "Ver similares</a>" +
        '<a class="btn btn--primary" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + ICON.external + "Ir al artículo</a>" +
      "</div>" +
    "</article>";
  }

  /* ---------- Generar resumen (teaser) ----------
     Cada botón pide el resumen de su propio artículo al modelo Qwen3 + LoRA (SageMaker).
     Una vez generado, el botón solo lo muestra u oculta. */
  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".js-summary");
    if (!btn) return;

    var card = btn.closest(".article-card");
    var box = card.querySelector(".summary");
    var text = box.querySelector(".summary__text");

    if (box.dataset.ready) {
      box.hidden = !box.hidden;
      btn.setAttribute("aria-expanded", String(!box.hidden));
      return;
    }
    if (box.classList.contains("is-loading")) return;

    box.hidden = false;
    box.classList.remove("is-error");
    box.classList.add("is-loading");
    text.textContent = "Generando el resumen del artículo…";
    btn.disabled = true;

    getJSON("/articles/" + encodeURIComponent(card.dataset.url) + "/teaser")
      .then(function (data) {
        text.textContent = data.teaser;
        box.dataset.ready = "1";
        btn.setAttribute("aria-expanded", "true");
      })
      .catch(function (err) {
        box.classList.add("is-error");
        text.textContent = "No se pudo generar el resumen: " + err.message.replace(/\.+$/, "") + ". Pulsa el botón para reintentar.";
      })
      .then(function () {
        box.classList.remove("is-loading");
        btn.disabled = false;
      });
  });

  /* ---------- Inicio: temas populares y artículos destacados ---------- */
  var topicChips = document.getElementById("topicChips");
  if (topicChips) {
    getJSON("/categories?limit=6").then(function (categories) {
      if (!categories || !categories.length) return;
      topicChips.innerHTML = categories.map(function (c) {
        return '<a class="chip" href="resultados.html?q=' + encodeURIComponent(c.category_name) + '" title="' +
          esc(c.total + " artículos") + '">' + esc(c.category_name) + "</a>";
      }).join("") + '<a class="chip" href="resultados.html">+ Más</a>';
    }).catch(function () { /* sin API se mantienen los temas de ejemplo */ });
  }

  var featured = document.getElementById("featured");
  if (featured) {
    getJSON("/articles?limit=50&offset=0").then(function (data) {
      var articles = shuffle(data.articles || []).slice(0, 3);
      featured.innerHTML = articles.length
        ? articles.map(function (a) { return cardHTML(a, false); }).join("")
        : stateHTML("empty", "Aún no hay artículos", "La base de datos no devolvió artículos.");
    }).catch(function (err) { featured.innerHTML = backendError(err); });
  }

  /* ---------- Resultados: búsqueda, similares o exploración ---------- */
  var results = document.getElementById("results");
  if (results) initResults();

  function initResults() {
    var params = new URLSearchParams(window.location.search);
    var query = (params.get("q") || "").trim();
    var similarUrl = params.get("similar");
    var similarTitle = params.get("title") || "";

    var titleEl = document.getElementById("resultsTitle");
    var countEl = document.getElementById("resultsCount");
    var filters = document.getElementById("filters");
    var categoryFilter = document.getElementById("categoryFilter");
    var loadMore = document.getElementById("loadMore");
    var related = document.getElementById("related");
    var input = document.getElementById("q");
    if (input && query) input.value = query;

    var shown = [];            // artículos cargados en la página
    var activeCategories = []; // filtro de categorías activo

    function render() {
      var list = activeCategories.length
        ? shown.filter(function (a) { return activeCategories.indexOf(a.category_name) !== -1; })
        : shown;
      results.innerHTML = list.length
        ? list.map(function (a) { return cardHTML(a, true); }).join("")
        : stateHTML("empty", "Sin resultados", "No se encontraron artículos. Prueba con otras palabras clave.");
    }

    // Filtro por categoría con los resultados cargados (selección múltiple; ninguna activa = todas)
    function renderFilters() {
      var counts = {};
      shown.forEach(function (a) {
        if (a.category_name) counts[a.category_name] = (counts[a.category_name] || 0) + 1;
      });
      var names = Object.keys(counts).sort(function (x, y) { return counts[y] - counts[x]; });
      if (names.length < 2) { filters.hidden = true; return; }

      categoryFilter.innerHTML = '<span class="filter-group__label">Categorías</span>' +
        names.map(function (name) {
          var on = activeCategories.indexOf(name) !== -1;
          return '<button class="chip' + (on ? " is-active" : "") + '" type="button" aria-pressed="' + on +
            '" data-category="' + esc(name) + '">' + esc(name) + " · " + counts[name] + "</button>";
        }).join("");
      filters.hidden = false;
    }

    categoryFilter.addEventListener("click", function (event) {
      var chip = event.target.closest("button.chip");
      if (!chip) return;
      var name = chip.dataset.category;
      var i = activeCategories.indexOf(name);
      if (i === -1) activeCategories.push(name); else activeCategories.splice(i, 1);
      renderFilters();
      render();
    });

    // Temas relacionados: categorías de los resultados (o las más populares al explorar)
    function renderRelated(names) {
      names = names.filter(function (n) { return n && n.toLowerCase() !== query.toLowerCase(); }).slice(0, 6);
      if (!names.length) { related.hidden = true; return; }
      related.innerHTML = '<span class="filter-group__label">Temas relacionados</span>' +
        names.map(function (n) {
          return '<a class="chip" href="resultados.html?q=' + encodeURIComponent(n) + '">' + esc(n) + "</a>";
        }).join("");
      related.hidden = false;
    }

    function categoriesOf(list) {
      var seen = [];
      list.forEach(function (a) { if (a.category_name && seen.indexOf(a.category_name) === -1) seen.push(a.category_name); });
      return seen;
    }

    function fail(err) {
      results.innerHTML = backendError(err);
      countEl.textContent = "";
    }

    // 1. Artículos similares a uno dado (recomendador BM25 + embeddings)
    if (similarUrl) {
      titleEl.textContent = "Artículos similares";
      document.title = "DATARA · Artículos similares";
      getJSON("/articles/" + encodeURIComponent(similarUrl) + "/related?top_n=5").then(function (data) {
        var base = (data && data.base_article) || {};
        shown = (data && data.related) || [];
        countEl.innerHTML = "Mostrando <strong>" + shown.length + " artículos</strong> similares a “" +
          esc(base.title || similarTitle) + "”";
        renderFilters(); render(); renderRelated(categoriesOf(shown));
      }).catch(fail);
      return;
    }

    // 2. Búsqueda en lenguaje natural
    if (query) {
      document.title = "DATARA · " + query;
      postJSON("/search", { query: query, top_n: 10 }).then(function (data) {
        shown = data || [];
        countEl.innerHTML = "Mostrando <strong>" + shown.length + " artículo" + (shown.length === 1 ? "" : "s") +
          "</strong> más relevantes para “" + esc(query) + "”";
        renderFilters(); render(); renderRelated(categoriesOf(shown));
      }).catch(fail);
      return;
    }

    // 3. Explorar todos los artículos, 10 por página con "Cargar más"
    var PAGE = 10;
    var total = 0;
    titleEl.textContent = "Explorar artículos";
    document.title = "DATARA · Explorar artículos";

    function loadPage() {
      var button = loadMore.querySelector("button");
      button.disabled = true;
      return getJSON("/articles?limit=" + PAGE + "&offset=" + shown.length).then(function (data) {
        total = data.total || 0;
        shown = shown.concat(data.articles || []);
        countEl.innerHTML = "Mostrando <strong>" + shown.length + "</strong> de " + total + " artículos";
        renderFilters(); render();
        loadMore.hidden = shown.length >= total;
      }).catch(fail).then(function () { button.disabled = false; });
    }

    loadMore.querySelector("button").addEventListener("click", loadPage);
    loadPage();
    getJSON("/categories?limit=8").then(function (categories) {
      renderRelated((categories || []).map(function (c) { return c.category_name; }));
    }).catch(function () {});
  }
})();
