/**
 * Selector de etiquetas por chips (catálogo clicable + seleccionadas con X).
 * No depende de Select2.
 */
(function (window, document) {
  'use strict';

  function isPlainColor(c) {
    var t = String(c || '').trim().toLowerCase();
    return !t || t === '#fff' || t === '#ffffff' || t === 'white';
  }

  function rebuildEmpty($selected, emptyText) {
    if ($selected.querySelector('[data-id]')) {
      var empty = $selected.querySelector('[data-role="empty"]');
      if (empty) empty.remove();
      return;
    }
    if (!$selected.querySelector('[data-role="empty"]')) {
      var span = document.createElement('span');
      span.className = 'sp-etiqueta-picker-empty';
      span.setAttribute('data-role', 'empty');
      span.textContent = emptyText || 'Ninguna seleccionada';
      $selected.appendChild(span);
    }
  }

  function syncCatalog(root) {
    var selectedIds = {};
    root.querySelectorAll('[data-role="selected"] [data-id]').forEach(function (chip) {
      selectedIds[String(chip.getAttribute('data-id'))] = true;
    });
    root.querySelectorAll('[data-role="catalog"] [data-id]').forEach(function (btn) {
      var id = String(btn.getAttribute('data-id'));
      var on = !!selectedIds[id];
      btn.classList.toggle('is-selected', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function addChip(root, id, nombre, color) {
    var selected = root.querySelector('[data-role="selected"]');
    if (!selected) return;
    if (selected.querySelector('[data-id="' + id + '"]')) return;

    var empty = selected.querySelector('[data-role="empty"]');
    if (empty) empty.remove();

    var name = root.getAttribute('data-input-name') || 'etiqueta_ids[]';
    var plain = isPlainColor(color);
    var chip = document.createElement('span');
    chip.className = 'sp-etiqueta-chip sp-etiqueta-chip--pick' + (plain ? ' sp-etiqueta-chip--plain' : '');
    chip.setAttribute('data-id', id);
    if (!plain) {
      chip.style.background = color;
      chip.style.borderColor = color;
      chip.style.color = '#fff';
    }

    var label = document.createElement('span');
    label.className = 'sp-etiqueta-chip-label';
    label.textContent = nombre;
    chip.appendChild(label);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'sp-etiqueta-chip-remove';
    btn.setAttribute('data-role', 'remove');
    btn.setAttribute('aria-label', 'Quitar');
    btn.innerHTML = '&times;';
    chip.appendChild(btn);

    var hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.name = name;
    hidden.value = id;
    chip.appendChild(hidden);

    selected.appendChild(chip);
    syncCatalog(root);
  }

  function removeChip(root, id) {
    var selected = root.querySelector('[data-role="selected"]');
    if (!selected) return;
    var chip = selected.querySelector('[data-id="' + id + '"]');
    if (chip) chip.remove();
    var emptyText = (selected.getAttribute('data-empty') || 'Ninguna seleccionada');
    rebuildEmpty(selected, emptyText);
    syncCatalog(root);
  }

  function bindPicker(root) {
    if (!root || root.dataset.bound === '1') return;
    if (root.classList.contains('sp-etiqueta-picker--disabled')) return;
    root.dataset.bound = '1';

    root.addEventListener('click', function (ev) {
      var removeBtn = ev.target.closest('[data-role="remove"]');
      if (removeBtn) {
        ev.preventDefault();
        var chip = removeBtn.closest('[data-id]');
        if (chip) removeChip(root, chip.getAttribute('data-id'));
        return;
      }
      var catalogBtn = ev.target.closest('[data-role="catalog"] [data-id]');
      if (catalogBtn) {
        ev.preventDefault();
        var id = catalogBtn.getAttribute('data-id');
        if (catalogBtn.classList.contains('is-selected')) {
          removeChip(root, id);
        } else {
          addChip(
            root,
            id,
            catalogBtn.getAttribute('data-nombre') || catalogBtn.textContent.trim(),
            catalogBtn.getAttribute('data-color') || ''
          );
        }
      }
    });
  }

  function initAll(scope) {
    var root = scope || document;
    root.querySelectorAll('.sp-etiqueta-picker').forEach(bindPicker);
  }

  window.initEtiquetaPickers = initAll;
  window.spEtiquetaChipHtml = function (nombre, color) {
    var plain = isPlainColor(color);
    var cls = 'sp-etiqueta-chip' + (plain ? ' sp-etiqueta-chip--plain' : '');
    var style = plain
      ? ''
      : ' style="background:' + String(color).replace(/"/g, '') + ';border-color:' + String(color).replace(/"/g, '') + ';color:#fff;"';
    var safe = String(nombre == null ? '' : nombre)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return '<span class="' + cls + '"' + style + '>' + safe + '</span>';
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { initAll(); });
  } else {
    initAll();
  }
})(window, document);
