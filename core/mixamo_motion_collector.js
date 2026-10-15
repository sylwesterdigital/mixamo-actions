/*
 Mixamo Motion Collector — browser DevTools console, no installation required.
 - Open https://www.mixamo.com/ with the Animations tab selected.
 - Paste this script in DevTools Console once.
 - Click animation cards normally to collect exact title, description, and thumbnail motion ID.
 - Click Export JSON to download animations.json for mixamo_pipeline.py.
 - Selections and panel position persist in localStorage on mixamo.com between page refreshes.
 - Drag the header to reposition the floating panel; Reset moves it back to the top-right.

 API: mixamoCollector.export(), .list(), .clear(), .destroy().
 This script never downloads FBXs or calls Mixamo's private APIs.
*/
(() => {
  'use strict';

  // Re-pasting the script replaces the UI without losing saved selections.
  window.mixamoCollector?.destroy?.();

  const STORE_KEY = 'mixamo-motion-collector-v1';
  const POSITION_KEY = 'mixamo-motion-collector-position-v1';
  const PRESETS_KEY = 'mixamo-motion-collector-presets-v1';
  const ACTIVE_PRESET_KEY = 'mixamo-motion-collector-active-preset-v1';
  const MINIMIZED_KEY = 'mixamo-motion-collector-minimized-v1';
  const RESULTS_SELECTOR = '.product-results .product.product-animation';
  const SELECTED_SELECTOR = '.product-results .product.product-animation.product-selected';
  const root = document.createElement('div');
  root.id = 'mixamo-motion-collector-root';
  root.style.cssText = 'all: initial; position: fixed; z-index: 2147483647; top: 72px; right: 18px; width: 390px; max-width: calc(100vw - 24px); font-family: Arial, Helvetica, sans-serif; color: #e9eef5;';
  document.body.appendChild(root);
  const shadow = root.attachShadow({mode: 'open'});
  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      *, *::before, *::after { box-sizing: border-box; }
      .panel { background: #161d29; color: #edf2fc; border: 1px solid #39445a; border-radius: 12px; box-shadow: 0 12px 36px #0009; overflow: hidden; font: 13px/1.42 Arial, Helvetica, sans-serif; display: flex; flex-direction: column; max-height: calc(100vh - 16px); }
      .head { padding: 12px 13px; background: #202c3e; display: flex; justify-content: space-between; align-items: center; gap: 12px; cursor: grab; touch-action: none; user-select: none; flex-shrink: 0; }
      .head.dragging { cursor: grabbing; }
      .panel.minimized .body { display: none; }
      .body { min-height: 0; display: flex; flex-direction: column; }
      .presets { display: flex; flex-direction: column; gap: 7px; padding: 10px 12px; border-bottom: 1px solid #354256; }
      .presets-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
      select { min-width: 0; width: 100%; padding: 6px; background: #101925; color: #f5f8fc; border: 1px solid #50647c; border-radius: 6px; font: inherit; }
      .presets-hint { font-size: 11px; color: #a9bad1; }
      .head-actions { display: flex; align-items: center; gap: 5px; flex-shrink: 0; }
      .head button { cursor: pointer; touch-action: auto; }
      .title { font-weight: 700; font-size: 14px; }
      .hint { color: #b4c1d7; font-size: 11px; margin-top: 2px; }
      button { font: inherit; background: #35455c; border: 1px solid #50647c; border-radius: 6px; color: #f5f8fc; cursor: pointer; padding: 6px 9px; }
      button:hover { background: #4a6381; }
      button:focus-visible, input:focus-visible { outline: 2px solid #93c5fd; outline-offset: 1px; }
      button.primary { background: #19784f; border-color: #21966a; font-weight: 700; }
      button.primary:hover { background: #218b5e; }
      button.warn { background: #522e33; border-color: #865159; }
      button.tiny { padding: 3px 7px; font-size: 12px; }
      .toolbar { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 12px; border-bottom: 1px solid #354256; }
      .bar { display: flex; justify-content: space-between; gap: 8px; align-items: center; color: #b9c8e0; padding: 8px 12px; }
      .items { max-height: 320px; min-height: 0; flex: 1 1 auto; overflow-y: auto; border-top: 1px solid #354256; }
      .item { padding: 10px 12px; border-bottom: 1px solid #303c4f; }
      .itemtop { display: flex; justify-content: space-between; align-items: flex-start; gap: 6px; }
      .name { font-weight: 700; overflow-wrap: anywhere; }
      .desc { color: #bfcce0; overflow-wrap: anywhere; margin: 4px 0; }
      .motion { color: #8fd7bb; font-family: ui-monospace, Menlo, monospace; font-size: 11px; }
      label { display: block; margin-top: 7px; color: #aebbd0; font-size: 11px; }
      input[type=text] { width: 100%; margin-top: 3px; color: #f1f5fa; background: #0f1620; border: 1px solid #44556b; border-radius: 4px; padding: 5px 7px; font: 12px/1.4 ui-monospace, Menlo, monospace; }
      .foot { padding: 10px 12px; border-top: 1px solid #354256; display: flex; flex-wrap: wrap; gap: 6px; }
      .status { color: #a9bad1; padding: 0 12px 11px; min-height: 20px; font-size: 11px; overflow-wrap: anywhere; }
      .empty { padding: 15px 12px; color: #9eafc6; }
    </style>
    <div class="panel">
      <div class="head">
        <div><div class="title">Mixamo Motion Collector</div><div class="hint">Click cards to collect · Drag this header to move</div></div>
        <div class="head-actions">
          <button class="tiny" id="minimize" title="Minimize floating window" aria-expanded="true">Hide ▾</button>
          <button class="tiny" id="reset-position" title="Return panel to the top-right corner">Reset</button>
          <button class="tiny" id="close" title="Close panel, retain saved selections">×</button>
        </div>
      </div>
      <div class="body" id="body">
      <div class="presets">
        <strong>Saved animation presets</strong>
        <select id="preset-select" aria-label="Saved preset"><option value="">Unsaved collection</option></select>
        <div class="presets-row">
          <button id="preset-save" class="primary" title="Save selection under a new name">Save as new</button>
          <button id="preset-update" title="Overwrite the selected saved preset">Update</button>
          <button id="preset-rename">Rename</button>
          <button id="preset-delete" class="warn">Delete</button>
        </div>
        <div class="presets-hint" id="preset-state">Unsaved collection</div>
      </div>
      <div class="toolbar">
        <button id="capture">Capture: ON</button>
        <button id="selected">Add selected card</button>
        <button id="copy">Copy JSON</button>
      </div>
      <div class="bar"><span id="count">0 motions collected</span><span>Saved on this browser</span></div>
      <div id="items" class="items"></div>
      <div class="foot">
        <button id="export" class="primary">Export animations.json</button>
        <button id="import">Import JSON / presets</button>
        <button id="export-all">Backup all presets</button>
        <button id="clear" class="warn">Clear list</button>
      </div>
      <div id="status" class="status" role="status" aria-live="polite"></div>
      </div>
    </div>
    <input id="file" type="file" accept=".json,application/json" style="display:none" />
  `;

  const el = id => shadow.getElementById(id);
  let entries = [];
  let presets = [];
  let activePresetId = '';
  let minimized = false;
  let capturing = true;
  let disposed = false;
  const listeners = new AbortController();

  const norm = val => String(val ?? '').trim();
  const normalized = val => norm(val).toLocaleLowerCase();
  const cleanFilename = val => norm(val)
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/[. ]+$/g, '').slice(0, 120) || 'Animation';

  function message(text) { el('status').textContent = text; }
  const sameMotions = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const snapshot = () => JSON.parse(JSON.stringify(payload().animations));
  const currentPreset = () => presets.find(p => p.id === activePresetId);
  function dirty() {
    return !!currentPreset() && !sameMotions(snapshot(), currentPreset().animations);
  }
  function renderPresetList() {
    const select = el('preset-select');
    select.replaceChildren(new Option('Unsaved collection', ''));
    for (const preset of [...presets].sort((a,b) => a.name.localeCompare(b.name))) {
      select.add(new Option(`${preset.name} (${preset.animations.length})`, preset.id));
    }
    if (currentPreset()) select.value = activePresetId;
    else select.value = '';
    const current = currentPreset();
    el('preset-state').textContent = current ?
      `${current.name}${dirty() ? ' — UNSAVED changes (click Update)' : ' — saved'}` :
      'Collection is a draft; click Save as new to keep it as a preset.';
    for (const id of ['preset-update','preset-rename','preset-delete']) {
      el(id).disabled = !current;
    }
  }
  function savePresets() {
    try {
      localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
      localStorage.setItem(ACTIVE_PRESET_KEY, activePresetId);
    } catch (err) { message('Could not persist presets: ' + err.message); }
    renderPresetList();
  }
  function loadPresets() {
    try {
      const data = JSON.parse(localStorage.getItem(PRESETS_KEY) || '[]');
      presets = Array.isArray(data) ? data.filter(x =>
        x && typeof x.name === 'string' && Array.isArray(x.animations) && typeof x.id === 'string') : [];
      activePresetId = localStorage.getItem(ACTIVE_PRESET_KEY) || '';
      if (!currentPreset()) activePresetId = '';
    } catch (err) { presets = []; activePresetId = ''; message(err.message); }
  }
  function uniqueName(name, exceptId='') {
    return !presets.some(p => p.id !== exceptId && normalized(p.name) === normalized(name));
  }
  function namedPreset(name, animations) {
    if (!name.trim() || name.length > 100) throw Error('Preset name must contain 1–100 characters.');
    if (!uniqueName(name)) throw Error('A preset with that name already exists.');
    const preset = {id: (crypto.randomUUID?.() || `p_${Date.now()}_${Math.random()}`),
      name: name.trim(), animations: JSON.parse(JSON.stringify(animations)),
      updatedAt: new Date().toISOString()};
    presets.push(preset);
    return preset;
  }
  function saveAsPreset() {
    const name = window.prompt('Name for this animation preset:', currentPreset()?.name || 'My Animations');
    if (name === null) return;
    try {
      const preset = namedPreset(name.trim(), snapshot());
      activePresetId = preset.id;
      savePresets();
      message(`Saved preset: ${preset.name} (${preset.animations.length} animations).`);
    } catch (err) { message(err.message); }
  }
  function updatePreset() {
    const preset = currentPreset();
    if (!preset) { saveAsPreset(); return; }
    preset.animations = snapshot();
    preset.updatedAt = new Date().toISOString();
    savePresets(); message(`Updated preset: ${preset.name}.`);
  }
  function selectPreset(id) {
    if (id === activePresetId) return;
    if (activePresetId && dirty() && !window.confirm('Discard unsaved changes to the current preset?')) {
      renderPresetList(); return;
    }
    if (!activePresetId && id && entries.length && !window.confirm('Replace this unsaved collection with the selected preset?')) {
      renderPresetList(); return;
    }
    if (id === '' && entries.length && !window.confirm('Start a new empty collection? Current draft will be replaced.')) {
      renderPresetList(); return;
    }
    activePresetId = id;
    entries = currentPreset() ? JSON.parse(JSON.stringify(currentPreset().animations)) : [];
    saveStore(); savePresets(); render();
    message(currentPreset() ? `Loaded preset: ${currentPreset().name}.` : 'New empty collection.');
  }
  function renamePreset() {
    const preset = currentPreset(); if (!preset) return;
    const name = window.prompt('New preset name:', preset.name);
    if (name === null) return;
    if (!name.trim() || name.trim().length > 100 || !uniqueName(name.trim(), preset.id)) {
      message('Preset name is empty, too long, or already taken.'); return;
    }
    preset.name = name.trim(); savePresets(); message(`Renamed preset: ${preset.name}.`);
  }
  function deletePreset() {
    const preset = currentPreset(); if (!preset) return;
    if (!window.confirm(`Delete saved preset "${preset.name}"? Collected motions remain in this window.`)) return;
    presets = presets.filter(p => p.id !== activePresetId);
    activePresetId = '';
    saveStore(); savePresets(); message('Preset deleted; current motions kept as an unsaved collection.');
  }
  function exportAllPresets() {
    const data = {format:'mixamo-motion-collector-presets-v1',
      exportedAt:new Date().toISOString(),
      presets:presets.map(p => ({name:p.name, animations:p.animations}))};
    exportObject(data, 'mixamo-presets-backup.json');
    message(`Backed up ${presets.length} presets.`);
  }
  function importPresets(data) {
    let imported = 0;
    for (const item of data.presets || []) {
      if (!item || typeof item.name !== 'string' || !Array.isArray(item.animations)) continue;
      let name = item.name.trim();
      if (!name) continue;
      let n = 2;
      while (!uniqueName(name)) name = `${item.name.trim()} (${n++})`;
      const parsed = item.animations.filter(x => x && /^\d+$/.test(String(x.motionId || '')))
        .map(x => ({search:norm(x.search || x.title), title:norm(x.title),
          description:norm(x.description), motionId:String(x.motionId),
          filename:cleanFilename(x.filename || `${x.title}__${x.motionId}`)}));
      namedPreset(name, parsed); imported++;
    }
    savePresets(); message(`Imported ${imported} saved preset(s).`);
  }
  function exportObject(data, filename) {
    const file = new Blob([JSON.stringify(data, null, 2) + '\n'], {type:'application/json;charset=utf-8'});
    const url = URL.createObjectURL(file);
    const a = document.createElement('a'); a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
  function setMinimized(value, persist=true) {
    minimized = !!value;
    shadow.querySelector('.panel').classList.toggle('minimized', minimized);
    el('minimize').textContent = minimized ? 'Show ▣' : 'Hide ▾';
    el('minimize').title = minimized ? 'Show collector contents' : 'Minimize to title bar';
    el('minimize').setAttribute('aria-expanded', String(!minimized));
    if (persist) try { localStorage.setItem(MINIMIZED_KEY, String(minimized)); } catch {}
    clampCurrentPosition();
  }


  // Save coordinates separately from the animation selections, in viewport pixels.
  // Clamp on load, drag, and resize so the panel's title bar stays reachable.
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  function placePanel(left, top, persist = false) {
    const rect = root.getBoundingClientRect();
    const minMargin = 8;
    const maxLeft = Math.max(minMargin, window.innerWidth - rect.width - minMargin);
    const maxTop = Math.max(minMargin, window.innerHeight - rect.height - minMargin);
    const x = clamp(Math.round(left), minMargin, maxLeft);
    const y = clamp(Math.round(top), minMargin, maxTop);
    root.style.right = 'auto';
    root.style.left = `${x}px`;
    root.style.top = `${y}px`;
    if (persist) {
      try { localStorage.setItem(POSITION_KEY, JSON.stringify({left: x, top: y})); }
      catch (err) { message('Panel position could not be saved: ' + err.message); }
    }
  }

  function restorePosition() {
    try {
      const saved = JSON.parse(localStorage.getItem(POSITION_KEY) || 'null');
      if (Number.isFinite(saved?.left) && Number.isFinite(saved?.top)) {
        placePanel(saved.left, saved.top);
        return;
      }
    } catch { /* The default position remains usable if storage is unavailable. */ }
    resetPosition(false);
  }

  function resetPosition(persist = true) {
    const width = root.getBoundingClientRect().width;
    placePanel(window.innerWidth - width - 18, 72, persist);
  }

  function clampCurrentPosition() {
    const rect = root.getBoundingClientRect();
    placePanel(rect.left, rect.top);
  }

  const dragHandle = shadow.querySelector('.head');
  let dragging = null;
  dragHandle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('button, a, input')) return;
    const rect = root.getBoundingClientRect();
    dragging = {
      pointerId: event.pointerId,
      pointerX: event.clientX,
      pointerY: event.clientY,
      left: rect.left,
      top: rect.top
    };
    dragHandle.setPointerCapture(event.pointerId);
    dragHandle.classList.add('dragging');
    event.preventDefault();
  });
  dragHandle.addEventListener('pointermove', event => {
    if (!dragging || event.pointerId !== dragging.pointerId) return;
    placePanel(
      dragging.left + event.clientX - dragging.pointerX,
      dragging.top + event.clientY - dragging.pointerY
    );
  });
  function endDragging(event) {
    if (!dragging || event.pointerId !== dragging.pointerId) return;
    dragging = null;
    dragHandle.classList.remove('dragging');
    if (dragHandle.hasPointerCapture(event.pointerId)) {
      dragHandle.releasePointerCapture(event.pointerId);
    }
    const rect = root.getBoundingClientRect();
    placePanel(rect.left, rect.top, true);
  }
  dragHandle.addEventListener('pointerup', endDragging);
  dragHandle.addEventListener('pointercancel', endDragging);
  window.addEventListener('resize', clampCurrentPosition, {signal: listeners.signal});
  el('minimize').addEventListener('click', () => setMinimized(!minimized));
  el('reset-position').addEventListener('click', () => {
    resetPosition();
    message('Panel position reset.');
  });

  function readStore() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORE_KEY) || '[]');
      entries = Array.isArray(parsed) ? parsed.filter(x => x && /^\d+$/.test(String(x.motionId || ''))) : [];
    } catch (err) {
      entries = [];
      message('Cannot load saved selections: ' + err.message);
    }
  }
  function saveStore() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(entries)); }
    catch (err) { message('Browser storage unavailable. Export JSON before closing: ' + err.message); }
  }

  function queryOnPage() {
    try { return norm(new URLSearchParams(location.hash.split('?')[1] || '').get('query')); }
    catch { return ''; }
  }

  function extractCard(card) {
    const title = norm(card.querySelector('.product-info > p')?.textContent);
    const description = norm(card.querySelector('.product-metadata li')?.textContent)
      .replace(/^Description:\s*/i, '').trim();
    const thumbnail = norm(card.querySelector('.product-image img')?.getAttribute('src'));
    const motionId = thumbnail.match(/\/thumbnails\/motions\/(\d+)\//)?.[1] || '';
    return {search: queryOnPage() || title, title, description, motionId};
  }

  function defaultFilename(entry) {
    // Including the ID avoids accidentally reusing a different Jump.fbx from an earlier run.
    return cleanFilename(`${entry.title}__${entry.motionId}`);
  }

  function addCard(card) {
    if (!card) { message('No animation card is selected. Click a result first.'); return; }
    const info = extractCard(card);
    if (!info.title || !info.motionId) {
      message('Cannot read a title or motion ID from this card; nothing added.');
      return;
    }
    const found = entries.find(x => x.motionId === info.motionId);
    if (found) {
      message(`${info.title} (${info.motionId}) is already collected.`);
      return;
    }
    entries.push({...info, filename: defaultFilename(info)});
    saveStore(); render();
    message(`Added: ${info.title} — ${info.description || '(no description)'} [${info.motionId}]`);
  }

  function render() {
    el('count').textContent = `${entries.length} motion${entries.length === 1 ? '' : 's'} collected`;
    el('capture').textContent = capturing ? 'Capture: ON' : 'Capture: PAUSED';
    renderPresetList();
    const list = el('items');
    list.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'No animations yet. Click a Mixamo result card to add it.';
      list.appendChild(empty);
      return;
    }
    for (const entry of entries) {
      const row = document.createElement('div'); row.className = 'item';
      const top = document.createElement('div'); top.className = 'itemtop';
      const name = document.createElement('div'); name.className = 'name';
      name.textContent = entry.title;
      const remove = document.createElement('button'); remove.className = 'tiny';
      remove.textContent = 'Remove'; remove.title = 'Remove from collection';
      remove.addEventListener('click', () => {
        entries = entries.filter(x => x.motionId !== entry.motionId);
        saveStore(); render(); message(`Removed ${entry.title} (${entry.motionId}).`);
      });
      top.append(name, remove); row.appendChild(top);
      const desc = document.createElement('div'); desc.className = 'desc';
      desc.textContent = entry.description || '(No description shown)';
      row.appendChild(desc);
      const motion = document.createElement('div'); motion.className = 'motion';
      motion.textContent = `motionId: ${entry.motionId} | search: ${entry.search}`;
      row.appendChild(motion);
      const label = document.createElement('label'); label.textContent = 'Output FBX / GLB action name';
      const input = document.createElement('input'); input.type = 'text';
      input.value = entry.filename;
      input.addEventListener('change', () => {
        entry.filename = cleanFilename(input.value) || defaultFilename(entry);
        input.value = entry.filename;
        saveStore(); renderPresetList(); message(`Renamed output for ${entry.motionId}.`);
      });
      label.appendChild(input); row.appendChild(label);
      list.appendChild(row);
    }
  }

  function payload() {
    // JSON shape is directly accepted by the existing Python read_animations().
    return {presetName: currentPreset()?.name || null, animations: entries.map(item => ({
      search: item.search || item.title,
      title: item.title,
      description: item.description,
      motionId: String(item.motionId),
      filename: item.filename || defaultFilename(item),
      // For existing exports with identical names, set redownload:true manually as needed.
    }))};
  }
  function jsonText() { return JSON.stringify(payload(), null, 2) + '\n'; }

  function exportJson() {
    if (!entries.length) { message('Nothing to export. Collect at least one animation.'); return; }
    const names = payload().animations.map(x => normalized(x.filename));
    if (new Set(names).size !== names.length) {
      message('Some filenames are duplicated. Rename them before exporting.');
      return;
    }
    const exportName = currentPreset() ?
      cleanFilename(currentPreset().name).replace(/[\s]+/g, '_') + '.json' : 'animations.json';
    exportObject(payload(), exportName);
    message(`Exported ${entries.length} exact animations to ${exportName}.`);
  }

  function ingestJson(data) {
    const incoming = Array.isArray(data) ? data : data?.animations;
    if (Array.isArray(data?.presets) && !Array.isArray(incoming)) { importPresets(data); return; }
    if (!Array.isArray(incoming)) throw Error('Expected {"animations": [...]} or a presets backup.');
    let added = 0, skipped = 0;
    for (const item of incoming) {
      if (!item || typeof item !== 'object' || !/^\d+$/.test(String(item.motionId || ''))) {
        skipped++; continue;
      }
      const motionId = String(item.motionId);
      if (entries.some(x => x.motionId === motionId)) { skipped++; continue; }
      const title = norm(item.title);
      if (!title) { skipped++; continue; }
      const record = {
        title, motionId,
        description: norm(item.description),
        search: norm(item.search) || title,
        filename: cleanFilename(item.filename || `${title}__${motionId}`)
      };
      entries.push(record); added++;
    }
    saveStore(); render();
    message(`Imported ${added} motion(s); skipped ${skipped} duplicates or entries without a motion ID.`);
  }

  function onCardClick(event) {
    if (!capturing) return;
    const target = event.target instanceof Element ? event.target : event.target?.parentElement;
    const card = target?.closest(RESULTS_SELECTOR);
    if (card) addCard(card);
  }

  document.addEventListener('click', onCardClick, {capture: true, signal: listeners.signal});
  el('preset-select').addEventListener('change', event => selectPreset(event.target.value));
  el('preset-save').addEventListener('click', saveAsPreset);
  el('preset-update').addEventListener('click', updatePreset);
  el('preset-rename').addEventListener('click', renamePreset);
  el('preset-delete').addEventListener('click', deletePreset);
  el('export-all').addEventListener('click', exportAllPresets);
  el('capture').addEventListener('click', () => { capturing = !capturing; render(); message(capturing ? 'Click card thumbnails to collect.' : 'Capture paused.'); });
  el('selected').addEventListener('click', () => addCard(document.querySelector(SELECTED_SELECTOR)));
  el('export').addEventListener('click', exportJson);
  el('copy').addEventListener('click', async () => {
    if (!entries.length) { message('No animations to copy.'); return; }
    try { await navigator.clipboard.writeText(jsonText()); message('JSON copied to clipboard.'); }
    catch (err) { console.log('[Mixamo Collector JSON]\n' + jsonText()); message('Clipboard unavailable. JSON printed to DevTools console instead.'); }
  });
  el('import').addEventListener('click', () => el('file').click());
  el('file').addEventListener('change', async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    try { ingestJson(JSON.parse(await file.text())); }
    catch (err) { message('Import failed: ' + err.message); }
    event.target.value = '';
  });
  el('clear').addEventListener('click', () => {
    if (!entries.length || !confirm(`Clear all ${entries.length} collected animations?`)) return;
    entries = []; saveStore(); render(); message('List cleared.');
  });

  function destroy() {
    if (disposed) return;
    disposed = true;
    listeners.abort();
    root.remove();
    if (window.mixamoCollector === api) delete window.mixamoCollector;
  }
  el('close').addEventListener('click', destroy);
  const api = {
    export: exportJson,
    list: () => JSON.parse(jsonText()).animations,
    clear: () => { entries = []; saveStore(); render(); },
    destroy,
    import: ingestJson,
    resetPosition,
    saveAsPreset, updatePreset, exportAllPresets,
    get presetNames() { return presets.map(p => p.name); },
    get activePreset() { return currentPreset()?.name || null; },
    get count() { return entries.length; }
  };
  window.mixamoCollector = api;
  loadPresets(); readStore(); render(); restorePosition();
  setMinimized(localStorage.getItem(MINIMIZED_KEY) === 'true', false);
  message('Ready. Click an animation card; drag the header to move this panel.');
  console.info('[Mixamo Motion Collector] Ready. Selections persist on this browser. Use mixamoCollector.list() to inspect.');
})();
