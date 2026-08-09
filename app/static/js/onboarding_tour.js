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
    return fetch('/admin/api/tour/fichaje', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
      },
      body: JSON.stringify({ activo: !!activo }),
      credentials: 'same-origin',
    }).then(function (r) { return r.json().catch(function () { return {}; }); });
  }

  function startTour(chapter) {
    var ch = chapter || 'trabajadores';
    saveState({
      active: true,
      chapter: ch,
      step: 0,
      createdDni: null,
      createdPin: null,
      createdObraNombre: null,
      // Si arrancas directo en fichaje (o obras tras probar), asumimos que quieren fichaje
      wantFichaje: ch === 'fichaje' ? true : null,
    });
    // Import se queda en el hub (modal de elección). Demo va al tablero.
    if (ch === 'demo' && pathIs(/\/admin\/primeros-pasos/)) {
      window.location.href = '/admin/obras_detailed?tour=demo';
      return;
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

  function pauseAtChapterEnd() {
    var state = loadState();
    if (!state) return;
    var chapter = state.chapter || '';
    var didFichaje = !!state.wantFichaje;
    state.active = false;
    state.chapter = 'blocked';
    state.step = 0;
    state.pendingComplete = false;
    state.createdPin = null;
    saveState(state);
    teardown();

    if (chapter === 'import' || chapter === 'demo') {
      ensureUi();
      clearTargets();
      placeHole(null);
      ui.card.classList.add('is-modal');
      ui.card.style.transform = 'translateX(-50%)';
      ui.card.style.top = '28%';
      ui.card.style.left = '50%';
      var msg = chapter === 'import'
        ? 'Importación guiada lista. Puedes seguir importando más listados o entrar al tablero.'
        : 'Ya conoces el mapa con datos de ejemplo. Explora libremente; el banner te deja borrarlos cuando quieras.';
      ui.card.innerHTML =
        '<h3>Guía terminada</h3><p>' + msg + '</p>' +
        '<div class="sp-tour-actions">' +
        '<button type="button" class="sp-tour-skip" data-act="hub">Volver a Primeros pasos</button>' +
        '<button type="button" class="sp-tour-primary" data-act="done">Ir al tablero</button></div>';
      ui.card.querySelector('[data-act="hub"]').onclick = function () {
        teardown();
        window.location.href = '/admin/primeros-pasos';
      };
      ui.card.querySelector('[data-act="done"]').onclick = function () {
        postOnboardingDone();
      };
      return;
    }

    showDoneCard(
      didFichaje
        ? 'Guía completada: alta, obra, fichaje de prueba y cómo resolver la pelota roja en auditoría. Puedes retomar otros pasos desde Primeros pasos.'
        : 'Hasta aquí la guía por ahora. Ya tienes trabajador y obra. ' +
          'Más adelante puedes activar fichaje en Configuración. Puedes retomar desde Primeros pasos.'
    );
  }

  function sectionSkipLabel(chapter) {
    if (chapter === 'trabajadores') return 'Saltar plantilla →';
    if (chapter === 'obra') return 'Saltar obras →';
    if (chapter === 'fichaje') return 'Saltar fichaje →';
    if (chapter === 'import') return 'Saltar importación →';
    if (chapter === 'demo') return 'Saltar exploración →';
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

    pauseAtChapterEnd();
  }

  var ui = { backdrop: null, hole: null, card: null, banner: null };

  function teardown() {
    document.body.classList.remove('sp-tour-active');
    document.querySelectorAll('.sp-tour-target').forEach(function (el) {
      el.classList.remove('sp-tour-target');
    });
    hideTourBanner();
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
  }

  function placeHole(el) {
    if (!ui.hole) return;
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
    ui.card.classList.remove('is-modal');
    ui.card.style.transform = '';
    ui.card.style.display = '';
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var cardW = Math.min(360, vw - 24);
    ui.card.style.width = cardW + 'px';
    var top = 24;
    var left = Math.max(12, (vw - cardW) / 2);
    var estH = Math.min(220, Math.max(140, ui.card.offsetHeight || 180));
    if (el && el.getBoundingClientRect) {
      var r = el.getBoundingClientRect();
      var isSidebar = !!(el.closest && el.closest('.sidebar-nav, .admin-sidebar, .sidebar'));
      if (isSidebar || (el.classList && el.classList.contains('sidebar-link'))) {
        // A la derecha del enlace del menú
        top = Math.max(12, Math.min(r.top, vh - estH - 12));
        left = Math.min(r.right + 16, vw - cardW - 12);
        if (left < 160) left = Math.max(12, (vw - cardW) / 2);
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
    var el = (!isModal && step.selector && !step.manualTarget) ? qs(step.selector) : null;

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
              var t = qs(step.selector);
              var href = t && t.getAttribute ? t.getAttribute('href') : null;
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
      try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); } catch (e) {}
    }

    var html = '';
    var stepTitle = (typeof step.title === 'function') ? step.title() : (step.title || '');
    var stepBody = (typeof step.body === 'function') ? step.body() : (step.body || '');
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
          (step.nextLabel || 'Ya lo hice →') + '</button>';
      } else if (step.primaryHref) {
        html += '<button type="button" class="sp-tour-primary" data-act="go">' +
          (step.primaryLabel || 'Continuar') + '</button>';
      } else if (step.reviewMode) {
        html += '<button type="button" class="sp-tour-primary" data-act="review">' +
          (step.reviewLabel || 'Revisar →') + '</button>';
        html += '<button type="button" class="sp-tour-ghost" data-act="next">' +
          (step.nextLabel || 'Terminar guía →') + '</button>';
      } else {
        html += '<button type="button" class="sp-tour-next" data-act="next">' +
          (step.nextLabel || 'Siguiente') + '</button>';
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
        // Si el paso pide un clic en un enlace del menú, «Ya lo hice» navega ahí.
        if (step.waitClick && step.selector) {
          var target = el || qs(step.selector);
          var href = target && target.getAttribute ? target.getAttribute('href') : null;
          if (href && href !== '#') {
            var st = loadState() || {};
            st.step = (typeof step.advanceTo === 'number') ? step.advanceTo : ((st.step || 0) + 1);
            saveState(st);
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

  function highlightAuditSection() {
    clearTargets();
    placeHole(null);
    var section = qs('[data-tour="audit-paracaidistas"]');
    var toggle = qs('[data-tour="audit-paracaidistas-toggle"]');
    var collapse = qs('#collapseParacaidistas');
    var target = toggle || section;
    if (!target) {
      placeCardModal();
      return null;
    }
    target.classList.add('sp-tour-target');
    try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    if (_visibleRect(target)) {
      placeHole(target);
      placeCardNear(target);
    } else {
      placeHole(null);
      placeCardModal();
    }
    // Abrir la sección para que se vea el contador y la fila, sin enfocar aún el botón
    try {
      if (collapse && !collapse.classList.contains('show')) {
        if (typeof window.openAuditoriaSection === 'function') {
          window.openAuditoriaSection('#collapseParacaidistas');
        } else if (window.jQuery) {
          window.jQuery(collapse).collapse('show');
        } else if (toggle) {
          toggle.click();
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
    var section = qs('[data-tour="audit-paracaidistas"]');
    var toggle = qs('[data-tour="audit-paracaidistas-toggle"]');
    var collapse = qs('#collapseParacaidistas');
    var settled = false;

    function finish(target, holeEl) {
      if (settled) return target || null;
      settled = true;
      if (!target) {
        placeHole(null);
        placeCardModal();
        if (done) done(null);
        return null;
      }
      target.classList.add('sp-tour-target');
      try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
      var holeTarget = holeEl || target;
      // Solo agujero si el rect es usable; si no, tarjeta modal (sin círculo fantasma).
      if (_visibleRect(holeTarget)) {
        placeHole(holeTarget);
        placeCardNear(holeTarget);
      } else if (_visibleRect(target)) {
        placeHole(target);
        placeCardNear(target);
      } else if (toggle && _visibleRect(toggle)) {
        placeHole(toggle);
        placeCardNear(toggle);
      } else if (section && _visibleRect(section)) {
        placeHole(section);
        placeCardNear(section);
      } else {
        placeHole(null);
        placeCardModal();
      }
      if (done) done(target);
      return target;
    }

    function pickRow() {
      var row = null;
      var scope = collapse || document;
      if (needle) {
        scope.querySelectorAll('[data-tour-audit-row]').forEach(function (tr) {
          if (row) return;
          if ((tr.getAttribute('data-dni') || '').toUpperCase().trim() === needle) row = tr;
        });
      }
      if (!row) row = (collapse && collapse.querySelector('[data-tour-audit-row]')) ||
        qs('#collapseParacaidistas [data-tour-audit-row]');
      return row;
    }

    function afterOpen() {
      if (settled) return null;
      var row = pickRow();
      if (row && _visibleRect(row)) {
        row.classList.add('sp-tour-target', 'sp-tour-highlight-user');
        var btn = row.querySelector('[data-tour="audit-aceptar"]');
        var btnOk = btn && _visibleRect(btn) ? btn : null;
        return finish(btnOk || row, row);
      }
      // Fila aún no medible: enfocar cabecera, no inventar agujero en (0,0)
      return finish(toggle || section, toggle || section);
    }

    function openThenFocus() {
      var needsOpen = collapse && !collapse.classList.contains('show');
      if (toggle && _visibleRect(toggle)) {
        toggle.classList.add('sp-tour-target');
        placeHole(toggle);
        placeCardNear(toggle);
      } else {
        placeHole(null);
        placeCardModal();
      }
      if (!needsOpen) {
        afterOpen();
        return toggle || section;
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
          window.openAuditoriaSection('#collapseParacaidistas');
        } else if (window.jQuery) {
          window.jQuery(collapse).collapse('show');
        } else if (toggle) {
          toggle.click();
        }
      } catch (e) {
        if (toggle) try { toggle.click(); } catch (e2) {}
      }
      // Fallback si el evento Bootstrap no llega
      setTimeout(function () {
        if (!settled) afterOpen();
      }, 500);
      return toggle || section;
    }

    return openThenFocus();
  }

  function fillCredsHint(kind) {
    var st = loadState() || {};
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
      // 0 — ¿Fichar?
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
              run();
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
        body: 'Ya está en plantilla. Siguiente: una obra. Pulsa Continuar y te pediremos ir a Directorio.',
        progress: 'Plantilla · listo',
        nextLabel: 'Continuar a obras',
        onShow: function () {
          var st = loadState() || {};
          highlightRowByDni(st.createdDni);
        },
        onNext: function () {
          var st = loadState() || {};
          saveState({
            active: true,
            chapter: 'obra',
            step: 0,
            wantFichaje: st.wantFichaje,
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
          saveState({
            active: true,
            chapter: 'obra',
            step: 0,
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
          if (st.wantFichaje) {
            st.pendingComplete = false;
            st.chapter = 'fichaje';
            st.step = 0;
            st.active = true;
            saveState(st);
            run();
            return;
          }
          pauseAtChapterEnd();
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
            });
            run();
            return;
          }
          pauseAtChapterEnd();
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
        body: 'Vas a entrar en /mi con el DNI y el PIN del trabajador. Ficharás en la obra y luego veremos el tablero y la auditoría.',
        progress: 'Fichaje · empezar',
        primaryHref: '/admin/tour/fichaje-probar',
        primaryLabel: 'Ir a fichar como operario',
        onBeforeGo: function () {
          var st = loadState() || {};
          st.chapter = 'fichaje';
          st.step = 1;
          st.active = true;
          st.wantFichaje = true;
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
      // 4 — Elegir obra
      {
        when: function () { return isMiFichar() && fichajeEstado() === 'fuera'; },
        selector: '[data-tour="fichar-obra"], #obra',
        title: 'Elige la obra',
        body: 'Selecciona la obra que creaste. Como no estaba planificado, el fichaje lo autoasignará.',
        progress: 'Fichaje · obra',
        onShow: function (el) {
          var st = loadState() || {};
          var name = (st.createdObraNombre || '').toLowerCase();
          if (!el || !name) return;
          Array.prototype.forEach.call(el.options || [], function (opt) {
            if ((opt.textContent || '').toLowerCase().indexOf(name) !== -1) {
              el.value = opt.value;
            }
          });
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
          if (!el) return;
          el.addEventListener('click', function () {
            var st = loadState();
            if (st) { st.step = 6; saveState(st); }
          }, { once: true });
        },
      },
      // 6 — Éxito → volver al tablero
      {
        when: function () { return isMiFichar() && fichajeEstado() === 'dentro'; },
        modal: true,
        title: '¡Fichaje hecho!',
        body: 'Volvemos al tablero: verás al operario dentro de la obra. La pelota roja indica que fichó sin estar planificado.',
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
      },
      // 7 — Tablero: chip en la obra + pelota roja
      {
        when: function () {
          return !pathIs(/\/sync\/auditoria/) && (
            pathIs(/\/admin\/obras_detailed/) ||
            (new URLSearchParams(window.location.search || '')).get('tour') === 'fichaje_done'
          );
        },
        manualTarget: true,
        title: 'En la obra, con pelota roja',
        body: 'El operario está en la obra (no en libres). La pelota roja significa que fichó sin estar planificado: hay que revisarlo en Auditoría de fichajes.',
        progress: 'Fichaje · tablero',
        nextLabel: 'Siguiente',
        onShow: function () {
          highlightWorkerChip();
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
      // 9 — Sección «Fichajes sin planificar»
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && !(st && (st.step || 0) >= 10);
        },
        manualTarget: true,
        title: 'Fichajes sin planificar',
        body: 'En esta sección aparece el fichaje que acabas de hacer: el operario no estaba planificado en esa obra.',
        progress: 'Fichaje · auditoría',
        nextLabel: 'Ver el fichaje →',
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
      // 10 — Fila concreta + Aceptar
      {
        when: function () {
          var st = loadState();
          return pathIs(/\/sync\/auditoria/) && !!(st && (st.step || 0) >= 10) && (st.step || 0) < 11;
        },
        manualTarget: true,
        title: 'Acepta este fichaje',
        body: 'Es el de tu operario. Pulsa <strong>Aceptar</strong> para validarlo en esa obra.',
        progress: 'Fichaje · resolver',
        waitClick: true,
        nextLabel: 'Ya lo acepté →',
        onShow: function () {
          highlightAuditParacaidista(function (btn) {
            if (!btn) return;
            btn.addEventListener('click', function () {
              var st = loadState();
              if (st) { st.step = 11; saveState(st); }
              setTimeout(function () { run(); }, 600);
            }, { once: true });
          });
        },
        onNext: function () {
          var st = loadState() || {};
          st.step = 11;
          saveState(st);
          run();
        },
      },
      // 11 — Fin
      {
        when: function () {
          var st = loadState();
          return !!(st && (st.step || 0) >= 11);
        },
        title: '',
        body: '',
        onShow: function () {
          pauseAtChapterEnd();
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

    // En /mi nunca debe correr el capítulo de plantilla/obras
    if ((isMiEntrar() || isMiFichar()) && state.chapter !== 'fichaje') {
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
    // Continuar capítulo fichaje en /mi (no reiniciar la guía)
    if (tour === 'mi' || tour === 'continuar') {
      var stMi = loadState() || {};
      stMi.active = true;
      stMi.chapter = 'fichaje';
      stMi.wantFichaje = true;
      if (isMiEntrar()) stMi.step = 1;
      else if (isMiFichar() && fichajeEstado() === 'dentro') stMi.step = 6;
      else if (isMiFichar()) stMi.step = 4;
      else if (typeof stMi.step !== 'number' || stMi.step < 1) stMi.step = 1;
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
      startTour('obra');
      return true;
    }
    if (tour === 'fichaje') {
      startTour('fichaje');
      return true;
    }
    return false;
  }

  function boot() {
    bindLauncher();
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
