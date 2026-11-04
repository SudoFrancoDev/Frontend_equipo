/* DATARA · cuentas de usuario (opcional: buscar y navegar no requiere sesión)
   - Persistencia: el token y el usuario se guardan en localStorage, así la sesión sobrevive a
     recargas y a cerrar el navegador (hasta que expire).
   - Inactividad en la aplicación: si el usuario no interactúa durante session_idle_seconds
     (lo define la API) se cierra la sesión; un minuto antes aparece un aviso. La última actividad
     se comparte entre pestañas.
   - Inactividad del token: mientras el usuario está activo se llama a /auth/me como máximo una vez
     por minuto para renovar el token en la API; si la API responde 401 (expiró o se inició sesión
     en otro navegador) se cierra la sesión local.
   - login.html: iniciar sesión, crear cuenta, "Olvidé mi contraseña" y restablecerla (#reset=<token>). */
(function () {
  "use strict";

  var API = (window.APP_CONFIG && window.APP_CONFIG.API_URL) || "http://localhost:8000";

  var SESSION_KEY = "datara-session";
  var ACTIVITY_KEY = "datara-last-activity";
  var RESET_KEY = "datara-reset-token";
  var WARN_BEFORE_MS = 60 * 1000;   // aviso antes de cerrar por inactividad
  var PING_GAP_MS = 60 * 1000;      // renovación del token como máximo cada minuto
  var CHECK_EVERY_MS = 5 * 1000;
  var ACTIVITY_WRITE_GAP_MS = 5 * 1000;

  /* ---------- Almacenamiento (con respaldo en memoria si localStorage no está disponible) ---------- */
  var memory = {};
  function read(store, key) {
    try { return window[store].getItem(key); } catch (e) { return memory[store + key] || null; }
  }
  function write(store, key, value) {
    try {
      if (value == null) window[store].removeItem(key); else window[store].setItem(key, value);
    } catch (e) {
      if (value == null) delete memory[store + key]; else memory[store + key] = value;
    }
  }

  function getSession() {
    try { return JSON.parse(read("localStorage", SESSION_KEY)) || null; } catch (e) { return null; }
  }
  function setSession(session) {
    write("localStorage", SESSION_KEY, session ? JSON.stringify(session) : null);
  }
  function lastActivity() { return Number(read("localStorage", ACTIVITY_KEY)) || 0; }
  function markActivity() { write("localStorage", ACTIVITY_KEY, String(Date.now())); }

  /* ---------- API ---------- */
  function call(method, path, body, token) {
    var headers = {};
    if (body) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = "Bearer " + token;
    return fetch(API + path, { method: method, headers: headers, body: body ? JSON.stringify(body) : undefined })
      .catch(function () {
        var err = new Error("No se pudo conectar con el servidor. Comprueba que la API esté en marcha.");
        err.status = 0;
        throw err;
      })
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) {
          if (!res.ok) {
            // FastAPI: "detail" es texto en los errores propios y una lista en los de validación
            var detail = data && data.detail;
            var err = new Error(typeof detail === "string" ? detail : "Revisa los datos del formulario.");
            err.status = res.status;
            throw err;
          }
          return data;
        });
      });
  }

  function startSession(data) {
    setSession({
      token: data.token,
      user: data.user,
      tokenIdle: data.token_idle_seconds,
      sessionIdle: data.session_idle_seconds
    });
    markActivity();
    lastPing = Date.now();
    renderAccount();
  }

  function login(email, password, force) {
    return call("POST", "/auth/login", { email: email, password: password, force: !!force }).then(startSession);
  }

  function register(name, email, password) {
    return call("POST", "/auth/register", { name: name, email: email, password: password });
  }

  // Cierra la sesión local; con notifyServer también la invalida en la API (si falla, expira sola)
  function endSession(message, notifyServer) {
    var session = getSession();
    setSession(null);
    write("localStorage", ACTIVITY_KEY, null);
    if (notifyServer && session) call("POST", "/auth/logout", null, session.token).catch(function () {});
    hideWarning();
    renderAccount();
    window.dispatchEvent(new Event("datara-auth-change"));
    if (message) toast(message);
  }

  /* ---------- Contraseña: mismas reglas que la API ---------- */
  var PASSWORD_RULES = [
    { id: "length", text: "Mínimo 8 caracteres", test: function (p) { return p.length >= 8; } },
    { id: "number", text: "Un número", test: function (p) { return /[0-9]/.test(p); } },
    { id: "upper", text: "Una letra mayúscula", test: function (p) { return /[A-ZÁÉÍÓÚÑÜ]/.test(p); } },
    { id: "special", text: "Un carácter especial (!@#$…)",
      test: function (p) { return /[^A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü\s]/.test(p); } }
  ];
  function passwordOk(p) {
    return p.length <= 128 && PASSWORD_RULES.every(function (r) { return r.test(p); });
  }

  /* ---------- Inactividad y renovación del token ---------- */
  var lastPing = 0;
  var lastActivityWrite = 0;

  function ping() {
    var session = getSession();
    if (!session) return;
    lastPing = Date.now();
    call("GET", "/auth/me", null, session.token).then(function (data) {
      var current = getSession();
      if (!current || current.token !== session.token) return;
      current.user = data.user;
      current.tokenIdle = data.token_idle_seconds;
      current.sessionIdle = data.session_idle_seconds;
      setSession(current);
      renderAccount();
    }).catch(function (err) {
      // Solo un 401 cierra la sesión; un fallo de red no
      if (err.status === 401) endSession(err.message, false);
    });
  }

  function onActivity() {
    if (!getSession()) return;
    var now = Date.now();
    if (now - lastActivityWrite > ACTIVITY_WRITE_GAP_MS) {
      lastActivityWrite = now;
      markActivity();
      hideWarning();
    }
    if (now - lastPing > PING_GAP_MS) ping();
  }

  function checkIdle() {
    var session = getSession();
    if (!session) { hideWarning(); return; }
    var limit = (session.sessionIdle || 900) * 1000;
    var idle = Date.now() - lastActivity();
    if (idle >= limit) {
      endSession("Tu sesión se cerró por inactividad.", true);
    } else if (idle >= limit - WARN_BEFORE_MS) {
      showWarning(Math.ceil((limit - idle) / 1000));
    } else {
      hideWarning();
    }
  }

  /* ---------- Avisos ---------- */
  var warningEl = null;
  function showWarning(seconds) {
    if (!warningEl) {
      warningEl = document.createElement("div");
      warningEl.className = "idle-warning";
      warningEl.setAttribute("role", "alertdialog");
      warningEl.setAttribute("aria-live", "assertive");
      warningEl.innerHTML = '<p class="idle-warning__text"></p>' +
        '<button class="btn btn--primary" type="button">Seguir conectado</button>';
      warningEl.querySelector("button").addEventListener("click", function () {
        lastActivityWrite = 0;
        lastPing = 0;
        onActivity();
      });
      document.body.appendChild(warningEl);
    }
    warningEl.querySelector(".idle-warning__text").textContent =
      "Tu sesión se cerrará por inactividad en " + seconds + " s.";
    warningEl.hidden = false;
  }
  function hideWarning() { if (warningEl) warningEl.hidden = true; }

  var toastTimer = null;
  function toast(message) {
    var el = document.getElementById("authToast");
    if (!el) {
      el = document.createElement("div");
      el.id = "authToast";
      el.className = "toast";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 6000);
  }

  /* ---------- Encabezado: botón "Iniciar sesión" o menú de la cuenta ---------- */
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function initials(name) {
    return String(name || "?").trim().split(/\s+/).slice(0, 2)
      .map(function (w) { return w.charAt(0).toUpperCase(); }).join("") || "?";
  }

  function currentPage() {
    var page = location.pathname.split("/").pop() || "index.html";
    return page + location.search;
  }

  function renderAccount() {
    var slot = document.getElementById("account");
    if (!slot) return;
    var session = getSession();

    if (!session) {
      var onLogin = /login\.html$/.test(location.pathname);
      slot.innerHTML = onLogin ? "" :
        '<a class="btn btn--outline btn--sm account__login" href="login.html?next=' + encodeURIComponent(currentPage()) +
        '" aria-label="Iniciar sesión">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>' +
        '<span class="account__label">Iniciar sesión</span></a>';
      return;
    }

    var user = session.user || {};
    slot.innerHTML =
      '<button class="avatar avatar--btn" type="button" aria-haspopup="true" aria-expanded="false" ' +
        'aria-controls="accountMenu" aria-label="Tu cuenta: ' + esc(user.name) + '">' + esc(initials(user.name)) + "</button>" +
      '<div class="account-menu" id="accountMenu" hidden>' +
        '<div class="account-menu__who"><strong>' + esc(user.name) + "</strong><span>" + esc(user.email) + "</span></div>" +
        '<button class="account-menu__item js-logout" type="button">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l-5-5 5-5M5 12h11"/></svg>' +
          "Cerrar sesión</button>" +
      "</div>";
  }

  function setMenu(open) {
    var btn = document.querySelector("#account .avatar--btn");
    var menu = document.getElementById("accountMenu");
    if (!btn || !menu) return;
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("#account .avatar--btn")) {
      var menu = document.getElementById("accountMenu");
      setMenu(menu && menu.hidden);
      return;
    }
    if (event.target.closest(".js-logout")) {
      endSession("Cerraste sesión.", true);
      return;
    }
    if (!event.target.closest("#accountMenu")) setMenu(false);
  });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") setMenu(false); });

  // Otra pestaña inició o cerró la sesión
  window.addEventListener("storage", function (event) {
    if (event.key === SESSION_KEY) { renderAccount(); hideWarning(); }
  });

  /* ---------- Arranque en cada página ---------- */
  ["pointerdown", "keydown", "scroll", "touchstart", "mousemove"].forEach(function (type) {
    window.addEventListener(type, onActivity, { passive: true });
  });

  renderAccount();
  if (getSession()) {
    checkIdle();          // cierra si se superó la inactividad mientras la página estaba cerrada
    if (getSession()) ping();
  }
  setInterval(checkIdle, CHECK_EVERY_MS);

  /* =========================================================
     login.html
     ========================================================= */
  var card = document.getElementById("authCard");
  if (card) initLoginPage();

  function initLoginPage() {
    var alertEl = document.getElementById("authAlert");
    var views = card.querySelectorAll("[data-view]");
    var params = new URLSearchParams(location.search);
    var resetToken = read("sessionStorage", RESET_KEY);

    var TITLES = {
      login: "Iniciar sesión", register: "Crear cuenta", forgot: "Recuperar contraseña",
      reset: "Nueva contraseña", signed: "Tu cuenta"
    };

    // Solo se vuelve a páginas del propio sitio (evita redirecciones abiertas)
    function nextUrl() {
      var next = params.get("next") || "";
      return /^[\w-]+\.html([?#][^\s]*)?$/.test(next) && !/^login\.html/.test(next) ? next : "index.html";
    }

    function showAlert(kind, html) {
      alertEl.className = "alert alert--" + kind;
      alertEl.innerHTML = html;
      alertEl.hidden = false;
    }
    function clearAlert() { alertEl.hidden = true; alertEl.innerHTML = ""; }

    function showView(name) {
      views.forEach(function (v) { v.hidden = v.dataset.view !== name; });
      document.title = "DATARA · " + TITLES[name];
      if (name === "signed") {
        var user = (getSession() || {}).user || {};
        document.getElementById("signedName").textContent = user.name || "";
        document.getElementById("signedEmail").textContent = user.email || "";
        document.getElementById("signedContinue").href = nextUrl();
      }
      var first = card.querySelector('[data-view="' + name + '"] input');
      if (first) first.focus();
    }

    function route() {
      clearAlert();
      var hash = location.hash.slice(1);
      if (hash.indexOf("reset=") === 0) {
        // El token sale de la URL y del historial en cuanto se lee
        resetToken = decodeURIComponent(hash.slice(6));
        write("sessionStorage", RESET_KEY, resetToken);
        history.replaceState(null, "", location.pathname + location.search + "#restablecer");
        hash = "restablecer";
      }
      if (hash === "restablecer" && resetToken) return showView("reset");
      if (getSession()) return showView("signed");
      if (hash === "registro") return showView("register");
      if (hash === "recuperar") return showView("forgot");
      showView("login");
    }
    window.addEventListener("hashchange", route);
    window.addEventListener("datara-auth-change", route);
    window.addEventListener("storage", function (event) { if (event.key === SESSION_KEY) route(); });

    // Mostrar u ocultar contraseña
    card.addEventListener("click", function (event) {
      var toggle = event.target.closest(".js-reveal");
      if (!toggle) return;
      var input = toggle.parentNode.querySelector("input");
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      toggle.setAttribute("aria-pressed", String(show));
      toggle.setAttribute("aria-label", show ? "Ocultar contraseña" : "Mostrar contraseña");
    });

    // Lista de requisitos en vivo bajo cada campo de contraseña nueva
    card.querySelectorAll(".pw-rules").forEach(function (list) {
      var input = document.getElementById(list.dataset.for);
      list.innerHTML = PASSWORD_RULES.map(function (r) {
        return '<li data-rule="' + r.id + '">' + esc(r.text) + "</li>";
      }).join("");
      input.addEventListener("input", function () {
        PASSWORD_RULES.forEach(function (r) {
          list.querySelector('[data-rule="' + r.id + '"]').classList.toggle("is-ok", r.test(input.value));
        });
      });
    });

    function busy(form, on) {
      var btn = form.querySelector('button[type="submit"]');
      btn.disabled = on;
      btn.classList.toggle("is-busy", on);
    }

    function newPasswordProblem(password, confirm) {
      if (!passwordOk(password)) return "La contraseña no cumple los requisitos.";
      if (password !== confirm) return "Las contraseñas no coinciden.";
      return "";
    }

    // Iniciar sesión
    var loginForm = document.getElementById("loginForm");
    function submitLogin(force) {
      var email = loginForm.email.value.trim();
      var password = loginForm.password.value;
      clearAlert();
      busy(loginForm, true);
      login(email, password, force).then(function () {
        location.href = nextUrl();
      }).catch(function (err) {
        busy(loginForm, false);
        if (err.status === 409) {
          showAlert("warning", "<p>" + esc(err.message) + "</p>" +
            '<button class="btn btn--primary btn--sm js-force" type="button">Cerrar la otra sesión e ingresar aquí</button>');
        } else if (err.status === 423) {
          showAlert("error", "<p>" + esc(err.message) + '</p><a href="#recuperar">Restablecer mi contraseña</a>');
        } else {
          showAlert("error", "<p>" + esc(err.message) + "</p>");
          loginForm.password.select();
        }
      });
    }
    loginForm.addEventListener("submit", function (event) { event.preventDefault(); submitLogin(false); });
    alertEl.addEventListener("click", function (event) {
      if (event.target.closest(".js-force")) submitLogin(true);
    });

    // Crear cuenta (y entrar directamente)
    var registerForm = document.getElementById("registerForm");
    registerForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var name = registerForm.name.value.trim();
      var email = registerForm.email.value.trim();
      var password = registerForm.password.value;
      var problem = name.length < 2 ? "Escribe tu nombre." : newPasswordProblem(password, registerForm.confirm.value);
      if (problem) return showAlert("error", "<p>" + esc(problem) + "</p>");

      clearAlert();
      busy(registerForm, true);
      register(name, email, password).then(function () {
        return login(email, password, false);
      }).then(function () {
        location.href = nextUrl();
      }).catch(function (err) {
        busy(registerForm, false);
        showAlert("error", "<p>" + esc(err.message) + "</p>" +
          (err.status === 409 ? '<a href="#">Iniciar sesión</a> · <a href="#recuperar">Olvidé mi contraseña</a>' : ""));
      });
    });

    // Olvidé mi contraseña
    var forgotForm = document.getElementById("forgotForm");
    forgotForm.addEventListener("submit", function (event) {
      event.preventDefault();
      clearAlert();
      busy(forgotForm, true);
      call("POST", "/auth/forgot-password", { email: forgotForm.email.value.trim() }).then(function (data) {
        showAlert("success", "<p>" + esc(data.message) + " Revisa también la carpeta de spam.</p>");
        forgotForm.reset();
      }).catch(function (err) {
        showAlert("error", "<p>" + esc(err.message) + "</p>");
      }).then(function () { busy(forgotForm, false); });
    });

    // Restablecer con el enlace del correo
    var resetForm = document.getElementById("resetForm");
    resetForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var password = resetForm.password.value;
      var problem = newPasswordProblem(password, resetForm.confirm.value);
      if (problem) return showAlert("error", "<p>" + esc(problem) + "</p>");

      clearAlert();
      busy(resetForm, true);
      call("POST", "/auth/reset-password", { token: resetToken, password: password }).then(function (data) {
        resetToken = null;
        write("sessionStorage", RESET_KEY, null);
        resetForm.reset();
        busy(resetForm, false);
        // La API cerró cualquier sesión abierta de la cuenta
        if (getSession()) endSession(null, false);
        history.replaceState(null, "", location.pathname + location.search);
        route();
        showAlert("success", "<p>" + esc(data.message) + "</p>");
      }).catch(function (err) {
        busy(resetForm, false);
        showAlert("error", "<p>" + esc(err.message) + "</p>" +
          (err.status === 400 ? '<a href="#recuperar">Solicitar un enlace nuevo</a>' : ""));
      });
    });

    route();
  }
})();
