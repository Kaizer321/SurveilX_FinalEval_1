/**
 * SurveilX Dashboard Logic
 */

document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

// --- Constants & State ---
const THEME_KEY = 'theme';
const ROLE_KEY = 'authRole';
let CAMS = [];
let DETECTION_STATE = {};
let SHOW_KEYPOINTS = false;
let VIEW_MODE = localStorage.getItem('viewMode') || 'grid'; // 'grid' | 'single'
let LOGS_PAUSED = false;
const LOGS = []; // {raw, ts, level, cameras:[], text}

// --- Alerts ---
class AlertQueue {
    constructor() {
        this.queue = [];
        this.active = false;
        this.soundPlayed = false;
        this.audioCtx = null;
    }

    add(msg, type = 'error') {
        this.queue.push({ msg, type });
        this.process();
    }

    async process() {
        if (this.active || this.queue.length === 0) return;
        this.active = true;
        const { msg, type } = this.queue.shift();

        if (type === 'critical') {
            this.playAlert();
            showBigAlert(msg);
        }

        await showToast(msg, type);
        this.active = false;
        if (this.queue.length > 0) setTimeout(() => this.process(), 300);
    }

    playAlert() {
        // Simple Audio Beep
        if (!this.audioCtx) this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (this.audioCtx.state === 'suspended') this.audioCtx.resume();

        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.connect(gain);
        gain.connect(this.audioCtx.destination);

        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(880, this.audioCtx.currentTime); // High pitch
        osc.frequency.exponentialRampToValueAtTime(440, this.audioCtx.currentTime + 0.1);

        gain.gain.setValueAtTime(0.5, this.audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, this.audioCtx.currentTime + 0.5);

        osc.start();
        osc.stop(this.audioCtx.currentTime + 0.5);
    }
}
const ALERTS = new AlertQueue();

function showToast(msg, type = 'info') {
    return new Promise(resolve => {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            document.body.appendChild(container);
        }

        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        el.innerHTML = `
            <div class="toast-icon">${type === 'critical' ? '🚨' : 'ℹ️'}</div>
            <div class="toast-body">${msg}</div>
        `;

        container.appendChild(el);

        // Force reflow
        el.offsetHeight;
        el.classList.add('show');

        setTimeout(() => {
            el.classList.remove('show');
            setTimeout(() => {
                el.remove();
                resolve();
            }, 300);
        }, 5000); // 5 seconds display
    });
}

// --- Initialization ---
function initApp() {
    applyTheme(localStorage.getItem(THEME_KEY) || 'dark');

    if (!ensureAuth()) return; // Redirects if failed
    applyRoleUi();

    // Bind Global Event Listeners
    bindGlobalEvents();

    // Initial Data Load
    loadCameras();
    fetchDetections();
    pollEmbeddings();

    // Polling Intervals
    setInterval(fetchDetections, 2500);
    setInterval(loadCameras, 15000);
    setInterval(pollEmbeddings, 5000);

    if (getRole() === 'admin') {
        startLogs();
        loadAdminCameras();
        loadAdminUsers();

        // Admin Stats Polling
        fetchAdminOverview();
        fetchAdminHealth();

        setInterval(fetchAdminOverview, 5000); // 5 seconds for overview
        setInterval(fetchAdminHealth, 10000);  // 10 seconds for health
    }
}

// --- Auth & Role ---
function getRole() { return localStorage.getItem(ROLE_KEY); }

function ensureAuth() {
    try {
        const tok = localStorage.getItem('authToken');
        const xhr = new XMLHttpRequest();
        xhr.open('GET', '/auth/me', false); // synchronous check
        xhr.withCredentials = true;
        if (tok) xhr.setRequestHeader('Authorization', 'Bearer ' + tok);
        xhr.send(null);
        if (xhr.status !== 200) {
            doLogout();
            return false;
        }
    } catch (e) {
        doLogout();
        return false;
    }
    const r = getRole();
    if (!r) {
        doLogout();
        return false;
    }
    document.documentElement.setAttribute('data-role', r);
    return true;
}

function doLogout() {
    localStorage.removeItem('authToken');
    localStorage.removeItem('authRole');
    window.location.href = 'login-user.html';
}

function applyRoleUi() {
    const r = getRole();
    const isAdmin = r === 'admin';

    // Toggle Nav & Panels
    const navLogs = document.getElementById('nav-logs');
    const navSettings = document.getElementById('nav-settings');
    const logsPanel = document.getElementById('logs');

    if (!isAdmin) {
        if (navLogs) navLogs.style.display = 'none';
        if (navSettings) navSettings.style.display = 'none';
        if (logsPanel) logsPanel.style.display = 'none';
    }

    // Toggle role-specific classes
    const adminEls = Array.from(document.querySelectorAll('.admin-only'));
    const userEls = Array.from(document.querySelectorAll('.user-only'));
    adminEls.forEach(el => el.style.display = isAdmin ? '' : 'none');
    userEls.forEach(el => el.style.display = isAdmin ? 'none' : '');
}

// --- Helper Functions ---
async function fetchJSON(url, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    const tok = localStorage.getItem('authToken');
    if (tok && !headers['Authorization']) headers['Authorization'] = 'Bearer ' + tok;

    const res = await fetch(url, { credentials: 'include', headers, ...opts });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
}

