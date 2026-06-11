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
        btn.addEventListener("click", function() {
            var group = btn.closest(".sidebar-nav-group");
            if (!group) return;
            var willOpen = !group.classList.contains("is-open");
            group.classList.toggle("is-open", willOpen);
            btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
        });
    });

    // 3. Auto-disparar modal de notificaciones si viene en la URL
    // (Esto reemplaza el script inline del final de tu base.html)
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('notification_id')) {
        // Asumiendo que usas jQuery y Bootstrap 4 por tus librerías
        if (typeof $ !== 'undefined') {
            $('#approveNotificationModal').modal('show');
        }
    }
});