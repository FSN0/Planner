/**
 * Guía interactiva SignaPlan — capítulos trabajadores + obra.
 * Estado en sessionStorage; se puede saltar en cualquier momento.
 */
(function (window, document) {
  'use strict';

  var STORAGE_KEY = 'signaplan_tour_v1';
  var PAD = 8;

  function loadState() {
    try {
      return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
    } catch (e) {
      return null;
    }
  }

  function saveState(state) {
    if (!state) {
      sessionStorage.removeItem(STORAGE_KEY);
      return;
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function pathIs(re) {
    return re.test(window.location.pathname || '');
  }

  function csrfToken() {
    var meta = qs('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function setFichaje(activo) {
    if (window.SP_pageLoading) {
      window.SP_pageLoading.show(activo ? 'Activando fichaje…' : 'Guardando…');
    }
    return fetch('/admin/api/tour/fichaje', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
      },
      body: JSON.stringify({ activo: !!activo }),
      credentials: 'same-origin',
    })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .finally(function () {
        // run() puede navegar después; si no, quitamos el overlay
        if (window.SP_pageLoading) window.SP_pageLoading.hide();
      });
  }

  function resolveWantFichaje(chapter, opts) {
    opts = opts || {};
    if (opts.wantFichaje === true || opts.wantFichaje === false) {
      return opts.wantFichaje;
    }
    var prev = loadState() || {};
    if (prev.wantFichaje === true || prev.wantFichaje === false) {
      return prev.wantFichaje;
    }
    if (window.__ONB_FICHAJE_ASKED__) {
      return !!window.__ONB_FICHAJE_ACTIVO__;
    }
    if (chapter === 'fichaje') return true;
    return null;
  }

  function hubReturnUrl(chapter) {
    var id = chapter ? academiaIdForChapter(chapter) : null;
    if (id && id !== 'seed' && id !== 'demo' && id !== 'import') {
      return '/admin/primeros-pasos?focus=tour&id=' + encodeURIComponent(id);
    }
    if (id === 'seed' || chapter === 'trabajadores' || chapter === 'obra' || chapter === 'fichaje') {
      return '/admin/primeros-pasos?focus=guide&done=seed';
    }
    return '/admin/primeros-pasos?focus=next';
  }

  function goHubAfterGuide(message) {
    teardown();
    saveState(null);
    try {
      sessionStorage.setItem(
        'signaplan_tour_flash',
        message || 'Tutorial guiado completado. Abajo ya puedes ver el resto de guías.'
      );
    } catch (e) { /* ignore */ }
    window.location.href = '/admin/primeros-pasos?focus=guide&done=seed';
  }

  function finishGuideToHub(message) {
    // Esperar al POST: si redirigimos al momento, el navegador cancela el fetch
    // y el tic de «Tutorial guiado» no se guarda. Tope 2.5s por si la red falla.
    var done = false;
    function go() {
      if (done) return;
      done = true;
      goHubAfterGuide(message);
    }
    markAcademiaDone('seed').then(go, go);
    setTimeout(go, 2500);
  }

  function finishSoloAndReturn(message) {
    var st = loadState() || {};
    var chapter = st.chapter || '';
    var href = st.returnTo || hubReturnUrl(chapter);
    var done = false;
    function go() {
      if (done) return;
      done = true;
      teardown();
      saveState(null);
      if (message) {
        try {
          sessionStorage.setItem('signaplan_tour_flash', message);
        } catch (e) { /* ignore */ }
      }
      window.location.href = href;
    }
    markAcademiaDone(chapter).then(go, go);
    setTimeout(go, 2500);
  }

  function ensureTourTargetVisible(selector) {
    if (!selector) return null;
    var el = qs(selector);
    if (!el) return null;
    var li = el.closest('li');
    if (li && li.classList.contains('is-nav-hidden')) {
      li.classList.remove('is-nav-hidden');
      li.setAttribute('data-tour-forced-visible', '1');
    }
    var section = el.closest('.sidebar-section');
    if (section) {
      section.classList.remove('is-section-all-hidden');
      section.setAttribute('data-tour-forced-visible', '1');
    }
    var group = el.closest('.sidebar-nav-group');
    if (group) group.classList.add('is-open');
    document.documentElement.classList.remove('sidebar-collapsed');
    return el;
  }

  var NAV_FALLBACK_HREF = {
    '[data-tour="nav-trabajadores"]': '/admin/personal',
    '[data-tour="nav-directorio"]': '/admin/obras',
    '[data-tour="nav-empresas"]': '/admin/companies',
    '[data-tour="nav-vehiculos"]': '/admin/vehiculos',
    '[data-tour="nav-coches-libres"]': '/admin/vehiculos/libres',
    '[data-tour="nav-auditoria-fichajes"]': '/sync/auditoria',
  };

  function hasDemoBanner() {
    try {
      return !!document.querySelector('[data-demo-banner]');
    } catch (e) {
      return false;
    }
  }

  function tourFromDemo() {
    var st = loadState() || {};
    if (st.fromDemo != null) return !!st.fromDemo;
    return hasDemoBanner();
  }

  function isSeedGuideState(st) {
    st = st || loadState() || {};
    if (st.fromGuide) return true;
    var ch = st.chapter || '';
    var step = st.step || 0;
    // Recuperar guía rota si alguien metió mode=solo en la URL a mitad del fichaje
    if (st.mode === 'solo') {
      if (ch === 'fichaje' && step >= 7) return true;
      if (ch === 'obra' && step >= 5) return true;
      if (ch === 'flota' && st.fleetAsked) return true;
      return false;
    }
    return ch === 'trabajadores' || ch === 'obra' || ch === 'fichaje' ||
      (ch === 'flota' && !!st.fleetAsked);
  }

  function startTour(chapter, opts) {
    opts = opts || {};
    var ch = chapter || 'trabajadores';
    var want = resolveWantFichaje(ch, opts);
    var mode = opts.mode || 'full';
    var fromGuide = !!opts.fromGuide;
    if (!fromGuide && mode !== 'solo' &&
        (ch === 'trabajadores' || ch === 'obra' || ch === 'fichaje')) {
      fromGuide = true;
    }
    saveState({
      active: true,
      chapter: ch,
      step: typeof opts.step === 'number' ? opts.step : 0,
      mode: mode,
      fromGuide: fromGuide,
      returnTo: opts.returnTo || hubReturnUrl(ch),
      createdDni: opts.keepCreds ? ((loadState() || {}).createdDni || null) : null,
      createdPin: opts.keepCreds ? ((loadState() || {}).createdPin || null) : null,
      createdObraNombre: opts.keepCreds ? ((loadState() || {}).createdObraNombre || null) : null,
      wantFichaje: want,
      fromDemo: opts.fromDemo != null ? !!opts.fromDemo : hasDemoBanner(),
      fleetAsked: !!opts.fleetAsked,
      fleetDecided: !!opts.fleetDecided,
    });
    document.body.classList.add('sp-tour-active');
    // Import se queda en el hub (modal de elección).
    // Demo: ya no arranca exploración; el hub muestra "ya tienes material".
    if (ch === 'demo' && pathIs(/\/admin\/primeros-pasos/)) {
      return;
    }
    // Capítulos cortos: si el ancla del menú no está, ir directo a la URL
    if (ch === 'trabajadores' && !pathIs(/\/admin\/personal/) && !pathIs(/\/admin\/create_user/)) {
      // run() iluminará el menú; ensureTourTargetVisible lo destapa
    }
    run();
  }

  function postOnboardingDone(redirectHref) {
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = '/admin/primeros-pasos';
    form.style.display = 'none';
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var token = csrf ? csrf.getAttribute('content') : '';
    [['csrf_token', token], ['accion', 'listo']].forEach(function (pair) {
      var inp = document.createElement('input');
      inp.type = 'hidden';
      inp.name = pair[0];
      inp.value = pair[1] || '';
      form.appendChild(inp);
    });
    document.body.appendChild(form);
    if (redirectHref) {
      // listo ya redirige al tablero; ignoramos redirectHref extra
    }
    form.submit();
  }

  function stopTour(opts) {
    opts = opts || {};
    teardown();
    saveState(null);
    if (opts.message) showDoneCard(opts.message);
  }

  function askFleetOrPause() {
    var st = loadState() || {};
    // Solo los tutoriales cortos sueltos del hub saltan la pregunta de flota
    if (st.mode === 'solo' && !isSeedGuideState(st)) {
      finishSoloAndReturn();
      return;
    }
    if (st.fleetDecided) {
      finishGuideToHub();
      return;
    }
    if (st.fleetPromptOpen) {
      // Reponer el modal si se perdió al navegar
      st.fleetPromptOpen = false;
      saveState(st);
    }

    st.fleetPromptOpen = true;
    st.pendingComplete = false;
    st.fromGuide = true;
    st.mode = 'full';
    saveState(st);
    ensureUi();
    clearTargets();
    placeHole(null);
    ui.card.classList.add('is-modal');
    ui.card.style.transform = 'translateX(-50%)';
    ui.card.style.top = '28%';
    ui.card.style.left = '50%';
    ui.card.style.zIndex = '20050';
    ui.card.style.display = '';
    ui.card.innerHTML =
      '<div class="sp-tour-progress">Tutorial guiado · flota</div>' +
      '<h3>¿Vais a usar vehículos?</h3>' +
      '<p>Si sí, te enseñamos a dar de alta el primero. Si no, damos el tutorial guiado por terminado y volvemos a Primeros pasos.</p>' +
      '<div class="sp-tour-actions" style="flex-direction:column;align-items:stretch;">' +
      '<button type="button" class="sp-tour-primary" data-act="fleet-yes">Sí, crear un vehículo</button>' +
      '<button type="button" class="sp-tour-ghost" data-act="fleet-no">No, terminar tutorial</button>' +
      '</div>';
    ui.card.querySelector('[data-act="fleet-yes"]').onclick = function () {
      var prev = loadState() || {};
      saveState({
        active: true,
        chapter: 'flota',
        step: 0,
        mode: 'full',
        fromGuide: true,
        fleetAsked: true,
        fleetDecided: true,
        fleetPromptOpen: false,
        returnTo: '/admin/primeros-pasos?focus=guide&done=seed',
        wantFichaje: prev.wantFichaje,
        fromDemo: prev.fromDemo,
        createdDni: prev.createdDni,
        createdObraNombre: prev.createdObraNombre,
      });
      document.body.classList.add('sp-tour-active');
      run();
    };
    ui.card.querySelector('[data-act="fleet-no"]').onclick = function () {
      var prev = loadState() || {};
      prev.fleetDecided = true;
      prev.fleetPromptOpen = false;
      prev.fleetAsked = true;
      prev.fromGuide = true;
      saveState(prev);
      finishGuideToHub(
        'Tutorial guiado completado. Abajo verás el resto de guías cuando tengas material.'
      );
    };
  }

  function pauseAtChapterEnd() {
    var state = loadState();
    if (!state) return;
    var chapter = state.chapter || '';
    var didFichaje = !!state.wantFichaje;
    var mode = state.mode || 'full';
    var returnTo = state.returnTo || hubReturnUrl(chapter);
    var seedChapters = chapter === 'trabajadores' || chapter === 'obra' || chapter === 'fichaje' ||
      (chapter === 'flota' && !!state.fleetAsked);
    var seedGuide = isSeedGuideState(state) || (seedChapters && mode !== 'solo');

    // Paso suelto del hub (Repetir este paso): volver sin pregunta de flota
    if (mode === 'solo' && !state.fromGuide && !state.fleetAsked && !isSeedGuideState(state)) {
      markAcademiaDone(chapter);
      finishSoloAndReturn();
      return;
    }

    // Fin del recorrido guiado: SIEMPRE preguntar flota / volver al hub
    if (seedGuide || seedChapters) {
      if (!state.fleetDecided && chapter !== 'flota') {
        askFleetOrPause();
        return;
      }
      if (chapter === 'flota') {
        markAcademiaDone('flota');
      }
      finishGuideToHub(
        chapter === 'flota'
          ? 'Vehículo creado. Tutorial guiado completado.'
          : (didFichaje
            ? 'Tutorial guiado completado (persona, obra y fichaje). Abajo tienes el resto de guías.'
            : 'Tutorial guiado completado (persona y obra). Abajo tienes el resto de guías.')
      );
      return;
    }

    state.active = false;
    state.chapter = 'blocked';
    state.step = 0;
    state.pendingComplete = false;
    state.createdPin = null;
    saveState(state);
    teardown();

    markAcademiaDone(chapter);

    if (chapter === 'import' || chapter === 'demo') {
      ensureUi();
      clearTargets();
      placeHole(null);
      ui.card.classList.add('is-modal');
      ui.card.style.transform = 'translateX(-50%)';
      ui.card.style.top = '28%';
      ui.card.style.left = '50%';
      var msg = chapter === 'import'
        ? 'Importación guiada lista. Puedes seguir importando más listados o abrir la Academia.'
        : 'Ya conoces el mapa con datos de ejemplo. Explora libremente; el banner te deja borrarlos cuando quieras.';
      ui.card.innerHTML =
        '<h3>Guía terminada</h3><p>' + msg + '</p>' +
        '<div class="sp-tour-actions">' +
        '<button type="button" class="sp-tour-skip" data-act="hub">Ir a Academia</button>' +
        '<button type="button" class="sp-tour-primary" data-act="done">Ir al tablero</button></div>';
      ui.card.querySelector('[data-act="hub"]').onclick = function () {
        teardown();
        window.location.href = hubReturnUrl(chapter);
      };
      ui.card.querySelector('[data-act="done"]').onclick = function () {
        postOnboardingDone();
      };
      return;
    }

    if (isAcademiaChapter(chapter)) {
      if (mode === 'solo') {
        saveState(null);
        try {
          sessionStorage.setItem(
            'signaplan_tour_flash',
            'Tutorial completado. Lo siguiente está justo debajo.'
          );
        } catch (e) { /* ignore */ }
        window.location.href = returnTo || hubReturnUrl(chapter);
        return;
      }
      showDoneCard(
        'Tutorial completado. Puedes repetirlo o seguir con el siguiente desde la Academia.'
      );
      return;
    }

    showDoneCard(
      didFichaje
        ? 'Guía completada: alta, obra, fichaje de prueba y cómo resolver la pelota roja en auditoría. Sigue en la Academia.'
        : 'Hasta aquí la guía por ahora. Ya tienes trabajador y obra. ' +
          'Más adelante puedes activar fichaje en Configuración. Sigue en la Academia.'
    );
  }

  function isAcademiaChapter(ch) {
    return [
      'tablero_basico', 'planificador_multi', 'fichajes',
      'auditoria_fichajes', 'registro_jornada',
      'flota', 'coches_libres', 'auditoria_vehiculos',
    ].indexOf(ch) >= 0;
  }

  function academiaIdForChapter(ch) {
    if (ch === 'trabajadores' || ch === 'obra' || ch === 'fichaje') return 'seed';
    if (ch === 'import') return 'import';
    if (ch === 'demo') return 'demo';
    if (ch === 'auditoria_fichajes' || ch === 'registro_jornada') return 'fichajes';
    if (isAcademiaChapter(ch)) return ch;
    return null;
  }

  function markAcademiaDone(chapter) {
    var id = academiaIdForChapter(chapter);
    if (!id) return Promise.resolve(false);
    var meta = document.querySelector('meta[name="csrf-token"]');
    var token = meta ? meta.getAttribute('content') : '';
    return fetch('/admin/api/tour/' + encodeURIComponent(id) + '/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
      credentials: 'same-origin',
      keepalive: true,
      body: '{}',
    }).then(function (r) {
      return !!(r && r.ok);
    }).catch(function () {
      return false;
    });
  }

  function sectionSkipLabel(chapter) {
    if (chapter === 'trabajadores') return 'Saltar plantilla →';
    if (chapter === 'obra') return 'Saltar obras →';
    if (chapter === 'fichaje') return 'Saltar fichaje →';
    if (chapter === 'import') return 'Saltar importación →';
    if (chapter === 'demo') return 'Saltar exploración →';
    if (isAcademiaChapter(chapter)) return 'Saltar tutorial →';
    return 'Saltar sección →';
  }

  /**
   * Salta el capítulo actual entero (plantilla / obras / fichaje).
   * Útil si ya lo tienes hecho o para probar tramos posteriores.
   */
  function skipSection() {
    var st = loadState();
    if (!st || !st.active) return;

    var chapter = st.chapter || 'trabajadores';

    if (chapter === 'trabajadores') {
      saveState({
        active: true,
        chapter: 'obra',
        step: 0,
        wantFichaje: st.wantFichaje,
        createdDni: st.createdDni,
        createdPin: st.createdPin,
        createdObraNombre: st.createdObraNombre,
        createdWorkerName: st.createdWorkerName,
      });
      // Si estamos en una pantalla de alta/import, volver a un sitio cómodo
      if (pathIs(/\/admin\/create_user/) || pathIs(/\/admin\/import_users/) || pathIs(/\/admin\/personal/)) {
        window.location.href = '/admin/obras';
        return;
      }
      run();
      return;
    }

    if (chapter === 'obra') {
      if (st.wantFichaje) {
        saveState({
          active: true,
          chapter: 'fichaje',
          step: 0,
          wantFichaje: true,
          createdDni: st.createdDni,
          createdPin: st.createdPin,
          createdObraNombre: st.createdObraNombre,
          createdWorkerName: st.createdWorkerName,
        });
        if (pathIs(/\/admin\/create_obra/) || pathIs(/\/admin\/import_obras/)) {
          window.location.href = '/admin/obras_detailed';
          return;
        }
        run();
        return;
      }
      pauseAtChapterEnd();
      return;
    }

    if (chapter === 'fichaje') {
      // Si la guía está en /mi como operario, restaurar admin y cerrar
      if (isMiEntrar() || isMiFichar()) {
        st.active = false;
        st.chapter = 'blocked';
        saveState(st);
        window.location.href = '/mi/tour-volver-admin';
        return;
      }
      pauseAtChapterEnd();
      return;
    }

    if (chapter === 'import') {
      // Salir limpio: sin cartel encima ni pantalla a oscuras
      stopTour({});
      return;
    }

    if (chapter === 'demo') {
      pauseAtChapterEnd();
      return;
    }

    if (isAcademiaChapter(chapter)) {
      pauseAtChapterEnd();
      return;
    }

    pauseAtChapterEnd();
  }

  var ui = { backdrop: null, hole: null, card: null, banner: null };
  var holeTrack = { el: null, els: null, opts: null, cardEl: null };

  function teardown() {
    document.body.classList.remove('sp-tour-active');
    document.querySelectorAll('.sp-tour-target').forEach(function (el) {
      el.classList.remove('sp-tour-target');
    });
    hideTourBanner();
    unbindHoleReposition();
    holeTrack.el = holeTrack.els = holeTrack.opts = holeTrack.cardEl = null;
    if (ui.backdrop) ui.backdrop.remove();
    if (ui.card) ui.card.remove();
    ui.backdrop = ui.hole = ui.card = null;
  }

  function ensureUi() {
    if (ui.backdrop) return;
    document.body.classList.add('sp-tour-active');
    ui.backdrop = document.createElement('div');
    ui.backdrop.className = 'sp-tour-backdrop';
    ui.hole = document.createElement('div');
    ui.hole.className = 'sp-tour-hole';
    ui.backdrop.appendChild(ui.hole);
    document.body.appendChild(ui.backdrop);
    ui.card = document.createElement('div');
    ui.card.className = 'sp-tour-card';
    document.body.appendChild(ui.card);
    bindHoleReposition();
  }

  function bindHoleReposition() {
    if (window.__spTourHoleBound) return;
    window.__spTourHoleBound = true;
    var ticking = false;
    function refresh() {
      ticking = false;
      if (!ui.hole || !document.body.classList.contains('sp-tour-active')) return;
      if (holeTrack.els && holeTrack.els.length) {
        placeHoleUnion(holeTrack.els, holeTrack.opts || {}, true);
      } else if (holeTrack.el && holeTrack.el.getBoundingClientRect) {
        placeHole(holeTrack.el, true);
      }
      if (holeTrack.cardEl && holeTrack.cardEl.getBoundingClientRect) {
        placeCardNear(holeTrack.cardEl);
      }
    }
    function onScrollOrResize() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(refresh);
    }
    window.__spTourHoleRefresh = onScrollOrResize;
    window.addEventListener('scroll', onScrollOrResize, true);
    window.addEventListener('resize', onScrollOrResize, { passive: true });
  }

  function unbindHoleReposition() {
    if (!window.__spTourHoleBound) return;
    window.__spTourHoleBound = false;
    if (window.__spTourHoleRefresh) {
      window.removeEventListener('scroll', window.__spTourHoleRefresh, true);
      window.removeEventListener('resize', window.__spTourHoleRefresh);
      window.__spTourHoleRefresh = null;
    }
  }

  function placeHole(el, fromTrack) {
    if (!ui.hole) return;
    if (!fromTrack) {
      if (el && el.getBoundingClientRect) {
        holeTrack.el = el;
        holeTrack.els = null;
        holeTrack.opts = null;
      } else {
        // null o rect crudo: no reanclar en scroll/resize
        holeTrack.el = holeTrack.els = holeTrack.opts = null;
      }
    }
    var r = null;
    if (el) {
      if (el.getBoundingClientRect) r = _visibleRect(el);
      else if (el.width >= 8 && el.height >= 8) r = el;
    }
    if (!r) {
      // Nunca dejar un agujero 0×0 en (0,0): se ve como círculo en la esquina.
      ui.hole.classList.add('is-hidden');
      ui.hole.style.top = '0';
      ui.hole.style.left = '0';
      ui.hole.style.width = '0';
      ui.hole.style.height = '0';
      return;
    }
    ui.hole.classList.remove('is-hidden');
    ui.hole.style.top = Math.max(0, r.top - PAD) + 'px';
    ui.hole.style.left = Math.max(0, r.left - PAD) + 'px';
    ui.hole.style.width = Math.max(0, r.width + PAD * 2) + 'px';
    ui.hole.style.height = Math.max(0, r.height + PAD * 2) + 'px';
  }

  /** Quita el gris del overlay (agujero a pantalla completa) para poder arrastrar viendo el desktop. */
  function revealTourDesktop() {
    placeHole({
      top: 0,
      left: 0,
      width: window.innerWidth || 1200,
      height: window.innerHeight || 800,
    });
  }

  /** Zona del planificador donde el doble clic crea bloques (centro, sin eje de obras). */
  function planifClickableGridEl() {
    return qs('#planificador-calendar .vis-panel.vis-center') ||
      qs('.vis-timeline .vis-panel.vis-center') ||
      qs('#planificador-calendar [data-tour="planif-grid"]') ||
      qs('#planificador-calendar');
  }

  /**
   * Zoom horizontal de toda la franja del timeline a la altura de la barra
   * (para poder coger el borde izq/dcho sin que el overlay tape el arrastre).
   */
  function placeHolePlanifItemStrip(el) {
    if (!el) {
      placeHole(planifClickableGridEl() || qs('#planificador-calendar'));
      return;
    }
    var center = planifClickableGridEl();
    var ir = el.getBoundingClientRect();
    var cr = center ? center.getBoundingClientRect() : ir;
    var padY = 14;
    var top = Math.max(cr.top, ir.top - padY);
    var bottom = Math.min(cr.bottom || (ir.top + ir.height + padY), ir.bottom + padY);
    var height = Math.max(bottom - top, Math.max(ir.height + padY * 2, 40));
    placeHole({
      top: top,
      left: cr.left,
      width: Math.max(cr.width, ir.width + 48),
      height: height,
    });
  }

  function findPlanifFeedbackToast() {
    return qs('.swal2-container.swal2-top .swal2-toast') ||
      qs('.swal2-container .swal2-toast') ||
      qs('.swal2-toast') ||
      qs('.toast.show') ||
      qs('.alert-success, .alert-info');
  }

  /** Agujero que cubre la unión de varios nodos (p. ej. chip + columna obra). */
  function placeHoleUnion(els, opts, fromTrack) {
    if (!ui.hole) return;
    opts = opts || {};
    if (!fromTrack) {
      holeTrack.els = (els || []).filter(Boolean);
      holeTrack.el = null;
      holeTrack.opts = opts;
    }
    var rects = [];
    (els || []).forEach(function (el) {
      var r = el && el.getBoundingClientRect ? _visibleRect(el) : null;
      if (r) rects.push(r);
    });
    if (!rects.length) {
      placeHole(null, true);
      return;
    }
    var top = Math.min.apply(null, rects.map(function (r) { return r.top; }));
    var left = Math.min.apply(null, rects.map(function (r) { return r.left; }));
    var right = Math.max.apply(null, rects.map(function (r) { return r.left + r.width; }));
    var bottom = Math.max.apply(null, rects.map(function (r) { return r.top + r.height; }));
    if (opts.clampViewport) {
      var maxBottom = (window.innerHeight || 800) - 16;
      var minTop = opts.minTop != null ? opts.minTop : 64;
      top = Math.max(minTop, top);
      bottom = Math.min(maxBottom, bottom);
      if (bottom < top + 80) bottom = Math.min(maxBottom, top + 220);
    }
    placeHole({ top: top, left: left, width: right - left, height: bottom - top }, true);
  }

  /**
   * Foco ajustado al contenido real de una tabla/listado (no al contenedor
   * scroll que a menudo ocupa casi toda la ventana).
   */
  function placeHoleForList(el) {
    if (!ui.hole || !el) {
      placeHole(el);
      return;
    }
    var table = el;
    if (el.querySelector) {
      table = el.matches && el.matches('table') ? el : (el.querySelector('table') || el);
    }
    var first = table.querySelector
      ? (table.querySelector('thead tr.header-row') || table.querySelector('thead tr') || table.querySelector('tbody tr') || table)
      : table;
    var last = table.querySelector
      ? (table.querySelector('tbody tr:last-child') || table.querySelector('thead tr:last-child') || first)
      : table;
    var box = table.getBoundingClientRect ? table.getBoundingClientRect() : null;
    var a = first && first.getBoundingClientRect ? first.getBoundingClientRect() : box;
    var b = last && last.getBoundingClientRect ? last.getBoundingClientRect() : box;
    if (!a || !box) {
      placeHole(table);
      return;
    }
    var top = a.top;
    var bottom = b ? b.bottom : a.bottom;
    // Si el contenedor es más alto que el contenido, recortar al contenido
    var height = Math.max(24, bottom - top);
    var maxH = Math.min(height, (window.innerHeight || height) - Math.max(0, top) - 12);
    placeHole({
      top: top,
      left: box.left,
      width: box.width,
      height: Math.min(height, maxH),
    });
  }

  function placeCardNear(el) {
    if (!ui.card) return;
    if (el && el.getBoundingClientRect) holeTrack.cardEl = el;
    else if (!el) holeTrack.cardEl = null;
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var cardW = Math.min(360, vw - 24);
    ui.card.style.width = cardW + 'px';
    var top = 24;
    var left = Math.max(12, (vw - cardW) / 2);
    var estH = Math.min(280, Math.max(140, ui.card.offsetHeight || 180));
    if (el && el.getBoundingClientRect) {
      var r = el.getBoundingClientRect();
      var isSidebar = !!(el.closest && el.closest('.sidebar-nav, .admin-sidebar, .sidebar'));
      var isTallSide = r.height > vh * 0.42 && r.width < vw * 0.42;
      var isLibres = !!(el.closest && (
        el.closest('[data-tour="tablero-libres"]') ||
        el.classList.contains('kanban-libres-panel') ||
        el.classList.contains('col-libres')
      ));
      if (isSidebar || (el.classList && el.classList.contains('sidebar-link'))) {
        // A la derecha del enlace del menú
        top = Math.max(12, Math.min(r.top, vh - estH - 12));
        left = Math.min(r.right + 16, vw - cardW - 12);
        if (left < 160) left = Math.max(12, (vw - cardW) / 2);
      } else if (isTallSide || isLibres) {
        // Paneles altos (libres): a la derecha, no debajo (quedaría fuera de vista)
        top = Math.max(72, Math.min(r.top + 8, vh - estH - 12));
        left = Math.min(r.right + 14, vw - cardW - 12);
        if (left < r.right - 20) {
          left = Math.max(12, vw - cardW - 12);
          top = Math.max(72, Math.min(120, vh - estH - 12));
        }
      } else {
        // Preferir ENCIMA del ancla (el tip no se pierde bajo el fold)
        top = r.top - estH - 12;
        left = Math.min(Math.max(12, r.left), vw - cardW - 12);
        if (top < 12) {
          top = Math.min(r.bottom + 14, vh - estH - 12);
        }
      }
    }
    top = Math.max(12, Math.min(top, vh - Math.min(estH, vh - 24)));
    left = Math.max(12, Math.min(left, vw - cardW - 12));
    ui.card.style.top = top + 'px';
    ui.card.style.left = left + 'px';
  }

  /** Tip fijo fuera del área de drop (no tapa la obra destino). */
  function placeCardClearOfKanban() {
    if (!ui.card) return;
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var cardW = Math.min(340, vw - 24);
    ui.card.style.width = cardW + 'px';
    var libres = qs('[data-tour="tablero-libres"], .kanban-libres-panel');
    var left = 12;
    var top = 72;
    if (libres) {
      var r = libres.getBoundingClientRect();
      left = Math.min(r.right + 12, vw - cardW - 12);
      top = Math.max(64, Math.min(r.top + 8, 120));
    } else {
      left = Math.max(12, vw - cardW - 16);
    }
    ui.card.style.top = top + 'px';
    ui.card.style.left = left + 'px';
  }

  /** Comentario fuera de un área (p. ej. calendario): no solapa el foco. */
  function placeCardOutside(avoidEl) {
    if (!ui.card) return;
    holeTrack.cardEl = null;
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var cardW = Math.min(340, vw - 24);
    ui.card.style.width = cardW + 'px';
    var estH = Math.min(260, Math.max(140, ui.card.offsetHeight || 180));
    var top = 16;
    var left = Math.max(12, vw - cardW - 16);
    var avoid = avoidEl && avoidEl.getBoundingClientRect ? avoidEl.getBoundingClientRect() : null;
    if (avoid && avoid.width > 8) {
      var rightSpace = vw - avoid.right;
      var leftSpace = avoid.left;
      if (rightSpace >= cardW + 20) {
        left = avoid.right + 14;
        top = Math.max(12, Math.min(avoid.top + 8, vh - estH - 12));
      } else if (leftSpace >= cardW + 20) {
        left = Math.max(12, avoid.left - cardW - 14);
        top = Math.max(12, Math.min(avoid.top + 8, vh - estH - 12));
      } else if (avoid.top > estH + 24) {
        top = Math.max(12, avoid.top - estH - 12);
        left = Math.min(Math.max(12, avoid.left), vw - cardW - 12);
      } else {
        top = Math.min(avoid.bottom + 12, vh - estH - 12);
        left = Math.min(Math.max(12, avoid.left), vw - cardW - 12);
      }
    }
    top = Math.max(12, Math.min(top, vh - Math.min(estH, vh - 24)));
    left = Math.max(12, Math.min(left, vw - cardW - 12));
    ui.card.style.top = top + 'px';
    ui.card.style.left = left + 'px';
  }

  /** Mensaje siempre visible + foco en un ancla (botón / nav). */
  function spotlightWithCard(el) {
    ensureUi();
    if (ui.card) ui.card.style.display = '';
    if (!el) {
      placeHole(null);
      placeCardModal();
      return;
    }
    el.classList.add('sp-tour-target');
    // Scroll instantáneo: si es smooth, placeCardNear calcula mal y el tip queda fuera
    try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {
      try { el.scrollIntoView(true); } catch (e2) {}
    }
    placeHole(el);
    placeCardNear(el);
    requestAnimationFrame(function () {
      placeHole(el);
      placeCardNear(el);
    });
  }

  function placeCardModal() {
    if (!ui.card) return;
    ui.card.classList.add('is-modal');
    var vw = window.innerWidth;
    var cardW = Math.min(ui.card.classList.contains('is-wide') ? 420 : 360, vw - 32);
    ui.card.style.width = cardW + 'px';
    ui.card.style.top = '22%';
    ui.card.style.left = '50%';
    ui.card.style.transform = 'translateX(-50%)';
    placeHole(null);
  }

  function hideTourBanner() {
    if (ui.banner && ui.banner.parentNode) ui.banner.parentNode.removeChild(ui.banner);
    ui.banner = null;
    document.body.classList.remove('sp-tour-banner-active');
  }

  function showTourBanner(opts) {
    opts = opts || {};
    ensureUi();
    hideTourBanner();
    clearTargets();
    placeHole(null);
    if (ui.card) {
      ui.card.style.display = 'none';
      ui.card.classList.remove('is-modal');
    }
    ui.banner = document.createElement('div');
    ui.banner.className = 'sp-tour-banner';
    ui.banner.innerHTML =
      '<p><strong>' + (opts.title || 'Guía en pausa') + '</strong> — ' +
      (opts.body || 'Revisa el mapeo con calma. Cuando quieras, vuelve a la guía.') + '</p>' +
      '<div class="sp-tour-actions">' +
      '<button type="button" class="sp-tour-skip" data-act="skip">Saltar guía</button>' +
      '<button type="button" class="sp-tour-ghost" data-act="skip-section">' +
      sectionSkipLabel((loadState() || {}).chapter) + '</button>' +
      (opts.doneLabel
        ? '<button type="button" class="sp-tour-primary" data-act="done">' + opts.doneLabel + '</button>'
        : '') +
      '<button type="button" class="sp-tour-primary" data-act="resume">' +
      (opts.resumeLabel || 'Volver a la guía') + '</button>' +
      '</div>';
    document.body.appendChild(ui.banner);
    document.body.classList.add('sp-tour-banner-active');
    ui.banner.querySelector('[data-act="skip"]').onclick = function () {
      hideTourBanner();
      var ch = (loadState() || {}).chapter;
      if (ch === 'import') {
        stopTour({});
        return;
      }
      stopTour({ message: 'Guía omitida. Puedes retomarla desde Primeros pasos.' });
    };
    var skipSec = ui.banner.querySelector('[data-act="skip-section"]');
    if (skipSec) {
      skipSec.onclick = function () {
        hideTourBanner();
        skipSection();
      };
    }
    var resume = ui.banner.querySelector('[data-act="resume"]');
    if (resume) {
      resume.onclick = function () {
        hideTourBanner();
        if (ui.card) ui.card.style.display = '';
        if (opts.onResume) opts.onResume();
        else run();
      };
    }
    var done = ui.banner.querySelector('[data-act="done"]');
    if (done) {
      done.onclick = function () {
        hideTourBanner();
        if (opts.onDone) opts.onDone();
        else pauseAtChapterEnd();
      };
    }
  }

  function clearTargets() {
    document.querySelectorAll('.sp-tour-target, .sp-tour-highlight-user').forEach(function (el) {
      el.classList.remove('sp-tour-target', 'sp-tour-highlight-user');
    });
  }

  function bindNavClick(el, nextStep) {
    if (!el) return;
    el.addEventListener('click', function (ev) {
      var st = loadState();
      if (!st) return;
      st.step = nextStep;
      saveState(st);
      // Navegar explícitamente: así el paso no se queda colgado si algo cancela el clic.
      var href = el.getAttribute('href');
      if (href && href !== '#' && !ev.defaultPrevented) {
        // Dejar que el navegador siga el enlace; el estado ya está guardado.
        return;
      }
      if (href && href !== '#') {
        ev.preventDefault();
        window.location.href = href;
      }
    }, { capture: true, once: true });
  }

  function renderStep(step) {
    ensureUi();
    hideTourBanner();
    clearTargets();
    if (ui.card) ui.card.style.display = '';

    var isModal = !!(step.modal || (step.choices && step.choices.length && !step.selector));
    var el = null;
    if (!isModal && step.selector && !step.manualTarget) {
      ensureTourTargetVisible(step.selector);
      el = qs(step.selector);
    }

    if (step.selector && !step.manualTarget && !el && !isModal) {
      if (step.ifMissing === 'skip') {
        advance(1);
        return;
      }
      if (step.ifMissing === 'wait') {
        // Mostrar el mensaje aunque el ancla aún no esté en el DOM
        placeHole(null);
        placeCardNear(null);
        var waitHtml = '';
        waitHtml += '<div class="sp-tour-progress">' + (step.progress || '') + '</div>';
        waitHtml += '<h3>' + ((typeof step.title === 'function') ? step.title() : (step.title || '')) + '</h3>';
        waitHtml += '<p>' + ((typeof step.body === 'function') ? step.body() : (step.body || '')) + '</p>';
        waitHtml += '<div class="sp-tour-actions">';
        waitHtml += '<button type="button" class="sp-tour-skip" data-act="skip">' +
          ((loadState() || {}).chapter === 'import' ? 'Salir de la guía' : 'Saltar guía') + '</button>';
        if (!step.noSkipSection) {
          waitHtml += '<button type="button" class="sp-tour-ghost" data-act="skip-section">' +
            sectionSkipLabel((loadState() || {}).chapter) + '</button>';
        }
        if (step.waitClick || step.nextLabel || step.onNext) {
          waitHtml += '<button type="button" class="sp-tour-primary" data-act="next">' +
            (step.nextLabel || (step.waitClick ? 'Ya lo hice →' : 'Siguiente')) + '</button>';
        }
        waitHtml += '</div>';
        ui.card.innerHTML = waitHtml;
        ui.card.querySelector('[data-act="skip"]').onclick = function () {
          var ch = (loadState() || {}).chapter;
          if (ch === 'import') {
            stopTour({});
            return;
          }
          stopTour({ message: 'Guía omitida. Puedes retomarla desde Primeros pasos.' });
        };
        var waitSkipSec = ui.card.querySelector('[data-act="skip-section"]');
        if (waitSkipSec) waitSkipSec.onclick = function () { skipSection(); };
        var waitNext = ui.card.querySelector('[data-act="next"]');
        if (waitNext) {
          waitNext.onclick = function () {
            if (step.onNext) {
              step.onNext();
              return;
            }
            if (step.selector) {
              ensureTourTargetVisible(step.selector);
              var t = qs(step.selector);
              var href = (t && t.getAttribute ? t.getAttribute('href') : null) ||
                NAV_FALLBACK_HREF[step.selector] || null;
              if (href && href !== '#') {
                var st = loadState() || {};
                st.step = (typeof step.advanceTo === 'number') ? step.advanceTo : ((st.step || 0) + 1);
                saveState(st);
                window.location.href = href;
                return;
              }
            }
            advance(1);
          };
        }
        setTimeout(function () { renderStep(step); }, 400);
        return;
      }
    }

    // Ancla: scroll ya; el tip se coloca DESPUÉS de rellenar el HTML (si no, mide mal)
    if (el) {
      el.classList.add('sp-tour-target');
      if (!step.noScroll) {
        try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
      }
    }

    var html = '';
    var stepTitle = (typeof step.title === 'function') ? step.title() : (step.title || '');
    var stepBody = (typeof step.body === 'function') ? step.body() : (step.body || '');
    var stepNextLabel = (typeof step.nextLabel === 'function') ? step.nextLabel() : step.nextLabel;
    html += '<div class="sp-tour-progress">' + (step.progress || '') + '</div>';
    html += '<h3>' + stepTitle + '</h3>';
    html += '<p>' + stepBody + '</p>';

    var stackChoices = !!(step.choices && step.choices.length && step.choicesLayout === 'stack');
    if (stackChoices) {
      ui.card.classList.add('is-wide');
      html += '<div class="sp-tour-choices">';
      step.choices.forEach(function (c, i) {
        var done = !!c.done;
        html += '<button type="button" class="sp-tour-primary' + (done ? ' is-done' : '') +
          '" data-act="choice" data-i="' + i + '">' +
          '<span>' + c.label + '</span>' +
          (done ? '<span class="sp-tour-choice-tick" aria-hidden="true">✓</span>' : '') +
          '</button>';
      });
      html += '</div>';
      html += '<div class="sp-tour-actions">';
      html += '<button type="button" class="sp-tour-skip" data-act="skip">' +
      ((loadState() || {}).chapter === 'import' ? 'Salir de la guía' : 'Saltar guía') + '</button>';
      if (!step.noSkipSection) {
        html += '<button type="button" class="sp-tour-ghost" data-act="skip-section">' +
          sectionSkipLabel((loadState() || {}).chapter) + '</button>';
      }
      html += '</div>';
    } else {
      ui.card.classList.remove('is-wide');
      html += '<div class="sp-tour-actions">';
      html += '<button type="button" class="sp-tour-skip" data-act="skip">' +
        ((loadState() || {}).chapter === 'import' ? 'Salir de la guía' : 'Saltar guía') + '</button>';
      if (!step.noSkipSection) {
        var stNow = loadState() || {};
        html += '<button type="button" class="sp-tour-ghost" data-act="skip-section">' +
          sectionSkipLabel(stNow.chapter) + '</button>';
      }
      if (step.choices && step.choices.length) {
        step.choices.forEach(function (c, i) {
          html += '<button type="button" class="sp-tour-primary" data-act="choice" data-i="' + i + '">' +
            c.label + '</button>';
        });
      } else if (step.waitClick) {
        html += '<button type="button" class="sp-tour-ghost" data-act="next">' +
          (stepNextLabel || 'Ya lo hice →') + '</button>';
      } else if (step.primaryHref) {
        html += '<button type="button" class="sp-tour-primary" data-act="go">' +
          (step.primaryLabel || 'Continuar') + '</button>';
      } else if (step.reviewMode) {
        html += '<button type="button" class="sp-tour-primary" data-act="review">' +
          (step.reviewLabel || 'Revisar →') + '</button>';
        html += '<button type="button" class="sp-tour-ghost" data-act="next">' +
          (stepNextLabel || 'Terminar guía →') + '</button>';
      } else {
        html += '<button type="button" class="sp-tour-next" data-act="next">' +
          (stepNextLabel || 'Siguiente') + '</button>';
      }
      html += '</div>';
    }
    ui.card.innerHTML = html;
    ui.card.style.display = '';

    // Posicionar tip ya con el contenido real
    if (isModal) {
      placeCardModal();
      requestAnimationFrame(function () { placeCardModal(); });
    } else if (el) {
      placeHole(el);
      placeCardNear(el);
    } else if (!step.manualTarget) {
      placeHole(null);
      placeCardNear(null);
    }

    ui.card.querySelector('[data-act="skip"]').onclick = function () {
      var ch = (loadState() || {}).chapter;
      if (ch === 'import') {
        stopTour({});
        return;
      }
      stopTour({ message: 'Guía omitida. Puedes retomarla desde Primeros pasos.' });
    };

    var skipSecBtn = ui.card.querySelector('[data-act="skip-section"]');
    if (skipSecBtn) {
      skipSecBtn.onclick = function () { skipSection(); };
    }

    var reviewBtn = ui.card.querySelector('[data-act="review"]');
    if (reviewBtn) {
      reviewBtn.onclick = function () {
        showTourBanner({
          title: step.bannerTitle || 'Revisa el asistente',
          body: step.bannerBody || 'Cuando termines el mapeo o la importación, vuelve aquí.',
          resumeLabel: 'Volver a la guía',
          doneLabel: step.nextLabel || 'Terminar guía →',
          onResume: function () {
            if (typeof step.onResumeFromBanner === 'function') {
              step.onResumeFromBanner();
              return;
            }
            renderStep(step);
          },
          onDone: function () {
            if (step.onNext) step.onNext();
            else advance(1);
          },
        });
      };
    }

    var nextBtn = ui.card.querySelector('[data-act="next"]');
    if (nextBtn) {
      nextBtn.onclick = function () {
        // Si el paso exige una acción y no está hecha:
        // - gateRetry → volver a enfocar el mismo paso (no cortar la guía)
        // - si no → cortar
        if (typeof step.requireGate === 'function') {
          var okGate = false;
          try { okGate = !!step.requireGate(); } catch (eGate) { okGate = false; }
          if (!okGate) {
            if (step.gateRetry) {
              if (typeof step.onGateFail === 'function') {
                try { step.onGateFail(); } catch (eFail) { /* ignore */ }
              }
              // Re-render del mismo paso para recuperar el foco/spotlight
              run();
              // Aviso breve en la tip si hay mensaje
              setTimeout(function () {
                if (!ui.card || !step.gateFail) return;
                var p = ui.card.querySelector('p');
                if (p) {
                  p.innerHTML = '<span style="color:#b45309;">' + step.gateFail + '</span>';
                }
              }, 30);
              return;
            }
            stopTour({
              message: step.gateFail ||
                'No se completó el paso indicado. Sin eso la guía no tiene sentido: reábrela cuando quieras intentarlo de nuevo.',
            });
            return;
          }
        }
        // Si el paso pide un clic en un enlace del menú, «Ya lo hice» navega ahí.
        if (step.waitClick && step.selector) {
          var target = el || qs(step.selector);
          var href = target && target.getAttribute ? target.getAttribute('href') : null;
          if (href && href !== '#') {
            var st = loadState() || {};
            st.step = (typeof step.advanceTo === 'number') ? step.advanceTo : ((st.step || 0) + 1);
            saveState(st);
            if (window.SP_pageLoading) window.SP_pageLoading.show('Cargando…');
            window.location.href = href;
            return;
          }
        }
        if (step.onNext) {
          step.onNext();
          return;
        }
        advance(1);
      };
    }

    var goBtn = ui.card.querySelector('[data-act="go"]');
    if (goBtn && step.primaryHref) {
      goBtn.onclick = function () {
        if (step.onBeforeGo) step.onBeforeGo();
        window.location.href = step.primaryHref;
      };
    }
    ui.card.querySelectorAll('[data-act="choice"]').forEach(function (btn) {
      btn.onclick = function () {
        var choice = step.choices[parseInt(btn.getAttribute('data-i'), 10)];
        if (choice && choice.onPick) choice.onPick();
      };
    });

    if (step.waitClick && el) {
      bindNavClick(el, typeof step.advanceTo === 'number' ? step.advanceTo : ((loadState() || {}).step || 0) + 1);
    }

    if (step.onShow) step.onShow(el, loadState() || {});
  }

  function advance(delta) {
    var state = loadState();
    if (!state || !state.active) return;
    state.step = (state.step || 0) + (delta || 1);
    saveState(state);
    run();
  }

  function showDoneCard(message) {
    ensureUi();
    clearTargets();
    placeHole(null);
    ui.card.classList.add('is-modal');
    ui.card.style.transform = 'translateX(-50%)';
    ui.card.innerHTML =
      '<h3>Guía en pausa</h3><p>' + message + '</p>' +
      '<div class="sp-tour-actions">' +
      '<button type="button" class="sp-tour-primary" data-act="ok">Entendido</button></div>';
    ui.card.style.top = '30%';
    ui.card.style.left = '50%';
    ui.card.querySelector('[data-act="ok"]').onclick = function () { teardown(); };
  }

  function highlightGroup(selector) {
    var group = qs(selector);
    if (!group) return null;
    clearTargets();
    group.classList.add('sp-tour-target');
    placeHole(group);
    placeCardNear(group);
    return group;
  }

  function highlightRowByDni(dni) {
    clearTargets();
    var needle = String(dni || '').toUpperCase().trim();
    var row = null;
    if (needle) {
      document.querySelectorAll('[data-tour-user-row]').forEach(function (tr) {
        if (row) return;
        var d = (tr.getAttribute('data-dni') || '').toUpperCase().trim();
        if (d === needle) row = tr;
      });
    }
    if (!row) return null;
    row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
    try { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    placeHole(row);
    placeCardNear(row);
    return row;
  }

  function highlightWorkerChip() {
    clearTargets();
    var st = loadState() || {};
    var needle = String(st.createdDni || '').toUpperCase().trim();
    var obraName = String(st.createdObraNombre || '').toLowerCase().trim();
    var obraRoot = qs('.kanban-works-wrapper') || document;
    var chip = null;

    // Solo chips DENTRO de una obra (nunca el panel de libres / ocupados)
    function chipsInObras() {
      return obraRoot.querySelectorAll('.kanban-col .worker-chip, .obra-card .worker-chip');
    }

    if (needle) {
      chipsInObras().forEach(function (el) {
        if (chip) return;
        if ((el.getAttribute('data-dni') || '').toUpperCase().trim() === needle) chip = el;
      });
    }

    if (!chip && obraName) {
      document.querySelectorAll('.kanban-col[data-obra-id]').forEach(function (col) {
        if (chip) return;
        var title = (col.querySelector('.header-title') || {}).textContent || '';
        if (title.toLowerCase().indexOf(obraName) === -1) return;
        chip = col.querySelector('.worker-chip');
      });
    }

    if (!chip) {
      var obraId = (new URLSearchParams(window.location.search || '')).get('obra');
      if (obraId) {
        var col = qs('.kanban-col[data-obra-id="' + obraId + '"]');
        if (col) chip = col.querySelector('.worker-chip');
      }
    }

    // Último recurso: primer chip con pelota roja dentro de una obra
    if (!chip) {
      chipsInObras().forEach(function (el) {
        if (chip) return;
        if (el.querySelector('.dot-danger')) chip = el;
      });
    }

    if (!chip) return null;
    chip.classList.add('sp-tour-target', 'sp-tour-highlight-user');
    var card = chip.closest('.kanban-col, .obra-card') || chip;
    try { card.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    placeHole(card);
    placeCardNear(card);
    return chip;
  }

  function _visibleRect(el) {
    if (!el || !el.getBoundingClientRect) return null;
    var r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return null;
    if (r.bottom < 0 || r.right < 0) return null;
    if (r.top > (window.innerHeight || 0) && r.left > (window.innerWidth || 0)) return null;
    return r;
  }

  function selectOficinaInFichajeSelect(el) {
    el = el || qs('[data-tour="fichar-obra"], #obra');
    if (!el || !el.options) return false;
    var found = null;
    var foundExact = null;
    Array.prototype.forEach.call(el.options, function (opt) {
      if (!opt || opt.disabled) return;
      var val = (opt.value || '').trim();
      if (!val) return;
      var t = (opt.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (t === 'oficina') foundExact = opt;
      else if (!found && t.indexOf('oficina') >= 0) found = opt;
    });
    found = foundExact || found;
    if (!found) return false;
    // Quitar selected de las demás y forzar esta
    Array.prototype.forEach.call(el.options, function (opt) {
      opt.selected = (opt === found);
      try { opt.removeAttribute('selected'); } catch (e0) { /* ignore */ }
    });
    try { found.setAttribute('selected', 'selected'); } catch (e1) { /* ignore */ }
    el.value = found.value;
    try { el.selectedIndex = found.index; } catch (e2) { /* ignore */ }
    try {
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e3) { /* ignore */ }
    return String(el.value) === String(found.value);
  }

  function ensureOficinaSelected(retries) {
    retries = retries == null ? 6 : retries;
    var ok = selectOficinaInFichajeSelect();
    if (ok || retries <= 0) return ok;
    setTimeout(function () { ensureOficinaSelected(retries - 1); }, 120);
    return false;
  }

  /**
   * Detecta en auditoría qué sección aplica al fichaje del tour
   * (desviación vs sin planificar) y enfoca esa.
   */
  function resolveAuditTourSection() {
    var st = loadState() || {};
    var dni = String(st.createdDni || '').toUpperCase().trim();

    var defs = [
      {
        kind: 'desviaciones',
        root: qs('[data-tour="audit-desviaciones"]'),
        toggle: qs('[data-tour="audit-desviaciones-toggle"]'),
        collapse: qs('#collapseConflictos'),
        collapseSel: '#collapseConflictos',
        title: 'Desviaciones de plan',
        explain:
          'Has fichado en <strong>Oficina</strong> pero estabas planificado en otra obra. Por eso cae aquí: <strong>Desviaciones de plan</strong>.',
      },
      {
        kind: 'paracaidistas',
        root: qs('[data-tour="audit-paracaidistas"]'),
        toggle: qs('[data-tour="audit-paracaidistas-toggle"]'),
        collapse: qs('#collapseParacaidistas'),
        collapseSel: '#collapseParacaidistas',
        title: 'Fichajes sin planificar',
        explain:
          'Has fichado sin tener cuadrante en esa obra. Por eso cae aquí: <strong>Fichajes sin planificar</strong>.',
      },
    ];

    function rowsIn(def) {
      if (!def.root) return [];
      return Array.prototype.slice.call(
        def.root.querySelectorAll('tr.audit-data-row, tr[data-tour-audit-row], tbody tr')
      ).filter(function (tr) {
        return tr.querySelectorAll('td').length > 2;
      });
    }

    function rowMatch(tr) {
      if (!tr) return false;
      if (dni && (tr.getAttribute('data-dni') || '').toUpperCase().trim() === dni) return true;
      if (/oficina/i.test(tr.textContent || '')) return true;
      return false;
    }

    // 1) Fila que encaja con el DNI / Oficina
    for (var i = 0; i < defs.length; i++) {
      var rows = rowsIn(defs[i]);
      for (var r = 0; r < rows.length; r++) {
        if (rowMatch(rows[r])) {
          defs[i].matchedRow = rows[r];
          return defs[i];
        }
      }
    }

    // 2) Sección abierta con filas
    for (var j = 0; j < defs.length; j++) {
      if (defs[j].collapse && defs[j].collapse.classList.contains('show') && rowsIn(defs[j]).length) {
        return defs[j];
      }
    }

    // 3) Primera con filas (desviaciones antes que sin planificar: caso típico con demo)
    for (var k = 0; k < defs.length; k++) {
      if (rowsIn(defs[k]).length) return defs[k];
    }

    // 4) Fallback
    return defs[0].root ? defs[0] : defs[1];
  }

  function highlightAuditSection() {
    clearTargets();
    placeHole(null);
    var info = resolveAuditTourSection();
    if (!info || !info.root) {
      placeCardModal();
      return null;
    }
    var target = info.toggle || info.root;
    target.classList.add('sp-tour-target');
    try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    if (_visibleRect(target)) {
      placeHole(target);
      placeCardNear(target);
    } else {
      placeHole(null);
      placeCardModal();
    }
    if (ui.card) {
      var h = ui.card.querySelector('h3');
      var p = ui.card.querySelector('p');
      if (h) h.textContent = info.title;
      if (p) p.innerHTML = info.explain;
    }
    try {
      if (info.collapse && !info.collapse.classList.contains('show')) {
        if (typeof window.openAuditoriaSection === 'function') {
          window.openAuditoriaSection(info.collapseSel);
        } else if (window.jQuery) {
          window.jQuery(info.collapse).collapse('show');
        } else if (info.toggle) {
          info.toggle.click();
        }
      }
    } catch (e2) {}
    return target;
  }

  function highlightAuditParacaidista(done) {
    clearTargets();
    placeHole(null);

    var st = loadState() || {};
    var needle = String(st.createdDni || '').toUpperCase().trim();
    var info = resolveAuditTourSection();
    var toggle = (info && info.toggle) || qs('[data-tour="audit-paracaidistas-toggle"]');
    var collapse = (info && info.collapse) || qs('#collapseParacaidistas');
    var collapseSel = (info && info.collapseSel) || '#collapseParacaidistas';
    var settled = false;
    var attempts = 0;
    var MAX_ATTEMPTS = 8;

    function finishRow(row) {
      if (settled) return row || null;
      settled = true;
      clearTargets();
      if (!row) {
        placeHole(null);
        placeCardModal();
        if (done) done(null);
        return null;
      }
      row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
      var actionsCell = row.querySelector('td.no-row-nav') ||
        row.querySelector('td.text-right') ||
        row.querySelector('td:last-child');
      var buttons = Array.prototype.slice.call(
        row.querySelectorAll('button.btn-audit, button[onclick*="resolver"], [data-tour="audit-aceptar"]')
      );
      buttons.forEach(function (b) { b.classList.add('sp-tour-target'); });
      try {
        (actionsCell || row).scrollIntoView({ block: 'center', behavior: 'smooth' });
      } catch (e) {}
      // Agujero en los botones; tip FUERA para no taparlos
      if (buttons.length >= 2) {
        placeHoleUnion(buttons);
      } else if (actionsCell && _visibleRect(actionsCell)) {
        placeHole(actionsCell);
      } else if (_visibleRect(row)) {
        placeHole(row);
      } else {
        placeHole(null);
      }
      placeCardOutside(actionsCell || row);
      if (done) done(buttons[0] || row, buttons, row);
      return buttons[0] || row;
    }

    function pickRow() {
      var row = null;
      var scope = collapse || (info && info.root) || document;
      if (needle) {
        scope.querySelectorAll('[data-tour-audit-row], tr.audit-data-row').forEach(function (tr) {
          if (row) return;
          if ((tr.getAttribute('data-dni') || '').toUpperCase().trim() === needle) row = tr;
        });
      }
      if (!row) {
        scope.querySelectorAll('[data-tour-audit-row], tr.audit-data-row').forEach(function (tr) {
          if (row) return;
          if (/oficina/i.test(tr.textContent || '')) row = tr;
        });
      }
      if (!row) {
        row = (collapse && collapse.querySelector('[data-tour-audit-row], tr.audit-data-row')) ||
          qs('#collapseConflictos tr.audit-data-row, #collapseParacaidistas [data-tour-audit-row]');
      }
      return row;
    }

    function afterOpen() {
      if (settled) return null;
      var row = pickRow();
      if (row && _visibleRect(row)) {
        return finishRow(row);
      }
      attempts += 1;
      if (attempts < MAX_ATTEMPTS) {
        setTimeout(afterOpen, 80);
        return null;
      }
      return finishRow(null);
    }

    function openThenFocus() {
      var needsOpen = collapse && !collapse.classList.contains('show');
      if (!needsOpen) {
        afterOpen();
        return null;
      }
      var onShown = function () {
        if (collapse) {
          collapse.removeEventListener('shown.bs.collapse', onShown);
        }
        setTimeout(afterOpen, 50);
      };
      if (collapse && collapse.addEventListener) {
        collapse.addEventListener('shown.bs.collapse', onShown);
      }
      try {
        if (typeof window.openAuditoriaSection === 'function') {
          window.openAuditoriaSection(collapseSel);
        } else if (window.jQuery) {
          window.jQuery(collapse).collapse('show');
        } else if (toggle) {
          toggle.click();
        }
      } catch (e) {
        if (toggle) try { toggle.click(); } catch (e2) {}
      }
      setTimeout(function () {
        if (!settled) afterOpen();
      }, 500);
      return null;
    }

    return openThenFocus();
  }

  function openAuditHistoricoSection() {
    var toggle = qs('[data-tour="audit-historico-toggle"]');
    var collapse = qs('#collapseHistorial');
    var root = qs('[data-tour="audit-historico"]');
    try {
      if (collapse && !collapse.classList.contains('show')) {
        if (typeof window.openAuditoriaSection === 'function') {
          window.openAuditoriaSection('#collapseHistorial');
        } else if (window.jQuery) {
          window.jQuery(collapse).collapse('show');
        } else if (toggle) {
          toggle.click();
        }
      }
    } catch (e) { /* ignore */ }
    return { toggle: toggle, collapse: collapse, root: root };
  }

  function findHistoricoTourRow() {
    var st = loadState() || {};
    var dni = String(st.createdDni || '').toUpperCase().trim();
    var scope = qs('#collapseHistorial') || qs('[data-tour="audit-historico"]') || document;
    var rows = Array.prototype.slice.call(
      scope.querySelectorAll('[data-tour-historico-row], #historialTable tbody tr.audit-data-row')
    );
    var hit = null;
    if (dni) {
      rows.forEach(function (tr) {
        if (hit) return;
        if ((tr.getAttribute('data-dni') || '').toUpperCase().trim() === dni) hit = tr;
      });
    }
    if (!hit) {
      rows.forEach(function (tr) {
        if (hit) return;
        if (/oficina/i.test(tr.textContent || '') &&
            /reasign|asignad|ignor|resuelto|multitarea/i.test(tr.textContent || '')) {
          hit = tr;
        }
      });
    }
    if (!hit) {
      rows.forEach(function (tr) {
        if (hit) return;
        if (/oficina/i.test(tr.textContent || '')) hit = tr;
      });
    }
    return hit || rows[0] || null;
  }

  /** Lee los hitos del modal de actividad y arma el tip según lo que realmente hay. */
  function buildActivityTourTipHtml(root) {
    var scope = root || document;
    var items = Array.prototype.slice.call(scope.querySelectorAll('.person-day-timeline-item'));
    if (!items.length) {
      if (scope.querySelector('.person-day-timeline-loading')) {
        return null; // aún cargando
      }
      return 'Aquí se lee la historia del día. En este caso aún no hay eventos listados.';
    }

    var hadPlan = false;
    var points = [];

    function esc(s) {
      return String(s || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    }

    function obraFromDesc(desc) {
      var m = /→\s*'([^']+)'/.exec(desc || '') ||
        /en\s+'([^']+)'/i.exec(desc || '') ||
        /fich[oó]\s+en\s+([^.]+)/i.exec(desc || '');
      return m ? m[1].trim() : '';
    }

    items.forEach(function (item) {
      var title = ((item.querySelector('.person-day-timeline-title') || {}).textContent || '').trim();
      var desc = ((item.querySelector('.person-day-timeline-desc') || {}).textContent || '').trim();
      var blob = (title + ' ' + desc).toLowerCase();
      if (!title || title === 'Sin actividad') return;

      if (/auto-?asignaci[oó]n|fichaje f[ií]sico/i.test(blob)) {
        var obraAuto = obraFromDesc(desc);
        if (hadPlan) {
          points.push(
            'Fichó en otra' + (obraAuto ? ' (<strong>' + esc(obraAuto) + '</strong>)' : '') +
            ': el sistema lo anota como <strong>autoasignación por fichaje físico</strong>.'
          );
        } else {
          points.push(
            'No estaba <strong>planificada</strong> en ninguna obra' +
            (obraAuto ? ' y fichó en <strong>' + esc(obraAuto) + '</strong>' : '') +
            ': cae como fichaje <strong>sin planificar</strong> (autoasignación por fichaje físico).'
          );
        }
        return;
      }

      if (/^planificaci[oó]n$/i.test(title) ||
          (/asignado/i.test(desc) && !/auto/i.test(blob) && !/resoluci/i.test(blob))) {
        hadPlan = true;
        var obraPlan = obraFromDesc(desc);
        points.push(
          'Estaba <strong>planificada</strong>' +
          (obraPlan ? ' en <strong>' + esc(obraPlan) + '</strong>' : ' en una obra') + '.'
        );
        return;
      }

      if (/resoluci[oó]n de fichaje|reabrir resoluci/i.test(title)) {
        if (/mover/i.test(blob)) {
          points.push('Tú resolviste con <strong>Mover</strong>: el cuadrante pasa a la obra del fichaje.');
        } else if (/a[ñn]adir|multi|pluri/i.test(blob)) {
          points.push('Tú resolviste con <strong>Añadir</strong>: se mantiene la planificada y se suma la del fichaje.');
        } else if (/ignor/i.test(blob)) {
          points.push('Tú resolviste con <strong>Ignorar</strong>: se oculta la alerta sin cambiar el plan.');
        } else if (/acept/i.test(blob)) {
          points.push('Tú resolviste con <strong>Aceptar</strong>: se asigna oficialmente a la obra del fichaje.');
        } else if (/borrar|error al planificar/i.test(blob)) {
          points.push('Tú resolviste borrando la planificación que no encajaba.');
        } else {
          points.push('Tú <strong>resolviste</strong> la incidencia en auditoría (<em>' + esc(title) + '</em>).');
        }
        return;
      }

      if (/entrada|salida|fichaje_app|fichaje en app|marca/i.test(blob) || /fichaje/i.test(title)) {
        points.push('Queda el <strong>registro de fichaje</strong> (entrada/salida) de ese momento.');
        return;
      }

      if (/pausa/i.test(blob)) {
        points.push('Hay una <strong>pausa</strong> registrada en la jornada.');
        return;
      }

      // Cualquier otro hito visible: un punto con su título
      points.push('<strong>' + esc(title) + '</strong>' + (desc ? ': ' + esc(desc.length > 110 ? desc.slice(0, 107) + '…' : desc) : ''));
    });

    if (!points.length) {
      return 'Aquí se lee la historia del día en orden. Abre cada evento del zoom para ver el detalle.';
    }

    var html = 'En esta actividad (el zoom) aparece, en orden:<br>';
    points.forEach(function (pt, i) {
      html += '<strong>' + (i + 1) + '.</strong> ' + pt + '<br>';
    });
    return html;
  }

  function highlightHistoricoTourRow() {
    clearTargets();
    var parts = openAuditHistoricoSection();
    var tries = 0;
    function focus() {
      var row = findHistoricoTourRow();
      if (!row && tries < 10) {
        tries += 1;
        setTimeout(focus, 120);
        return null;
      }
      if (!row) {
        var fallback = parts.toggle || parts.root;
        if (fallback) {
          placeHole(fallback);
          placeCardOutside(fallback);
        } else {
          placeHole(null);
          placeCardModal();
        }
        return null;
      }
      row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
      try { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
      placeHole(row);
      placeCardOutside(row);
      return row;
    }
    setTimeout(focus, 350);
    return focus();
  }

  function fillCredsHint(kind) {
    var st = loadState() || {};
    // Academia fichajes: textos cortos (no “acabas de crear”)
    if (st.chapter === 'fichajes') {
      if (kind === 'dni') {
        return st.createdDni
          ? ('Introduce el <strong>DNI</strong>: <strong>' + st.createdDni + '</strong>.')
          : 'Introduce el <strong>DNI</strong>.';
      }
      if (kind === 'pin') {
        return st.createdPin
          ? ('Introduce el <strong>PIN</strong>: <strong>' + st.createdPin + '</strong>.')
          : 'Introduce el <strong>PIN</strong>.';
      }
      return '';
    }
    var dni = (st.createdDni || '').trim();
    var pin = (st.createdPin || '').trim();
    var name = (st.createdWorkerName || '').trim();
    var who = name ? (' de <strong>' + name + '</strong>') : ' del operario que acabas de crear';
    if (kind === 'dni') {
      return dni
        ? ('Introduce el DNI' + who + ' (<strong>' + dni + '</strong>).')
        : ('Introduce el DNI' + who + '.');
    }
    if (kind === 'pin') {
      return pin
        ? ('Introduce el PIN' + who + ' (<strong>' + pin + '</strong>).')
        : ('Introduce el PIN' + who + ' (el que pusiste al crearlo).');
    }
    return '';
  }

  function prefillLoginField(kind) {
    var st = loadState() || {};
    if (kind === 'dni') {
      var dniEl = qs('[data-tour="fichar-dni"]') || qs('#dni');
      if (dniEl && st.createdDni) {
        dniEl.value = st.createdDni;
        try { dniEl.focus(); dniEl.select(); } catch (e) {}
      }
      return dniEl;
    }
    if (kind === 'pin') {
      var pinEl = qs('[data-tour="fichar-pin"]') || qs('#pin');
      if (pinEl && st.createdPin) {
        pinEl.value = st.createdPin;
        try { pinEl.type = 'text'; } catch (e2) {}
        try { pinEl.focus(); pinEl.select(); } catch (e3) {}
      } else if (pinEl) {
        try { pinEl.focus(); } catch (e4) {}
      }
      return pinEl;
    }
    return null;
  }

  function isMiEntrar() {
    return pathIs(/\/mi\/entrar/);
  }

  function isMiFichar() {
    var p = (window.location.pathname || '').replace(/\/$/, '') || '';
    return p === '/mi' || /\/mi$/.test(p);
  }

  function fichajeEstado() {
    var root = qs('.fichaje');
    return root ? (root.getAttribute('data-estado') || '') : '';
  }

  function stepsTrabajadores() {
    return [
      // 0 — ¿Fichar? (omitir si ya se decidió en el hub / demo / sesión)
      {
        when: function () {
          var st = loadState();
          return !st || st.wantFichaje === null || typeof st.wantFichaje === 'undefined';
        },
        title: '¿Van a fichar tus operarios?',
        body: 'Si dices que sí, activamos el fichaje móvil ahora. Si no, solo planificáis (podrás activarlo después en Configuración).',
        progress: 'Inicio · 1',
        modal: true,
        choices: [
          {
            label: 'Sí, activar fichaje',
            onPick: function () {
              var st = loadState() || {};
              st.wantFichaje = true;
              st.step = 1;
              st.active = true;
              st.chapter = 'trabajadores';
              saveState(st);
              window.__ONB_FICHAJE_ASKED__ = true;
              window.__ONB_FICHAJE_ACTIVO__ = true;
              setFichaje(true).finally(function () { run(); });
            },
          },
          {
            label: 'No, solo planificar',
            onPick: function () {
              var st = loadState() || {};
              st.wantFichaje = false;
              st.step = 1;
              st.active = true;
              st.chapter = 'trabajadores';
              saveState(st);
              window.__ONB_FICHAJE_ASKED__ = true;
              window.__ONB_FICHAJE_ACTIVO__ = false;
              setFichaje(false).finally(function () { run(); });
            },
          },
        ],
      },
      // 1 — Sidebar Trabajadores
      {
        when: function () { return !pathIs(/\/admin\/personal/) && !pathIs(/\/admin\/create_user/) && !pathIs(/\/admin\/import_users/); },
        selector: '[data-tour="nav-trabajadores"]',
        title: 'Ve a Trabajadores',
        body: 'Pulsa <strong>Trabajadores</strong> en el menú de la izquierda. Desde esta sección gestionarás a tu personal: operarios internos y externos (subcontratas).',
        progress: 'Plantilla · menú',
        waitClick: true,
        advanceTo: 2,
        ifMissing: 'wait',
      },
      // 2 — Nuevo / Importar
      {
        when: function () { return pathIs(/\/admin\/personal/); },
        selector: '[data-tour="personal-actions"]',
        title: '¿Nuevo o importar?',
        body: 'Si tienes Excel, Importar internos. Si no, Nuevo y te guiamos. Casi cualquier Excel vale con nombre, apellidos y DNI.',
        progress: 'Plantilla · elegir',
        waitClick: true,
        onShow: function () {
          highlightGroup('[data-tour="personal-actions"]');
          var nuevo = qs('[data-tour="personal-nuevo"]');
          var imp = qs('[data-tour="personal-import"]');
          if (nuevo) {
            nuevo.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 3; st.branch = 'nuevo'; saveState(st); }
            }, { once: true });
          }
          if (imp) {
            imp.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 20; st.branch = 'import'; saveState(st); }
            }, { once: true });
          }
        },
      },
      // 3 — Nombre
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: 'input[name="name"]',
        title: 'Nombre del operario',
        body: 'Escribe el nombre. Deja el rol en Operario.',
        progress: 'Alta · nombre',
        onShow: function (el) { if (el) el.focus(); },
      },
      // 4 — Apellidos
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: 'input[name="lastname"]',
        title: 'Apellidos',
        body: 'Apellidos del trabajador.',
        progress: 'Alta · apellidos',
        onShow: function (el) { if (el) el.focus(); },
      },
      // 5 — DNI
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: 'input[name="dni"]',
        title: 'DNI / NIE',
        body: 'Con el DNI y el PIN entrará a fichar en el móvil (/mi).',
        progress: 'Alta · DNI',
        onShow: function (el) { if (el) el.focus(); },
      },
      // 6 — Acceso completo (radios + PIN)
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: '[data-tour="user-acceso"]',
        title: 'Acceso del operario',
        body: 'Elige si estableces el PIN ahora (p. ej. 2345 para probar) o envías un enlace por correo para que lo defina él. Si envías enlace, hace falta el email.',
        progress: 'Alta · acceso',
        nextLabel: 'Siguiente',
        onShow: function () {
          highlightGroup('[data-tour="user-acceso"]');
        },
      },
      // 7 — Guardar
      {
        when: function () { return pathIs(/\/admin\/create_user/); },
        selector: '[data-tour="user-guardar"]',
        title: 'Guardar usuario',
        body: 'Pulsa Crear usuario. Volverás al listado para verlo creado.',
        progress: 'Alta · guardar',
        waitClick: true,
        onShow: function () {
          var form = qs('#userCreateForm') || qs('form');
          if (!form) return;
          form.addEventListener('submit', function () {
            var dni = (qs('input[name="dni"]') || {}).value || '';
            var pin = (qs('#pinInput') || qs('input[name="pin"]') || {}).value || '';
            var name = ((qs('input[name="name"]') || {}).value || '').trim();
            var last = ((qs('input[name="lastname"]') || {}).value || '').trim();
            var st = loadState();
            if (st) {
              st.createdDni = (dni || '').toUpperCase();
              if (pin) st.createdPin = String(pin);
              st.createdWorkerName = (name + ' ' + last).trim();
              st.step = 8;
              saveState(st);
            }
          }, { once: true });
        },
      },
      // 8 — Listado (solo la fila del operario creado)
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/personal/) && st && st.createdDni;
        },
        manualTarget: true,
        title: '¡Operario creado!',
        body: function () {
          var st = loadState() || {};
          if (st.mode === 'solo') {
            return 'Ya está en plantilla. Te devolvemos a Primeros pasos para que sigas con el material o elijas el siguiente tutorial.';
          }
          return 'Ya está en plantilla. Siguiente: una obra. Pulsa Continuar y te pediremos ir a Directorio.';
        },
        progress: 'Plantilla · listo',
        nextLabel: function () {
          var st = loadState() || {};
          return st.mode === 'solo' ? 'Volver a Primeros pasos →' : 'Continuar a obras';
        },
        onShow: function () {
          var st = loadState() || {};
          highlightRowByDni(st.createdDni);
        },
        onNext: function () {
          var st = loadState() || {};
          if (st.mode === 'solo') {
            finishSoloAndReturn('Persona creada. Sigue reuniendo material o abre el siguiente tutorial.');
            return;
          }
          saveState({
            active: true,
            chapter: 'obra',
            step: 0,
            mode: st.mode || 'full',
            returnTo: st.returnTo,
            wantFichaje: st.wantFichaje,
            createdDni: st.createdDni,
            createdPin: st.createdPin,
          });
          run();
        },
      },
      { when: function () { return false; }, title: '', body: '', onShow: function () {} },
      // Import branch
      {
        when: function () {
          var st = loadState();
          return st && (st.step || 0) >= 20 && pathIs(/\/admin\/import_users/);
        },
        selector: 'main',
        title: 'Importar personal',
        body: 'Sube tu Excel/CSV (nombre, apellidos, DNI). Cuando termines, continúa hacia Directorio.',
        progress: 'Importar',
        nextLabel: 'Continuar a obras',
        onNext: function () {
          var st = loadState() || {};
          if (st.mode === 'solo') {
            finishSoloAndReturn('Personal importado. Sigue reuniendo material o abre el siguiente tutorial.');
            return;
          }
          saveState({
            active: true,
            chapter: 'obra',
            step: 0,
            mode: st.mode || 'full',
            returnTo: st.returnTo,
            wantFichaje: st.wantFichaje,
          });
          run();
        },
      },
    ];
  }

  function stepsObra() {
    return [
      // 0 — Sidebar Directorio
      {
        when: function () {
          return !pathIs(/\/admin\/obras(\/|$|\?)/) &&
            !pathIs(/\/admin\/create_obra/) &&
            !pathIs(/\/admin\/import_obras/);
        },
        selector: '[data-tour="nav-directorio"]',
        title: 'Ve a Directorio',
        body: 'Pulsa <strong>Directorio</strong> en el menú. Es el directorio de obras: desde aquí crearás y gestionarás todas las obras de la empresa.',
        progress: 'Obra · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      // 1 — Nueva / Importar
      {
        when: function () { return pathIs(/\/admin\/obras(\/|$|\?)/); },
        selector: '[data-tour="obra-actions"]',
        title: '¿Nueva obra o importar?',
        body: 'Pulsa Nueva para crear una a mano, o Importar si ya tienes listado de obras.',
        progress: 'Obra · elegir',
        waitClick: true,
        onShow: function () {
          highlightGroup('[data-tour="obra-actions"]');
          var neu = qs('[data-tour="obra-nueva"]');
          var imp = qs('[data-tour="obra-import"]');
          if (neu) {
            neu.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 2; saveState(st); }
            }, { once: true });
          }
          if (imp) {
            imp.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 10; saveState(st); }
            }, { once: true });
          }
        },
      },
      // 2 — Nombre
      {
        when: function () { return pathIs(/\/admin\/create_obra/); },
        selector: '[data-tour="obra-nombre"], input[name="nombre"]',
        title: 'Nombre de la obra',
        body: 'Pon un nombre claro (tajo real o «Obra demo»).',
        progress: 'Obra · nombre',
        onShow: function () {
          var input = qs('input[name="nombre"]');
          if (input) input.focus();
        },
      },
      // 3 — Fechas (inicio + fin visibles)
      {
        when: function () { return pathIs(/\/admin\/create_obra/); },
        selector: '[data-tour="obra-inicio"]',
        title: 'Fechas',
        body: 'Inicio por defecto hoy; fin a un año vista. Puedes cambiarlas.',
        progress: 'Obra · fechas',
        onShow: function () {
          var a = qs('[data-tour="obra-inicio"]');
          var b = qs('[data-tour="obra-fin"]');
          if (a && b) {
            var top = Math.min(a.getBoundingClientRect().top, b.getBoundingClientRect().top);
            var left = Math.min(a.getBoundingClientRect().left, b.getBoundingClientRect().left);
            var right = Math.max(a.getBoundingClientRect().right, b.getBoundingClientRect().right);
            var bottom = Math.max(a.getBoundingClientRect().bottom, b.getBoundingClientRect().bottom);
            var fake = {
              getBoundingClientRect: function () {
                return { top: top, left: left, width: right - left, height: bottom - top, right: right, bottom: bottom };
              },
            };
            clearTargets();
            a.classList.add('sp-tour-target');
            b.classList.add('sp-tour-target');
            placeHole(fake);
            placeCardNear(fake);
          }
        },
      },
      // 4 — Jefe
      {
        when: function () { return pathIs(/\/admin\/create_obra/); },
        selector: '[data-tour="obra-jefe"]',
        title: 'Jefe de esta obra',
        body: 'Elige quién responde de la obra. En esta guía dejamos tu usuario admin marcado por defecto; puedes cambiarlo.',
        progress: 'Obra · jefe',
      },
      // 5 — Guardar
      {
        when: function () { return pathIs(/\/admin\/create_obra/); },
        selector: '[data-tour="obra-guardar"]',
        title: 'Crear obra',
        body: 'Pulsa Crear obra. Si activaste fichaje, después probaremos a fichar como el operario.',
        progress: 'Obra · guardar',
        waitClick: true,
        onShow: function () {
          var form = qs('#createObraForm');
          if (!form) return;
          form.addEventListener('submit', function () {
            var st = loadState();
            if (st) {
              st.createdObraNombre = ((qs('input[name="nombre"]') || {}).value || '').trim();
              st.pendingComplete = true;
              st.step = 6;
              saveState(st);
            }
          }, { once: true });
        },
      },
      // 6 — Fin obra → fichaje o pausa
      {
        when: function () {
          var st = loadState();
          return !!(st && st.pendingComplete);
        },
        title: '',
        body: '',
        onShow: function () {
          var st = loadState() || {};
          if (st.mode === 'solo') {
            st.pendingComplete = false;
            saveState(st);
            finishSoloAndReturn('Obra creada. Sigue reuniendo material o abre el siguiente tutorial.');
            return;
          }
          if (st.wantFichaje) {
            st.pendingComplete = false;
            st.chapter = 'fichaje';
            st.step = 0;
            st.active = true;
            st.fromGuide = true;
            st.mode = 'full';
            saveState(st);
            run();
            return;
          }
          st.pendingComplete = false;
          saveState(st);
          askFleetOrPause();
        },
      },
      // Import obras
      {
        when: function () {
          var st = loadState();
          return st && (st.step || 0) >= 10 && pathIs(/\/admin\/import_obras/);
        },
        selector: 'main',
        title: 'Importar obras',
        body: 'Sube el Excel de obras. Cuando termines, si activaste fichaje seguiremos con una prueba de entrada.',
        progress: 'Importar obras',
        nextLabel: 'Continuar',
        onNext: function () {
          var st = loadState() || {};
          if (st.wantFichaje) {
            saveState({
              active: true,
              chapter: 'fichaje',
              step: 0,
              wantFichaje: true,
              createdDni: st.createdDni,
              createdPin: st.createdPin,
              createdObraNombre: st.createdObraNombre,
              mode: st.mode,
              returnTo: st.returnTo,
            });
            run();
            return;
          }
          askFleetOrPause();
        },
      },
    ];
  }

  function stepsFichaje() {
    return [
      // 0 — Intro en admin
      {
        when: function () { return !isMiEntrar() && !isMiFichar() && !pathIs(/\/sync\/auditoria/); },
        modal: true,
        title: 'Prueba el fichaje del operario',
        body: 'Vas a entrar en /mi con el DNI y el PIN. Ficharás en <strong>Oficina</strong> y luego veremos auditoría.',
        progress: 'Fichaje · empezar',
        primaryHref: '/admin/tour/fichaje-probar?chapter=fichaje',
        primaryLabel: 'Ir a fichar como operario',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.chapter = 'fichaje';
          st.step = 1;
          st.active = true;
          st.wantFichaje = true;
          st.ficharOficina = true;
          saveState(st);
        },
      },
      // 1 — DNI
      {
        when: function () { return isMiEntrar(); },
        selector: '[data-tour="fichar-dni"], #dni',
        title: 'DNI del operario',
        body: 'Introduce el DNI del usuario que acabas de crear.',
        progress: 'Fichaje · DNI',
        nextLabel: 'Siguiente',
        onShow: function () {
          prefillLoginField('dni');
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) p.innerHTML = fillCredsHint('dni');
          }
        },
      },
      // 2 — PIN
      {
        when: function () { return isMiEntrar(); },
        selector: '[data-tour="fichar-pin"], #pin',
        title: 'PIN de fichaje',
        body: 'Introduce el PIN del usuario que acabas de crear.',
        progress: 'Fichaje · PIN',
        nextLabel: 'Siguiente',
        onShow: function () {
          prefillLoginField('pin');
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) p.innerHTML = fillCredsHint('pin');
          }
        },
      },
      // 3 — Entrar
      {
        when: function () { return isMiEntrar(); },
        selector: '[data-tour="fichar-submit"]',
        title: 'Entrar a fichar',
        body: 'Con DNI y PIN listos, pulsa Entrar para abrir la pantalla de fichaje.',
        progress: 'Fichaje · acceso',
        waitClick: true,
        nextLabel: 'Ya entré →',
        advanceTo: 4,
        onShow: function () {
          // Asegurar credenciales antes de enviar
          prefillLoginField('dni');
          prefillLoginField('pin');
          var form = qs('[data-tour="fichar-login"]') || qs('form');
          if (!form) return;
          form.addEventListener('submit', function () {
            var cur = loadState();
            if (cur) { cur.step = 4; cur.chapter = 'fichaje'; saveState(cur); }
          }, { once: true });
        },
      },
      // 4 — Elegir obra (tutorial: Oficina sí o sí)
      {
        when: function () { return isMiFichar() && fichajeEstado() === 'fuera'; },
        selector: '[data-tour="fichar-obra"], #obra',
        title: 'Dónde fichas',
        body: 'En el día a día aquí sale por defecto la obra en la que estás <strong>planificado</strong>. En este tutorial usamos <strong>Oficina</strong> para generar un desvío y verlo luego en auditoría.',
        progress: 'Fichaje · obra',
        onShow: function (el) {
          ensureOficinaSelected(8);
          selectOficinaInFichajeSelect(el || qs('[data-tour="fichar-obra"], #obra'));
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              p.innerHTML = 'Normalmente eliges (o te sale) la obra donde estás. Aquí, para el tutorial, dejamos <strong>Oficina</strong>.';
            }
          }
          setTimeout(function () { ensureOficinaSelected(4); }, 200);
        },
      },
      // 5 — Botón entrada
      {
        when: function () { return isMiFichar() && fichajeEstado() === 'fuera'; },
        selector: '[data-tour="fichar-entrada"], [data-tipo="entrada"]',
        title: 'Fichar entrada',
        body: 'Pulsa Entrar. Queda anotado en el libro de fichajes de la empresa.',
        progress: 'Fichaje · entrada',
        waitClick: true,
        advanceTo: 6,
        onShow: function (el) {
          ensureOficinaSelected(8);
          selectOficinaInFichajeSelect(qs('[data-tour="fichar-obra"], #obra') || el);
          if (!el) el = qs('[data-tour="fichar-entrada"], [data-tipo="entrada"]');
          if (!el) return;
          el.addEventListener('click', function () {
            ensureOficinaSelected(2);
            selectOficinaInFichajeSelect();
            var st = loadState();
            if (st) { st.step = 6; saveState(st); }
          }, true);
        },
      },
      // 6 — Éxito → volver al tablero
      {
        when: function () { return isMiFichar() && fichajeEstado() === 'dentro'; },
        modal: true,
        title: '¡Fichaje hecho!',
        body: 'Volvemos al tablero para ver el resultado del fichaje.',
        progress: 'Fichaje · listo',
        primaryHref: '/mi/tour-volver-admin',
        primaryLabel: 'Ver en el tablero',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.step = 7;
          st.chapter = 'fichaje';
          st.active = true;
          saveState(st);
        },
        onShow: function () {
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              p.innerHTML = 'Has fichado en <strong>Oficina</strong>. En el tablero verás la marca según encaje o no con el plan; en auditoría resolvemos el desvío.';
            }
          }
        },
      },
      // 7 — Tablero: chip en la obra + pelota
      {
        when: function () {
          return !pathIs(/\/sync\/auditoria/) && (
            pathIs(/\/admin\/obras_detailed/) ||
            (new URLSearchParams(window.location.search || '')).get('tour') === 'fichaje_done'
          );
        },
        manualTarget: true,
        title: 'En la obra',
        body: 'El operario está en la obra (no en libres).',
        progress: 'Fichaje · tablero',
        nextLabel: 'Siguiente',
        onShow: function () {
          highlightWorkerChip();
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              var focus = qs('.sp-tour-highlight-user') || qs('.worker-chip.sp-tour-target');
              var red = focus && focus.querySelector('.dot-danger');
              var green = focus && focus.querySelector('.dot-success, .dot-auto');
              if (!red && !green) {
                red = qs('.kanban-col .worker-chip .dot-danger');
                green = qs('.kanban-col .worker-chip .dot-success, .kanban-col .worker-chip .dot-auto');
              }
              if (red) {
                p.innerHTML = 'La marca está en <strong>rojo</strong>: fichó sin estar planificado (o hay conflicto). En el siguiente paso lo revisamos en Auditoría de fichajes.';
              } else if (green) {
                p.innerHTML = 'La marca está en <strong>verde</strong>: el fichaje encaja con la planificación.';
              } else {
                p.innerHTML = 'El operario está en la obra. Mira el punto de color: <strong>rojo</strong> = revisar en auditoría; <strong>verde</strong> = correcto.';
              }
            }
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 8;
          saveState(st);
          run();
        },
      },
      // 8 — Menú: el usuario pulsa Auditoría fichajes
      {
        when: function () {
          return !pathIs(/\/sync\/auditoria/) && (
            pathIs(/\/admin\/obras_detailed/) ||
            (new URLSearchParams(window.location.search || '')).get('tour') === 'fichaje_done'
          );
        },
        selector: '[data-tour="nav-auditoria-fichajes"]',
        title: 'Auditoría de fichajes',
        body: 'Pulsa <strong>Auditoría fichajes</strong> en el menú (sección Jornada). Ahí revisas fichajes sin planificar, desviaciones y ausencias.',
        progress: 'Fichaje · menú',
        waitClick: true,
        advanceTo: 9,
        ifMissing: 'wait',
        onShow: function (el) {
          if (el) {
            try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
          }
        },
      },
      // 9 — Sección de auditoría (desviación o sin planificar)
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && !(st && (st.step || 0) >= 10);
        },
        manualTarget: true,
        title: 'Tu fichaje en auditoría',
        body: 'Abrimos la sección donde ha caído el fichaje y te explicamos cuál es.',
        progress: 'Fichaje · auditoría',
        nextLabel: 'Ver acciones →',
        onShow: function () {
          highlightAuditSection();
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 10;
          saveState(st);
          run();
        },
      },
      // 10 — Resolver fila (botones según sección)
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && !!(st && (st.step || 0) >= 10) && (st.step || 0) < 11;
        },
        manualTarget: true,
        title: 'Cómo resolverlo',
        body: 'Elige una acción sobre la fila.',
        progress: 'Fichaje · resolver',
        waitClick: true,
        nextLabel: 'Ya lo resolví →',
        onShow: function () {
          var info = resolveAuditTourSection();
          var advanced = false;
          function goNext() {
            if (advanced) return;
            advanced = true;
            var st = loadState() || {};
            st.step = 11;
            st.auditResolved = true;
            st.chapter = 'fichaje';
            st.active = true;
            st.fromGuide = true;
            st.mode = 'full';
            saveState(st);
            setTimeout(function () {
              // NO usar mode=solo: rompía la guía y saltaba la pregunta de flota
              window.location.href = '/sync/auditoria?tour=fichaje&continue=1';
            }, 700);
          }
          highlightAuditParacaidista(function (btn, buttons) {
            var list = (buttons && buttons.length) ? buttons : (btn ? [btn] : []);
            list.forEach(function (b) {
              b.addEventListener('click', goNext, true);
            });
          });
          if (ui.card) {
            var h = ui.card.querySelector('h3');
            var p = ui.card.querySelector('p');
            if (info && info.kind === 'desviaciones') {
              if (h) h.textContent = 'Desviaciones: tres acciones';
              if (p) {
                p.innerHTML =
                  '<strong>Mover</strong>: cambia el cuadrante a Oficina.<br>' +
                  '<strong>+ Añadir</strong>: mantiene la planificada y añade Oficina.<br>' +
                  '<strong>Ignorar</strong>: oculta la alerta sin tocar el plan.';
              }
            } else {
              if (h) h.textContent = 'Sin planificar: dos acciones';
              if (p) {
                p.innerHTML =
                  '<strong>Aceptar</strong>: asigna oficialmente a esa obra.<br>' +
                  '<strong>Ignorar</strong>: oculta la alerta sin cambiar el cuadrante.';
              }
            }
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 11;
          st.fromGuide = true;
          st.mode = 'full';
          saveState(st);
          run();
        },
      },
      // 11 — Fin → pregunta flota (recorrido completo)
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 11);
        },
        title: '',
        body: '',
        onShow: function () {
          var st = loadState() || {};
          st.fromGuide = true;
          st.mode = 'full';
          saveState(st);
          askFleetOrPause();
        },
      },
    ];
  }

  function isImportPage() {
    return pathIs(/\/admin\/import_(obras|users|companies)/);
  }

  function isImportUploadPage() {
    return isImportPage()
      && !pathIs(/\/preview/)
      && !pathIs(/\/confirm/)
      && !pathIs(/\/results/)
      && !qs('#import-confirm-form')
      && !qs('[data-tour="import-results"]');
  }

  function isPrimerosPasos() {
    return pathIs(/\/admin\/primeros-pasos/);
  }

  function stepsImport() {
    function ensureImportEntity() {
      var st = loadState() || {};
      if (st.importEntity) return st.importEntity;
      if (pathIs(/import_users/)) st.importEntity = 'users';
      else if (pathIs(/import_companies/)) st.importEntity = 'companies';
      else if (pathIs(/import_obras/)) st.importEntity = 'obras';
      else return '';
      saveState(st);
      return st.importEntity;
    }
    function stepNum(st) {
      return Number((st && st.step) || 0);
    }
    function isImportPreviewPage() {
      if (!isImportPage()) return false;
      if (pathIs(/\/preview/)) return true;
      // Fallback: UI de preview aunque la URL no traiga /preview
      return !!(qs('#import-confirm-form') || qs('[data-tour="import-confirm"]') || qs('[data-tour="import-preview-table"]'));
    }
    function isImportResultsPage() {
      if (!isImportPage()) return false;
      if (pathIs(/\/confirm/) || pathIs(/\/results/)) return true;
      return !!qs('[data-tour="import-results"]');
    }
    function importDestinationHref() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || '';
      if (ent === 'users') return '/admin/personal';
      if (ent === 'companies') return '/admin/companies';
      return '/admin/obras';
    }
    function importDestinationLabel() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || '';
      if (ent === 'users') return 'Trabajadores';
      if (ent === 'companies') return 'Empresas';
      return 'Directorio';
    }
    function importNavSelector() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || '';
      if (ent === 'users') return '[data-tour="nav-trabajadores"]';
      if (ent === 'companies') return '[data-tour="nav-empresas"]';
      return '[data-tour="nav-directorio"]';
    }
    function isImportDestinationPage() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || 'obras';
      if (ent === 'users') return pathIs(/\/admin\/personal/);
      if (ent === 'companies') return pathIs(/\/admin\/companies/);
      return pathIs(/\/admin\/obras(\/|$|\?)/) && !pathIs(/obras_detailed/);
    }
    function importDoneMap() {
      var fromWindow = window.__ONB_IMPORT_DONE__ || {};
      var fromStorage = {};
      try {
        fromStorage = JSON.parse(sessionStorage.getItem('signaplan_import_done') || '{}') || {};
      } catch (e) {
        fromStorage = {};
      }
      return {
        obras: !!(fromWindow.obras || fromStorage.obras),
        users_internos: !!(fromWindow.users_internos || fromStorage.users_internos),
        users_externos: !!(fromWindow.users_externos || fromStorage.users_externos),
        companies: !!(fromWindow.companies || fromStorage.companies),
      };
    }
    function currentImportDoneKey() {
      ensureImportEntity();
      var st = loadState() || {};
      if (st.importEntity === 'companies') return 'companies';
      if (st.importEntity === 'users') {
        return st.importMode === 'externos' ? 'users_externos' : 'users_internos';
      }
      return 'obras';
    }
    function markImportDoneClient(key) {
      if (!key) key = currentImportDoneKey();
      var m = importDoneMap();
      m[key] = true;
      window.__ONB_IMPORT_DONE__ = m;
      try { sessionStorage.setItem('signaplan_import_done', JSON.stringify(m)); } catch (e) {}
    }
    function importListExplainTitle() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || 'obras';
      if (ent === 'users') return 'Personal importado';
      if (ent === 'companies') return 'Empresas importadas';
      return 'Obras importadas';
    }
    function importListExplainBody() {
      ensureImportEntity();
      var st = loadState() || {};
      var ent = st.importEntity || 'obras';
      if (ent === 'users') {
        return 'Este es el listado de personal que acabas de importar. Cada fila es una persona.';
      }
      if (ent === 'companies') {
        return 'Este es el listado de empresas/subcontratas que acabas de importar. Cada fila es una empresa.';
      }
      return 'Este es el listado de obras que acabas de importar. Cada fila es una obra.';
    }

    return [
      {
        when: function () { return !isImportPage() && !isImportDestinationPage(); },
        modal: true,
        choicesLayout: 'stack',
        noSkipSection: true,
        title: 'Importar desde Excel',
        body: 'Elige qué listado quieres subir. Los que ya hayas importado aparecen con un tick.',
        progress: 'Importar · empezar',
        choices: [
          {
            label: 'Obras',
            done: !!importDoneMap().obras,
            onPick: function () {
              var st = loadState() || {};
              st.step = 1;
              st.chapter = 'import';
              st.active = true;
              st.importEntity = 'obras';
              st.importMode = null;
              saveState(st);
              window.location.href = '/admin/import_obras?desde=primeros-pasos';
            },
          },
          {
            label: 'Personal interno',
            done: !!importDoneMap().users_internos,
            onPick: function () {
              var st = loadState() || {};
              st.step = 1;
              st.importEntity = 'users';
              st.importMode = 'internos';
              saveState(st);
              window.location.href = '/admin/import_users?modo=internos&desde=primeros-pasos';
            },
          },
          {
            label: 'Personal externo',
            done: !!importDoneMap().users_externos,
            onPick: function () {
              var st = loadState() || {};
              st.step = 1;
              st.importEntity = 'users';
              st.importMode = 'externos';
              saveState(st);
              window.location.href = '/admin/import_users?modo=externos&desde=primeros-pasos';
            },
          },
          {
            label: 'Subcontratas / empresas externas',
            done: !!importDoneMap().companies,
            onPick: function () {
              var st = loadState() || {};
              st.step = 1;
              st.importEntity = 'companies';
              st.importMode = null;
              saveState(st);
              window.location.href = '/admin/import_companies?desde=primeros-pasos';
            },
          },
        ],
      },
      // 1 — Título + explicación juntos (lo que hay que leer)
      {
        when: function () {
          var st = loadState();
          return isImportUploadPage() && st && stepNum(st) <= 1;
        },
        selector: '[data-tour="import-intro"]',
        noSkipSection: true,
        title: 'Lee la explicación de la página',
        body: 'En la zona resaltada está qué hace esta importación y qué columnas hacen falta. Léelo ahí. Luego pulsa el botón azul <strong>Siguiente</strong>.',
        progress: 'Importar · explicación',
        ifMissing: 'wait',
        nextLabel: 'Siguiente',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      // 2 — Archivo
      {
        when: function () {
          var st = loadState();
          return isImportUploadPage() && st && stepNum(st) === 2;
        },
        selector: '[data-tour="import-file-zone"]',
        noSkipSection: true,
        title: 'Elige el archivo',
        body: 'Selecciona el Excel o CSV. Al elegirlo, te llevamos al botón Continuar.',
        progress: 'Importar · archivo',
        ifMissing: 'wait',
        nextLabel: 'Ya lo elegí →',
        onShow: function () {
          var input = qs('[data-tour="import-file"]') || qs('#file');
          if (!input) return;
          input.addEventListener('change', function () {
            if (!input.files || !input.files.length) return;
            var st = loadState() || {};
            st.step = 3;
            saveState(st);
            setTimeout(function () { run(); }, 200);
          }, { once: true });
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      // 3 — Continuar
      {
        when: function () {
          var st = loadState();
          return isImportUploadPage() && st && stepNum(st) >= 3 && stepNum(st) < 4;
        },
        selector: '[data-tour="import-submit"]',
        noSkipSection: true,
        title: 'Continuar',
        body: 'Pulsa <strong>Continuar</strong> para mapear columnas y ver la vista previa.',
        progress: 'Importar · subir',
        waitClick: true,
        advanceTo: 4,
        ifMissing: 'wait',
        nextLabel: 'Ya continué →',
        onShow: function (el) {
          if (!el) return;
          el.addEventListener('click', function () {
            var st = loadState();
            if (st) { st.step = 4; saveState(st); }
          }, { once: true });
        },
      },
      // 4 — Preview: Revisar (banner)
      {
        when: function () {
          var st = loadState();
          return isImportPreviewPage() && st && stepNum(st) === 4;
        },
        modal: true,
        reviewMode: true,
        noSkipSection: true,
        title: 'Revisa el listado',
        body: 'Pulsa <strong>Revisar</strong> para quitar este cartel y trabajar con la tabla. Puedes desticar filas que no quieras importar. Quedará una barra arriba; cuando acabes, <strong>Volver a la guía</strong>.',
        progress: 'Importar · asistente',
        reviewLabel: 'Revisar →',
        nextLabel: 'Terminar guía →',
        bannerTitle: 'Guía en pausa',
        bannerBody: 'Revisa el mapeo, destica lo que no quieras y, cuando estés listo, vuelve a la guía para confirmar.',
        onResumeFromBanner: function () {
          var st = loadState() || {};
          st.step = 5;
          saveState(st);
          run();
        },
        onNext: function () {
          hideTourBanner();
          pauseAtChapterEnd();
        },
      },
      // 5 — Confirmar importación (spotlight en el botón + mensaje siempre a la vista)
      {
        when: function () {
          var st = loadState();
          if (!(st && stepNum(st) === 5)) return false;
          return isImportPreviewPage()
            || !!qs('[data-tour="import-confirm"]')
            || !!qs('#import-confirm-form');
        },
        selector: '[data-tour="import-confirm"]',
        manualTarget: true,
        noSkipSection: true,
        title: 'Confirma la importación',
        body: 'Pulsa el botón resaltado <strong>Confirmar importación</strong> (solo las filas ticadas). Si prefieres no confirmar ahora, usa <strong>Saltar</strong>.',
        progress: 'Importar · confirmar',
        waitClick: true,
        advanceTo: 6,
        ifMissing: 'wait',
        nextLabel: 'Saltar →',
        onShow: function () {
          var btn = qs('[data-tour="import-confirm"]');
          spotlightWithCard(btn);
          if (btn) bindNavClick(btn, 6);
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      // 6 — Resumen (tras confirmar de verdad)
      {
        when: function () {
          var st = loadState();
          return isImportResultsPage() && st && stepNum(st) === 6;
        },
        selector: '[data-tour="import-results"]',
        noSkipSection: true,
        title: 'Resumen de lo importado',
        body: 'Aquí tienes el resultado: creados, duplicados u omitidos. Pulsa <strong>Siguiente</strong> para ir al listado en el menú.',
        progress: 'Importar · resumen',
        ifMissing: 'wait',
        nextLabel: 'Siguiente',
        onShow: function (el) {
          markImportDoneClient();
          if (el) spotlightWithCard(el);
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      // 7 — Navbar: Directorio / Trabajadores / Empresas
      {
        when: function () {
          var st = loadState();
          if (!(st && stepNum(st) === 7)) return false;
          if (isImportDestinationPage()) return false;
          return isImportResultsPage() || isImportPreviewPage() || isImportPage()
            || !!qs('[data-tour="import-confirm"]') || !!qs('[data-tour="import-results"]');
        },
        selector: '[data-tour="nav-directorio"]',
        manualTarget: true,
        noSkipSection: true,
        title: function () { return 'Ve a ' + importDestinationLabel(); },
        body: function () {
          return 'En el menú de la <strong>izquierda</strong>, pulsa <strong>' +
            importDestinationLabel() +
            '</strong> para ver el listado.';
        },
        progress: 'Importar · menú',
        waitClick: true,
        advanceTo: 8,
        ifMissing: 'wait',
        nextLabel: 'Ya estoy →',
        onShow: function () {
          var el = qs(importNavSelector()) || qs('[data-tour="nav-directorio"]');
          spotlightWithCard(el);
          if (el) bindNavClick(el, 8);
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 8;
          saveState(st);
          window.location.href = importDestinationHref();
        },
      },
      // 8 — Explicación del listado (mensaje SIEMPRE visible + listado resaltado)
      {
        when: function () {
          var st = loadState();
          return !!(st && stepNum(st) === 8 && isImportDestinationPage());
        },
        selector: '[data-tour="import-list-dest"], #obrasTable, main .admin-data-table, main',
        manualTarget: true,
        noSkipSection: true,
        title: function () { return importListExplainTitle(); },
        body: function () { return importListExplainBody(); },
        progress: 'Importar · listado',
        ifMissing: 'wait',
        nextLabel: 'Volver a primeros pasos →',
        onShow: function () {
          markImportDoneClient();
          // Preferir la tabla real: el wrapper .admin-table-scroll suele ser mucho más alto
          var el = qs('#obrasTable')
            || qs('[data-tour="import-list-dest"] table')
            || qs('main .admin-data-table')
            || qs('[data-tour="import-list-dest"]')
            || qs('main');
          ensureUi();
          if (ui.card) ui.card.style.display = '';
          if (el) {
            el.classList.add('sp-tour-target');
            try { el.scrollIntoView({ block: 'nearest', behavior: 'auto' }); } catch (e) {}
            placeHoleForList(el);
          } else {
            placeHole(null);
          }
          // Mensaje centrado, por encima del listado
          ui.card.classList.remove('is-modal');
          ui.card.style.transform = 'translateX(-50%)';
          ui.card.style.top = '18%';
          ui.card.style.left = '50%';
          ui.card.style.width = Math.min(380, window.innerWidth - 32) + 'px';
          ui.card.style.zIndex = '12060';
        },
        onNext: function () {
          markImportDoneClient();
          var st = loadState() || {};
          st.step = 0;
          st.chapter = 'import';
          st.active = true;
          saveState(st);
          window.location.href = '/admin/primeros-pasos?tour=import';
        },
      },
    ];
  }

  function stepsDemo() {
    return [
      {
        when: function () {
          return pathIs(/\/admin\/obras_detailed/) ||
            (new URLSearchParams(window.location.search || '')).get('tour') === 'demo';
        },
        manualTarget: true,
        title: 'Tablero con datos de ejemplo',
        body: 'Esto es el día a día: obras y gente planificada. Son datos demo — puedes mover, fichar y romper sin miedo.',
        progress: 'Demo · tablero',
        nextLabel: 'Siguiente',
        onShow: function () {
          var main = qs('main') || qs('.admin-main');
          if (main && _visibleRect(main)) {
            placeHole(main.querySelector('.kanban, .obras-detailed, .tablero') || main);
            placeCardNear(main);
          } else {
            placeCardModal();
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 1;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          return !pathIs(/\/admin\/obras(\/|$|\?)/) && !pathIs(/\/admin\/personal/) &&
            !pathIs(/\/sync\/auditoria/);
        },
        selector: '[data-tour="nav-directorio"]',
        title: 'Directorio de obras',
        body: 'Desde aquí gestionas el catálogo de obras (crear, importar, archivar). Pulsa Directorio.',
        progress: 'Demo · directorio',
        waitClick: true,
        advanceTo: 2,
        ifMissing: 'wait',
      },
      {
        when: function () { return pathIs(/\/admin\/obras(\/|$|\?)/); },
        selector: 'main',
        title: 'Listado de obras',
        body: 'Aquí están las obras demo. Más adelante crearás las tuyas reales o las importarás desde Excel.',
        progress: 'Demo · obras',
        nextLabel: 'Ver trabajadores →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () { return !pathIs(/\/admin\/personal/) && !pathIs(/\/sync\/auditoria/); },
        selector: '[data-tour="nav-trabajadores"]',
        title: 'Trabajadores',
        body: 'Plantilla interna y externa. Pulsa Trabajadores para ver los operarios de ejemplo.',
        progress: 'Demo · personal',
        waitClick: true,
        advanceTo: 4,
        ifMissing: 'wait',
      },
      {
        when: function () { return pathIs(/\/admin\/personal/); },
        selector: 'main',
        title: 'Tu plantilla demo',
        body: 'Cada operario puede tener PIN para fichar en /mi. En la guía interactiva lo harás con uno real tuyo.',
        progress: 'Demo · plantilla',
        nextLabel: 'Ver auditoría →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 5;
          saveState(st);
          run();
        },
      },
      {
        when: function () { return !pathIs(/\/sync\/auditoria/); },
        selector: '[data-tour="nav-auditoria-fichajes"]',
        title: 'Auditoría de fichajes',
        body: 'Aquí revisas fichajes sin planificar, desviaciones y ausencias. Pulsa Auditoría fichajes.',
        progress: 'Demo · auditoría',
        waitClick: true,
        advanceTo: 6,
        ifMissing: 'skip',
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) || (st && (st.step || 0) >= 6 && (st.step || 0) < 7);
        },
        modal: true,
        title: 'Listo para explorar',
        body: 'Con el mapa claro: tablero, directorio, trabajadores y auditoría. Sigue toqueteando o entra al tablero y cierra Primeros pasos.',
        progress: 'Demo · fin',
        nextLabel: 'Terminar guía →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 7);
        },
        title: '',
        body: '',
        onShow: function () {
          pauseAtChapterEnd();
        },
      },
    ];
  }

  function stepsTableroBasico() {
    return [
      {
        when: function () { return !pathIs(/\/admin\/obras_detailed/) && !pathIs(/\/jefe\/obras_detailed/); },
        selector: '[data-tour="nav-tablero"], a[href*="obras_detailed"]',
        title: 'Ve al Tablero',
        body: 'Pulsa <strong>Tablero</strong> en el menú. Ahí ves obras y gente día a día.',
        progress: 'Tablero · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) < 2;
        },
        selector: '[data-tour="tablero-fecha"], .timeline-header-wrapper',
        title: 'El día que estás viendo',
        body: 'Arriba eliges la fecha: te posicionas en el día cuyos datos quieres ver. Usa las cápsulas o el selector; el tablero se actualiza con ese día.',
        progress: 'Tablero · fecha',
        nextLabel: 'Siguiente →',
        noScroll: true,
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 2 && (st.step || 0) < 3;
        },
        selector: '[data-tour="tablero-libres"], .kanban-libres-panel',
        title: 'Operarios libres',
        body: 'Aquí están las personas sin obra ese día. Desde esta columna las arrastras para asignarlas.',
        progress: 'Tablero · libres',
        nextLabel: 'Siguiente →',
        noScroll: true,
        onShow: function (el) {
          if (!el) return;
          // No tocar sticky: solo agujero + tip a la derecha
          requestAnimationFrame(function () {
            placeHole(el);
            placeCardNear(el);
          });
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 3 && (st.step || 0) < 4;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Las obras del día',
        body: 'A la derecha están las obras en curso. Cada columna es una obra; dentro verás quién está asignado ese día.',
        progress: 'Tablero · obras',
        nextLabel: 'Siguiente →',
        onShow: function () {
          clearTargets();
          var wrap = qs('#kanbanWorksWrapper');
          var scrollLeft = wrap ? wrap.scrollLeft : 0;
          var scrollTop = wrap ? wrap.scrollTop : 0;
          var pageScroll = window.scrollY || document.documentElement.scrollTop || 0;
          var obras = Array.prototype.slice.call(
            document.querySelectorAll('#kanbanWorksWrapper > .kanban-col-wrapper, #kanbanWorksWrapper > .obra-card, #kanbanWorksWrapper > .kanban-col'),
            0,
            3
          );
          // Solo las 3 primeras obras visibles; sin libres ni scroll
          placeHoleUnion(obras, { clampViewport: true, minTop: 72 });
          placeCardClearOfKanban();
          if (wrap) {
            wrap.scrollLeft = scrollLeft;
            wrap.scrollTop = scrollTop;
          }
          try { window.scrollTo(0, pageScroll); } catch (e) { /* ignore */ }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 4;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 4 && (st.step || 0) < 5;
        },
        manualTarget: true,
        title: 'Asigna arrastrando',
        body: 'Arrastra un operario libre hasta una obra. Al soltarlo se abre el calendario de asignación.',
        progress: 'Tablero · arrastrar',
        nextLabel: 'Ya lo arrastré →',
        requireGate: function () {
          var modal = qs('#assignmentModal');
          return !!(modal && modal.classList.contains('show'));
        },
        gateRetry: true,
        gateFail: 'Aún no se ha abierto el calendario. Arrastra un operario libre hasta una obra y suéltalo ahí.',
        onShow: function () {
          clearTargets();
          var chip = qs('#list-libres-body .worker-chip');
          var obraCol = qs('#kanbanWorksWrapper .kanban-col, #kanbanWorksWrapper .obra-card');
          var drop = obraCol
            ? (obraCol.querySelector('.worker-list-body') || obraCol)
            : null;
          if (chip) chip.classList.add('sp-tour-target');
          if (drop) drop.classList.add('sp-tour-target');
          if (chip || drop) {
            placeHoleUnion([chip, drop || obraCol]);
          } else {
            placeHole(qs('#kanbanContainer') || qs('main'));
          }
          // Tip fuera de la obra destino para no tapar el drop
          placeCardClearOfKanban();
          var advanced = false;
          function goNext() {
            if (advanced) return;
            advanced = true;
            try {
              if (window.jQuery) {
                window.jQuery(document).off('shown.bs.modal.spTourTablero');
              }
            } catch (e) { /* ignore */ }
            var st = loadState() || {};
            st.step = 5;
            saveState(st);
            run();
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('shown.bs.modal.spTourTablero');
              window.jQuery(document).on(
                'shown.bs.modal.spTourTablero',
                '#assignmentModal',
                goNext
              );
            }
          } catch (e2) { /* ignore */ }
        },
        onNext: function () {
          try {
            if (window.jQuery) {
              window.jQuery(document).off('shown.bs.modal.spTourTablero');
            }
          } catch (e) { /* ignore */ }
          var st = loadState() || {};
          st.step = 5;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 5 && (st.step || 0) < 6;
        },
        selector: '#assignmentModal.show #modal-calendar-container, #modal-calendar-container',
        title: 'Calendario de la obra',
        body: 'Se abre el <strong>calendario de la obra</strong>: ves al resto de gente ya asignada a esa obra y en qué días. Así encajas la nueva asignación sin pisar a nadie.',
        progress: 'Tablero · calendario',
        nextLabel: 'Siguiente →',
        noScroll: true,
        requireGate: function () {
          var modal = qs('#assignmentModal');
          return !!(modal && modal.classList.contains('show'));
        },
        gateFail: 'El calendario ya no está abierto. Sin verlo la guía no puede continuar.',
        onShow: function (el) {
          var modal = qs('#assignmentModal');
          if (modal && modal.classList.contains('show') && el) {
            el.classList.add('sp-tour-target');
            placeHole(el);
            placeCardNear(el);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 6;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 6 && (st.step || 0) < 7;
        },
        manualTarget: true,
        title: 'Bloque «Nueva asignación»',
        body: 'Ese bloque es lo que acabas de crear. Si quieres, arrástralo a otro día o <strong>estira un borde</strong> para cubrir varios días. Si te vale el día actual, pulsa Siguiente.',
        progress: 'Tablero · bloque',
        nextLabel: 'Siguiente →',
        onShow: function () {
          clearTargets();
          window.__spTourGhostAdjusted = false;
          var cal = qs('#assignmentModal #modal-calendar-container, #modal-calendar-container');
          var ghost = qs('#assignmentModal .fc-ghost-event, .fc-ghost-event');
          var startInput = qs('#assignmentModal [id$="-start"], .univ-calendar-panel [id$="-start"]');
          var endInput = qs('#assignmentModal [id$="-end"], .univ-calendar-panel [id$="-end"]');
          var initial = {
            s: startInput ? startInput.value : '',
            e: endInput ? endInput.value : '',
            w: ghost ? ghost.getBoundingClientRect().width : 0,
            l: ghost ? ghost.getBoundingClientRect().left : 0,
          };
          if (ghost) {
            ghost.classList.add('sp-tour-target');
            placeHole(ghost);
          } else if (cal) {
            placeHole(cal);
          } else {
            placeHole(null);
          }
          // Comentario fuera del calendario (no tapa el bloque ni el grid)
          placeCardOutside(cal || ghost);

          function expandToCalendar() {
            if (cal) {
              clearTargets();
              cal.classList.add('sp-tour-target');
              placeHole(cal);
              placeCardOutside(cal);
            }
          }
          if (cal) {
            cal.addEventListener('mousedown', function (ev) {
              if (ev.target && ev.target.closest &&
                  ev.target.closest('.fc-ghost-event, .fc-event-resizer, .fc-event')) {
                expandToCalendar();
              }
            }, { once: false });
          }

          var advanced = false;
          function goNext() {
            if (advanced) return;
            advanced = true;
            window.__spTourGhostAdjusted = true;
            if (window.__spTourGhostPoll) {
              clearInterval(window.__spTourGhostPoll);
              window.__spTourGhostPoll = null;
            }
            var st = loadState() || {};
            st.step = 7;
            saveState(st);
            run();
          }
          if (window.__spTourGhostPoll) clearInterval(window.__spTourGhostPoll);
          window.__spTourGhostPoll = setInterval(function () {
            var g = qs('#assignmentModal .fc-ghost-event, .fc-ghost-event');
            var sEl = qs('#assignmentModal [id$="-start"], .univ-calendar-panel [id$="-start"]');
            var eEl = qs('#assignmentModal [id$="-end"], .univ-calendar-panel [id$="-end"]');
            var changed = false;
            if (sEl && sEl.value !== initial.s) changed = true;
            if (eEl && eEl.value !== initial.e) changed = true;
            if (g && initial.w) {
              var r = g.getBoundingClientRect();
              if (Math.abs(r.width - initial.w) > 12 || Math.abs(r.left - initial.l) > 12) {
                changed = true;
                expandToCalendar();
              }
            }
            if (changed) goNext();
          }, 280);
        },
        onNext: function () {
          if (window.__spTourGhostPoll) {
            clearInterval(window.__spTourGhostPoll);
            window.__spTourGhostPoll = null;
          }
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 7 && (st.step || 0) < 8;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Panel Nueva asignación',
        body: 'Abajo tienes el panel de la nueva asignación: fechas, destino y opciones. Si quieres, puedes <strong>añadir más trabajadores</strong> (compañeros) a esta misma asignación. Si el rango incluye sábado o domingo, activa <strong>Asignar fines de semana</strong>.',
        progress: 'Tablero · panel',
        nextLabel: 'Siguiente →',
        requireGate: function () {
          var modal = qs('#assignmentModal');
          return !!(modal && modal.classList.contains('show'));
        },
        gateFail: 'El calendario ya no está abierto. Sin el panel la guía no puede continuar.',
        onShow: function () {
          clearTargets();
          var panel = qs('#assignmentModal .univ-calendar-panel, .univ-calendar-panel');
          if (panel) {
            panel.style.display = 'block';
            panel.classList.add('sp-tour-target');
            placeHole(panel);
            placeCardNear(panel);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 8;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/obras_detailed/) && (st.step || 0) >= 8 && (st.step || 0) < 9;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Guarda con el tic',
        body: 'Pulsa el <strong>tic verde</strong> <i class="fas fa-check"></i> para guardar. Sin ese clic la asignación no se aplica.',
        progress: 'Tablero · guardar',
        nextLabel: 'Ya guardé →',
        waitClick: true,
        requireGate: function () {
          var modal = qs('#assignmentModal');
          return !!(modal && modal.classList.contains('show')) || !!window.__spTourTableroSaved;
        },
        gateFail: 'Todavía no has guardado. Pulsa el tic verde; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          window.__spTourTableroSaved = false;
          var panel = qs('#assignmentModal .univ-calendar-panel, .univ-calendar-panel');
          var save = qs('#assignmentModal [id$="-save"], .univ-calendar-panel [id$="-save"]');
          if (panel) panel.style.display = 'block';
          if (save) {
            save.classList.add('sp-tour-target');
            placeHole(save);
            placeCardNear(panel || save);
            save.addEventListener('click', function () {
              window.__spTourTableroSaved = true;
              var st = loadState() || {};
              st.step = 9;
              saveState(st);
              setTimeout(function () { run(); }, 400);
            }, { once: true });
          } else if (panel) {
            panel.classList.add('sp-tour-target');
            placeHole(panel);
            placeCardNear(panel);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var save = qs('#assignmentModal [id$="-save"], .univ-calendar-panel [id$="-save"]');
          if (save) {
            try { save.click(); } catch (e) { /* ignore */ }
            window.__spTourTableroSaved = true;
          }
          var st = loadState() || {};
          st.step = 9;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 9);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function findTourPlanifBarEl(opts) {
    opts = opts || {};
    var doFocus = !!opts.focus;
    var id = window.__spTourPlanifItemId;
    var sel = window.currentSelectedItem;
    if (id == null && sel && sel.id != null) id = sel.id;

    function isRealAssignment(item) {
      if (!item) return false;
      var wid = String(item.worker_id || '');
      if (!wid || wid === 'NEW' || wid === 'SYSTEM' || wid === 'REQUEST') return false;
      if (item.type === 'background') return false;
      return true;
    }

    // Solo la barra que el usuario acaba de abrir — nunca “la última” de esa persona
    var item = null;
    if (id != null && window.AppItems && window.AppItems.get) {
      try { item = window.AppItems.get(id); } catch (e) { item = null; }
    }
    if (!isRealAssignment(item) && sel && isRealAssignment(sel)) {
      item = sel;
      id = sel.id;
    }
    if (!isRealAssignment(item)) return null;

    var byId = document.querySelector('.vis-item[data-id="' + item.id + '"]');
    if (doFocus && byId) {
      try {
        byId.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'auto' });
      } catch (e2) { /* ignore */ }
      try {
        if (window.AppTimeline && item.start && typeof window.AppTimeline.moveTo === 'function') {
          var mid = new Date(
            (new Date(item.start).getTime() + new Date(item.end || item.start).getTime()) / 2
          );
          window.AppTimeline.moveTo(mid, { animation: false });
        }
      } catch (e3) { /* ignore */ }
      byId = document.querySelector('.vis-item[data-id="' + item.id + '"]') || byId;
    }
    return byId;
  }

  // Compat: el nombre antiguo se usaba en varios sitios
  function findLastPlanifAssignmentEl(opts) {
    return findTourPlanifBarEl(opts);
  }

  function planifQuickCalOpen() {
    var modal = qs('#quickCalendarModal');
    return !!(modal && (modal.classList.contains('show') || modal.style.display === 'block'));
  }

  function planifPhantomExists() {
    if (document.querySelector('.vis-item.phantom-item, .phantom-item')) return true;
    try {
      if (window.AppItems && window.AppItems.get && window.AppItems.get('phantom_new')) return true;
    } catch (e) { /* ignore */ }
    return false;
  }

  function stepsPlanificadorMulti() {
    return [
      {
        when: function () { return !pathIs(/\/admin\/planificador/); },
        selector: '[data-tour="nav-planificador"], a[href*="planificador"]',
        title: 'Abre el Planificador',
        body: 'Pulsa <strong>Planificador</strong>. Es la vista de varias personas y varios días.',
        progress: 'Planificador · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) < 2;
        },
        selector: '[data-tour="planif-filtros"], .planificador-filters',
        title: 'Filtros de arriba',
        body: 'Puedes filtrar por <strong>empresas</strong>, por <strong>jefe de obra</strong> (solo verás las obras de ese jefe) o por obras concretas. Así acotas el mapa antes de planificar.',
        progress: 'Planificador · filtros',
        nextLabel: 'Siguiente →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 2 && (st.step || 0) < 3;
        },
        manualTarget: true,
        title: 'Cómo se lee el cuadrante',
        body: 'A la <strong>izquierda</strong> van las obras (eje vertical). Arriba van las <strong>fechas</strong> (eje horizontal). En el centro aparecen las asignaciones: si alguien está en una obra un día, su barra está en esa celda.',
        progress: 'Planificador · ejes',
        nextLabel: 'Siguiente →',
        onShow: function () {
          clearTargets();
          var root = qs('[data-tour="planif-grid"], #planificador-calendar');
          // No añadir sp-tour-target a .vis-panel (rompe position:absolute de vis.js)
          // No scroll: el usuario debe conservar el contexto del cuadrante
          if (root) {
            placeHole(root);
            placeCardNear(root);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
          try {
            if (window.AppTimeline && typeof window.AppTimeline.redraw === 'function') {
              setTimeout(function () { window.AppTimeline.redraw(); }, 50);
            }
          } catch (e2) { /* ignore */ }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 3 && (st.step || 0) < 4;
        },
        manualTarget: true,
        title: 'Abre una asignación',
        body: 'Haz <strong>clic</strong> en una barra de color del cuadrante (una persona en una obra). Se abrirá su ficha rápida.',
        progress: 'Planificador · clic',
        nextLabel: 'Ya hice clic →',
        requireGate: function () {
          var pop = qs('#worker-popover');
          return !!(pop && !pop.classList.contains('d-none'));
        },
        gateFail: 'No se ha abierto la ficha del trabajador. Haz clic en una barra del cuadrante; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          var item = qs('.vis-item.vis-range:not(.vis-item-visible-frame), .vis-item.vis-range, .vis-item');
          if (item) {
            try { item.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
            placeHole(item);
            placeCardNear(item);
          } else {
            var root = qs('#planificador-calendar');
            placeHole(root);
            placeCardNear(root);
          }
          var advanced = false;
          function goNext() {
            if (advanced) return;
            var pop = qs('#worker-popover');
            if (pop && pop.classList.contains('d-none')) return;
            // Solo avanzamos con asignación real de persona (no solicitudes / sistema)
            var sel = window.currentSelectedItem;
            var wid = sel ? String(sel.worker_id || '') : '';
            if (!sel || !wid || wid === 'NEW' || wid === 'SYSTEM' || wid === 'REQUEST') {
              return;
            }
            advanced = true;
            try {
              window.__spTourPlanifItemId = sel.id;
            } catch (eId) { /* ignore */ }
            try {
              if (window.jQuery) window.jQuery(document).off('click.spTourPlanif');
            } catch (e) { /* ignore */ }
            var st = loadState() || {};
            st.step = 4;
            saveState(st);
            run();
          }
          try {
            if (window.jQuery) {
              window.jQuery(document).off('click.spTourPlanif');
              window.jQuery(document).on('click.spTourPlanif', '.vis-item', function () {
                var id = this.getAttribute && this.getAttribute('data-id');
                if (id) window.__spTourPlanifItemId = id;
                setTimeout(goNext, 150);
              });
            }
          } catch (e2) { /* ignore */ }
          // Poll por si el popover se abre sin el handler
          var tries = 0;
          var timer = setInterval(function () {
            tries += 1;
            var pop = qs('#worker-popover');
            if (pop && !pop.classList.contains('d-none')) {
              goNext();
              if (advanced) clearInterval(timer);
            }
            if (tries > 80) clearInterval(timer);
          }, 250);
        },
        onNext: function () {
          try {
            if (window.jQuery) window.jQuery(document).off('click.spTourPlanif');
          } catch (e) { /* ignore */ }
          var st = loadState() || {};
          st.step = 4;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 4 && (st.step || 0) < 5;
        },
        selector: '#worker-popover:not(.d-none), #worker-popover, .planificador-worker-popover',
        title: 'Ficha de la persona',
        body: 'Aquí ves quién es, su empresa y acciones rápidas (calendario, desasignar, etc.).',
        progress: 'Planificador · ficha',
        nextLabel: 'Siguiente →',
        onShow: function (el) {
          var pop = qs('#worker-popover');
          if (pop && !pop.classList.contains('d-none')) {
            pop.classList.add('sp-tour-target');
            placeHole(pop);
            placeCardNear(pop);
          } else if (el) {
            el.classList.add('sp-tour-target');
            placeHole(el);
            placeCardNear(el);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 5;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 5 && (st.step || 0) < 6;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Ampliar arrastrando',
        body: 'Cierra la ficha si molesta. Estira el <strong>borde</strong> de esa barra (o muévela de día). Solo al soltar, tras haberla cambiado, pasamos al siguiente paso.',
        progress: 'Planificador · arrastre',
        nextLabel: 'Ya lo moví →',
        requireGate: function () { return !!window.__spTourPlanifDragged; },
        gateFail: 'Todavía no has movido ni estirado la barra. Hazlo en el cuadrante; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          window.__spTourPlanifDragged = false;
          var item = findLastPlanifAssignmentEl({ focus: true });
          var itemId = null;
          try {
            if (item && item.getAttribute) itemId = item.getAttribute('data-id');
            if (!itemId && window.__spTourPlanifItemId != null) itemId = String(window.__spTourPlanifItemId);
          } catch (e0) { /* ignore */ }

          function highlightItem(el) {
            if (!el) {
              placeHole(qs('#planificador-calendar'));
              placeCardNear(qs('#planificador-calendar'));
              return;
            }
            // Franja horizontal completa a la altura de la barra (borde arrastrable)
            placeHolePlanifItemStrip(el);
            placeCardNear(el);
          }
          highlightItem(item);

          var startSnap = null;
          var armed = false;
          var advanced = false;
          var dragging = false;
          var downPt = null;

          function readSnap(el) {
            var data = null;
            try {
              if (itemId && window.AppItems && window.AppItems.get) {
                data = window.AppItems.get(itemId);
              }
            } catch (e) { /* ignore */ }
            var r = el ? el.getBoundingClientRect() : null;
            return {
              s: data && data.start ? new Date(data.start).getTime() : 0,
              e: data && data.end ? new Date(data.end).getTime() : 0,
              w: r ? r.width : 0,
              l: r ? r.left : 0,
            };
          }

          function changedEnough(a, b) {
            if (!a || !b) return false;
            if (a.s && b.s && Math.abs(a.s - b.s) > 1000) return true;
            if (a.e && b.e && Math.abs(a.e - b.e) > 1000) return true;
            if (a.w && Math.abs(b.w - a.w) > 14) return true;
            if (a.l && Math.abs(b.l - a.l) > 14) return true;
            return false;
          }

          function advanceToDoubleClick() {
            var st = loadState() || {};
            st.step = 6;
            saveState(st);
            run();
          }

          function goNext() {
            if (advanced) return;
            advanced = true;
            window.__spTourPlanifDragged = true;
            if (window.__spTourPlanifDragPoll) {
              clearInterval(window.__spTourPlanifDragPoll);
              window.__spTourPlanifDragPoll = null;
            }
            if (window.__spTourPlanifDragSettle) {
              clearTimeout(window.__spTourPlanifDragSettle);
              window.__spTourPlanifDragSettle = null;
            }
            try {
              document.removeEventListener('pointerdown', onPointerDown, true);
              document.removeEventListener('pointermove', onPointerMove, true);
              document.removeEventListener('pointerup', onPointerUp, true);
            } catch (e) { /* ignore */ }

            // Zoom breve a la señal de arriba (cambios / sin cambios), luego doble clic
            var tries = 0;
            function focusToastThenNext() {
              var toast = findPlanifFeedbackToast();
              if (toast) {
                clearTargets();
                placeHole(toast);
                placeCardNear(toast);
                if (ui.card) {
                  var h = ui.card.querySelector('h3');
                  var p = ui.card.querySelector('p');
                  if (h) h.textContent = 'Señal de guardado';
                  if (p) {
                    p.innerHTML = 'Arriba te confirma si hubo cambios o no. En el siguiente paso asignamos con <strong>doble clic</strong>.';
                  }
                }
                setTimeout(advanceToDoubleClick, 1600);
                return;
              }
              tries += 1;
              if (tries < 8) {
                setTimeout(focusToastThenNext, 180);
                return;
              }
              advanceToDoubleClick();
            }
            setTimeout(focusToastThenNext, 250);
          }

          function onPointerDown(ev) {
            var hit = ev.target && ev.target.closest && ev.target.closest('.vis-item');
            if (!hit) {
              armed = false;
              downPt = null;
              return;
            }
            // Solo la barra objetivo (evita saltar al clic en otra)
            if (itemId && hit.getAttribute('data-id') && String(hit.getAttribute('data-id')) !== String(itemId)) {
              armed = false;
              downPt = null;
              return;
            }
            armed = true;
            dragging = false;
            downPt = { x: ev.clientX, y: ev.clientY };
            startSnap = readSnap(hit);
            highlightItem(hit);
          }
          function onPointerMove(ev) {
            if (!armed || !downPt) return;
            // Mantener la franja (no abrir overlay a pantalla completa: se pierde el zoom)
            if (Math.abs(ev.clientX - downPt.x) > 10 || Math.abs(ev.clientY - downPt.y) > 10) {
              dragging = true;
              var el = itemId
                ? document.querySelector('.vis-item[data-id="' + itemId + '"]')
                : null;
              if (el) placeHolePlanifItemStrip(el);
            }
          }
          function onPointerUp() {
            if (!armed) return;
            var el = itemId
              ? document.querySelector('.vis-item[data-id="' + itemId + '"]')
              : findLastPlanifAssignmentEl({ focus: false });
            var now = readSnap(el);
            var ok = dragging && changedEnough(startSnap, now);
            armed = false;
            dragging = false;
            downPt = null;
            if (ok) {
              goNext();
              return;
            }
            // Clic simple o sin cambio real: volver a enfocar la franja
            highlightItem(el || item);
          }

          document.addEventListener('pointerdown', onPointerDown, true);
          document.addEventListener('pointermove', onPointerMove, true);
          document.addEventListener('pointerup', onPointerUp, true);

          if (window.__spTourPlanifDragSettle) clearTimeout(window.__spTourPlanifDragSettle);
          window.__spTourPlanifDragSettle = setTimeout(function () {
            item = findLastPlanifAssignmentEl({ focus: false }) || item;
            if (item && item.getAttribute) itemId = item.getAttribute('data-id') || itemId;
            highlightItem(item);
            startSnap = readSnap(item);
          }, 350);
        },
        onNext: function () {
          if (window.__spTourPlanifDragPoll) {
            clearInterval(window.__spTourPlanifDragPoll);
            window.__spTourPlanifDragPoll = null;
          }
          if (window.__spTourPlanifDragSettle) {
            clearTimeout(window.__spTourPlanifDragSettle);
            window.__spTourPlanifDragSettle = null;
          }
          var st = loadState() || {};
          st.step = 6;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 6 && (st.step || 0) < 7;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Asignar con doble clic',
        body: 'Desde aquí también se asigna gente. Haz <strong>doble clic</strong> en una celda vacía de una obra, en un día <strong>a partir de hoy</strong>. Aparecerá un bloque nuevo.',
        progress: 'Planificador · crear',
        nextLabel: 'Ya creé el bloque →',
        requireGate: function () { return planifPhantomExists(); },
        gateFail: 'No hay un bloque nuevo. Haz doble clic en una celda vacía; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          var grid = planifClickableGridEl();
          if (grid) {
            placeHole(grid);
            placeCardNear(grid);
          } else {
            placeHole(qs('#planificador-calendar'));
            placeCardNear(qs('#planificador-calendar'));
          }
          var advanced = false;
          function goNext() {
            if (advanced) return;
            advanced = true;
            if (window.__spTourPhantomPoll) {
              clearInterval(window.__spTourPhantomPoll);
              window.__spTourPhantomPoll = null;
            }
            var st = loadState() || {};
            st.step = 7;
            saveState(st);
            run();
          }
          if (window.__spTourPhantomPoll) clearInterval(window.__spTourPhantomPoll);
          window.__spTourPhantomPoll = setInterval(function () {
            if (planifPhantomExists()) goNext();
          }, 300);
        },
        onNext: function () {
          if (window.__spTourPhantomPoll) {
            clearInterval(window.__spTourPhantomPoll);
            window.__spTourPhantomPoll = null;
          }
          var st = loadState() || {};
          st.step = 7;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 7 && (st.step || 0) < 8;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Abre el bloque',
        body: 'Haz <strong>doble clic</strong> en ese bloque nuevo para abrir el calendario de asignación. También puedes <strong>moverlo o arrastrarlo</strong> al día que quieras (y luego abrir el calendario para afinar detalles).',
        progress: 'Planificador · abrir',
        nextLabel: 'Ya abrí el calendario →',
        requireGate: function () { return planifQuickCalOpen(); },
        gateFail: 'El calendario de asignación no se ha abierto. Haz doble clic en el bloque nuevo; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          function phantomEl() {
            return qs('.vis-item.phantom-item, .vis-item[data-id="phantom_new"], .phantom-item');
          }
          function focusPhantom() {
            var phantom = phantomEl();
            if (phantom) {
              placeHole(phantom);
              placeCardNear(phantom);
            } else {
              placeHole(planifClickableGridEl() || qs('#planificador-calendar'));
              placeCardNear(null);
            }
          }
          focusPhantom();

          var advanced = false;
          function goNext() {
            if (advanced) return;
            if (!planifQuickCalOpen()) return;
            advanced = true;
            try {
              if (window.jQuery) {
                window.jQuery(document).off('shown.bs.modal.spTourPlanifCal');
              }
            } catch (e) { /* ignore */ }
            if (window.__spTourPlanifCalPoll) {
              clearInterval(window.__spTourPlanifCalPoll);
              window.__spTourPlanifCalPoll = null;
            }
            try {
              document.removeEventListener('pointerdown', onPhDown, true);
              document.removeEventListener('pointermove', onPhMove, true);
              document.removeEventListener('pointerup', onPhUp, true);
            } catch (e2) { /* ignore */ }
            var st = loadState() || {};
            st.step = 8;
            saveState(st);
            run();
          }

          var phArmed = false;
          var phDragging = false;
          function onPhDown(ev) {
            var hit = ev.target && ev.target.closest &&
              ev.target.closest('.vis-item.phantom-item, .vis-item[data-id="phantom_new"], .phantom-item');
            phArmed = !!hit;
            phDragging = false;
          }
          function onPhMove() {
            if (!phArmed) return;
            phDragging = true;
            revealTourDesktop();
          }
          function onPhUp() {
            if (!phArmed) return;
            phArmed = false;
            // Tras soltar el arrastre, volver a enfocar el bloque para el doble clic
            setTimeout(focusPhantom, 80);
            phDragging = false;
          }
          document.addEventListener('pointerdown', onPhDown, true);
          document.addEventListener('pointermove', onPhMove, true);
          document.addEventListener('pointerup', onPhUp, true);

          try {
            if (window.jQuery) {
              window.jQuery(document).off('shown.bs.modal.spTourPlanifCal');
              window.jQuery(document).on(
                'shown.bs.modal.spTourPlanifCal',
                '#quickCalendarModal',
                goNext
              );
            }
          } catch (e2) { /* ignore */ }
          if (window.__spTourPlanifCalPoll) clearInterval(window.__spTourPlanifCalPoll);
          window.__spTourPlanifCalPoll = setInterval(function () {
            if (planifQuickCalOpen()) goNext();
          }, 300);
        },
        onNext: function () {
          try {
            if (window.jQuery) {
              window.jQuery(document).off('shown.bs.modal.spTourPlanifCal');
            }
          } catch (e) { /* ignore */ }
          if (window.__spTourPlanifCalPoll) {
            clearInterval(window.__spTourPlanifCalPoll);
            window.__spTourPlanifCalPoll = null;
          }
          var st = loadState() || {};
          st.step = 8;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 8 && (st.step || 0) < 9;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Bloque de la nueva asignación',
        body: 'En el calendario ves el bloque de la asignación que acabas de crear sobre la obra.',
        progress: 'Planificador · bloque',
        nextLabel: 'Siguiente →',
        requireGate: function () { return planifQuickCalOpen(); },
        gateFail: 'El calendario ya no está abierto. Sin ver el bloque la guía no puede continuar.',
        onShow: function () {
          clearTargets();
          var ghost = qs('#quickCalendarModal .fc-ghost-event, .fc-ghost-event');
          var cal = qs('#quickCalendarModal #modal-calendar-container, #modal-calendar-container');
          if (ghost) {
            ghost.classList.add('sp-tour-target');
            placeHole(ghost);
            placeCardNear(cal || ghost);
          } else if (cal) {
            cal.classList.add('sp-tour-target');
            placeHole(cal);
            placeCardNear(cal);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 9;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 9 && (st.step || 0) < 10;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Ajustar fechas (opcional)',
        body: 'Si quieres, puedes <strong>estirar</strong> o mover el bloque para cubrir más días. No es obligatorio: con «Siguiente» seguimos.',
        progress: 'Planificador · fechas',
        nextLabel: 'Siguiente →',
        requireGate: function () { return planifQuickCalOpen(); },
        gateFail: 'El calendario ya no está abierto. Sin él la guía no puede continuar.',
        onShow: function () {
          clearTargets();
          var cal = qs('#quickCalendarModal #modal-calendar-container, #modal-calendar-container');
          var ghost = qs('#quickCalendarModal .fc-ghost-event, .fc-ghost-event');
          if (cal) {
            placeHole(cal);
            placeCardNear(cal);
          } else if (ghost) {
            placeHole(ghost);
            placeCardNear(ghost);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 10;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 10 && (st.step || 0) < 11;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Elige a la persona',
        body: 'Abajo, en el panel, <strong>elige el trabajador</strong> (o trabajadores) que quieres asignar a esa obra. Ajusta fechas si hace falta.',
        progress: 'Planificador · persona',
        nextLabel: 'Siguiente →',
        requireGate: function () { return planifQuickCalOpen(); },
        gateFail: 'El calendario ya no está abierto. Sin el panel la guía no puede continuar.',
        onShow: function () {
          clearTargets();
          var panel = qs('#quickCalendarModal .univ-calendar-panel, .univ-calendar-panel');
          var dest = qs('#quickCalendarModal [id$="-selector-container"], .univ-calendar-panel [id$="-selector-container"]');
          if (panel) panel.style.display = 'block';
          var focus = dest || panel;
          if (focus) {
            try { focus.scrollIntoView({ block: 'nearest', behavior: 'auto' }); } catch (e) {}
            if (panel) panel.classList.add('sp-tour-target');
            placeHole(panel || focus);
            placeCardNear(panel || focus);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 11;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/planificador/) && (st.step || 0) >= 11 && (st.step || 0) < 12;
        },
        manualTarget: true,
        noScroll: true,
        title: 'Guarda con el tic',
        body: 'Pulsa el <strong>tic verde</strong> <i class="fas fa-check"></i> para guardar. Sin ese clic la asignación no se aplica.',
        progress: 'Planificador · guardar',
        nextLabel: 'Ya guardé →',
        waitClick: true,
        requireGate: function () { return planifQuickCalOpen() || !!window.__spTourPlanifSaved; },
        gateFail: 'Todavía no has guardado. Pulsa el tic verde; si no, la guía se corta aquí.',
        onShow: function () {
          clearTargets();
          window.__spTourPlanifSaved = false;
          var panel = qs('#quickCalendarModal .univ-calendar-panel, .univ-calendar-panel');
          var save = qs('#quickCalendarModal [id$="-save"], .univ-calendar-panel [id$="-save"]');
          if (panel) panel.style.display = 'block';
          if (save) {
            save.classList.add('sp-tour-target');
            placeHole(save);
            placeCardNear(panel || save);
            save.addEventListener('click', function () {
              window.__spTourPlanifSaved = true;
              var st = loadState() || {};
              st.step = 12;
              saveState(st);
              setTimeout(function () { run(); }, 400);
            }, { once: true });
          } else if (panel) {
            panel.classList.add('sp-tour-target');
            placeHole(panel);
            placeCardNear(panel);
          } else {
            placeHole(null);
            placeCardNear(null);
          }
        },
        onNext: function () {
          var save = qs('#quickCalendarModal [id$="-save"], .univ-calendar-panel [id$="-save"]');
          if (save && planifQuickCalOpen()) {
            try { save.click(); } catch (e) { /* ignore */ }
            window.__spTourPlanifSaved = true;
          }
          var st = loadState() || {};
          st.step = 12;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 12);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsAuditoriaFichajesTour() {
    return [
      {
        when: function () { return !pathIs(/\/sync\/auditoria/); },
        selector: '[data-tour="nav-auditoria-fichajes"]',
        title: 'Auditoría de fichajes',
        body: 'Pulsa <strong>Auditoría fichajes</strong>. Ahí llegan las pelotas rojas del día a día.',
        progress: 'Auditoría · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () { return pathIs(/\/sync\/auditoria/); },
        selector: '[data-tour="audit-paracaidistas"], .auditoria-section, main',
        title: 'Secciones de alerta',
        body: 'Sin planificar, desvíos y ausencias. Abre una sección para ver filas concretas.',
        progress: 'Auditoría · mapa',
        nextLabel: 'Seguir →',
        onShow: function () { highlightAuditSection(); },
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && !!(st && (st.step || 0) >= 2) && (st.step || 0) < 3;
        },
        modal: true,
        title: 'Aceptar o ignorar',
        body: 'Cada fila se resuelve: <strong>Aceptar</strong> valida el fichaje en esa obra; <strong>Ignorar</strong> oculta la alerta sin cambiar el cuadrante.',
        progress: 'Auditoría · resolver',
        nextLabel: 'Entendido →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 3);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsRegistroJornada() {
    return [
      {
        when: function () { return !pathIs(/\/admin\/registro[-_]jornada/); },
        selector: '[data-tour="nav-registro-jornada"], a[href*="registro"]',
        title: 'Registro de jornada',
        body: 'Pulsa <strong>Registro jornada</strong>. Es el informe listo para inspección.',
        progress: 'Jornada · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () { return pathIs(/\/admin\/registro[-_]jornada/); },
        selector: '.page-toolbar, main',
        title: 'Tu kit de inspección',
        body: 'Desde aquí filtras fechas, imprimes o exportas. Guárdalo mentalmente: es lo que te pedirán en una visita.',
        progress: 'Jornada · informe',
        nextLabel: 'Listo →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 2);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsFlota() {
    return [
      {
        when: function () {
          return !pathIs(/\/admin\/vehiculos/) || pathIs(/\/admin\/vehiculos\/nuevo/) ||
            pathIs(/\/admin\/vehiculos\/\d+\/editar/) ||
            pathIs(/\/admin\/vehiculos_libres/) || pathIs(/\/admin\/vehiculos\/libres/);
        },
        selector: '[data-tour="nav-vehiculos"], a[href*="/admin/vehiculos"]:not([href*="libres"]):not([href*="nuevo"])',
        title: 'Ve a Flota',
        body: 'Pulsa <strong>Flota</strong> en el menú. Ahí gestionas los vehículos de la empresa.',
        progress: 'Flota · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          return pathIs(/\/admin\/vehiculos\/?(\?|$)/) && !pathIs(/nuevo/) && !pathIs(/editar/) && !pathIs(/libres/);
        },
        selector: '[data-tour="veh-nuevo"]',
        title: 'Nuevo vehículo',
        body: 'Pulsa <strong>Nuevo vehículo</strong> para abrir el formulario de alta (igual que en personal u obras).',
        progress: 'Flota · elegir',
        waitClick: true,
        advanceTo: 2,
      },
      {
        when: function () { return pathIs(/\/admin\/vehiculos\/nuevo/); },
        selector: '[data-tour="veh-nombre"], input[name="nombre"]',
        title: 'Nombre del vehículo',
        body: 'Pon un nombre claro (p. ej. Furgoneta 1).',
        progress: 'Alta · nombre',
        onShow: function (el) { if (el) el.focus(); },
      },
      {
        when: function () { return pathIs(/\/admin\/vehiculos\/nuevo/); },
        selector: '[data-tour="veh-matricula"], input[name="matricula"]',
        title: 'Matrícula',
        body: 'Opcional pero útil. Marca y modelo están en opciones avanzadas si los quieres.',
        progress: 'Alta · matrícula',
        onShow: function (el) { if (el) el.focus(); },
      },
      {
        when: function () { return pathIs(/\/admin\/vehiculos\/nuevo/); },
        selector: '[data-tour="veh-guardar"]',
        title: 'Crear vehículo',
        body: 'Pulsa Crear vehículo. Volverás al listado de flota.',
        progress: 'Alta · guardar',
        waitClick: true,
        onShow: function () {
          var form = qs('#vehiculoForm') || qs('form');
          if (!form) return;
          form.addEventListener('submit', function () {
            var st = loadState();
            if (st) {
              st.createdVehiculoNombre = ((qs('input[name="nombre"]') || {}).value || '').trim();
              st.step = 5;
              saveState(st);
            }
          }, { once: true });
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/vehiculos\/?(\?|$)/) && !pathIs(/nuevo/) && st && (st.step || 0) >= 5;
        },
        manualTarget: true,
        title: '¡Vehículo creado!',
        body: function () {
          var st = loadState() || {};
          if (st.mode === 'solo') {
            return 'Ya está en flota. Te devolvemos a Primeros pasos.';
          }
          return 'Ya está en flota. Puedes asignarlo por día desde el tablero o su ficha.';
        },
        progress: 'Flota · listo',
        nextLabel: function () {
          var st = loadState() || {};
          return st.mode === 'solo' ? 'Volver a Primeros pasos →' : 'Entendido →';
        },
        onShow: function () {
          var st = loadState() || {};
          var name = (st.createdVehiculoNombre || '').toLowerCase();
          if (!name) return;
          document.querySelectorAll('#vehiclesTable .data-row').forEach(function (tr) {
            if ((tr.textContent || '').toLowerCase().indexOf(name) >= 0) {
              tr.classList.add('sp-tour-target');
              placeHole(tr);
              placeCardNear(tr);
            }
          });
        },
        onNext: function () {
          var st = loadState() || {};
          if (st.fromGuide) {
            markAcademiaDone('flota');
            finishGuideToHub('Vehículo creado. Tutorial guiado completado.');
            return;
          }
          if (st.mode === 'solo') {
            finishSoloAndReturn('Vehículo creado. Sigue cuando quieras con el resto de tutoriales.');
            return;
          }
          pauseAtChapterEnd();
        },
      },
    ];
  }

  function stepsFichajes() {
    return [
      {
        when: function () {
          return !pathIs(/\/admin\/personal/) && !pathIs(/\/admin\/edit_operario/) &&
            !pathIs(/\/admin\/create_user/) && !isMiEntrar() && !isMiFichar() &&
            !pathIs(/\/sync\/auditoria/) && !pathIs(/\/admin\/registro/);
        },
        selector: '[data-tour="nav-trabajadores"], a[href*="/admin/personal"]',
        title: 'Abre Trabajadores',
        body: 'Desde aquí, pulsa <strong>Trabajadores</strong> en el menú (misma pestaña). Ahí gestionas el acceso de las personas.',
        progress: 'Fichajes · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/personal/) && (st.step || 0) < 2;
        },
        manualTarget: true,
        title: 'Abre un operario',
        body: 'Abre la ficha de un <strong>operario</strong> (lápiz de editar). Ahí verás el rol y el bloque de PIN de fichaje.',
        progress: 'Fichajes · persona',
        waitClick: true,
        nextLabel: 'Ya abrí la ficha →',
        onShow: function () {
          clearTargets();
          // Preferir Internos: ahí está el lápiz de editar de los operarios de ejemplo
          try {
            var tabInt = qs('#internos-tab');
            if (tabInt && window.jQuery) window.jQuery(tabInt).tab('show');
            else if (tabInt) tabInt.click();
          } catch (eTab) { /* ignore */ }

          function pickOperarioEdit() {
            var scopes = ['#internos', '#operarios', ''];
            for (var s = 0; s < scopes.length; s++) {
              var root = scopes[s] ? qs(scopes[s]) : document;
              if (!root) continue;
              var rows = Array.prototype.slice.call(
                root.querySelectorAll('[data-tour-user-row], tr[data-dni]')
              );
              if (!rows.length) {
                rows = Array.prototype.slice.call(root.querySelectorAll('tbody tr')).filter(function (tr) {
                  var badge = (tr.textContent || '').toLowerCase();
                  return badge.indexOf('operario') >= 0;
                });
              }
              for (var i = 0; i < rows.length; i++) {
                var a = rows[i].querySelector('a[href*="edit_operario"]');
                if (a) return a;
              }
              var any = root.querySelector('a[href*="edit_operario"]');
              if (any) return any;
            }
            return qs('a[href*="edit_operario"]');
          }

          // Esperar un instante a que la pestaña Internos pinte filas
          function tryHighlight(attempt) {
            var edit = pickOperarioEdit();
            if (edit) {
              try {
                var tabPane = edit.closest('.tab-pane');
                if (tabPane && tabPane.id === 'operarios') {
                  var tabExt = qs('#operarios-tab');
                  if (tabExt && window.jQuery) window.jQuery(tabExt).tab('show');
                  else if (tabExt) tabExt.click();
                }
              } catch (eSw) { /* ignore */ }
              edit.classList.add('sp-tour-target');
              placeHole(edit);
              placeCardNear(edit);
              bindNavClick(edit, 2);
              edit.addEventListener('click', function () {
                var st = loadState() || {};
                var row = edit.closest('tr');
                if (row && row.getAttribute('data-dni')) {
                  st.createdDni = row.getAttribute('data-dni');
                }
                st.step = 2;
                saveState(st);
              }, { once: true });
              return;
            }
            if ((attempt || 0) < 6) {
              setTimeout(function () { tryHighlight((attempt || 0) + 1); }, 120);
              return;
            }
            placeHole(qs('main'));
            placeCardNear(null);
          }
          setTimeout(function () { tryHighlight(0); }, 80);
        },
        onNext: function () {
          var edit = qs('#internos a[href*="edit_operario"]') ||
            qs('#operarios a[href*="edit_operario"]') ||
            qs('a[href*="edit_operario"]');
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          if (edit && edit.href) {
            window.location.href = edit.href;
            return;
          }
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/edit_operario|\/admin\/create_user/) && (st.step || 0) >= 2 && (st.step || 0) < 3;
        },
        manualTarget: true,
        title: 'Rol del sistema',
        body: 'El <strong>rol</strong> define cómo entra cada persona. Un <strong>operario</strong> ficha con DNI + PIN. El resto de roles entran al panel con nombre (email) y contraseña.',
        progress: 'Fichajes · rol',
        nextLabel: 'Siguiente: PIN →',
        onShow: function () {
          clearTargets();
          var role = qs('#roleSelect');
          var wrap = role ? (role.closest('.form-group') || role) : null;
          if (wrap) {
            try { wrap.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
            wrap.classList.add('sp-tour-target');
            placeHole(wrap);
            placeCardNear(wrap);
          } else {
            placeHole(qs('main'));
            placeCardNear(null);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 3;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/admin\/edit_operario|\/admin\/create_user/) && (st.step || 0) >= 3 && (st.step || 0) < 4;
        },
        manualTarget: true,
        title: 'PIN de fichaje',
        body: 'Elige <strong>Guardar PIN</strong> tú o <strong>Enviar enlace</strong> por correo (solo una). Al guardar o enviar, seguimos solos.',
        progress: 'Fichajes · PIN',
        nextLabel: 'PIN listo →',
        onShow: function () {
          clearTargets();
          var pin = qs('#pinEditSection, [data-tour="user-pin-edit"]');
          var office = qs('#officeAccessBlock, [data-tour="user-acceso-office"]');
          var focus = pin || office;
          var advanced = false;

          function refocusPin() {
            var el = qs('#pinEditSection, [data-tour="user-pin-edit"]') || focus;
            if (!el) return;
            try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
            el.classList.add('sp-tour-target');
            // Tras cambiar a “Enviar enlace” el bloque crece: recalcular agujero
            placeHole(el);
            placeCardNear(el);
          }

          if (focus) {
            refocusPin();
          } else {
            placeHole(qs('main'));
            placeCardNear(null);
          }
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              if (pin) {
                p.innerHTML = 'Bloque de <strong>PIN de fichaje</strong>: guarda uno tú o envía enlace. Al hacerlo avanzamos al siguiente paso.';
              } else if (office) {
                p.innerHTML = 'Este perfil no usa PIN. Cambia el rol a <strong>operario</strong> o vuelve a Personal y abre uno.';
              }
            }
          }

          function advanceAfterPin() {
            if (advanced) return;
            advanced = true;
            var st = loadState() || {};
            st.step = 4;
            st.wantFichaje = true;
            st.pinDone = true;
            saveState(st);
          }

          document.querySelectorAll(
            '#pinEditSection form, #pinEditManualBlock form, #pinEditEmailBlock form, ' +
            'form[action*="reset_pin"], form[action*="enviar_acceso"]'
          ).forEach(function (form) {
            form.addEventListener('submit', advanceAfterPin, { once: true });
          });

          ['pinEditModeManual', 'pinEditModeEmail', 'pinModeManual', 'pinModeEmail'].forEach(function (id) {
            var radio = document.getElementById(id);
            if (!radio) return;
            radio.addEventListener('change', function () {
              setTimeout(refocusPin, 40);
              setTimeout(refocusPin, 200);
            });
          });
          document.addEventListener('sp-pin-mode-changed', function onPinMode() {
            setTimeout(refocusPin, 40);
            setTimeout(refocusPin, 200);
          });

          // Si ya se guardó PIN en esta visita (reload tras submit)
          var stNow = loadState() || {};
          if (stNow.pinDone) {
            setTimeout(function () {
              if (advanced) return;
              advanced = true;
              stNow.step = 4;
              saveState(stNow);
              run();
            }, 200);
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 4;
          st.wantFichaje = true;
          st.pinDone = true;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return (st.step || 0) >= 4 && (st.step || 0) < 5 &&
            !isMiEntrar() && !isMiFichar() && !pathIs(/\/sync\/auditoria/) && !pathIs(/\/admin\/registro/);
        },
        modal: true,
        title: 'Prueba a fichar',
        body: 'Vas a entrar en /mi con el DNI y el PIN. Ficharás en <strong>Oficina</strong> (la activamos para el tutorial): así el fichaje no está planificado y luego lo revisas en auditoría.',
        progress: 'Fichajes · probar',
        primaryHref: '/admin/tour/fichaje-probar?chapter=fichajes',
        primaryLabel: 'Ir a fichar como operario',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.chapter = 'fichajes';
          st.step = 5;
          st.active = true;
          st.wantFichaje = true;
          st.ficharOficina = true;
          saveState(st);
        },
      },
      {
        when: function () { return isMiEntrar() && (loadState() || {}).chapter === 'fichajes'; },
        selector: '[data-tour="fichar-dni"], #dni',
        title: 'DNI',
        body: 'Introduce el DNI.',
        progress: 'Fichajes · DNI',
        nextLabel: 'Siguiente',
        onShow: function () {
          prefillLoginField('dni');
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) p.innerHTML = fillCredsHint('dni');
          }
        },
      },
      {
        when: function () { return isMiEntrar() && (loadState() || {}).chapter === 'fichajes'; },
        selector: '[data-tour="fichar-pin"], #pin',
        title: 'PIN',
        body: 'Introduce el PIN.',
        progress: 'Fichajes · PIN acceso',
        nextLabel: 'Siguiente',
        onShow: function () {
          prefillLoginField('pin');
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) p.innerHTML = fillCredsHint('pin');
          }
        },
      },
      {
        when: function () { return isMiEntrar() && (loadState() || {}).chapter === 'fichajes'; },
        selector: '[data-tour="fichar-submit"]',
        title: 'Entrar a fichar',
        body: 'Con DNI y PIN, pulsa Entrar.',
        progress: 'Fichajes · acceso',
        waitClick: true,
        nextLabel: 'Ya entré →',
        advanceTo: 8,
        onShow: function () {
          prefillLoginField('dni');
          prefillLoginField('pin');
          var form = qs('[data-tour="fichar-login"]') || qs('form');
          if (!form) return;
          form.addEventListener('submit', function () {
            var cur = loadState();
            if (cur) { cur.step = 8; cur.chapter = 'fichajes'; saveState(cur); }
          }, { once: true });
        },
      },
      {
        when: function () {
          return isMiFichar() && fichajeEstado() === 'fuera' && (loadState() || {}).chapter === 'fichajes';
        },
        selector: '[data-tour="fichar-obra"], #obra',
        title: 'Dónde fichas',
        body: 'En el día a día aquí sale por defecto la obra en la que estás <strong>planificado</strong>. En este tutorial usamos <strong>Oficina</strong> para generar un desvío y verlo luego en auditoría.',
        progress: 'Fichajes · obra',
        nextLabel: 'Siguiente',
        onShow: function (el) {
          ensureOficinaSelected(8);
          selectOficinaInFichajeSelect(el || qs('[data-tour="fichar-obra"], #obra'));
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              p.innerHTML = 'Normalmente eliges (o te sale) la obra donde estás. Aquí, para el tutorial, dejamos <strong>Oficina</strong>.';
            }
          }
          setTimeout(function () { ensureOficinaSelected(4); }, 200);
          setTimeout(function () { ensureOficinaSelected(2); }, 600);
        },
      },
      {
        when: function () {
          return isMiFichar() && fichajeEstado() === 'fuera' && (loadState() || {}).chapter === 'fichajes';
        },
        selector: '[data-tour="fichar-entrada"], [data-tipo="entrada"], button[data-tipo="entrada"]',
        title: 'Ficha entrada',
        body: 'Pulsa <strong>Entrada</strong> para registrar el fichaje en Oficina.',
        progress: 'Fichajes · entrada',
        waitClick: true,
        nextLabel: 'Ya fiché →',
        onShow: function () {
          ensureOficinaSelected(6);
          var btn = qs('[data-tour="fichar-entrada"], [data-tipo="entrada"]');
          if (!btn) return;
          btn.addEventListener('click', function () {
            ensureOficinaSelected(2);
            selectOficinaInFichajeSelect();
            var st = loadState() || {};
            st.step = 10;
            st.fichoOficina = true;
            saveState(st);
          }, true);
        },
        onNext: function () {
          ensureOficinaSelected(2);
          selectOficinaInFichajeSelect();
          var st = loadState() || {};
          st.step = 10;
          st.fichoOficina = true;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          return isMiFichar() && (fichajeEstado() === 'dentro' || (loadState() || {}).step >= 10) &&
            (loadState() || {}).chapter === 'fichajes' && (loadState() || {}).step < 11;
        },
        modal: true,
        title: 'Fichaje hecho',
        body: 'Has fichado en <strong>Oficina</strong>. Primero lo miramos en el <strong>tablero</strong> y después en auditoría.',
        progress: 'Fichajes · puente',
        primaryHref: '/mi/tour-volver-admin?next=' +
          encodeURIComponent('/admin/obras_detailed?tour=fichajes&mode=solo'),
        primaryLabel: 'Ver en el tablero →',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.chapter = 'fichajes';
          st.step = 11;
          st.active = true;
          saveState(st);
        },
      },
      {
        when: function () {
          var st = loadState();
          return (st.chapter === 'fichajes') && (st.step || 0) >= 11 && (st.step || 0) < 12 &&
            !pathIs(/\/sync\/auditoria/) &&
            (pathIs(/\/admin\/obras_detailed/) ||
              (new URLSearchParams(window.location.search || '')).get('tour') === 'fichajes');
        },
        manualTarget: true,
        title: 'En el tablero',
        body: 'El operario ya no está en libres: está en la obra del fichaje. Mira el color de la marca.',
        progress: 'Fichajes · tablero',
        nextLabel: 'Siguiente →',
        onShow: function () {
          highlightWorkerChip();
          if (ui.card) {
            var p = ui.card.querySelector('p');
            if (p) {
              var focus = qs('.sp-tour-highlight-user') || qs('.worker-chip.sp-tour-target');
              var red = focus && focus.querySelector('.dot-danger');
              var green = focus && focus.querySelector('.dot-success, .dot-auto');
              if (!red && !green) {
                red = qs('.kanban-col .worker-chip .dot-danger');
                green = qs('.kanban-col .worker-chip .dot-success, .kanban-col .worker-chip .dot-auto');
              }
              if (red) {
                p.innerHTML = 'Marca en <strong>rojo</strong>: el fichaje no encaja con el plan (desvío o conflicto). Ahora lo resolvemos en auditoría.';
              } else if (green) {
                p.innerHTML = 'Marca en <strong>verde</strong>: el fichaje encaja con el plan. Aun así, en auditoría verás el rastro si hubo resolución.';
              } else {
                p.innerHTML = 'Mira la marca del operario en la obra. <strong>Rojo</strong> = revisar en auditoría; <strong>verde</strong> = correcto.';
              }
            }
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 12;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return (st.chapter === 'fichajes') && (st.step || 0) >= 12 && (st.step || 0) < 13 &&
            !pathIs(/\/sync\/auditoria/);
        },
        selector: '[data-tour="nav-auditoria-fichajes"]',
        title: 'Auditoría de fichajes',
        body: 'Pulsa <strong>Auditoría fichajes</strong> en el menú (sección Jornada). Ahí resolvemos el desvío.',
        progress: 'Fichajes · menú',
        waitClick: true,
        advanceTo: 13,
        ifMissing: 'wait',
        onShow: function (el) {
          if (el) {
            try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
          }
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && (st.chapter === 'fichajes') &&
            (st.step || 0) >= 13 && (st.step || 0) < 14;
        },
        selector: '[data-tour="audit-desviaciones"], [data-tour="audit-paracaidistas"], .auditoria-section, main',
        title: 'Tu fichaje en auditoría',
        body: 'Abrimos la sección donde ha caído tu fichaje de Oficina (desviación o sin planificar) y te explicamos cuál es.',
        progress: 'Fichajes · auditoría',
        nextLabel: 'Siguiente →',
        onShow: function () { highlightAuditSection(); },
        onNext: function () {
          var st = loadState() || {};
          st.step = 14;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && (st.step || 0) >= 14 && (st.step || 0) < 15;
        },
        manualTarget: true,
        title: 'Cómo resolverlo',
        body: 'Elige una acción sobre la fila.',
        progress: 'Fichajes · resolver',
        waitClick: true,
        nextLabel: 'Ya lo resolví →',
        onShow: function () {
          var info = resolveAuditTourSection();
          var advanced = false;
          function goHistorico() {
            if (advanced) return;
            advanced = true;
            var st = loadState() || {};
            st.step = 15;
            st.auditResolved = true;
            if (info && info.kind) st.auditKind = info.kind;
            saveState(st);
            setTimeout(function () {
              window.location.href = '/sync/auditoria?tour=fichajes&mode=solo';
            }, 700);
          }
          highlightAuditParacaidista(function (btn, buttons) {
            var list = (buttons && buttons.length) ? buttons : (btn ? [btn] : []);
            list.forEach(function (b) {
              b.addEventListener('click', goHistorico, true);
            });
          });
          if (ui.card) {
            var h = ui.card.querySelector('h3');
            var p = ui.card.querySelector('p');
            if (info && info.kind === 'desviaciones') {
              if (h) h.textContent = 'Desviaciones: tres acciones';
              if (p) {
                p.innerHTML =
                  '<strong>Mover</strong>: cambia el cuadrante a Oficina.<br>' +
                  '<strong>+ Añadir</strong>: mantiene la planificada y añade Oficina.<br>' +
                  '<strong>Ignorar</strong>: oculta la alerta sin tocar el plan.';
              }
            } else {
              if (h) h.textContent = 'Sin planificar: dos acciones';
              if (p) {
                p.innerHTML =
                  '<strong>Aceptar</strong>: asigna oficialmente a esa obra.<br>' +
                  '<strong>Ignorar</strong>: oculta la alerta sin cambiar el cuadrante.';
              }
            }
          }
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 15;
          st.auditResolved = true;
          saveState(st);
          window.location.href = '/sync/auditoria?tour=fichajes&mode=solo';
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && (st.step || 0) >= 15 && (st.step || 0) < 16;
        },
        manualTarget: true,
        title: 'Histórico global',
        body: 'Esta sección es el <strong>Histórico global</strong>: ahí quedan las decisiones ya resueltas. <strong>Expándela</strong> tú (haz clic en la cabecera).',
        progress: 'Fichajes · histórico',
        waitClick: true,
        nextLabel: 'Continuar →',
        onShow: function () {
          clearTargets();
          var toggle = qs('[data-tour="audit-historico-toggle"]');
          var root = qs('[data-tour="audit-historico"]');
          var collapse = qs('#collapseHistorial');
          var target = toggle || root;
          if (!target) {
            placeHole(null);
            placeCardModal();
            return;
          }
          target.classList.add('sp-tour-target');
          placeHole(target);
          placeCardOutside(target);

          var advanced = false;
          function goRowStep() {
            if (advanced) return;
            advanced = true;
            if (window.__spTourHistPoll) {
              clearInterval(window.__spTourHistPoll);
              window.__spTourHistPoll = null;
            }
            var st = loadState() || {};
            st.step = 16;
            saveState(st);
            setTimeout(function () { run(); }, 180);
          }

          function isOpen() {
            return !!(collapse && collapse.classList.contains('show'));
          }

          if (isOpen()) {
            goRowStep();
            return;
          }

          function onShown() {
            if (collapse) collapse.removeEventListener('shown.bs.collapse', onShown);
            goRowStep();
          }
          if (collapse) collapse.addEventListener('shown.bs.collapse', onShown);

          function onToggleClick() {
            setTimeout(function () {
              if (isOpen()) goRowStep();
            }, 280);
          }
          if (toggle) toggle.addEventListener('click', onToggleClick);
          if (root && root !== toggle) root.addEventListener('click', onToggleClick);

          if (window.__spTourHistPoll) clearInterval(window.__spTourHistPoll);
          window.__spTourHistPoll = setInterval(function () {
            if (isOpen()) goRowStep();
          }, 250);
        },
        onNext: function () {
          openAuditHistoricoSection();
          var st = loadState() || {};
          st.step = 16;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && (st.step || 0) >= 16 && (st.step || 0) < 17;
        },
        manualTarget: true,
        title: 'Tu decisión en el histórico',
        body: 'Esta es la fila de quien acabas de fichar / resolver. Haz <strong>clic en la fila</strong> para abrir la actividad del día.',
        progress: 'Fichajes · fila',
        waitClick: true,
        nextLabel: 'Ya abrí la actividad →',
        onShow: function () {
          clearTargets();
          var collapse = qs('#collapseHistorial');
          if (collapse && !collapse.classList.contains('show')) {
            openAuditHistoricoSection();
          }
          var advanced = false;
          function goTimeline() {
            if (advanced) return;
            advanced = true;
            var st = loadState() || {};
            st.step = 17;
            saveState(st);
            setTimeout(function () { run(); }, 500);
          }
          function bindRow(tries) {
            tries = tries || 0;
            var row = findHistoricoTourRow();
            if (!row) {
              if (tries < 20) setTimeout(function () { bindRow(tries + 1); }, 180);
              return;
            }
            row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
            try { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
            placeHole(row);
            placeCardOutside(row);
            row.addEventListener('click', goTimeline, { once: true });
          }
          setTimeout(function () { bindRow(0); }, 350);
        },
        onNext: function () {
          var row = findHistoricoTourRow();
          if (row) {
            try { row.click(); } catch (e) { /* ignore */ }
          }
          var st = loadState() || {};
          st.step = 17;
          saveState(st);
          setTimeout(function () { run(); }, 500);
        },
      },
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && (st.step || 0) >= 17 && (st.step || 0) < 18;
        },
        manualTarget: true,
        title: 'Qué cuenta esta actividad',
        body: 'Aquí se lee la historia del día, en orden.',
        progress: 'Fichajes · actividad',
        nextLabel: 'Completar tutorial →',
        onShow: function () {
          clearTargets();
          var tries = 0;
          function placeTipReadable(modalOrRoot) {
            if (!ui.card) return false;
            var tip = buildActivityTourTipHtml(modalOrRoot || document);
            var p = ui.card.querySelector('p');
            if (tip === null) {
              // Timeline aún cargando: reintentar
              if (p) p.textContent = 'Cargando la actividad del día…';
              ui.card.style.zIndex = '20050';
              if (ui.backdrop) ui.backdrop.style.zIndex = '20040';
              return false;
            }
            if (p) p.innerHTML = tip;
            ui.card.style.zIndex = '20050';
            if (ui.backdrop) ui.backdrop.style.zIndex = '20040';
            return true;
          }
          function focusTimeline() {
            var modal = qs('#modalPersonDayTimeline.show, .person-day-timeline-modal.show');
            if (!modal) {
              var any = qs('#modalPersonDayTimeline, .person-day-timeline-modal');
              if (any && (any.classList.contains('show') || (any.style && any.style.display === 'block'))) {
                modal = any;
              } else if (any && tries < 16) {
                tries += 1;
                setTimeout(focusTimeline, 200);
                return;
              } else {
                modal = any;
              }
            }
            var holeEl = null;
            if (modal) {
              holeEl = modal.querySelector('.person-day-timeline-container') ||
                modal.querySelector('[data-timeline-content]') ||
                modal.querySelector('[data-person-day-timeline-root]') ||
                modal.querySelector('.modal-body') ||
                modal.querySelector('.person-day-timeline-modal-content') ||
                modal.querySelector('.modal-content') ||
                modal;
            }
            if (holeEl) {
              var r = holeEl.getBoundingClientRect ? holeEl.getBoundingClientRect() : null;
              var tipReady = placeTipReadable(modal || holeEl);
              var loading = !!(modal && modal.querySelector('.person-day-timeline-loading'));
              if (((!r || r.width < 40 || r.height < 40) || loading || tipReady === false) && tries < 20) {
                tries += 1;
                setTimeout(focusTimeline, 220);
                if (r && r.width >= 40 && r.height >= 40) {
                  placeHole(holeEl);
                  placeCardOutside(holeEl);
                  holeTrack.cardEl = null;
                }
                return;
              }
              placeHole(holeEl);
              placeTipReadable(modal || holeEl);
              placeCardOutside(holeEl);
              // Si el tip sigue solapando el foco (modal grande), forzar franja inferior
              try {
                var cr = ui.card.getBoundingClientRect();
                var hr = holeEl.getBoundingClientRect();
                var overlaps = !(cr.right < hr.left - 8 || cr.left > hr.right + 8 ||
                  cr.bottom < hr.top - 8 || cr.top > hr.bottom + 8);
                if (overlaps) {
                  var vw = window.innerWidth || 800;
                  var vh = window.innerHeight || 600;
                  var cardW = Math.min(400, vw - 24);
                  ui.card.classList.remove('is-modal');
                  ui.card.style.transform = '';
                  ui.card.style.width = cardW + 'px';
                  ui.card.style.left = Math.max(12, (vw - cardW) / 2) + 'px';
                  ui.card.style.top = Math.max(12, Math.min(hr.bottom + 14, vh - (ui.card.offsetHeight || 180) - 16)) + 'px';
                  cr = ui.card.getBoundingClientRect();
                  overlaps = !(cr.right < hr.left - 8 || cr.left > hr.right + 8 ||
                    cr.bottom < hr.top - 8 || cr.top > hr.bottom + 8);
                  if (overlaps) {
                    ui.card.style.top = Math.max(12, hr.top - (ui.card.offsetHeight || 180) - 14) + 'px';
                  }
                }
              } catch (e) { /* ignore */ }
              holeTrack.cardEl = null;
            } else if (tries < 16) {
              tries += 1;
              setTimeout(focusTimeline, 200);
            } else {
              placeHole(null);
              placeTipReadable(document);
              placeCardModal();
            }
          }
          setTimeout(focusTimeline, 280);
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 18;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 18);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsCochesLibres() {
    function onCochesLibresPage() {
      return pathIs(/\/admin\/vehiculos\/libres/) || pathIs(/\/admin\/vehiculos_libres/);
    }
    return [
      {
        when: function () { return !onCochesLibresPage(); },
        selector: '[data-tour="nav-coches-libres"], a[href*="vehiculos/libres"], a[href*="vehiculos_libres"]',
        title: 'Coches libres',
        body: 'Pulsa <strong>Coches libres</strong> para ver disponibilidad.',
        progress: 'Libres · menú',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
        onShow: function (el) {
          if (!el) {
            // Fallback: botón en Flota
            var fallback = qs('a[href*="vehiculos/libres"]');
            if (fallback) {
              fallback.classList.add('sp-tour-target');
              placeHole(fallback);
              placeCardNear(fallback);
              bindNavClick(fallback, 1);
            }
          }
        },
      },
      {
        when: function () { return onCochesLibresPage(); },
        selector: '.vl-kpis, .page-toolbar, main',
        title: 'Quién está libre',
        body: 'Los KPI y la tabla te dicen qué coches no están asignados en el periodo. Úsalo antes de pedir uno más.',
        progress: 'Libres · lectura',
        nextLabel: 'Entendido →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 2);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  function stepsAuditoriaVehiculos() {
    return [
      {
        when: function () { return !pathIs(/\/sync\/auditoria-vehiculos/) && !pathIs(/\/sync\/auditoria_vehiculos/); },
        selector: 'a[href*="auditoria-vehiculos"], a[href*="auditoria_vehiculos"]',
        title: 'Auditoría de vehículos',
        body: 'Pulsa la auditoría de vehículos para revisar odómetros y alertas.',
        progress: 'Flota · auditoría',
        waitClick: true,
        advanceTo: 1,
        ifMissing: 'wait',
      },
      {
        when: function () { return pathIs(/auditoria-vehiculos/) || pathIs(/auditoria_vehiculos/); },
        selector: 'main',
        title: 'Qué mirar',
        body: 'Secciones de saltos, desvíos o sin planificar. Resuelve lo urgente; el resto puede esperar.',
        progress: 'Flota · alertas',
        nextLabel: 'Listo →',
        onNext: function () {
          var st = loadState() || {};
          st.step = 2;
          saveState(st);
          run();
        },
      },
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 2);
        },
        title: '',
        body: '',
        onShow: function () { pauseAtChapterEnd(); },
      },
    ];
  }

  // Fix import trabajadores "Continuar a obras" — step 20 next should hand off
  function fixImportAdvance() {
    // handled by rewriting step: use next that sets chapter
  }

  function currentSteps() {
    var state = loadState();
    if (!state || !state.active) return [];
    if (state.chapter === 'obra') return stepsObra();
    if (state.chapter === 'fichaje') return stepsFichaje();
    if (state.chapter === 'import') return stepsImport();
    if (state.chapter === 'demo') return stepsDemo();
    if (state.chapter === 'tablero_basico') return stepsTableroBasico();
    if (state.chapter === 'planificador_multi') return stepsPlanificadorMulti();
    if (state.chapter === 'fichajes') return stepsFichajes();
    if (state.chapter === 'auditoria_fichajes') return stepsFichajes();
    if (state.chapter === 'registro_jornada') return stepsFichajes();
    if (state.chapter === 'flota') return stepsFlota();
    if (state.chapter === 'coches_libres') return stepsCochesLibres();
    if (state.chapter === 'auditoria_vehiculos') return stepsAuditoriaVehiculos();
    return stepsTrabajadores();
  }

  function pickStep() {
    var state = loadState();
    if (!state || !state.active) return null;
    var steps = currentSteps();
    var idx = state.step || 0;

    // Special: trabajadores step 8 "Continuar" advances to 9 which hands off
    for (var i = idx; i < steps.length; i++) {
      var s = steps[i];
      if (s.when && !s.when()) continue;
      if (i !== idx) {
        state.step = i;
        saveState(state);
      }
      return s;
    }
    for (var j = 0; j < steps.length; j++) {
      if (steps[j].when && steps[j].when()) {
        state.step = j;
        saveState(state);
        return steps[j];
      }
    }
    return null;
  }

  function run() {
    var state = loadState();
    if (!state || state.chapter === 'blocked' || !state.active) {
      if (state && state.pendingComplete) pauseAtChapterEnd();
      return;
    }

    // En /mi solo corre fichaje (seed) o fichajes (academia). No pisar academia.
    if ((isMiEntrar() || isMiFichar()) &&
        state.chapter !== 'fichaje' && state.chapter !== 'fichajes') {
      state.chapter = 'fichaje';
      state.wantFichaje = true;
      if (isMiEntrar()) state.step = 1;
      else if (fichajeEstado() === 'dentro') state.step = 6;
      else state.step = 4;
      saveState(state);
    }

    // Import users: if step>=20 and user clicked Continuar, hand off on next advance
    // Patch step 20 to hand off via custom next
    var step = pickStep();
    if (!step) return;

    // Rewrite import continuar
    if (state.chapter === 'trabajadores' && (state.step || 0) >= 20 && pathIs(/\/admin\/import_users/)) {
      step = {
        selector: 'main',
        title: 'Importar personal',
        body: 'Sube tu Excel/CSV (nombre, apellidos, DNI). Luego continúa hacia Directorio para crear una obra.',
        progress: 'Importar',
        nextLabel: 'Continuar a obras',
        onShow: function () {},
      };
      var origAdvance = null;
      renderStep(step);
      var btn = ui.card && ui.card.querySelector('[data-act="next"]');
      if (btn) {
        btn.onclick = function () {
          saveState({
            active: true,
            chapter: 'obra',
            step: 0,
            wantFichaje: state.wantFichaje,
          });
          run();
        };
      }
      return;
    }

    // Import obras close
    if (state.chapter === 'obra' && (state.step || 0) >= 10 && pathIs(/\/admin\/import_obras/)) {
      renderStep({
        selector: 'main',
        title: 'Importar obras',
        body: 'Sube el Excel. Cuando acabes, continuamos si activaste fichaje.',
        progress: 'Importar obras',
        nextLabel: 'Continuar',
      });
      var b2 = ui.card && ui.card.querySelector('[data-act="next"]');
      if (b2) {
        b2.onclick = function () {
          if (state.wantFichaje) {
            saveState({
              active: true,
              chapter: 'fichaje',
              step: 0,
              wantFichaje: true,
              createdDni: state.createdDni,
              createdPin: state.createdPin,
              createdObraNombre: state.createdObraNombre,
            });
            run();
          } else {
            pauseAtChapterEnd();
          }
        };
      }
      return;
    }

    if (step.onShow && !step.selector && !step.choices && step.title === '') {
      step.onShow();
      return;
    }
    // Hand-off empty step
    if (step.title === '' && step.onShow) {
      step.onShow();
      return;
    }
    renderStep(step);
  }

  function bindLauncher() {
    document.querySelectorAll('[data-tour-start]').forEach(function (btn) {
      if (btn.getAttribute('data-tour-bound') === '1') return;
      btn.setAttribute('data-tour-bound', '1');
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        var chapter = btn.getAttribute('data-tour-start') || 'trabajadores';
        startTour(chapter);
      });
    });
  }

  function bootFromUrl() {
    var params = new URLSearchParams(window.location.search || '');
    var tour = params.get('tour');
    if (tour === 'fichaje_done') {
      var stDone = loadState() || { wantFichaje: true, createdDni: null };
      stDone.active = true;
      stDone.chapter = 'fichaje';
      stDone.step = 7;
      stDone.pendingComplete = false;
      saveState(stDone);
      run();
      return true;
    }
    if (tour === 'demo') {
      var stDemo = loadState() || {};
      stDemo.active = true;
      stDemo.chapter = 'demo';
      stDemo.step = 0;
      stDemo.pendingComplete = false;
      saveState(stDemo);
      run();
      return true;
    }
    if (tour === 'import') {
      startTour('import');
      return true;
    }
    // Continuar capítulo fichaje / fichajes en /mi (no reiniciar la guía)
    if (tour === 'mi' || tour === 'continuar') {
      var stMi = loadState() || {};
      var chUrl = (params.get('chapter') || '').trim();
      var chMi = 'fichajes';
      if (chUrl === 'fichaje' || chUrl === 'fichajes') chMi = chUrl;
      else if (stMi.chapter === 'fichaje' || stMi.chapter === 'fichajes') chMi = stMi.chapter;
      // Probar fichaje desde academia / demo: nunca caer al seed viejo
      if (stMi.ficharOficina || chUrl === 'fichajes' || stMi.chapter === 'fichajes') {
        chMi = 'fichajes';
      }
      stMi.active = true;
      stMi.chapter = chMi;
      stMi.wantFichaje = true;
      stMi.ficharOficina = true;
      if (chMi === 'fichajes') {
        if (isMiEntrar()) stMi.step = 5;
        else if (isMiFichar() && fichajeEstado() === 'dentro') stMi.step = 10;
        else if (isMiFichar()) stMi.step = 8;
        else if (typeof stMi.step !== 'number' || stMi.step < 5) stMi.step = 5;
      } else {
        if (isMiEntrar()) stMi.step = 1;
        else if (isMiFichar() && fichajeEstado() === 'dentro') stMi.step = 6;
        else if (isMiFichar()) stMi.step = 4;
        else if (typeof stMi.step !== 'number' || stMi.step < 1) stMi.step = 1;
      }
      saveState(stMi);
      run();
      return true;
    }
    if (tour === '1' || tour === 'start') {
      // Solo reiniciar desde Primeros pasos / Config, no desde /mi
      if (isMiEntrar() || isMiFichar()) {
        var stSafe = loadState() || {};
        stSafe.active = true;
        stSafe.chapter = 'fichaje';
        stSafe.wantFichaje = true;
        stSafe.step = isMiEntrar() ? 1 : (fichajeEstado() === 'dentro' ? 6 : 4);
        saveState(stSafe);
        run();
        return true;
      }
      startTour('trabajadores');
      return true;
    }
    if (tour === 'obra') {
      startTour('obra', { mode: params.get('mode') || 'full' });
      return true;
    }
    if (tour === 'fichaje') {
      var stF = loadState() || {};
      var cont = params.get('continue') === '1' || params.get('mode') !== 'solo';
      // Continuar guía a medias (p. ej. tras resolver en auditoría): NO reiniciar
      if (stF.active && stF.chapter === 'fichaje' && (stF.step || 0) > 0 &&
          (cont || params.get('continue') === '1' || (stF.step || 0) >= 7)) {
        stF.fromGuide = true;
        stF.mode = 'full';
        stF.active = true;
        saveState(stF);
        document.body.classList.add('sp-tour-active');
        run();
        return true;
      }
      // mode=solo solo si se pide explícitamente (tutorial suelto); la guía completa es full
      var modeF = params.get('mode') === 'solo' ? 'solo' : 'full';
      startTour('fichaje', {
        mode: modeF,
        fromGuide: modeF !== 'solo',
        keepCreds: true,
        step: 0,
      });
      return true;
    }
    var academiaTours = [
      'tablero_basico', 'planificador_multi', 'fichajes',
      'auditoria_fichajes', 'registro_jornada',
      'flota', 'coches_libres', 'auditoria_vehiculos',
    ];
    if (academiaTours.indexOf(tour) >= 0) {
      var ch = (tour === 'auditoria_fichajes' || tour === 'registro_jornada') ? 'fichajes' : tour;
      var existing = loadState();
      // Continuar capítulo a medias (p. ej. tras volver de /mi al registro)
      if (existing && existing.active && existing.chapter === ch && (existing.step || 0) > 0) {
        document.body.classList.add('sp-tour-active');
        run();
        return true;
      }
      startTour(ch, { mode: params.get('mode') || 'solo' });
      return true;
    }
    return false;
  }

  function boot() {
    bindLauncher();
    // /mi tutorial: Oficina sí o sí (HTML + JS), y capítulo desde servidor/URL
    try {
      if (window.__SP_TOUR_CHAPTER__ === 'fichajes' || window.__SP_TOUR_CHAPTER__ === 'fichaje') {
        var stBoot = loadState() || {};
        stBoot.active = true;
        stBoot.chapter = window.__SP_TOUR_CHAPTER__;
        stBoot.ficharOficina = true;
        stBoot.wantFichaje = true;
        saveState(stBoot);
      }
      if (window.__SP_TOUR_FORCE_OFICINA__ || qs('.fichaje[data-tour-force-oficina]')) {
        ensureOficinaSelected(10);
        setTimeout(function () { ensureOficinaSelected(6); }, 50);
        setTimeout(function () { ensureOficinaSelected(4); }, 250);
      }
    } catch (eBoot) { /* ignore */ }
    if (bootFromUrl()) return;
    var state = loadState();
    if (state && state.active) run();
    else if (state && state.pendingComplete) pauseAtChapterEnd();
  }

  window.SignaPlanTour = {
    start: startTour,
    stop: stopTour,
    skipSection: skipSection,
    run: run,
    loadState: loadState,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.addEventListener('resize', function () {
    var state = loadState();
    if (state && state.active && ui.hole) run();
  });
})(window, document);
