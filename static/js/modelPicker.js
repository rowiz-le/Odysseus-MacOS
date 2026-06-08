// Model Picker — chatbox model selector dropdown
// Extracted from sessions.js

import { providerLogo } from './providers.js';
import uiModule from './ui.js';

const API_BASE = window.location.origin;

// ── Shared keyboard nav for model pickers ──
function _handlePickerKeydown(e, listEl, itemSelector, closeFn) {
  if (e.key === 'Escape') { closeFn(); return; }
  if (e.key === 'Enter') {
    e.preventDefault();
    const active = listEl.querySelector(itemSelector + '.kb-active') || listEl.querySelector(itemSelector);
    if (active) active.click();
    return;
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const items = [...listEl.querySelectorAll(itemSelector)].filter(el => el.style.display !== 'none');
    if (!items.length) return;
    const cur = items.findIndex(el => el.classList.contains('kb-active'));
    items.forEach(el => el.classList.remove('kb-active'));
    let next;
    if (e.key === 'ArrowDown') next = cur < items.length - 1 ? cur + 1 : 0;
    else next = cur > 0 ? cur - 1 : items.length - 1;
    items[next].classList.add('kb-active');
    items[next].scrollIntoView({ block: 'nearest' });
  }
}

// Dependencies injected via initModelPicker()
let _deps = null;
let _pickerItems = [];
let _pickerFetchPromise = null;

/**
 * Initialize the model picker dropdown.
 * @param {Object} deps
 * @param {function} deps.getCurrentSessionId - returns current session ID
 * @param {function} deps.getSessions - returns sessions array
 * @param {function} deps.getPendingChat - returns _pendingChat object
 * @param {function} deps.setPendingChat - sets _pendingChat object
 * @param {function} deps.createDirectChat - creates a new direct chat session
 */
export function initModelPicker(deps) {
  _deps = deps;
  _initModelPickerDropdown();
}