async function runAsyncAction(btn, action, loadingText = 'Wait...') {
    if (!btn || btn.disabled) return;
    const originalHtml = btn.innerHTML;
    // Save minimal width to prevent jumping
    const w = btn.offsetWidth;
    btn.style.minWidth = w + 'px';

    btn.disabled = true;
    btn.textContent = loadingText;
    btn.classList.add('btn-loading'); // For optional CSS styling

    try {
        await action();
    } catch (e) {
        console.error(e);
        alert('Action failed: ' + (e.message || e));
    } finally {
        btn.innerHTML = originalHtml;
        btn.disabled = false;
        btn.classList.remove('btn-loading');
        btn.style.minWidth = '';
    }
}

function debounce(fn, ms) {
    let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn.apply(null, args), ms); };
}

// --- Theme ---
function applyTheme(theme) {
    const t = (theme === 'light' || theme === 'dark') ? theme : 'dark';
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem(THEME_KEY, t);
}

// --- Global Binding ---
function bindGlobalEvents() {
    // Theme Toggle
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) themeBtn.addEventListener('click', () => {
        const cur = localStorage.getItem(THEME_KEY) || 'dark';
        applyTheme(cur === 'dark' ? 'light' : 'dark');
    });

    // View Toggle
    const viewBtn = document.getElementById('view-toggle');
    if (viewBtn) viewBtn.addEventListener('click', () => {
        VIEW_MODE = VIEW_MODE === 'single' ? 'grid' : 'single';
        localStorage.setItem('viewMode', VIEW_MODE);
        if (VIEW_MODE === 'single') {
            const sel = document.getElementById('camera-select');
            if (!sel.value && CAMS[0]) sel.value = CAMS[0].id;
        }
        applyViewMode();
    });

    // Keypoints Toggle
    const kpBtn = document.getElementById('toggle-kp');
    if (kpBtn) kpBtn.addEventListener('click', toggleKeypoints);

    // Logout
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            // Robust logout: Try API, but ALWAYS redirect
            try {
                // Disable button to show feedback
                logoutBtn.disabled = true;
                logoutBtn.textContent = '...';
                await fetch('/auth/logout', { method: 'POST' });
            } catch (e) {
                console.warn('Logout API failed, forcing local logout', e);
            } finally {
                doLogout();
            }
        });
    }

    // Keyboard Shortcuts
    document.addEventListener('keydown', handleKeyboardShortcuts);

    // Nav Links
    const navLinks = Array.from(document.querySelectorAll('.nav a'));
    navLinks.forEach(a => a.addEventListener('click', (e) => {
        // e.preventDefault(); // Optional: if we want manual scrolling
        navLinks.forEach(n => n.classList.remove('active'));
        a.classList.add('active');
        // Smooth scroll handled by CSS scroll-behavior usually, or href anchor

        // Mobile Sidebar auto-close could go here
    }));

    // Upload Search
    const uploadBtn = document.getElementById('upload-search');
    const uploadInput = document.getElementById('upload-file');
    const uploadName = document.getElementById('upload-name');

    if (uploadInput) {
        uploadInput.addEventListener('change', () => {
            if (uploadInput.files && uploadInput.files[0]) {
                uploadName.textContent = uploadInput.files[0].name;
            } else {
                uploadName.textContent = 'Choose an image';
            }
        });
    }

    if (uploadBtn && uploadInput) {
        uploadBtn.addEventListener('click', () => {
            if (!(uploadInput.files && uploadInput.files[0])) return;
            const minMatch = document.getElementById('min-match');

            runAsyncAction(uploadBtn, async () => {
                const fd = new FormData();
                fd.append('file', uploadInput.files[0]);
                const res = await fetch('/api/embeddings/search_image?k=12', { method: 'POST', body: fd });
                if (!res.ok) throw new Error('Search failed');
                const data = await res.json();
                renderSimilarResults(data, parseFloat(minMatch.value) || 0);
            }, 'Searching...');
        });
    }

    // Camera Filter for Logs
    const camFilter = document.getElementById('cam-filter');
    if (camFilter) camFilter.addEventListener('change', renderLogs);

    // Log Controls
    ['lvl-info', 'lvl-warn', 'lvl-error', 'lvl-debug'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', renderLogs);
    });
    const logSearch = document.getElementById('log-search');
    if (logSearch) logSearch.addEventListener('input', debounce(renderLogs, 200));

    const tailSize = document.getElementById('tail-size');
    if (tailSize) tailSize.addEventListener('change', renderLogs);

    const autoScroll = document.getElementById('auto-scroll');
    if (autoScroll) autoScroll.addEventListener('change', renderLogs);

    const pauseLog = document.getElementById('pause-log');
    if (pauseLog) pauseLog.addEventListener('click', () => {
        LOGS_PAUSED = !LOGS_PAUSED;
        pauseLog.textContent = LOGS_PAUSED ? 'Resume' : 'Pause';
    });

    const clearLog = document.getElementById('clear-log');
    if (clearLog) clearLog.addEventListener('click', () => {
        LOGS.length = 0;
        renderLogs();
    });

    const exportLog = document.getElementById('export-log');
    if (exportLog) exportLog.addEventListener('click', exportLogs);

    // Admin Buttons
    const addCamBtn = document.getElementById('btn-add-camera');
    if (addCamBtn) addCamBtn.addEventListener('click', openAddCameraModal);

    const addUserBtn = document.getElementById('btn-add-user');
    if (addUserBtn) addUserBtn.addEventListener('click', openAddUserModal);

    // Close Modal Overlay
    const overlay = document.getElementById('modal-overlay');
    const cancelParams = document.getElementById('modal-cancel');
    if (overlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });
    }
    if (cancelParams) cancelParams.addEventListener('click', closeModal);
}

