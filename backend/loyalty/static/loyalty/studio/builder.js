/* Campagne Studio builder: action-section toggling, matcher rows, live
   Shopify product search, live rule sentence and push-notification mock.
   Plain vanilla JS, same approach as the analytics dashboard. */
(function () {
  'use strict';

  var form = document.getElementById('builder-form');
  if (!form) return;

  var sentenceUrl = form.dataset.sentenceUrl;
  var searchUrl = form.dataset.searchUrl;
  var userSearchUrl = form.dataset.userSearchUrl;
  var audienceCountUrl = form.dataset.audienceCountUrl;
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

  var audienceModeSelect = document.getElementById('id_audience_mode');
  var audienceModeHint = document.getElementById('audience-mode-hint');

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
    var audienceOnly = audienceModeSelect.value === 'audience';
    document.querySelectorAll('[data-orders-only]').forEach(function (el) {
      el.hidden = audienceOnly;
    });
    var entryModeField = document.getElementById('id_entry_mode');
    if (entryModeField) entryModeField.closest('.field').hidden = audienceOnly;
    // Per-prize code fields only matter for a Shopify-code fulfillment.
    syncPrizes();
    if (audienceModeHint) {
      audienceModeHint.textContent = audienceOnly
        ? 'Iedereen in de doelgroep doet automatisch mee zodra de campagne actief wordt. ' +
          'Klanten die later aan de filters gaan voldoen worden ’s nachts toegevoegd.'
        : 'Filters en handmatige selectie zijn hier een extra voorwaarde bovenop de ' +
          'aankoopvoorwaarden. Alles leeg = iedereen kan meedoen.';
    }
    updatePushMock();
  }
  actionSelect.addEventListener('change', function () { updateSections(); scheduleSentence(); });
  fulfillmentSelect.addEventListener('change', function () { updateSections(); scheduleSentence(); });
  audienceModeSelect.addEventListener('change', function () {
    updateSections();
    scheduleSentence();
    scheduleAudienceCount();
  });

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

  // ---------- Prize tiers ----------
  // Same idiom as the matcher rows: the visible inputs are mirrored into one
  // hidden JSON field that the form parser reads back.
  var prizeContainer = document.getElementById('prize-rows');
  var prizeInput = document.getElementById('id_raffle_prizes');
  var numWinnersField = document.getElementById('num-winners-field');
  var numWinnersInput = document.getElementById('id_num_winners');

  var DISCOUNT_TYPES = [
    ['', 'Zelfde als campagne'],
    ['fixed_amount', 'Vast bedrag'],
    ['percentage', 'Percentage'],
    ['free_shipping', 'Gratis verzending'],
    ['free_product', 'Gratis product'],
  ];

  function readPrizes() {
    try {
      var parsed = JSON.parse(prizeInput.value || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function syncPrizes() {
    var prizes = [];
    prizeContainer.querySelectorAll('.prize-row').forEach(function (row) {
      var value = function (field) {
        var el = row.querySelector('[data-prize-field="' + field + '"]');
        return el ? el.value.trim() : '';
      };
      if (!value('name')) return;
      prizes.push({
        name: value('name'),
        description: value('description'),
        image_url: value('image_url'),
        quantity: value('quantity') || '1',
        discount_type: value('discount_type'),
        discount_value: value('discount_value'),
        discount_product_gid: value('discount_product_gid'),
        discount_validity_days: value('discount_validity_days'),
      });
    });
    prizeInput.value = JSON.stringify(prizes);
    updatePrizeChrome(prizes);
  }

  function updatePrizeChrome(prizes) {
    // With tiers the winner count is the sum of the quantities, so the
    // manual field would only be able to contradict the draw.
    var total = 0;
    prizes.forEach(function (prize) {
      total += parseInt(prize.quantity, 10) || 1;
    });
    if (numWinnersField) numWinnersField.hidden = prizes.length > 0;
    if (numWinnersInput && prizes.length) numWinnersInput.value = String(total);
    prizeContainer.querySelectorAll('.prize-row').forEach(function (row, index) {
      var label = row.querySelector('.prize-index');
      if (label) label.textContent = 'Prijs ' + (index + 1);
      var discountBlock = row.querySelector('[data-prize-discount]');
      if (discountBlock) {
        discountBlock.hidden = fulfillmentSelect.value !== 'shopify_code';
      }
    });
  }

  function prizeField(row, labelText, field, attrs) {
    var wrap = document.createElement('div');
    wrap.className = 'field';
    var label = document.createElement('label');
    label.textContent = labelText;
    wrap.appendChild(label);
    var input = document.createElement(attrs.tag || 'input');
    if (!attrs.tag) input.type = attrs.type || 'text';
    if (attrs.min) input.min = attrs.min;
    if (attrs.step) input.step = attrs.step;
    if (attrs.placeholder) input.placeholder = attrs.placeholder;
    input.dataset.prizeField = field;
    input.value = attrs.value || '';
    input.addEventListener('input', function () { syncPrizes(); scheduleSentence(); });
    input.addEventListener('change', function () { syncPrizes(); scheduleSentence(); });
    wrap.appendChild(input);
    row.appendChild(wrap);
    return input;
  }

  function addPrizeRow(prize) {
    prize = prize || {};
    var row = document.createElement('div');
    row.className = 'prize-row';

    var head = document.createElement('div');
    head.className = 'prize-head';
    var index = document.createElement('span');
    index.className = 'prize-index';
    head.appendChild(index);
    var remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove';
    remove.textContent = 'Verwijderen';
    remove.addEventListener('click', function () {
      row.remove();
      syncPrizes();
      scheduleSentence();
    });
    head.appendChild(remove);
    row.appendChild(head);

    var top = document.createElement('div');
    top.className = 'field-row';
    prizeField(top, 'Naam', 'name', {
      value: prize.name, placeholder: 'bijv. T-shirt',
    });
    prizeField(top, 'Aantal', 'quantity', {
      type: 'number', min: '1', value: prize.quantity || 1,
    });
    row.appendChild(top);

    var details = document.createElement('div');
    details.className = 'field-row';
    prizeField(details, 'Omschrijving (zichtbaar in de app)', 'description', {
      tag: 'textarea', value: prize.description,
    });
    prizeField(details, 'Afbeelding-URL (optioneel)', 'image_url', {
      type: 'url', value: prize.image_url,
    });
    row.appendChild(details);

    var discount = document.createElement('div');
    discount.dataset.prizeDiscount = 'true';
    var discountRow = document.createElement('div');
    discountRow.className = 'field-row';

    var typeWrap = document.createElement('div');
    typeWrap.className = 'field';
    var typeLabel = document.createElement('label');
    typeLabel.textContent = 'Kortingstype van deze prijs';
    typeWrap.appendChild(typeLabel);
    var typeSelect = document.createElement('select');
    typeSelect.dataset.prizeField = 'discount_type';
    DISCOUNT_TYPES.forEach(function (pair) {
      var opt = document.createElement('option');
      opt.value = pair[0];
      opt.textContent = pair[1];
      if ((prize.discount_type || '') === pair[0]) opt.selected = true;
      typeSelect.appendChild(opt);
    });
    typeSelect.addEventListener('change', function () { syncPrizes(); });
    typeWrap.appendChild(typeSelect);
    discountRow.appendChild(typeWrap);

    prizeField(discountRow, 'Waarde (€ of %)', 'discount_value', {
      type: 'number', step: '0.01', min: '0', value: prize.discount_value,
    });
    prizeField(discountRow, 'Geldigheid (dagen)', 'discount_validity_days', {
      type: 'number', min: '1', value: prize.discount_validity_days,
    });
    discount.appendChild(discountRow);

    var gidRow = document.createElement('div');
    gidRow.className = 'field-row';
    prizeField(gidRow, 'Shopify product-ID of GID (bij gratis product)',
      'discount_product_gid', {
        value: prize.discount_product_gid,
        placeholder: '123456789 of gid://shopify/Product/123456789',
      });
    discount.appendChild(gidRow);
    row.appendChild(discount);

    prizeContainer.appendChild(row);
  }

  document.getElementById('add-prize').addEventListener('click', function () {
    addPrizeRow();
    syncPrizes();
  });

  readPrizes().forEach(addPrizeRow);
  syncPrizes();

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

  // ---------- Audience: manual user picker ----------
  var userSearchInput = document.getElementById('id_user_search');
  var userSearchResults = document.getElementById('user-search-results');
  var userSearchStatus = document.getElementById('user-search-status');
  var userChips = document.getElementById('manual-user-chips');
  var manualUsersInput = document.getElementById('id_manual_users');
  var userSearchTimer = null;

  function readManualUsers() {
    try {
      var parsed = JSON.parse(manualUsersInput.value || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function writeManualUsers(users) {
    manualUsersInput.value = JSON.stringify(users);
    renderUserChips(users);
    scheduleAudienceCount();
  }

  function renderUserChips(users) {
    userChips.innerHTML = '';
    users.forEach(function (user) {
      var chip = document.createElement('div');
      chip.className = 'matcher-row';
      var label = document.createElement('span');
      label.className = 'matcher-label';
      label.textContent = user.label;
      chip.appendChild(label);
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'remove';
      remove.textContent = 'Verwijderen';
      remove.addEventListener('click', function () {
        writeManualUsers(readManualUsers().filter(function (u) {
          return u.id !== user.id;
        }));
      });
      chip.appendChild(remove);
      userChips.appendChild(chip);
    });
  }

  function addManualUser(user) {
    var users = readManualUsers();
    if (users.some(function (u) { return u.id === user.id; })) return;
    users.push({ id: user.id, label: user.email });
    writeManualUsers(users);
  }

  userSearchInput.addEventListener('input', function () {
    var query = userSearchInput.value.trim();
    clearTimeout(userSearchTimer);
    if (query.length < 2) {
      userSearchResults.hidden = true;
      userSearchStatus.hidden = true;
      return;
    }
    userSearchTimer = setTimeout(function () {
      userSearchStatus.textContent = 'Zoeken…';
      userSearchStatus.hidden = false;
      fetch(userSearchUrl + '?q=' + encodeURIComponent(query), {
        credentials: 'same-origin',
      })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          var users = data.users || [];
          userSearchResults.innerHTML = '';
          if (!users.length) {
            userSearchStatus.textContent = 'Geen klanten gevonden.';
            userSearchStatus.hidden = false;
            userSearchResults.hidden = true;
            return;
          }
          userSearchStatus.hidden = true;
          users.forEach(function (user) {
            var item = document.createElement('div');
            item.className = 'result';
            var title = document.createElement('div');
            title.className = 'r-title';
            title.textContent = user.email;
            item.appendChild(title);
            if (user.name) {
              var meta = document.createElement('div');
              meta.className = 'r-meta';
              meta.textContent = user.name;
              item.appendChild(meta);
            }
            item.addEventListener('click', function () {
              addManualUser(user);
              userSearchResults.hidden = true;
              userSearchInput.value = '';
            });
            userSearchResults.appendChild(item);
          });
          userSearchResults.hidden = false;
        })
        .catch(function () {
          userSearchStatus.textContent = 'Zoeken mislukt.';
          userSearchStatus.hidden = false;
        });
    }, 350);
  });

  renderUserChips(readManualUsers());

  // ---------- Audience: live count ----------
  var audienceCountBox = document.getElementById('audience-count');
  var audienceCountTimer = null;

  function scheduleAudienceCount() {
    clearTimeout(audienceCountTimer);
    audienceCountTimer = setTimeout(fetchAudienceCount, 500);
  }

  function fetchAudienceCount() {
    if (!audienceCountBox) return;
    fetch(audienceCountUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfToken },
      body: new FormData(form),
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (!data.restricted) {
          audienceCountBox.textContent = audienceModeSelect.value === 'audience'
            ? 'Nog geen doelgroep: kies een filter of selecteer klanten.'
            : 'Geen doelgroepbeperking — iedereen kan meedoen.';
        } else {
          audienceCountBox.textContent = 'Doelgroep op dit moment: ' +
            data.count + (data.count === 1 ? ' klant.' : ' klanten.');
        }
      })
      .catch(function () { /* transient; next change retries */ });
  }

  ['id_aud_min_age', 'id_aud_birthday_month', 'id_aud_min_app_age_days',
   'id_aud_min_lifetime_orders', 'id_aud_active_within_days'].forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('change', function () { scheduleAudienceCount(); scheduleSentence(); });
    el.addEventListener('input', function () { scheduleAudienceCount(); scheduleSentence(); });
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
    syncPrizes();
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
  scheduleAudienceCount();

  // Keep the hidden matcher/prize JSON current on submit.
  form.addEventListener('submit', function () {
    syncHidden();
    syncPrizes();
  });
})();
