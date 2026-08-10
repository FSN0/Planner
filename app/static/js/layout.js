document.addEventListener("DOMContentLoaded", function() {
    
    // 1. Manejo del Preloader
    setTimeout(function() {
        document.body.classList.remove('preload');
    }, 100);

    // 2. Lógica del Sidebar (Menú lateral)
    var toggle = document.getElementById("sidebar-toggle");
    
    // Intentamos buscar el shell, si no existe usamos body o documentElement como fallback
    // Ajusta '.admin-shell' si tu contenedor principal tiene otro nombre
    var shell = document.querySelector(".admin-shell") || document.body; 
    
    if (toggle) {
        toggle.addEventListener("click", function() {
            document.documentElement.classList.toggle("sidebar-collapsed");
            var isCollapsed = document.documentElement.classList.contains("sidebar-collapsed");
            localStorage.setItem("sidebarCollapsed", isCollapsed ? "1" : "0");
        });
    }

    document.querySelectorAll("[data-sidebar-subtoggle]").forEach(function(btn) {
        btn.addEventListener("click", function(ev) {
            if (document.documentElement.classList.contains("sidebar-config-mode")) {
                ev.preventDefault();
                return;
            }
            var group = btn.closest(".sidebar-nav-group");
            if (!group) return;
            var willOpen = !group.classList.contains("is-open");
            group.classList.toggle("is-open", willOpen);
            btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
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
                    alert((res.j && res.j.message) || "No se pudo guardar el menú");
                    return;
                }
                if (cb) cb();
            })
            .catch(function () {
                saving = false;
                alert("Error de red al guardar el menú");
            });
    }

    function bindSortables() {
        if (typeof $ === "undefined" || !$.fn.sortable) return;
        destroySortables();
        $("#sidebar-sections").sortable({
            handle: ".sidebar-sec-handle",
            axis: "y",
            tolerance: "pointer",
            placeholder: "sidebar-section-placeholder",
            forcePlaceholderSize: true,
        });
        $("#sidebar-sections .sidebar-nav").sortable({
            connectWith: "#sidebar-sections .sidebar-nav",
            handle: ".sidebar-item-handle",
            axis: "y",
            tolerance: "pointer",
            placeholder: "sidebar-item-placeholder",
            forcePlaceholderSize: true,
            receive: function () {
                // ok
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
                '<input type="text" class="sidebar-section-title-input" value="Nueva sección" maxlength="60">' +
                '<div class="sidebar-section-title">Nueva sección</div>' +
                '<button type="button" class="sidebar-sec-remove" title="Eliminar sección"><i class="fas fa-trash-alt"></i></button>' +
                "</div>" +
                '<ul class="sidebar-nav" data-section-items="' + id + '"></ul>';
            sectionsRoot.appendChild(wrap);
            bindSortables();
            syncTitleInputs();
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
                alert("Mueve o vacía las entradas antes de eliminar la sección.");
                return;
            }
            sec.remove();
            return;
        }
        // En modo config, no navegar
        if (document.documentElement.classList.contains("sidebar-config-mode")) {
            var link = ev.target.closest("a.sidebar-link");
            if (link) {
                ev.preventDefault();
            }
        }
    });
}
