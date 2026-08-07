/**
 * Select2: anclar el desplegable al campo con position:fixed + getBoundingClientRect.
 * Necesario cuando el scroll está en .admin-main / .planificador-page / .modal-body
 * (Select2 solo escucha scroll de window y se “despega” del control).
 */
(function (global) {
  'use strict';

  function defaultScrollRoots() {
    return [
      document.querySelector('.planificador-page'),
      document.querySelector('.admin-main'),
      document.querySelector('.modal.show .modal-body'),
      document.querySelector('.modal.show'),
    ].filter(Boolean);
  }

  /**
   * @param {JQuery} $select
   * @param {Element[]} [scrollRoots]
   */
  function bindFixedDropdown($select, scrollRoots) {
    if (!$select || !$select.length || typeof $ === 'undefined') return;
    if ($select.data('spFixedDropdownBound')) return;
    $select.data('spFixedDropdownBound', true);

    const roots = (scrollRoots && scrollRoots.length) ? scrollRoots : defaultScrollRoots();
    let reposition = null;

    function findOpenDropdown() {
      // Contenedor que Select2 AttachBody coloca en dropdownParent
      const $open = $('.select2-container--open').filter(function () {
        return $(this).find('.select2-dropdown').length > 0;
      }).last();
      return $open.length ? $open : null;
    }

    function place() {
      const $trigger = $select.next('.select2-container');
      const $open = findOpenDropdown();
      if (!$trigger.length || !$open) return;
      const r = $trigger[0].getBoundingClientRect();
      const $dd = $open.find('.select2-dropdown');
      const ddH = $dd.outerHeight() || 280;
      const spaceBelow = window.innerHeight - r.bottom;
      const openAbove = spaceBelow < Math.min(ddH, 240) && r.top > spaceBelow;
      const top = openAbove
        ? Math.max(8, r.top - ddH - 2)
        : (r.bottom + 2);
      $open.css({
        position: 'fixed',
        top: top + 'px',
        left: Math.max(8, r.left) + 'px',
        width: Math.max(r.width, 160) + 'px',
        transform: 'none',
      });
    }

    function attachListeners() {
      reposition = function () { place(); };
      requestAnimationFrame(place);
      // Segundo frame: Select2 termina de medir resultados AJAX
      setTimeout(place, 0);
      roots.forEach(function (el) {
        el.addEventListener('scroll', reposition, { passive: true });
      });
      window.addEventListener('resize', reposition);
      window.addEventListener('scroll', reposition, true);
    }

    function detachListeners() {
      if (!reposition) return;
      roots.forEach(function (el) {
        el.removeEventListener('scroll', reposition);
      });
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
      reposition = null;
    }

    $select.on('select2:open.spFixed', function () {
      attachListeners();
      // Resultados AJAX / búsqueda
      $select.on('select2:selecting.spFixed select2:clearing.spFixed', place);
      const obsTarget = document.body;
      if (obsTarget && typeof MutationObserver !== 'undefined') {
        const mo = new MutationObserver(function () { place(); });
        mo.observe(obsTarget, { childList: true, subtree: true });
        $select.data('spFixedMo', mo);
        setTimeout(function () {
          const m = $select.data('spFixedMo');
          if (m) { m.disconnect(); $select.removeData('spFixedMo'); }
        }, 2500);
      }
    });

    $select.on('select2:close.spFixed', function () {
      detachListeners();
      $select.off('select2:selecting.spFixed select2:clearing.spFixed');
      const m = $select.data('spFixedMo');
      if (m) { m.disconnect(); $select.removeData('spFixedMo'); }
    });
  }

  global.SignaPlanSelect2 = {
    bindFixedDropdown: bindFixedDropdown,
    defaultScrollRoots: defaultScrollRoots,
  };
})(window);