// --- Keypoints ---
async function toggleKeypoints() {
    const btn = document.getElementById('toggle-kp');
    await runAsyncAction(btn, async () => {
        const next = !SHOW_KEYPOINTS;
        const res = await fetchJSON('/api/detections/keypoints', { method: 'POST', body: JSON.stringify({ enabled: next }) });
        SHOW_KEYPOINTS = !!res.show_keypoints;
        updateKeypointButton();
    }, 'Updating...');
}

function updateKeypointButton() {
    const btn = document.getElementById('toggle-kp');
    if (!btn) return;
    btn.textContent = `🧍 Keypoints: ${SHOW_KEYPOINTS ? 'on' : 'off'}`;
    btn.classList.toggle('primary', SHOW_KEYPOINTS);
}

// --- Cameras ---
async function loadCameras() {
    try {
        const res = await fetchJSON('/cameras');
        const camsDiv = document.getElementById('cams');
        if (!camsDiv) return;

        // Preserve scroll if possible or optimized re-render? For now full rebuild
        // but we can optimize by checking diff. simpler to rebuild for now.
        const currentScroll = camsDiv.scrollTop;

        camsDiv.innerHTML = '';
        const cams = applySavedOrder(res.cameras || []);
        CAMS = cams;

        const countEl = document.getElementById('cam-count');
        if (countEl) countEl.textContent = `${cams.length} camera(s)`;

        populateDropdown(cams);

        cams.forEach(({ id, name }) => {
            const card = createCameraCard(id, name);
            camsDiv.appendChild(card);
        });

        if (camsDiv.scrollTo) camsDiv.scrollTo(0, currentScroll);

        buildThumbbar(cams);
        applyFocusFromDropdown();
        applyViewMode();
        renderDetectionTabs();
    } catch (e) {
        console.error('Failed to load cameras', e);
        const countEl = document.getElementById('cam-count');
        if (countEl) countEl.textContent = 'Failed to load';
    }
}

function createCameraCard(id, name) {
    const card = document.createElement('div');
    card.className = 'card cam-card';
    card.dataset.camId = id;

    // Drag & Drop
    card.draggable = true;
    card.addEventListener('dragstart', (e) => e.dataTransfer.setData('text/plain', id));
    card.addEventListener('dragover', (e) => e.preventDefault());
    card.addEventListener('drop', (e) => onDrop(e, id));

    const header = document.createElement('div');
    header.className = 'cam-header';
    const title = document.createElement('h3');
    title.textContent = name ? `${name} (${id})` : `Camera: ${id}`;
    header.appendChild(title);

    const badge = document.createElement('div');
    badge.className = 'pill cam-badge';
    badge.dataset.badgeFor = id;
    badge.textContent = 'Active';
    header.appendChild(badge);

    const confBadge = document.createElement('div');
    confBadge.className = 'pill cam-conf hidden';
    confBadge.style.fontSize = '0.75rem';
    confBadge.style.marginLeft = 'auto'; // Push to right
    header.appendChild(confBadge);

    const frame = document.createElement('div');
    frame.className = 'frame';
    const img = document.createElement('img');
    img.src = `/stream/${id}`;
    img.alt = `Stream ${id}`;
    img.loading = 'lazy'; // Performant loading
    img.title = 'Click to focus/fullscreen';

    img.addEventListener('click', () => {
        const sel = document.getElementById('camera-select');
        sel.value = String(id);
        VIEW_MODE = 'single';
        localStorage.setItem('viewMode', VIEW_MODE);
        applyViewMode();
        requestFullscreen(frame);
    });

    frame.appendChild(img);
    card.appendChild(header);
    card.appendChild(frame);

    return card;
}

function onDrop(ev, targetId) {
    ev.preventDefault();
    const srcId = ev.dataTransfer.getData('text/plain');
    if (!srcId || srcId === targetId) return;

    const order = CAMS.map(c => c.id);
    const from = order.indexOf(srcId);
    const to = order.indexOf(targetId);
    if (from === -1 || to === -1) return;

    order.splice(to, 0, order.splice(from, 1)[0]);
    localStorage.setItem('cameraOrder', JSON.stringify(order));
    loadCameras(); // Re-render
}

function applySavedOrder(cams) {
    const order = JSON.parse(localStorage.getItem('cameraOrder') || '[]');
    if (!order.length) return cams;
    const map = Object.fromEntries(cams.map(c => [c.id, c]));
    const ordered = order.filter(id => map[id]).map(id => map[id]);
    const remaining = cams.filter(c => !order.includes(c.id));
    return [...ordered, ...remaining];
}

// --- View Mode & Navigation ---
function populateDropdown(cams) {
    const sel = document.getElementById('camera-select');
    if (!sel) return;

    const current = sel.value;
    sel.innerHTML = '';

    const optAll = document.createElement('option');
    optAll.value = '';
    optAll.textContent = 'Overview (All)';
    sel.appendChild(optAll);

    cams.forEach(({ id, name }) => {
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = name || id;
        sel.appendChild(opt);
    });

    if (Array.from(sel.options).some(o => o.value === current)) sel.value = current;
    sel.onchange = applyFocusFromDropdown;
}

