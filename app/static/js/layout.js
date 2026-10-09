var t = window.SP_T || function (key) { return key; };

document.addEventListener("DOMContentLoaded", function() {
    
    // 1. Manejo del Preloader
    setTimeout(function() {
        document.body.classList.remove('preload');
    }, 100);

    // 1b. Indicador de navegación (sidebar / enlaces internos): feedback inmediato
    initPageNavLoading();

    // 2. Lógica del Sidebar (Menú lateral + cajón en móvil)
    var toggle = document.getElementById("sidebar-toggle");
    var navOpen = document.getElementById("admin-nav-open");
    var navClose = document.getElementById("sidebar-close-mobile");
    var navBackdrop = document.getElementById("admin-nav-backdrop");
    var sidebar = document.getElementById("admin-sidebar");

    function isMobileNav() {
        return window.matchMedia("(max-width: 960px)").matches;
    }

    function setMobileNav(open) {
        document.documentElement.classList.toggle("sidebar-open", !!open);
        if (navOpen) navOpen.setAttribute("aria-expanded", open ? "true" : "false");
        if (navBackdrop) navBackdrop.hidden = !open;
        if (open && typeof window.jQuery !== "undefined") {
            try { window.jQuery(".select2-hidden-accessible").select2("close"); } catch (e) {}
            try { window.jQuery(".dropdown-menu.show").removeClass("show"); } catch (e2) {}
            try { window.jQuery(".dropdown.show").removeClass("show"); } catch (e3) {}
        }
    }

    function closeMobileNav() { setMobileNav(false); }

    if (toggle) {
        toggle.addEventListener("click", function() {
            if (isMobileNav()) {
                closeMobileNav();
                return;
            }
            document.documentElement.classList.toggle("sidebar-collapsed");
            var isCollapsed = document.documentElement.classList.contains("sidebar-collapsed");
            localStorage.setItem("sidebarCollapsed", isCollapsed ? "1" : "0");
        });
    }
    if (navOpen) {
        navOpen.addEventListener("click", function() {
            setMobileNav(!document.documentElement.classList.contains("sidebar-open"));
        });
    }
    if (navClose) navClose.addEventListener("click", closeMobileNav);
    if (navBackdrop) navBackdrop.addEventListener("click", closeMobileNav);
    document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") closeMobileNav();
    });
    if (sidebar) {
        sidebar.addEventListener("click", function (ev) {
            var a = ev.target.closest("a.sidebar-link[href]");
            if (a && isMobileNav()) closeMobileNav();
        });
    }
    window.addEventListener("resize", function () {
        if (!isMobileNav()) closeMobileNav();
    });

    document.querySelectorAll("[data-sidebar-subtoggle]").forEach(function(btn) {
        btn.addEventListener("click", function(ev) {
            ev.preventDefault();
            ev.stopPropagation();
            if (document.documentElement.classList.contains("sidebar-config-mode")) {
                return;
            }
            var group = btn.closest(".sidebar-nav-group");
            if (!group) return;
            var willOpen = !group.classList.contains("is-open");
            group.classList.toggle("is-open", willOpen);
            btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
            // Evita el marco de foco del botón (raya blanca entre nombre y flecha).
            if (typeof btn.blur === "function") btn.blur();
        });
    });

    // 3. Auto-disparar modal de notificaciones si viene en la URL
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('notification_id')) {
        if (typeof $ !== 'undefined') {
            $('#approveNotificationModal').modal('show');
        }
    }

    // 4. Personalizar menú lateral
    initSidebarConfig();
});