function _initModelPickerDropdown() {
  const wrap = document.getElementById('model-picker-wrap');
  const btn = document.getElementById('model-picker-btn');
  const menu = document.getElementById('model-picker-menu');
  const search = document.getElementById('model-picker-search');
  const listEl = document.getElementById('model-picker-list');
  if (!wrap || !btn || !menu || !search || !listEl) return;

  let _closeTimer = null;
  let _closeSeq = 0;

  function _close() {
    if (menu.classList.contains('hidden')) return;
    const closeToken = ++_closeSeq;
    // Restore scroll button
    const _scrollBtn = document.getElementById('scroll-bottom-btn');
    if (_scrollBtn) _scrollBtn.style.display = '';
    menu.classList.add('closing');
    menu.addEventListener('animationend', function _onDone() {
      menu.removeEventListener('animationend', _onDone);
      if (closeToken !== _closeSeq) return;
      if (_closeTimer) {
        clearTimeout(_closeTimer);
        _closeTimer = null;
      }
      menu.classList.remove('closing');
      menu.classList.add('hidden');
      search.value = '';
    }, { once: true });
    // Fallback if animationend doesn't fire
    if (_closeTimer) clearTimeout(_closeTimer);
    _closeTimer = setTimeout(() => {
      if (closeToken !== _closeSeq) return;
      if (!menu.classList.contains('hidden')) {
        menu.classList.remove('closing');
        menu.classList.add('hidden');
        search.value = '';
      }
      _closeTimer = null;
    }, 200);
  }

  // Local endpoint health — only probed for LOCAL endpoints, since
  // cloud APIs are essentially always up. Cached briefly on the
  // server side too (8s TTL). Picker opens trigger a refresh.
  let _localProbe = {};            // {endpoint_id: {alive, latency_ms, error}}
  let _localProbeFetchedAt = 0;
  const _LOCAL_PROBE_TTL_MS = 30000;  // Increased from 5s to 30s to reduce refresh frequency
  // Hysteresis: a single slow probe (e.g. a local server busy loading/serving a
  // large model) used to flip the endpoint to "offline", dimming its models;
  // the next probe flipped it back. That flap is the model-picker flicker.
  // Require two consecutive failures before showing offline; clear instantly
  // on any success.
  const _probeFailCounts = {};     // {endpoint_id: consecutiveFailures}
  const _PROBE_FAIL_THRESHOLD = 2;

  function _cachedModelItems() {
    return (window.modelsModule && window.modelsModule.getCachedItems)
      ? (window.modelsModule.getCachedItems() || [])
      : [];
  }

  function _showPickerStatus(text) {
    listEl.innerHTML = '';
    const row = document.createElement('div');
    row.className = 'model-switch-empty';
    row.textContent = text;
    listEl.appendChild(row);
  }

  async function _ensurePickerItems() {
    const cached = _cachedModelItems();
    if (cached.length > 0) {
      _pickerItems = [];
      return cached;
    }
    if (_pickerFetchPromise) return _pickerFetchPromise;
    _pickerFetchPromise = (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/models`, { credentials: 'same-origin' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _pickerItems = Array.isArray(data.items) ? data.items : [];
        return _pickerItems;
      } catch (e) {
        console.warn('Model picker failed to load models:', e);
        return _cachedModelItems();
      } finally {
        _pickerFetchPromise = null;
      }
    })();
    return _pickerFetchPromise;
  }

  async function _refreshLocalProbe() {
    const now = Date.now();
    if (now - _localProbeFetchedAt < _LOCAL_PROBE_TTL_MS) return;
    _localProbeFetchedAt = now;
    try {
      const r = await fetch('/api/model-endpoints/probe-local', { credentials: 'same-origin' });
      if (r.ok) {
        const raw = (await r.json()) || {};
        // Apply hysteresis so a single slow/timed-out probe doesn't flap the
        // endpoint to "offline" (which dims its models and looks like flicker).
        const smoothed = {};
        for (const [epId, res] of Object.entries(raw)) {
          if (res && res.alive === false) {
            const n = (_probeFailCounts[epId] || 0) + 1;
            _probeFailCounts[epId] = n;
            // Keep reporting alive until we've seen enough consecutive misses.
            smoothed[epId] = n >= _PROBE_FAIL_THRESHOLD ? res : { ...res, alive: true, _pending: true };
          } else {
            _probeFailCounts[epId] = 0;
            smoothed[epId] = res;
          }
        }
        _localProbe = smoothed;
      }
    } catch (_) { /* leave stale data; picker still works */ }
  }

  function _getAllModels() {
    const cached = _cachedModelItems();
    const items = cached.length > 0 ? cached : _pickerItems;
    const result = [];
    const seen = new Set();
    items.forEach(item => {
      if (item.offline) return;
      const allModels = (item.models || []).concat(item.models_extra || []);
      const allDisplay = (item.models_display || []).concat(item.models_extra_display || []);
      // Mark local endpoints whose live probe failed.
      const probeResult = item.endpoint_id ? _localProbe[item.endpoint_id] : null;
      const isLocalDead = !!(probeResult && probeResult.alive === false);
      allModels.forEach((mid, i) => {
        // Deduplicate by model ID — prefer DB endpoints over env-discovered
        if (seen.has(mid)) return;
        seen.add(mid);
        result.push({
          mid,
          display: (allDisplay[i] || mid).split('/').pop(),
          url: item.url,
          endpointId: item.endpoint_id,
          epName: item.endpoint_name || '',
          stale: isLocalDead,
          staleReason: isLocalDead ? (probeResult.error || 'not responding') : '',
        });
      });
    });
    return result;
  }

  function _populate(filter) {
    listEl.innerHTML = '';
    const all = _getAllModels();
    const q = (filter || '').toLowerCase();

    // Load favorites
    const favs = (function() { try { return JSON.parse(localStorage.getItem('odysseus-model-favorites') || '[]'); } catch { return []; } })();

    // Partition: favorites first, then rest
    const favModels = [];
    const restModels = [];
    all.forEach(m => {
      if (q && !m.mid.toLowerCase().includes(q) && !m.display.toLowerCase().includes(q)) return;
      if (favs.includes(m.mid)) favModels.push(m);
      else restModels.push(m);
    });

    function _addSection(label) {
      const el = document.createElement('div');
      el.className = 'mp-section-label';
      el.textContent = label;
      listEl.appendChild(el);
    }
    function _addRow(m) {
      const row = document.createElement('div');
      row.className = 'model-switch-item';
      if (m.stale) {
        row.classList.add('model-switch-stale');
        row.style.opacity = '0.45';
        row.title = `Local server appears offline: ${m.staleReason}. Click to try anyway, or relaunch in Cookbook.`;
      }
      const _mlogo = providerLogo(m.mid);
      if (_mlogo) {
        const logoSpan = document.createElement('span');
        logoSpan.className = 'provider-logo';
        logoSpan.style.opacity = '0.6';
        logoSpan.innerHTML = _mlogo;
        row.appendChild(logoSpan);
      }
      const nameSpan = document.createElement('span');
      nameSpan.textContent = m.display;
      row.appendChild(nameSpan);
      if (m.stale) {
        const badge = document.createElement('span');
        badge.className = 'model-switch-stale-badge';
        badge.textContent = 'offline';
        badge.style.cssText = 'font-size:10px;opacity:0.7;padding:1px 6px;border:1px solid var(--border);border-radius:8px;margin-left:6px;';
        badge.addEventListener('click', (e) => e.stopPropagation());
        row.appendChild(badge);
      }
      const epSpan = document.createElement('span');
      epSpan.className = 'model-switch-ep';
      // Don't show endpoint name if it matches the model name (local self-hosted)
      const _epDisplayText = m.epName && !m.display.toLowerCase().includes(m.epName.toLowerCase().split('/').pop()) ? m.epName : '';
      epSpan.textContent = _epDisplayText;
      row.appendChild(epSpan);
      // FIX: Add stopPropagation to prevent event bubbling that closes picker immediately
      row.addEventListener('click', (e) => {
        e.stopPropagation();
        _pick(m);
      });
      listEl.appendChild(row);
    }

    if (favModels.length > 0) {
      _addSection('Favorites');
      favModels.forEach(_addRow);
    }
    if (restModels.length > 0) {
      if (favModels.length > 0) _addSection('All models');
      restModels.forEach(_addRow);
    }
    if (listEl.children.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'model-switch-empty';
      empty.textContent = 'No models available';
      listEl.appendChild(empty);
    }
  }

  async function _pick(m) {
    const currentSessionId = _deps.getCurrentSessionId();
    const _pendingChat = _deps.getPendingChat();

    // Broadcast immediately so listeners (e.g. the tour) can advance without
    // waiting for the async session-create/PATCH that follows.
    try { document.dispatchEvent(new CustomEvent('odysseus:model-picked', { detail: m })); } catch {}

    // FIX: Don't close picker immediately - wait until model selection completes
    // This prevents the "closing too fast" issue where modal closes before user sees result

    if (!currentSessionId && _pendingChat) {
      // Already have a deferred session — just update the model
      _deps.setPendingChat({ url: m.url, modelId: m.mid, endpointId: m.endpointId });
      // Header stays as session name — model switch only updates picker
      updateModelPicker();
      uiModule.showToast(`Using ${m.display}`);
      // Close picker after successful selection
      _close();
      if (document.activeElement) document.activeElement.blur();
      return;
    } else if (!currentSessionId) {
      // No session yet — create one with this model
      await _deps.createDirectChat(m.url, m.mid, m.endpointId);
    } else {
      // Existing session with no model — PATCH it
      const fd = new FormData();
      fd.append('model', m.mid);
      fd.append('endpoint_url', m.url);
      if (m.endpointId) fd.append('endpoint_id', m.endpointId);
      try {
        const res = await fetch(`${API_BASE}/api/session/${currentSessionId}`, {
          method: 'PATCH',
          body: fd,
          credentials: 'same-origin',
        });
        if (!res.ok) {
          uiModule.showError('Failed to set model');
          return;
        }
        let payload = {};
        try { payload = await res.json(); } catch {}
        const sessions = _deps.getSessions();
        const s = sessions.find(x => x.id === currentSessionId);
        if (s) {
          s.model = payload.model || m.mid;
          s.endpoint_url = payload.endpoint_url || m.url;
          if (payload.endpoint_id || m.endpointId) s.endpoint_id = payload.endpoint_id || m.endpointId;
        }
        // Header stays as session name — model info shown in picker only
      } catch (e) {
        uiModule.showError('Failed to set model: ' + e);
        return;
      }
    }
    // Update picker visibility — model is now set
    updateModelPicker();
    uiModule.showToast(`Using ${m.display}`);
    // Close picker after successful selection
    _close();
    if (document.activeElement) document.activeElement.blur();
  }

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.classList.contains('hidden') || menu.classList.contains('closing')) {
      // Force-clear any in-progress close animation
      _closeSeq++;
      if (_closeTimer) {
        clearTimeout(_closeTimer);
        _closeTimer = null;
      }
      menu.classList.remove('closing', 'hidden');
      const hasModels = _cachedModelItems().length > 0 || _pickerItems.length > 0;
      if (hasModels) _populate('');
      else _showPickerStatus('Loading models...');
      // Kick off a local-endpoint probe — when it returns, re-render
      // the list so stale local servers get dimmed. Cloud entries
      // aren't probed; they stay visible.
      // FIX: Only re-render if picker is still open after probe completes
      Promise.allSettled([_ensurePickerItems(), _refreshLocalProbe()]).then(() => {
        // Only re-render if picker hasn't been closed in the meantime
        if (!menu.classList.contains('hidden') && !menu.classList.contains('closing')) {
          _populate(search.value || '');
        }
      });
      if (window.innerWidth >= 768) search.focus();
      // Hide scroll button so it doesn't overlap
      const _scrollBtn = document.getElementById('scroll-bottom-btn');
      if (_scrollBtn) _scrollBtn.style.display = 'none';
    } else {
      _close();
    }
  });

  search.addEventListener('input', () => {
    if (_cachedModelItems().length === 0 && _pickerItems.length === 0) {
      _showPickerStatus('Loading models...');
      _ensurePickerItems().then(() => {
        if (!menu.classList.contains('hidden')) _populate(search.value || '');
      });
      return;
    }
    _populate(search.value);
  });
  search.addEventListener('click', (e) => e.stopPropagation());
  search.addEventListener('keydown', (e) => {
    _handlePickerKeydown(e, listEl, '.model-switch-item', _close);
  });
  document.addEventListener('click', (e) => {
    if (!menu.classList.contains('hidden') && !menu.contains(e.target) && !btn.contains(e.target)) {
      _close();
    }
  });
}

/**
 * Update the model picker label to show the current model.
 * Always visible — shows current model name or "Select model" if none.
 * Called after selectSession, createDirectChat, and model switch.
 */
export function updateModelPicker() {
  if (!_deps) return;
  const label = document.getElementById('model-picker-label');
  if (!label) return;
  // Hide model picker when group chat is active
  const wrap = document.getElementById('model-picker-wrap');
  if (window.groupModule && window.groupModule.isActive()) {
    if (wrap) { wrap.style.display = 'none'; }
    return;
  }
  // Reset inline visibility (may have been hidden by typing in previous session)
  if (wrap) {
    wrap.style.display = '';
    wrap.style.opacity = '';
    wrap.style.pointerEvents = '';
  }
  const currentSessionId = _deps.getCurrentSessionId();
  const sessions = _deps.getSessions();
  const _pendingChat = _deps.getPendingChat();
  const s = sessions.find(x => x.id === currentSessionId);
  let modelId = null;
  if (s && s.model) {
    modelId = s.model;
  } else if (_pendingChat && _pendingChat.modelId) {
    modelId = _pendingChat.modelId;
  }
  // SECURITY: deliberately NOT auto-injecting `odysseus-model-favorites[0]`
  // here. localStorage favorites are per-browser, not per-user, so on a
  // shared browser the previous account's first favorited model would
  // silently pre-populate the chatbox of the next user that signed in. If
  // we have no session model and no pending-chat pick, fall through to
  // the "Select model" placeholder below.

  // Check if selected model is still available — fall back ONLY for pending chats with no user selection
  // Never override an existing session's model — the user explicitly chose it
  if (modelId && !currentSessionId && _pendingChat && window.modelsModule && window.modelsModule.getCachedItems) {
    const items = window.modelsModule.getCachedItems();
    const allAvailable = [];
    items.forEach(item => {
      if (item.offline) return;
      (item.models || []).concat(item.models_extra || []).forEach(m => allAvailable.push(m));
    });
    if (allAvailable.length > 0 && !allAvailable.includes(modelId)) {
      // Model no longer available — switch to first available
      const fallback = items.find(item => !item.offline && (item.models || []).length > 0);
      if (fallback) {
        modelId = fallback.models[0];
        _deps.setPendingChat({ url: fallback.url, modelId, endpointId: fallback.endpoint_id });
      }
    }
  }

  const displayName = modelId ? modelId.split('/').pop() : 'Select model';
  const logo = modelId ? providerLogo(modelId) : null;
  if (logo) {
    label.innerHTML = '<span class="model-picker-logo">' + logo + '</span> ' + displayName;
  } else {
    label.textContent = displayName;
  }
}
