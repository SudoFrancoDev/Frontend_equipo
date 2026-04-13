/* ============================================================
   SMART SEARCH — app.js
   Backend: FastAPI en http://localhost:8000
   ============================================================ */

const API = "http://localhost:8000";

/* ────────────────────────────────────────────────────────────
   UTILIDADES
──────────────────────────────────────────────────────────── */
async function apiGet(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`Error ${res.status}: ${res.statusText}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(`Error ${res.status}: ${res.statusText}`);
  return res.json();
}

// Extrae una etiqueta legible del feed_tag_name (primera palabra)
function formatTag(raw) {
  if (!raw) return "artículo";
  const first = raw.split(" ")[0];
  return first.length > 16 ? first.slice(0, 14) + "…" : first;
}

// Acorta una URL larga (article_id) para mostrar en label
function shortId(url) {
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    const last = parts[parts.length - 1] || "";
    return last.length > 40 ? last.slice(0, 38) + "…" : last;
  } catch {
    return url.length > 40 ? url.slice(0, 38) + "…" : url;
  }
}

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/* ============================================================
   HOME PAGE
   ============================================================ */
if (document.getElementById("slider-track")) {
  initHome();
}

async function initHome() {
  await loadSlider();
  setupHeroSearch();
}

// ---- Slider ------------------------------------------------
let sliderData = { articles: [], page: 0, perPage: 3, timer: null };

async function loadSlider() {
  const track = document.getElementById("slider-track");
  track.innerHTML = skeletonSlider();

  try {
    // Intentamos cargar desde el backend; si no responde, usamos demo
    const data = await apiGet("/articles?limit=50&offset=0");
    const arts = shuffle(data.articles || []);
    sliderData.articles = arts;
    renderSlider();
    startSliderAutoPlay();
  } catch (e) {
    track.innerHTML = `
      <div class="skeleton-card" style="flex:1;padding:28px;">
        <div class="state-msg">
          <span class="icon">⚠️</span>
          <h3>Backend no disponible</h3>
          <p>Asegúrate de que el servidor FastAPI esté corriendo en<br>
          <a href="#">http://localhost:8000</a><br>
          Consulta el archivo <strong>SETUP.md</strong> para instrucciones.</p>
        </div>
      </div>`;
  }
}

function skeletonSlider() {
  return Array(3).fill(0).map(() => `
    <div class="skeleton-card">
      <div class="skeleton-line" style="width:60px;height:20px;border-radius:50px;"></div>
      <div class="skeleton-line" style="width:90%;height:14px;margin-top:14px;"></div>
      <div class="skeleton-line" style="width:75%;height:14px;"></div>
      <div class="skeleton-line" style="width:50%;height:14px;"></div>
    </div>`
  ).join("");
}

function renderSlider() {
  const { articles, page, perPage } = sliderData;
  const total = Math.ceil(articles.length / perPage);
  const start = page * perPage;
  const visible = articles.slice(start, start + perPage);

  const track = document.getElementById("slider-track");
  track.style.transition = "none";
  track.innerHTML = visible.map(a => `
    <div class="slider-card" onclick="goToArticle('${encodeURIComponent(a.article_id)}', '${encodeURIComponent(a.title || "")}')">
      <span class="slider-card-tag">${formatTag(a.feed_tag_name)}</span>
      <div class="slider-card-title">${a.title || "Sin título"}</div>
      <div class="slider-card-action">Ver similares →</div>
    </div>`
  ).join("");

  // Dots
  const dotsEl = document.getElementById("slider-dots");
  if (dotsEl) {
    dotsEl.innerHTML = Array(total).fill(0).map((_, i) =>
      `<div class="dot ${i === page ? "active" : ""}" onclick="goToSliderPage(${i})"></div>`
    ).join("");
  }
}

function goToSliderPage(page) {
  const total = Math.ceil(sliderData.articles.length / sliderData.perPage);
  sliderData.page = (page + total) % total;
  renderSlider();
}

function sliderNext() {
  goToSliderPage(sliderData.page + 1);
  resetSliderTimer();
}

function sliderPrev() {
  goToSliderPage(sliderData.page - 1);
  resetSliderTimer();
}

function startSliderAutoPlay() {
  sliderData.timer = setInterval(() => {
    goToSliderPage(sliderData.page + 1);
  }, 4500);
}

function resetSliderTimer() {
  clearInterval(sliderData.timer);
  startSliderAutoPlay();
}

function goToArticle(encodedId, encodedTitle) {
  // Navega a la página de artículos buscando el título
  const title = decodeURIComponent(encodedTitle);
  window.location.href = `articles.html?q=${encodeURIComponent(title)}`;
}

// ---- Hero search ------------------------------------------
function setupHeroSearch() {
  const input = document.getElementById("heroSearch");
  if (!input) return;
  input.addEventListener("keydown", e => {
    if (e.key === "Enter") heroSearch();
  });
}

function heroSearch() {
  const q = document.getElementById("heroSearch").value.trim();
  if (!q) return;
  window.location.href = `articles.html?q=${encodeURIComponent(q)}`;
}

function goTag(tag) {
  window.location.href = `articles.html?q=${encodeURIComponent(tag)}`;
}


/* ============================================================
   ARTICLES PAGE
   ============================================================ */
const articlesPage = document.getElementById("articles-list");
if (articlesPage) {
  initArticlesPage();
}

const state = {
  articles: [],
  total: 0,
  page: 1,
  perPage: 10,
  selectedId: null,
  selectedTitle: "",
  mode: "list",   // "list" | "search"
  query: "",
  loading: false
};

async function initArticlesPage() {
  const params = new URLSearchParams(window.location.search);
  const q = params.get("q");

  // Verificar que el backend esté activo
  try {
    await apiGet("/health");
  } catch {
    showBackendError();
    return;
  }

  if (q) {
    document.getElementById("searchInput").value = q;
    await doSearch(q);
  } else {
    await loadPage(1);
  }

  // Enter en el input
  document.getElementById("searchInput").addEventListener("keydown", e => {
    if (e.key === "Enter") doSearch();
  });
}

function showBackendError() {
  document.getElementById("articles-list").innerHTML = `
    <div class="state-msg">
      <span class="icon">🔌</span>
      <h3>No se puede conectar al servidor</h3>
      <p>El backend FastAPI no está corriendo en <strong>http://localhost:8000</strong>.<br>
      Consulta <strong>SETUP.md</strong> para iniciar el servidor correctamente.</p>
    </div>`;
  document.getElementById("results-bar").innerHTML = "";
  document.getElementById("pagination").innerHTML = "";
}

// ---- Carga página paginada --------------------------------
async function loadPage(page) {
  if (state.loading) return;
  state.loading = true;
  state.mode = "list";
  state.page = page;
  clearSelection(false);

  showLoadingState();

  try {
    const offset = (page - 1) * state.perPage;
    const data = await apiGet(`/articles?limit=${state.perPage}&offset=${offset}`);
    state.articles = data.articles || [];
    state.total    = data.total    || 0;
    renderArticles();
    renderResultsBar(null, state.total);
    renderPagination();
  } catch (e) {
    showError(e.message);
  } finally {
    state.loading = false;
  }
}

// ---- Búsqueda ---------------------------------------------
async function doSearch(query) {
  const q = (query !== undefined ? query : document.getElementById("searchInput").value).trim();
  if (!q) {
    await loadPage(1);
    return;
  }

  if (state.loading) return;
  state.loading = true;
  state.query   = q;
  state.mode    = "search";
  state.page    = 1;
  clearSelection(false);

  // Actualiza la URL sin recargar
  const url = new URL(window.location);
  url.searchParams.set("q", q);
  window.history.pushState({}, "", url);

  showLoadingState();

  try {
    const data = await apiPost("/search", { query: q, top_n: state.perPage });
    state.articles = data || [];
    state.total    = state.articles.length;
    renderArticles();
    renderResultsBar(q, state.total);
    renderPagination(); // En búsqueda no hay paginación adicional
  } catch (e) {
    showError(e.message);
  } finally {
    state.loading = false;
  }
}

// ---- Render artículos -------------------------------------
function renderArticles() {
  const list = document.getElementById("articles-list");
  if (!state.articles.length) {
    list.innerHTML = `
      <div class="state-msg">
        <span class="icon">🔍</span>
        <h3>Sin resultados</h3>
        <p>No se encontraron artículos para tu búsqueda.<br>Prueba con otras palabras clave.</p>
      </div>`;
    return;
  }

  list.innerHTML = state.articles.map(a => `
    <div class="article-card"
         id="card-${CSS.escape(a.article_id)}"
         data-id="${escAttr(a.article_id)}"
         data-title="${escAttr(a.title || "")}"
         onclick="handleCardClick(this)">
      <span class="article-tag" title="${escAttr(a.feed_tag_name || "")}">
        ${formatTag(a.feed_tag_name)}
      </span>
      <div class="article-body">
        <div class="article-title">${escHtml(a.title || "Sin título")}</div>
        <div class="article-id-label">${shortId(a.article_id)}</div>
      </div>
      <button class="btn-ver-similares"
              onclick="handleVerSimilares(event, this)">
        Ver similares
      </button>
    </div>`
  ).join("");
}

function escAttr(s) {
  return String(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function escHtml(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ---- Barra de resultados ----------------------------------
function renderResultsBar(query, total) {
  const bar = document.getElementById("results-bar");
  const countText = `<span class="results-info">
    <strong>${total}</strong> artículo${total !== 1 ? "s" : ""} encontrado${total !== 1 ? "s" : ""}
  </span>`;
  const queryChip = query
    ? `<span class="results-query">🔍 "${escHtml(query)}"</span>` : "";
  bar.innerHTML = countText + queryChip;
}

// ---- Paginación -------------------------------------------
function renderPagination() {
  const el = document.getElementById("pagination");

  // En modo búsqueda no hay paginación adicional
  if (state.mode === "search") { el.innerHTML = ""; return; }

  const totalPages = Math.ceil(state.total / state.perPage);
  if (totalPages <= 1) { el.innerHTML = ""; return; }

  const p = state.page;
  let btns = "";

  // Prev
  btns += `<button class="page-btn arrow" ${p === 1 ? "disabled" : ""}
             onclick="loadPage(${p - 1})">‹</button>`;

  // Páginas (ventana de ±2)
  const range = [];
  for (let i = Math.max(1, p - 2); i <= Math.min(totalPages, p + 2); i++) range.push(i);
  if (range[0] > 1) {
    btns += `<button class="page-btn" onclick="loadPage(1)">1</button>`;
    if (range[0] > 2) btns += `<span style="color:var(--text-muted);padding:0 4px;">…</span>`;
  }
  range.forEach(i => {
    btns += `<button class="page-btn ${i === p ? "active" : ""}" onclick="loadPage(${i})">${i}</button>`;
  });
  if (range[range.length - 1] < totalPages) {
    if (range[range.length - 1] < totalPages - 1)
      btns += `<span style="color:var(--text-muted);padding:0 4px;">…</span>`;
    btns += `<button class="page-btn" onclick="loadPage(${totalPages})">${totalPages}</button>`;
  }

  // Next
  btns += `<button class="page-btn arrow" ${p === totalPages ? "disabled" : ""}
             onclick="loadPage(${p + 1})">›</button>`;

  el.innerHTML = btns;
}

// ---- Selección de card ------------------------------------
function handleCardClick(cardEl) {
  // Si hace clic en el botón, no seleccionar/deseleccionar
  if (event && event.target.classList.contains("btn-ver-similares")) return;

  const id    = cardEl.dataset.id;
  const title = cardEl.dataset.title;

  if (state.selectedId === id) {
    clearSelection(true);
    return;
  }

  state.selectedId    = id;
  state.selectedTitle = title;

  document.querySelectorAll(".article-card").forEach(c => {
    if (c.dataset.id === id) {
      c.classList.add("selected");
      c.classList.remove("dimmed");
    } else {
      c.classList.add("dimmed");
      c.classList.remove("selected");
    }
  });
}

function clearSelection(hideSimilar = true) {
  state.selectedId    = null;
  state.selectedTitle = "";
  document.querySelectorAll(".article-card").forEach(c => {
    c.classList.remove("selected", "dimmed");
  });
  if (hideSimilar) hideSimilarSection();
}

// ---- Ver similares ----------------------------------------
async function handleVerSimilares(event, btnEl) {
  event.stopPropagation();

  const card  = btnEl.closest(".article-card");
  const id    = card.dataset.id;
  const title = card.dataset.title;

  // Deshabilita el botón mientras carga
  btnEl.textContent = "Cargando…";
  btnEl.style.opacity = "0.6";
  btnEl.disabled = true;

  try {
    // Usamos /search con el título como query (compatible con cualquier article_id)
    const results = await apiPost("/search", { query: title, top_n: 6 });
    // Filtramos el artículo seleccionado y tomamos los 5 primeros
    const similar = (results || []).filter(a => a.article_id !== id).slice(0, 5);
    renderSimilarSection(title, similar);
  } catch (e) {
    alert("Error al cargar artículos similares: " + e.message);
  } finally {
    btnEl.textContent = "Ver similares";
    btnEl.style.opacity = "";
    btnEl.disabled = false;
  }
}

function renderSimilarSection(baseTitle, articles) {
  const section = document.getElementById("similar-section");

  if (!articles.length) {
    section.innerHTML = `
      <div class="state-msg">
        <span class="icon">🤔</span>
        <h3>Sin similares</h3>
        <p>No se encontraron artículos similares.</p>
      </div>`;
    section.classList.add("visible");
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  section.innerHTML = `
    <div class="similar-header">
      <span class="similar-label">● Artículos similares</span>
      <span class="similar-base-title">"${escHtml(baseTitle)}"</span>
      <button class="similar-close" onclick="clearSelection(true)">✕ Cerrar</button>
    </div>
    <div class="similar-grid">
      ${articles.map(a => `
        <div class="similar-card">
          <span class="similar-card-tag">${formatTag(a.feed_tag_name)}</span>
          <div class="similar-card-title">${escHtml(a.title || "Sin título")}</div>
        </div>`
      ).join("")}
    </div>`;

  section.classList.add("visible");

  // Scroll suave hacia la sección
  setTimeout(() => {
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 100);
}

function hideSimilarSection() {
  const section = document.getElementById("similar-section");
  if (section) {
    section.classList.remove("visible");
    section.innerHTML = "";
  }
}

// ---- Estados de carga / error ----------------------------
function showLoadingState() {
  document.getElementById("articles-list").innerHTML = `
    <div class="state-msg" style="padding:40px;">
      <div class="loading-dots"><span></span><span></span><span></span></div>
      <p style="margin-top:14px;font-size:0.85rem;">Cargando artículos…</p>
    </div>`;
  document.getElementById("pagination").innerHTML = "";
  document.getElementById("results-bar").innerHTML = "";
}

function showError(msg) {
  document.getElementById("articles-list").innerHTML = `
    <div class="state-msg">
      <span class="icon">❌</span>
      <h3>Error de conexión</h3>
      <p>${escHtml(msg)}<br><br>
      Verifica que el backend esté corriendo.<br>
      Consulta <strong>SETUP.md</strong> para instrucciones.</p>
    </div>`;
}