function initPageNavLoading() {
    if (document.getElementById("sp-page-loading")) return;

    var bar = document.createElement("div");
    bar.id = "sp-page-loading";
    bar.className = "sp-page-loading";
    bar.setAttribute("hidden", "");
    bar.innerHTML =
        '<div class="sp-page-loading-bar" aria-hidden="true"></div>' +
        '<div class="sp-page-loading-card" role="status" aria-live="polite">' +
        '<div class="sp-page-loading-spinner" aria-hidden="true"></div>' +
        '<span class="sp-page-loading-text">' + t('Cargando…') + '</span>' +
        "</div>";
    document.body.appendChild(bar);

    function show(msg) {
        var text = bar.querySelector(".sp-page-loading-text");
        if (text && msg) text.textContent = msg;
        bar.removeAttribute("hidden");
        document.documentElement.classList.add("sp-nav-loading");
    }

    function hide() {
        bar.setAttribute("hidden", "");
        document.documentElement.classList.remove("sp-nav-loading");
    }

    window.SP_pageLoading = { show: show, hide: hide };

    document.addEventListener("click", function (ev) {
        if (document.documentElement.classList.contains("sidebar-config-mode")) return;
        var a = ev.target.closest("a[href]");
        if (!a) return;
        if (ev.defaultPrevented || ev.button !== 0) return;
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
        if (a.target && a.target !== "_self") return;
        // Descargas / PDF: no navegan la página → la barra se quedaría eterna.
        if (a.hasAttribute("download") || a.getAttribute("data-no-page-loading") != null) return;
        if (a.classList.contains("js-no-page-loading") || a.classList.contains("cert-banner-pdf")) return;
        var href = a.getAttribute("href") || "";
        if (!href || href.charAt(0) === "#" || href.indexOf("javascript:") === 0) return;
        if (/\/pdf(\/|$|\?)/i.test(href) || /\.pdf(\?|$)/i.test(href)) return;
        // Solo navegación misma origen / relativa
        if (/^https?:\/\//i.test(href) && href.indexOf(window.location.origin) !== 0) return;
        show(t("Cargando…"));
    }, true);

    window.addEventListener("pageshow", function () { hide(); });
}

function initSidebarConfig() {
    var configBtn = document.getElementById("sidebar-config-btn");
    var doneBtn = document.getElementById("sidebar-config-done");
    var addBtn = document.getElementById("sidebar-config-add");
    var bar = document.getElementById("sidebar-config-bar");
    var sectionsRoot = document.getElementById("sidebar-sections");
    if (!configBtn || !sectionsRoot) return;

    var saving = false;

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    function enterConfig() {
        // Si estaba colapsado, expandir para poder editar
        document.documentElement.classList.remove("sidebar-collapsed");
        document.documentElement.classList.add("sidebar-config-mode");
        configBtn.setAttribute("aria-pressed", "true");
        if (bar) bar.hidden = false;
        bindSortables();
        syncTitleInputs();
    }

    function leaveConfig(save) {
        if (save) {
            persistPrefs(function () {
                document.documentElement.classList.remove("sidebar-config-mode");
                configBtn.setAttribute("aria-pressed", "false");
                if (bar) bar.hidden = true;
                destroySortables();
                // Recargar para aplicar hidden/orden en plantilla limpia
                window.location.reload();
            });
            return;
        }
        document.documentElement.classList.remove("sidebar-config-mode");
        configBtn.setAttribute("aria-pressed", "false");
        if (bar) bar.hidden = true;
        destroySortables();
        window.location.reload();
    }

    function syncTitleInputs() {
        sectionsRoot.querySelectorAll(".sidebar-section").forEach(function (sec) {
            var input = sec.querySelector(".sidebar-section-title-input");
            var label = sec.querySelector(".sidebar-section-title");
            if (!input || !label || input.dataset.bound === "1") return;
            input.dataset.bound = "1";
            input.addEventListener("input", function () {
                label.textContent = input.value;
                label.classList.toggle("is-empty", !input.value.trim());
            });
        });
    }

    function collectPrefs() {
        var sections = [];
        var hidden = [];
        sectionsRoot.querySelectorAll(".sidebar-section").forEach(function (sec) {
            var sid = sec.getAttribute("data-section-id") || ("sec_" + Math.random().toString(36).slice(2, 10));
            var input = sec.querySelector(".sidebar-section-title-input");
            var title = input ? input.value : "";
            var items = [];
            sec.querySelectorAll(":scope > .sidebar-nav > li[data-nav-id]").forEach(function (li) {
                var id = li.getAttribute("data-nav-id");
                if (!id) return;
                items.push(id);
                if (li.getAttribute("data-nav-hidden") === "1") hidden.push(id);
            });
            sections.push({ id: sid, title: title, items: items });
        });
        return { sections: sections, hidden: hidden };
    }

    function persistPrefs(cb) {
        if (saving) return;
        saving = true;
        var payload = collectPrefs();
        fetch("/api/v6/sidebar_prefs", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrfToken(),
            },
            body: JSON.stringify(payload),
            credentials: "same-origin",
        })
            .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
            .then(function (res) {
                saving = false;
                if (!res.ok || !res.j.success) {
                    alert((res.j && res.j.message) || t("No se pudo guardar el menú"));
                    return;
                }
                if (cb) cb();
            })
            .catch(function () {
                saving = false;
                alert(t("Error de red al guardar el menú"));
            });
    }

    function markEmptyNavs() {
        sectionsRoot.querySelectorAll(".sidebar-section").forEach(function (sec) {
            var nav = sec.querySelector(":scope > .sidebar-nav");
            if (!nav) return;
            var hasItem = !!nav.querySelector(":scope > li[data-nav-id]");
            sec.classList.toggle("is-nav-empty", !hasItem);
            nav.classList.toggle("is-empty-nav", !hasItem);
        });
    }

    function bindSortables() {
        if (typeof $ === "undefined" || !$.fn.sortable) return;
        destroySortables();
        markEmptyNavs();
        $("#sidebar-sections").sortable({
            handle: ".sidebar-sec-handle",
            axis: "y",
            tolerance: "pointer",
            placeholder: "sidebar-section-placeholder",
            forcePlaceholderSize: true,
        });
        // Sin axis:y — facilita soltar en listas vacías / otras secciones.
        // dropOnEmpty + min-height CSS: las .sidebar-nav vacías deben poder recibir.
        $("#sidebar-sections .sidebar-nav").sortable({
            connectWith: "#sidebar-sections .sidebar-nav",
            handle: ".sidebar-item-handle",
            tolerance: "pointer",
            dropOnEmpty: true,
            placeholder: "sidebar-item-placeholder",
            forcePlaceholderSize: true,
            receive: function () {
                markEmptyNavs();
            },
            remove: function () {
                markEmptyNavs();
            },
            stop: function () {
                markEmptyNavs();
                try {
                    $("#sidebar-sections .sidebar-nav").sortable("refresh");
                } catch (e) { /* ignore */ }
            },
        });
    }

    function destroySortables() {
        if (typeof $ === "undefined" || !$.fn.sortable) return;
        try { $("#sidebar-sections .sidebar-nav").sortable("destroy"); } catch (e) {}
        try { $("#sidebar-sections").sortable("destroy"); } catch (e) {}
    }

    configBtn.addEventListener("click", function () {
        if (document.documentElement.classList.contains("sidebar-config-mode")) {
            leaveConfig(true);
        } else {
            enterConfig();
        }
    });

    if (doneBtn) {
        doneBtn.addEventListener("click", function () {
            leaveConfig(true);
        });
    }

    if (addBtn) {
        addBtn.addEventListener("click", function () {
            var id = "sec_" + Math.random().toString(36).slice(2, 10);
            var wrap = document.createElement("div");
            wrap.className = "sidebar-section";
            wrap.setAttribute("data-section-id", id);
            wrap.innerHTML =
                '<div class="sidebar-section-head">' +
                '<span class="sidebar-sec-handle" aria-hidden="true"><i class="fas fa-grip-vertical"></i></span>' +
                '<input type="text" class="sidebar-section-title-input" value="' + t("Nueva sección") + '" maxlength="60">' +
                '<div class="sidebar-section-title">' + t("Nueva sección") + '</div>' +
                '<button type="button" class="sidebar-sec-remove" title="' + t("Eliminar sección") + '"><i class="fas fa-trash-alt"></i></button>' +
                "</div>" +
                '<ul class="sidebar-nav" data-section-items="' + id + '"></ul>';
            sectionsRoot.appendChild(wrap);
            bindSortables();
            syncTitleInputs();
            markEmptyNavs();
        });
    }

    sectionsRoot.addEventListener("click", function (ev) {
        var visBtn = ev.target.closest(".sidebar-item-visibility");
        if (visBtn) {
            ev.preventDefault();
            var li = visBtn.closest("li[data-nav-id]");
            if (!li) return;
            var hidden = li.getAttribute("data-nav-hidden") === "1";
            li.setAttribute("data-nav-hidden", hidden ? "0" : "1");
            li.classList.toggle("is-nav-hidden", !hidden);
            var icon = visBtn.querySelector("i");
            if (icon) {
                icon.className = "fas " + (!hidden ? "fa-eye-slash" : "fa-eye");
            }
            return;
        }
        var remBtn = ev.target.closest(".sidebar-sec-remove");
        if (remBtn) {
            ev.preventDefault();
            var sec = remBtn.closest(".sidebar-section");
            if (!sec) return;
            var items = sec.querySelectorAll(":scope > .sidebar-nav > li[data-nav-id]");
            if (items.length) {
                alert(t("Mueve o vacía las entradas antes de eliminar la sección."));
                return;
            }
            sec.remove();
            return;
        }
        // En modo config, no navegar
        if (document.documentElement.classList.contains("sidebar-config-mode")) {
            var link = ev.target.closest("a.sidebar-link, a.sidebar-parent-main");
            if (link) {
                ev.preventDefault();
            }
        }
    });
}
