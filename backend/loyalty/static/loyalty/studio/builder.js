/* Campagne Studio builder: action-section toggling, matcher rows, live
   Shopify product search, live rule sentence and push-notification mock.
   Plain vanilla JS, same approach as the analytics dashboard. */
(function () {
  'use strict';

  var form = document.getElementById('builder-form');
  if (!form) return;

  var sentenceUrl = form.dataset.sentenceUrl;
  var searchUrl = form.dataset.searchUrl;
  var csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;

  var MATCHER_TYPES = [
    ['sku', 'SKU'],
    ['product_id', 'Product-ID'],
    ['title', 'Titel bevat'],
    ['tag', 'Tag'],
    ['collection', 'Collectie'],
  ];

  var DEFAULT_TITLES = {
    points: 'Je hebt bonuspunten verdiend!',
    discount_code: 'Je hebt een kortingscode verdiend!',
    raffle: 'Je doet mee met de loting!',
  };

  // ---------- Action sections ----------
  var actionSelect = document.getElementById('id_action_type');
  var fulfillmentSelect = document.getElementById('id_fulfillment_type');

  function updateSections() {
    var action = actionSelect.value;
    document.querySelectorAll('[data-action-section]').forEach(function (el) {
      el.hidden = el.dataset.actionSection !== action;
    });
    var needsDiscount = action === 'discount_code' ||
      (action === 'raffle' && fulfillmentSelect.value === 'shopify_code');
    document.querySelectorAll('[data-discount-section]').forEach(function (el) {
      el.hidden = !needsDiscount;
    });
    updatePushMock();
  }
  actionSelect.addEventListener('change', function () { updateSections(); scheduleSentence(); });
  fulfillmentSelect.addEventListener('change', function () { updateSections(); scheduleSentence(); });

  // ---------- Matcher rows ----------
  var rowsContainer = document.getElementById('matcher-rows');
  var hiddenInput = document.getElementById('id_product_matchers');

  function readMatchers() {
    try {
      var parsed = JSON.parse(hiddenInput.value || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function syncHidden() {
    var matchers = [];
    rowsContainer.querySelectorAll('.matcher-row').forEach(function (row) {
      var type = row.querySelector('select').value;
      var value = row.querySelector('input').value.trim();
      var label = row.dataset.label || '';
      if (!value) return;
      var entry = { type: type, value: value };
      if (label) entry.label = label;
      matchers.push(entry);
    });
    hiddenInput.value = JSON.stringify(matchers);
  }

  function addRow(matcher) {
    matcher = matcher || { type: 'sku', value: '' };
    var row = document.createElement('div');
    row.className = 'matcher-row';
    if (matcher.label) row.dataset.label = matcher.label;

    var select = document.createElement('select');
    MATCHER_TYPES.forEach(function (pair) {
      var opt = document.createElement('option');
      opt.value = pair[0];
      opt.textContent = pair[1];
      if (matcher.type === pair[0]) opt.selected = true;
      select.appendChild(opt);
    });

    var input = document.createElement('input');
    input.type = 'text';
    input.value = matcher.value || '';
    input.placeholder = 'waarde…';

    var label = document.createElement('span');
    label.className = 'matcher-label';
    label.textContent = matcher.label || '';

    var remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove';
    remove.textContent = 'Verwijderen';
    remove.addEventListener('click', function () {
      row.remove();
      syncHidden();
      scheduleSentence();
    });

    select.addEventListener('change', function () {
      delete row.dataset.label;
      label.textContent = '';
      syncHidden();
      scheduleSentence();
    });
    input.addEventListener('input', function () { syncHidden(); scheduleSentence(); });

    row.appendChild(select);
    row.appendChild(input);
    row.appendChild(label);
    row.appendChild(remove);
    rowsContainer.appendChild(row);
  }

  document.getElementById('add-matcher').addEventListener('click', function () {
    addRow();
  });

  readMatchers().forEach(addRow);
  syncHidden();

  // ---------- Product search ----------
  var searchInput = document.getElementById('id_product_search');
  var searchResults = document.getElementById('search-results');
  var searchStatus = document.getElementById('search-status');
  var searchTimer = null;

  function addProductRow(product) {
    addRow({ type: 'product_id', value: String(product.id), label: product.title });
  }

  function renderResults(products, opts) {
    opts = opts || {};
    searchResults.innerHTML = '';
    if (!products.length) {
      searchStatus.textContent = opts.idLookup
        ? 'Geen producten gevonden bij deze product-ID(’s).'
        : 'Geen producten gevonden.';
      searchStatus.hidden = false;
      searchResults.hidden = true;
      return;
    }
    if (opts.missing && opts.missing.length) {
      searchStatus.textContent = 'Niet gevonden in Shopify: ' + opts.missing.join(', ');
      searchStatus.hidden = false;
    } else {
      searchStatus.hidden = true;
    }
    if (opts.idLookup && products.length > 1) {
      var addAll = document.createElement('div');
      addAll.className = 'result add-all';
      addAll.textContent = '+ Voeg alle ' + products.length + ' producten toe';
      addAll.addEventListener('click', function () {
        products.forEach(addProductRow);
        syncHidden();
        scheduleSentence();
        searchResults.hidden = true;
        searchInput.value = '';
      });
      searchResults.appendChild(addAll);
    }
    products.forEach(function (product) {
      var item = document.createElement('div');
      item.className = 'result';
      if (product.image_url) {
        var img = document.createElement('img');
        img.src = product.image_url;
        img.alt = '';
        item.appendChild(img);
      }
      var title = document.createElement('div');
      title.className = 'r-title';
      title.textContent = product.title;
      item.appendChild(title);
      var meta = document.createElement('div');
      meta.className = 'r-meta';
      meta.textContent = product.sku ? 'SKU ' + product.sku : 'ID ' + product.id;
      item.appendChild(meta);
      item.addEventListener('click', function () {
        addProductRow(product);
        syncHidden();
        scheduleSentence();
        searchResults.hidden = true;
        searchInput.value = '';
      });
      searchResults.appendChild(item);
    });
    searchResults.hidden = false;
  }

  searchInput.addEventListener('input', function () {
    var query = searchInput.value.trim();
    clearTimeout(searchTimer);
    if (query.length < 2) {
      searchResults.hidden = true;
      searchStatus.hidden = true;
      return;
    }
    searchTimer = setTimeout(function () {
      searchStatus.textContent = 'Zoeken…';
      searchStatus.hidden = false;
      fetch(searchUrl + '?q=' + encodeURIComponent(query), {
        credentials: 'same-origin',
      })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          renderResults(data.products || [], {
            idLookup: !!data.id_lookup,
            missing: data.missing || [],
          });
        })
        .catch(function () {
          searchStatus.textContent = 'Zoeken mislukt — controleer de Shopify-koppeling.';
          searchStatus.hidden = false;
        });
    }, 350);
  });

  // ---------- Live rule sentence ----------
  var sentenceBox = document.getElementById('sentence-preview');
  var sentenceTimer = null;

  function scheduleSentence() {
    clearTimeout(sentenceTimer);
    sentenceTimer = setTimeout(fetchSentence, 450);
  }

  function fetchSentence() {
    syncHidden();
    var body = new FormData(form);
    fetch(sentenceUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfToken },
      body: body,
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (data.sentence) {
          sentenceBox.textContent = data.sentence;
          sentenceBox.classList.remove('muted');
        } else {
          sentenceBox.textContent = data.error || 'De zin kon nog niet gemaakt worden.';
          sentenceBox.classList.add('muted');
        }
        updatePushMock(data.sentence || '');
      })
      .catch(function () { /* transient; next keystroke retries */ });
  }

  ['id_window_start', 'id_window_end', 'id_points_amount', 'id_points_mode',
   'id_discount_type', 'id_discount_value', 'id_min_distinct_products',
   'id_min_total_quantity', 'id_min_order_count', 'id_min_order_value',
   'id_min_total_spend', 'id_first_order_only', 'id_requires_untappd',
   'id_prize_name', 'id_entry_mode'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('change', scheduleSentence);
    if (el) el.addEventListener('input', scheduleSentence);
  });

  // ---------- Push-notification mock ----------
  var titleInput = document.getElementById('id_qualify_title');
  var bodyInput = document.getElementById('id_qualify_body');
  var mockTitle = document.getElementById('push-mock-title');
  var mockBody = document.getElementById('push-mock-body');
  var lastSentence = '';

  function updatePushMock(sentence) {
    if (typeof sentence === 'string' && sentence) lastSentence = sentence;
    var action = actionSelect.value;
    mockTitle.textContent = titleInput.value.trim() ||
      DEFAULT_TITLES[action] || 'House of Beers';
    var fallbackBody = lastSentence || 'Standaardtekst op basis van de campagne.';
    if (action === 'raffle') {
      var prize = document.getElementById('id_prize_name').value.trim();
      if (prize) fallbackBody = 'Je loot mee voor: ' + prize + '. ' + (lastSentence || '');
    }
    mockBody.textContent = bodyInput.value.trim() || fallbackBody;
  }
  titleInput.addEventListener('input', function () { updatePushMock(); });
  bodyInput.addEventListener('input', function () { updatePushMock(); });
  var prizeInput = document.getElementById('id_prize_name');
  if (prizeInput) prizeInput.addEventListener('input', function () { updatePushMock(); });

  // ---------- Init ----------
  updateSections();
  updatePushMock();
  scheduleSentence();

  // Keep the hidden matcher JSON current on submit.
  form.addEventListener('submit', syncHidden);
})();