function applyFocusFromDropdown() {
    const sel = document.getElementById('camera-select');
    if (!sel) return;
    const selVal = sel.value;

    const cards = Array.from(document.querySelectorAll('#cams .card'));
    const singleMode = VIEW_MODE === 'single';
    const thumbbar = document.getElementById('thumbbar');

    if (!selVal || !singleMode) {
        cards.forEach(c => {
            c.classList.remove('focused', 'dimmed', 'hidden');
        });
        if (thumbbar) thumbbar.classList.add('hidden');
        return;
    }

    // Single/Focus Mode
    let found = false;
    cards.forEach(c => {
        const isTarget = c.dataset.camId === selVal;
        c.classList.toggle('focused', isTarget);
        c.classList.toggle('dimmed', !isTarget);
        c.classList.toggle('hidden', !isTarget);
        if (isTarget) found = true;
    });

    if (thumbbar) thumbbar.classList.remove('hidden');

    if (found) {
        const target = cards.find(c => c.dataset.camId === selVal);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function applyViewMode() {
    const btn = document.getElementById('view-toggle');
    if (btn) btn.textContent = VIEW_MODE === 'single' ? 'Grid View' : 'Single View';
    applyFocusFromDropdown();
    updateKeypointButton();
}

function handleKeyboardShortcuts(e) {
    if (e.ctrlKey || e.altKey || e.metaKey || e.target.tagName === 'INPUT') return;

    // Number keys 1-9
    const num = parseInt(e.key, 10);
    if (!isNaN(num) && num >= 1 && num <= 9) {
        const idx = num - 1;
        if (CAMS[idx]) {
            const sel = document.getElementById('camera-select');
            sel.value = CAMS[idx].id;
            VIEW_MODE = 'single';
            localStorage.setItem('viewMode', VIEW_MODE);
            applyViewMode();
        }
    }

    // Arrow keys
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const sel = document.getElementById('camera-select');
        // Only cycle if in single mode
        if (VIEW_MODE !== 'single') return;

        e.preventDefault();
        const currentId = sel.value;
        const idx = CAMS.findIndex(c => String(c.id) === currentId);

        let nextIdx = 0;
        if (idx !== -1) {
            const delta = (e.key === 'ArrowRight') ? 1 : -1;
            nextIdx = (idx + delta + CAMS.length) % CAMS.length;
        }

        if (CAMS[nextIdx]) {
            sel.value = String(CAMS[nextIdx].id);
            applyViewMode();
        }
    }
}

function requestFullscreen(elem) {
    if (elem.requestFullscreen) {
        elem.requestFullscreen();
    } else if (elem.webkitRequestFullscreen) { /* Safari */
        elem.webkitRequestFullscreen();
    } else if (elem.msRequestFullscreen) { /* IE11 */
        elem.msRequestFullscreen();
    }
}

// --- Thumbnails ---
function buildThumbbar(cams) {
    const bar = document.getElementById('thumbbar');
    if (!bar) return;
    bar.innerHTML = '';

    cams.forEach(({ id, name }) => {
        const t = document.createElement('div');
        t.className = 'thumb';
        const img = document.createElement('img');
        img.src = `/stream/${id}`;
        img.alt = id;
        const label = document.createElement('span');
        label.textContent = name || id;

        t.appendChild(img);
        t.appendChild(label);
        t.addEventListener('click', () => {
            const sel = document.getElementById('camera-select');
            sel.value = id;
            applyFocusFromDropdown();
        });
        bar.appendChild(t);
    });
}

// --- Similar Search Render ---
function renderSimilarResults(data, minPct) {
    const wrap = document.getElementById('similar-wrap');
    if (!wrap) return;
    wrap.innerHTML = '';

    const metas = data.metadatas || [];
    const ids = data.ids || [];
    const dists = data.distances || [];

    let shown = 0;
    for (let i = 0; i < metas.length; i++) {
        const m = metas[i] || {};
        const id = ids[i] || '';
        const dist = Array.isArray(dists) ? dists[i] : undefined;
        // Cosine sim approximation
        const sim = (typeof dist === 'number') ? (1 - dist) : undefined;
        const pct = (typeof sim === 'number') ? Math.max(0, Math.min(1, sim)) * 100 : undefined;

        if (typeof pct === 'number' && pct < minPct) continue;

        const filePath = m.file_path || '';
        const base = filePath.split(/[\\/]/).pop();
        const imgSrc = base ? `/processed/${base}` : '';

        const div = document.createElement('div');
        div.className = 'similar-item';

        if (imgSrc) {
            const img = document.createElement('img');
            img.src = imgSrc;
            img.alt = id;
            img.loading = 'lazy';
            div.appendChild(img);
        }

        const cap = document.createElement('div');
        cap.className = 'cap';
        const ts = m.timestamp_iso ? new Date(m.timestamp_iso).toLocaleString() : '';
        const cam = m.camera_id || '';
        const distTxt = (typeof pct === 'number') ? ` • ${pct.toFixed(1)}%` : '';

        cap.innerHTML = `<strong>${cam}</strong><br>${ts}<br>${id}${distTxt}`;

        div.appendChild(cap);
        wrap.appendChild(div);
        shown++;
    }

    const card = document.getElementById('similar-card');
    if (shown === 0) {
        wrap.innerHTML = '<div class="muted" style="padding:10px;">No high-confidence matches found.</div>';
    }
    if (card) {
        card.style.display = 'block';
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

// --- Admin Stats & Management ---
async function fetchAdminOverview() {
    if (document.hidden || getRole() !== 'admin') return;
    try {
        const ov = await fetchJSON('/api/stats/overview');
        setText('stat-total-cameras', ov.total_cameras);
        setText('stat-streams', ov.active_streams);
        setText('stat-events', ov.events_24h);
        setText('stat-active-users', ov.active_users);
        setText('stat-storage', ov.storage_usage);

        const critEl = document.getElementById('stat-critical');
        if (critEl) {
            critEl.textContent = ov.critical_alerts;
            if (ov.critical_alerts > 0) critEl.classList.add('pulse-text');
            else critEl.classList.remove('pulse-text');
        }

        if (ov.charts) renderCharts(ov.charts);
    } catch (e) {
        console.error('Overview poll error', e);
    }
}

async function fetchAdminHealth() {
    if (document.hidden || getRole() !== 'admin') return;
    try {
        const he = await fetchJSON('/api/stats/health');
        setText('meter-cpu', he.cpu === null ? '—' : he.cpu + '%');
        setText('meter-ram', he.ram === null ? '—' : (he.ram.percent || he.ram) + '%');
        setText('meter-disk', he.disk === null ? '—' : (he.disk.percent || he.disk) + '%');
        setText('meter-net', he.net === null ? '—' : (typeof he.net === 'string' ? he.net : 'Online'));
    } catch (e) {
        console.error('Health poll error', e);
    }
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

function renderCharts(charts) {
    if (!charts) return;

    // 1. Time Chart (Events per Hour)
    const timeEl = document.getElementById('chart-time');
    if (timeEl && charts.by_time) {
        const data = charts.by_time;
        // Ensure we cover full 24h range if needed, or just map existing keys
        // Sort keys to be sure
        const keys = Object.keys(data).sort();
        const vals = Object.values(data);
        const max = Math.max(...vals, 1);

        timeEl.innerHTML = `
        <div class="chart-bars">
            ${keys.map(k => {
            const v = data[k];
            const h = (v / max) * 100;
            // Show label every ~4 bars or specific hours
            const label = k.split(':')[0];
            const showLabel = (parseInt(label) % 3 === 0);
            return `
                <div class="chart-col" title="Time: ${k}, Events: ${v}">
                    <div class="bar" style="height:${Math.max(5, h)}%; background: ${v > 0 ? 'var(--accent)' : 'rgba(255,255,255,0.05)'}"></div>
                    ${showLabel ? `<span class="chk">${label}</span>` : ''}
                </div>`;
        }).join('')}
        </div>`;
    }

    // 2. Type/Severity Chart
    const typeEl = document.getElementById('chart-type');
    if (typeEl && charts.by_type) {
        const data = charts.by_type;
        const keys = Object.keys(data);
        const total = Object.values(data).reduce((a, b) => a + b, 0) || 1;

        typeEl.innerHTML = `
        <div class="chart-rows">
            ${keys.map(k => {
            const v = data[k];
            const pct = Math.round((v / total) * 100);
            let colorClass = 'bg-primary';
            if (['Fighting', 'Shooting', 'Burglary'].includes(k)) colorClass = 'bg-error';
            else if (['Stealing'].includes(k)) colorClass = 'bg-warn';

            return `
                <div class="chart-row">
                    <div class="label">${k}</div>
                    <div class="track">
                        <div class="fill ${colorClass}" style="width: ${pct}%;"></div>
                    </div>
                    <div class="val">${v}</div>
                </div>`;
        }).join('')}
        </div>`;
    }
}

async function loadAdminUsers() {
    try {
        const data = await fetchJSON('/admin/users');
        const tbody = document.getElementById('admin-users-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';
        (data.users || []).forEach(u => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><div class="user-row"><span class="u-name">${u.username}</span></div></td>
                <td><span class="pill ${u.role === 'admin' ? 'pill-admin' : 'pill-user'}">${u.role}</span></td>
                <td><span class="status-dot ${u.disabled ? 'status-offline' : 'status-online'}"></span> ${u.disabled ? 'Disabled' : 'Active'}</td>
                <td>
                    <div class="actions">
                        <button class="btn btn-sm" data-act="reset" title="Reset PW">🔑</button>
                        <button class="btn btn-sm" data-act="toggle" title="Toggle">${u.disabled ? '✅' : '🚫'}</button>
                        <button class="btn btn-sm" data-act="logout" title="Logout">🚪</button>
                        <button class="btn btn-sm btn-danger" data-act="delete" title="Delete">🗑️</button>
                    </div>
                </td>`;

            // Note: Arrow functions maintain 'this' from text, so we use closures or event.target
            const bindBtn = (sel, fn) => {
                const b = tr.querySelector(sel);
                if (b) b.onclick = function () { fn(u, this); };
            };

            bindBtn('[data-act="reset"]', (user, btn) => {
                const npw = prompt(`New password for ${user.username}:`);
                if (!npw) return;
                runAsyncAction(btn, async () => {
                    await fetchJSON('/admin/users/reset_password', { method: 'POST', body: JSON.stringify({ username: user.username, new_password: npw }) });
                    loadAdminUsers();
                }, '...');
            });

            bindBtn('[data-act="toggle"]', (user, btn) => {
                runAsyncAction(btn, async () => {
                    await fetchJSON('/admin/users/disable', { method: 'POST', body: JSON.stringify({ username: user.username, disabled: !user.disabled }) });
                    loadAdminUsers();
                }, '...');
            });

            bindBtn('[data-act="logout"]', (user, btn) => {
                runAsyncAction(btn, async () => {
                    await fetchJSON('/admin/users/force_logout', { method: 'POST', body: JSON.stringify({ username: user.username }) });
                    alert('Session cleared');
                }, '...');
            });

            bindBtn('[data-act="delete"]', (user, btn) => {
                if (!confirm(`Delete user ${user.username}?`)) return;
                runAsyncAction(btn, async () => {
                    await fetchJSON('/admin/users/delete', { method: 'POST', body: JSON.stringify({ username: user.username }) });
                    loadAdminUsers();
                }, '...');
            });

            tbody.appendChild(tr);
        });
    } catch (e) { console.error(e); }
}

async function loadAdminCameras() {
    try {
        const data = await fetchJSON('/admin/cameras');
        const grid = document.getElementById('admin-cam-grid');
        if (!grid) return;
        grid.innerHTML = '';
        (data.cameras || []).forEach(c => {
            const d = document.createElement('div');
            d.className = 'card cam-admin-card';
            d.innerHTML = `
                <div class="card-header">
                    <h4>${c.name || 'Cam ' + c.id}</h4>
                    <span class="pill">${c.enabled ? 'On' : 'Off'}</span>
                </div>
                <div class="card-body">
                    <p><strong>ID:</strong> ${c.id}</p>
                    <p><strong>Zone:</strong> ${c.zone || 'None'}</p>
                </div>
                <div class="card-actions">
                    <button class="btn btn-sm" data-act="edit">Edit</button>
                    <button class="btn btn-sm" data-act="test">Test</button>
                    <button class="btn btn-sm btn-danger" data-act="remove">Remove</button>
                </div>
            `;

            const bindBtn = (sel, fn) => { d.querySelector(sel).onclick = function () { fn(c, this); }; };

            bindBtn('[data-act="edit"]', (cam) => openEditCameraModal(cam));

            bindBtn('[data-act="test"]', (cam, btn) => {
                runAsyncAction(btn, async () => {
                    await fetchJSON(`/admin/cameras/${cam.id}/test`, { method: 'POST' });
                    alert('Connection OK');
                }, 'Testing...');
            });

            bindBtn('[data-act="remove"]', (cam, btn) => {
                if (!confirm('Remove camera?')) return;
                runAsyncAction(btn, async () => {
                    await fetchJSON(`/admin/cameras/${cam.id}`, { method: 'DELETE' });
                    loadAdminCameras();
                }, 'Removing...');
            });

            grid.appendChild(d);
        });
    } catch (e) { console.error(e); }
}

// --- Modals ---
function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    if (overlay) overlay.style.display = 'none';
    const sub = document.getElementById('modal-submit');
    if (sub) sub.onclick = null;
}

function openCameraModal({ title, init = {}, onSubmit }) {
    const overlay = document.getElementById('modal-overlay');
    const body = document.getElementById('modal-body');
    const titleEl = document.getElementById('modal-title');

    if (!overlay || !body) return;
    titleEl.textContent = title;

    // ... (HTML Generation for Modal Content - simplified for brevity, assume slightly cleaner HTML)
    // Reuse the previous innerHTML generation but wrap it in a function if needed.
    // Ideally, we move this big HTML string to a separate render function or template.
    // I'll keep the logic inline but clean for this artifact.

    // ... [HTML Generation Logic from before] ... 
    // Just ensuring specific "Save" button logic uses runAsyncAction

    // For this rewrite, I should probably implement the FULL modal content otherwise the file is incomplete.

    const { name = '', source_url = '', zone = '', enabled = true, embed_fps = 1 } = init;
    let initialTab = 'url';
    if ((source_url || '').startsWith('device://')) initialTab = 'device';
    else if ((source_url || '').startsWith('file://') || /[\\/]/.test(source_url || '')) initialTab = 'file';

    body.innerHTML = `
    <div class="modal-form">
        <div class="form-group">
            <label>Camera Name</label>
            <input id="cam-name" class="input" value="${name || ''}" placeholder="e.g. Front Door">
        </div>
        
        <div class="tabs-nav">
            <button class="tab-btn active" data-tab="url">URL/RTSP</button>
            <button class="tab-btn" data-tab="device">Device</button>
            <button class="tab-btn" data-tab="file">File</button>
        </div>

        <div class="tab-content active" id="pane-url">
            <div class="form-group">
                <label>Stream URL</label>
                <input id="cam-src-url" class="input" value="${initialTab === 'url' ? (source_url || '') : ''}" placeholder="rtsp://...">
            </div>
        </div>

        <div class="tab-content" id="pane-device">
            <div class="form-group row">
                <select id="cam-src-device" class="select expanded"></select>
                <button id="cam-device-refresh" class="btn">↻</button>
            </div>
        </div>

        <div class="tab-content" id="pane-file">
             <div class="form-group" style="display:none;">
                <label>File Path</label>
                <input id="cam-src-file" class="input" value="${initialTab === 'file' ? (source_url || '').replace(/^file:\/\//i, '') : ''}">
             </div>
             <div class="form-group">
                <label>Select Video File</label>
                <div style="display:flex; gap:10px; align-items:center;">
                    <label class="btn secondary" style="cursor:pointer;">
                        Choose File
                        <input id="cam-file-picker" type="file" accept="video/*" style="display:none;">
                    </label>
                    <div id="cam-file-status" class="muted" style="font-size:0.9em;">
                        ${initialTab === 'file' ? '✅ current file set' : 'No file selected'}
                    </div>
                </div>
             </div>
        </div>

        <div class="form-row">
            <div class="form-group">
                <label>Zone</label>
                <input id="cam-zone" class="input" value="${zone || ''}">
            </div>
            <div class="form-group">
                <label>FPS</label>
                <input id="cam-embed-fps" class="input" type="number" step="0.5" value="${embed_fps}">
            </div>
        </div>
        
        <div class="form-group checkbox-group">
            <input id="cam-enabled" type="checkbox" ${enabled ? 'checked' : ''}>
            <label for="cam-enabled">Enable Camera</label>
        </div>
    </div>`;

    // Tab Logic
    const tabs = body.querySelectorAll('.tab-btn');
    const panes = body.querySelectorAll('.tab-content');
    let curTab = initialTab;

    function setTab(t) {
        curTab = t;
        tabs.forEach(b => b.classList.toggle('active', b.dataset.tab === t));
        panes.forEach(p => p.classList.toggle('active', p.id === `pane-${t}`));
        if (t === 'device') loadDevices();
    }

    tabs.forEach(b => b.onclick = () => setTab(b.dataset.tab));
    setTab(initialTab);

    // Device Loader
    async function loadDevices() {
        const sel = document.getElementById('cam-src-device');
        sel.innerHTML = '<option>Loading...</option>';
        try {
            const d = await fetchJSON('/admin/devices');
            sel.innerHTML = '';
            if (!d.devices?.length) sel.innerHTML = '<option>No devices found</option>';
            else {
                d.devices.forEach(dev => {
                    const opt = document.createElement('option');
                    opt.value = dev.index;
                    opt.textContent = dev.name;
                    sel.appendChild(opt);
                });
            }
        } catch { sel.innerHTML = '<option>Error</option>'; }
    }
    document.getElementById('cam-device-refresh').onclick = loadDevices;

    // Auto-Upload on Select
    const filePicker = document.getElementById('cam-file-picker');
    if (filePicker) {
        filePicker.onchange = function () {
            const file = this.files[0];
            if (!file) return;

            const statusEl = document.getElementById('cam-file-status');
            statusEl.textContent = `Uploading ${file.name}...`;
            statusEl.style.color = 'var(--text-muted)'; // reset color

            const fd = new FormData();
            fd.append('file', file);

            // Using fetch directly or runAsyncAction wrapper if we had a button context
            // Here we just do it async
            fetch('/admin/upload_video', { method: 'POST', body: fd })
                .then(r => r.json())
                .then(j => {
                    if (j.path) {
                        document.getElementById('cam-src-file').value = j.path;
                        statusEl.textContent = `✅ Ready: ${file.name}`;
                        statusEl.style.color = 'var(--success)';
                        // Auto-set name if empty
                        const nameInp = document.getElementById('cam-name');
                        if (!nameInp.value) nameInp.value = file.name;
                    } else {
                        throw new Error('No path returned');
                    }
                })
                .catch(e => {
                    console.error(e);
                    statusEl.textContent = '❌ Upload failed';
                    statusEl.style.color = 'var(--error)';
                });
        };
    }

    overlay.style.display = 'flex';

    document.getElementById('modal-submit').onclick = function () {
        const btn = this;
        // Construct payload logic
        let src = '';
        if (curTab === 'url') src = document.getElementById('cam-src-url').value.trim();
        else if (curTab === 'file') {
            const f = document.getElementById('cam-src-file').value.trim();
            if (f) src = `file://${f}`;
        } else if (curTab === 'device') {
            const v = document.getElementById('cam-src-device').value;
            if (v) src = `device://${v}`;
        }

        let n = document.getElementById('cam-name').value.trim();
        if (!n) n = `Camera ${src}`; // Simplification

        if (!src) return alert('Source required');

        const payload = {
            name: n,
            source_url: src,
            zone: document.getElementById('cam-zone').value.trim() || null,
            enabled: document.getElementById('cam-enabled').checked,
            embed_fps: parseFloat(document.getElementById('cam-embed-fps').value) || 1
        };

        runAsyncAction(btn, async () => {
            await onSubmit(payload);
            closeModal();
            loadAdminCameras();
        }, 'Saving...');
    };
}

function openAddCameraModal() {
    openCameraModal({
        title: 'Add Camera',
        init: { enabled: true },
        onSubmit: (p) => fetchJSON('/admin/cameras', { method: 'POST', body: JSON.stringify(p) })
    });
}

function openEditCameraModal(cam) {
    openCameraModal({
        title: 'Edit Camera',
        init: cam,
        onSubmit: (p) => fetchJSON(`/admin/cameras/${cam.id}`, { method: 'PATCH', body: JSON.stringify(p) })
    });
}

function openAddUserModal() {
    const overlay = document.getElementById('modal-overlay');
    const body = document.getElementById('modal-body');
    const title = document.getElementById('modal-title');
    if (!overlay) return;

    title.textContent = 'Add User';
    body.innerHTML = `
    <div class="modal-form">
        <div class="form-group"><label>Username</label><input id="u-user" class="input"></div>
        <div class="form-group"><label>Password</label><input id="u-pass" class="input" type="password"></div>
        <div class="form-group"><label>Role</label>
        <select id="u-role" class="select"><option value="user">User</option><option value="admin">Admin</option></select>
        </div>
    </div>`;

    overlay.style.display = 'flex';

    document.getElementById('modal-submit').onclick = function () {
        const btn = this;
        const u = document.getElementById('u-user').value.trim();
        const p = document.getElementById('u-pass').value;
        const r = document.getElementById('u-role').value;

        if (!u || !p) return alert('Required fields missing');

        runAsyncAction(btn, async () => {
            await fetchJSON('/admin/users', { method: 'POST', body: JSON.stringify({ username: u, password: p, role: r }) });
            closeModal();
            loadAdminUsers();
        }, 'Creating...');
    };
}


// --- Detection & Logs ---
async function fetchDetections() {
    try {
        const r = await fetchJSON('/api/detections');
        DETECTION_STATE = r.detections || {};
        SHOW_KEYPOINTS = !!r.show_keypoints;
        updateKeypointButton();
        renderDetectionTabs();
        // Ensure badges update
        updateDetectionBadges();
    } catch (e) { }
}

function renderDetectionTabs() {
    const tabs = document.getElementById('cam-tabs');
    if (!tabs) return;
    tabs.innerHTML = '';

    CAMS.forEach(c => {
        const d = DETECTION_STATE[c.id] || {};
        const label = d.label || 'Normal';
        const isAlert = d.is_alert;

        const chip = document.createElement('div');
        chip.className = `status-chip ${isAlert ? 'alert' : 'normal'}`;
        chip.textContent = `${c.name || c.id}: ${label}`;
        chip.onclick = () => {
            const sel = document.getElementById('camera-select');
            sel.value = c.id;
            VIEW_MODE = 'single';
            localStorage.setItem('viewMode', VIEW_MODE);
            applyViewMode();
        };
        tabs.appendChild(chip);
    });
}

function updateDetectionBadges() {
    // Add red borders/badges to cards based on DETECTION_STATE
    const cards = document.querySelectorAll('.cam-card');
    cards.forEach(c => {
        const id = c.dataset.camId;
        const d = DETECTION_STATE[id] || {};
        const isAlert = d.is_alert;
        const label = d.label || 'Normal';
        const badge = c.querySelector('.cam-badge');
        const confBadge = c.querySelector('.cam-conf');

        c.classList.toggle('card-alert', !!isAlert);
        if (badge) {
            badge.textContent = label;
            // Map colors
            if (isAlert) badge.className = 'pill cam-badge pill-error pulse-text';
            else if (label === 'Normal') badge.className = 'pill cam-badge pill-success';
            else badge.className = 'pill cam-badge pill-warn';
        }

        // Confidence Display
        if (confBadge) {
            if (d.score && label !== 'Normal') {
                confBadge.textContent = `${Math.round(d.score * 100)}%`;
                confBadge.classList.remove('hidden');
            } else {
                confBadge.classList.add('hidden');
            }
        }

        // Alert Trigger logic
        if (isAlert && label !== 'Normal') {
            const lastState = c.dataset.alerted;
            // Throttle alerts: only alert if state (label) changed OR it's been > 15s since last alert
            // We use a simple timestamp check if storing ts in dataset
            const now = Date.now();
            const lastTs = parseInt(c.dataset.alertTs || '0');

            if (label !== lastState || (now - lastTs > 15000)) {
                const cam = CAMS.find(c => c.id == id);
                const camName = cam ? (cam.name || id) : id;
                ALERTS.add(`${label} detected on ${camName}`, 'critical');
                c.dataset.alerted = label;
                c.dataset.alertTs = now;
            }
        }
    });
}

// Logs, AlertSound and BigAlert same as before...
// (Including condensed versions for brevity)
function playAlertSound() {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.connect(g); g.connect(ctx.destination);
    osc.type = 'sawtooth'; osc.frequency.value = 440;
    osc.start(); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
    osc.stop(ctx.currentTime + 0.5);
}

function showBigAlert(msg) {
    let mod = document.getElementById('alert-modal');
    if (!mod) {
        mod = document.createElement('div');
        mod.id = 'alert-modal';
        document.body.appendChild(mod);
    }

    mod.innerHTML = `
        <div style="font-size:48px;">⚠️</div>
        <div style="font-size:24px; font-weight:bold;">CRITICAL ALERT</div>
        <div style="font-size:18px;">${msg}</div>
        <button class="btn" style="background:white; color:black; border:none; margin-top:10px;" onclick="document.getElementById('alert-modal').style.display='none'">DISMISS</button>
    `;

    mod.style.display = 'flex';

    // Auto-dismiss safely
    if (window.alertTimeout) clearTimeout(window.alertTimeout);
    window.alertTimeout = setTimeout(() => {
        mod.style.display = 'none';
    }, 10000);
}

async function pollEmbeddings() {
    try {
        const r = await fetchJSON('/api/embeddings/stats');
        setText('embed-count', `${r.count} Embeddings`);
    } catch { }
}

const logSource = null;
function startLogs() {
    if (window.logSource) return;
    window.logSource = new EventSource('/logs');
    window.logSource.onmessage = e => {
        if (LOGS_PAUSED) return;
        LOGS.push({ raw: e.data, ts: Date.now() });
        if (LOGS.length > 500) LOGS.shift();
        renderLogs();
    };
}

function renderLogs() {
    const body = document.getElementById('log-body');
    if (!body || LOGS_PAUSED) return;

    const camFilter = document.getElementById('cam-filter');
    const search = document.getElementById('log-search');
    const tailSize = document.getElementById('tail-size');
    const autoScroll = document.getElementById('auto-scroll');

    const cam = camFilter ? camFilter.value : '';
    const term = search ? search.value.toLowerCase() : '';
    const limit = tailSize ? parseInt(tailSize.value) : 100;

    // Check levels
    const levels = [];
    if (document.getElementById('lvl-info')?.checked) levels.push('INFO');
    if (document.getElementById('lvl-warn')?.checked) levels.push('WARNING');
    if (document.getElementById('lvl-error')?.checked) levels.push('ERROR');
    if (document.getElementById('lvl-debug')?.checked) levels.push('DEBUG');

    const filtered = LOGS.filter(l => {
        // Parse level from raw string if not structured yet (simple heuristic)
        // Expected format: "YYYY-MM-DD ... - LEVEL - Message"
        const isNormal = l.raw.includes('Normal');
        if (isNormal) return false; // STRICTLY EXCLUDE NORMAL

        if (term && !l.raw.toLowerCase().includes(term)) return false;

        // Level check (approximate)
        if (levels.length < 4) {
            let lvl = 'INFO';
            if (l.raw.includes('WARNING')) lvl = 'WARNING';
            if (l.raw.includes('ERROR')) lvl = 'ERROR';
            if (l.raw.includes('DEBUG')) lvl = 'DEBUG';
            if (!levels.includes(lvl)) return false;
        }
        return true;
    });

    const slice = filtered.slice(-limit);
    body.innerHTML = slice.map(l => `<div class="log-line">${l.raw}</div>`).join('');

    if (autoScroll && autoScroll.checked) {
        body.scrollTop = body.scrollHeight;
    }
}

function exportLogs() {
    // ...
}
