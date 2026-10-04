// ============================================
//  Messages, player actions, backups, worlds,
//  world map and AI builder
//  (uses the helpers defined in app.js)
// ============================================

function when(epochSeconds) {
    const d = new Date(epochSeconds * 1000);
    const today = new Date().toDateString() === d.toDateString();
    const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    return today ? `Today ${time}` : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`;
}

// apiPost() from app.js swallows errors; these calls want the server's message
async function post(endpoint, payload = {}) {
    const result = await apiPost(endpoint, payload);
    if (!result) return { success: false, error: 'The dashboard is not answering' };
    return result;
}

// ---------- Messages ----------

async function announce(message) {
    message = (message || '').trim();
    if (!message) return;
    const result = await post('announce', { message });
    if (result.success) {
        toast(result.players ? `Shown to ${result.players} player${result.players === 1 ? '' : 's'}` : 'Sent (nobody is online right now)', 'success');
        $('#announce-input').value = '';
    } else {
        toast(result.error, 'error');
    }
}

// ---------- Player actions ----------

const PLAYER_ACTION_DONE = {
    heal: 'Healed and fed', kit: 'Starter kit given', creative: 'Switched to Creative', survival: 'Switched to Survival',
    bring_all: 'Everyone teleported', op: 'Now an operator', deop: 'No longer an operator', tp_to: 'Teleported',
    tp_spot: 'Teleported',
};

function initPlayerActions() {
    $('#player-list').addEventListener('click', async (e) => {
        const item = e.target.closest('.player-item');
        if (!item) return;
        const button = e.target.closest('[data-action]');
        if (!button) {
            if (e.target.closest('.player-actions')) return;   // clicks on the select, etc.
            const actions = item.querySelector('.player-actions');
            const opening = actions.hidden;
            $$('.player-actions').forEach(a => { a.hidden = true; });
            actions.hidden = !opening;
            return;
        }
        const payload = { player: item.dataset.player, action: button.dataset.action };
        if (payload.action === 'tp_to') payload.target = item.querySelector('.pa-target').value;
        const result = await post('player', payload);
        toast(result.success ? `${payload.player}: ${PLAYER_ACTION_DONE[payload.action]}` : result.error,
              result.success ? 'success' : 'error');
    });
}

// ---------- Backups ----------

const BACKUP_KIND = { manual: 'Saved by you', auto: 'Automatic', daily: 'Nightly', 'before-restore': 'Before a restore' };

async function loadBackups() {
    const data = await api('backups');
    if (!data) return;
    const list = $('#backup-list');
    if (!data.backups.length) {
        list.innerHTML = '<div class="empty-note">No backups yet. The first automatic one is made after someone plays.</div>';
        return;
    }
    list.innerHTML = data.backups.map(b => `
        <div class="row-item" data-id="${escapeHtml(b.id)}">
            <div class="row-main">
                <div class="row-title">${escapeHtml(when(b.time))} <span class="tag-soft">${escapeHtml(BACKUP_KIND[b.kind] || b.kind)}</span></div>
                <div class="row-sub">${escapeHtml(b.world)} &middot; ${b.size_mb} MB</div>
            </div>
            <button class="chip" type="button" data-backup="restore">Restore</button>
            <button class="chip danger" type="button" data-backup="delete" title="Delete this backup">&#10005;</button>
        </div>`).join('');
}

function initBackups() {
    $('#btn-backup-now').addEventListener('click', async () => {
        toast('Backing up...', 'info');
        const result = await post('backups');
        toast(result.success ? 'Backup saved' : result.error, result.success ? 'success' : 'error');
        loadBackups();
    });
    $('#backup-list').addEventListener('click', async (e) => {
        const button = e.target.closest('[data-backup]');
        if (!button) return;
        const row = button.closest('.row-item');
        const label = row.querySelector('.row-title').textContent.trim();
        if (button.dataset.backup === 'restore') {
            if (!confirm(`Put the world back to how it was at:\n\n${label}\n\nEveryone playing is disconnected for a moment, and anything built since then is replaced. (The current world is backed up first, so this can be reversed.)`)) return;
            toast('Restoring... this takes about half a minute', 'info');
            const result = await post('backups/restore', { id: row.dataset.id });
            toast(result.success ? 'World restored' : result.error, result.success ? 'success' : 'error');
        } else {
            if (!confirm(`Delete this backup?\n\n${label}`)) return;
            const result = await post('backups/delete', { id: row.dataset.id });
            if (!result.success) toast(result.error, 'error');
        }
        loadBackups();
        setTimeout(refreshAll, 3000);
    });
}

// ---------- Worlds ----------

async function loadWorlds() {
    const data = await api('worlds');
    if (!data) return;
    const list = $('#world-list');
    if (!data.worlds.length) {
        list.innerHTML = '<div class="empty-note">The first world is still being created...</div>';
        return;
    }
    list.innerHTML = data.worlds.map(w => `
        <div class="row-item ${w.active ? 'active' : ''}" data-name="${escapeHtml(w.name)}">
            <div class="row-main">
                <div class="row-title">${escapeHtml(w.name)}</div>
                <div class="row-sub">${escapeHtml(w.gamemode || 'unknown mode')} &middot; ${w.size_mb} MB</div>
            </div>
            ${w.active ? '<span class="tag-soft on">Playing now</span>'
                       : '<button class="chip" type="button" data-world="switch">Switch to this</button>'}
        </div>`).join('');
}

function initWorlds() {
    $('#world-list').addEventListener('click', async (e) => {
        const button = e.target.closest('[data-world]');
        if (!button) return;
        const name = button.closest('.row-item').dataset.name;
        if (!confirm(`Switch everyone to "${name}"?\n\nThe server restarts, so players are disconnected for a moment and rejoin into the new world. The current world is kept.`)) return;
        toast(`Switching to ${name}...`, 'info');
        const result = await post('worlds/switch', { name });
        toast(result.success ? `Now playing ${name}` : result.error, result.success ? 'success' : 'error');
        afterWorldChange();
    });
    $('#btn-world-create').addEventListener('click', async () => {
        const name = $('#world-name').value.trim();
        if (!name) { toast('Give the world a name', 'error'); return; }
        if (!confirm(`Create "${name}" and switch everyone to it?\n\nThe server restarts, so players are disconnected for a moment. The current world is kept.`)) return;
        toast(`Creating ${name}...`, 'info');
        const result = await post('worlds/create', {
            name, gamemode: $('#world-gamemode').value, difficulty: $('#world-difficulty').value, seed: $('#world-seed').value.trim(),
        });
        if (result.success) {
            toast(`${name} is loading`, 'success');
            $('#world-name').value = '';
            $('#world-seed').value = '';
        } else {
            toast(result.error, 'error');
        }
        afterWorldChange();
    });
}

function afterWorldChange() {
    loadWorlds();
    loadSettings();
    mapState.version = -1;
    mapState.world = null;
    clearPickedSpot();
    setTimeout(() => { refreshAll(); loadWorlds(); loadBackups(); loadMap(); }, 8000);
}

// ---------- World map ----------

const mapState = { map: null, tiles: null, version: -1, world: null, picked: null, pickMarker: null, playerMarkers: {}, fitted: false };

// World (x, z) <-> Leaflet: one map unit is one block, north is up
const toLatLng = (x, z) => L.latLng(-z, x);

function initMap() {
    if (typeof L === 'undefined') {
        $('#map-meta').textContent = 'Map needs an internet connection to load';
        return;
    }
    const map = L.map('map', { crs: L.CRS.Simple, minZoom: -2, maxZoom: 4, zoomSnap: 1, attributionControl: false });
    map.setView(toLatLng(0, 0), 1);
    const TileLayer = L.TileLayer.extend({
        getTileUrl(coords) { return `/api/map/tile/${coords.x}/${coords.y}.png?v=${mapState.version}`; },
    });
    mapState.tiles = new TileLayer('', { tileSize: 256, minNativeZoom: 0, maxNativeZoom: 0, className: 'map-tiles' }).addTo(map);
    mapState.map = map;

    map.on('mousemove', (e) => {
        $('#map-coords').textContent = `X ${Math.floor(e.latlng.lng)}   Z ${Math.floor(-e.latlng.lat)}`;
    });
    map.on('click', (e) => pickSpot(Math.floor(e.latlng.lng), Math.floor(-e.latlng.lat)));

    $('#btn-map-refresh').addEventListener('click', async () => {
        $('#map-meta').textContent = 'Saving the world and redrawing...';
        const result = await post('map/refresh');
        if (!result.success) toast(result.error, 'error');
        loadMap();
    });
    $('#map-picked').addEventListener('click', async (e) => {
        const button = e.target.closest('[data-send]');
        if (!button || !mapState.picked) return;
        const result = await post('player', { action: 'tp_spot', player: button.dataset.send, x: mapState.picked.x, z: mapState.picked.z });
        toast(result.success ? `${button.dataset.send} sent there` : result.error, result.success ? 'success' : 'error');
    });
}

async function loadMap() {
    if (!mapState.map) return;
    const info = await api('map/info');
    if (!info) return;
    $('#map-empty').hidden = info.chunks > 0;
    $('#map-meta').textContent = info.chunks
        ? `${info.world} · updated ${info.updated ? when(info.updated) : 'just now'}`
        : info.world;
    const worldChanged = mapState.world !== info.world;
    if (worldChanged || info.version !== mapState.version) {
        mapState.version = info.version;
        mapState.world = info.world;
        mapState.tiles.redraw();
    }
    if (info.bounds && (worldChanged || !mapState.fitted)) {
        mapState.fitted = true;
        mapState.map.setView(toLatLng(info.spawn.x, info.spawn.z), 1);
    }
}

async function pickSpot(x, z) {
    const data = await api(`map/height?x=${x}&z=${z}`);
    const y = data && data.y !== null && data.y !== undefined ? data.y : null;
    mapState.picked = { x, z, y };
    if (!mapState.pickMarker) {
        mapState.pickMarker = L.marker(toLatLng(x + 0.5, z + 0.5), {
            icon: L.divIcon({ className: 'map-pick', iconSize: [18, 18] }), interactive: false,
        }).addTo(mapState.map);
    }
    mapState.pickMarker.setLatLng(toLatLng(x + 0.5, z + 0.5));
    renderPickedSpot();
}

function clearPickedSpot() {
    mapState.picked = null;
    if (mapState.pickMarker) { mapState.pickMarker.remove(); mapState.pickMarker = null; }
    renderPickedSpot();
}

function renderPickedSpot() {
    const spot = mapState.picked;
    const text = spot ? `X ${spot.x}, Z ${spot.z}${spot.y === null ? ' (not explored yet)' : `, ground at Y ${spot.y}`}` : '';
    $('#ai-spot').textContent = spot ? text : 'none yet - click the map';
    const send = spot && spot.y !== null
        ? onlinePlayers.map(p => `<button class="chip" type="button" data-send="${escapeHtml(p)}">Send ${escapeHtml(p)} here</button>`).join('')
        : '';
    $('#map-picked').innerHTML = spot ? `<span class="picked-label">Picked: ${escapeHtml(text)}</span>${send}` : '';
}

async function updateMapPlayers() {
    if (!mapState.map || !onlinePlayers.length) {
        Object.values(mapState.playerMarkers).forEach(m => m.remove());
        mapState.playerMarkers = {};
        return;
    }
    // Only ask the server where everyone is while the map is actually on screen
    const box = $('#map').getBoundingClientRect();
    if (box.bottom < 0 || box.top > window.innerHeight || document.hidden) return;
    const data = await api('map/players');
    if (!data) return;
    const seen = new Set();
    data.players.forEach(p => {
        seen.add(p.name);
        let marker = mapState.playerMarkers[p.name];
        if (!marker) {
            marker = L.marker(toLatLng(p.x, p.z), {
                icon: L.divIcon({ className: 'map-player', iconSize: [16, 16], html: `<span style="background:${getPlayerColor(p.name)}"></span>` }),
            }).bindTooltip(p.name, { permanent: true, direction: 'right', offset: [8, 0], className: 'map-player-name' }).addTo(mapState.map);
            mapState.playerMarkers[p.name] = marker;
        }
        marker.setLatLng(toLatLng(p.x, p.z));
    });
    Object.keys(mapState.playerMarkers).forEach(name => {
        if (!seen.has(name)) { mapState.playerMarkers[name].remove(); delete mapState.playerMarkers[name]; }
    });
}

// ---------- AI builder ----------

const aiState = { design: null, available: false, pollTimer: null };

async function loadAi() {
    const data = await api('ai/status');
    if (!data) return;
    aiState.available = data.available;
    $('#ai-setup').hidden = data.available;
    $('#btn-ai-design').disabled = !data.available;
    $('#ai-prompt').disabled = !data.available;
    $('#ai-meta').textContent = data.available ? `Designs by Claude · up to ${data.max_size} blocks wide` : 'Needs an API key for new designs';
    const undo = $('#btn-ai-undo');
    undo.disabled = !data.last_build;
    undo.title = data.last_build ? `Removes "${data.last_build.label}" and puts the land back` : 'Nothing to undo';
    $('#ai-recent').innerHTML = data.recent.length ? data.recent.map(d => `
        <div class="row-item clickable ${aiState.design && aiState.design.id === d.id ? 'active' : ''}" data-design="${escapeHtml(d.id)}">
            <div class="row-main">
                <div class="row-title">${escapeHtml(d.name || 'Untitled')}</div>
                <div class="row-sub">${d.stats ? `${d.stats.size.x} x ${d.stats.size.z} x ${d.stats.size.y} tall` : ''}${d.status === 'built' ? ' &middot; built' : ''}</div>
            </div>
        </div>`).join('') : '<div class="empty-note">None yet</div>';
}

function showDesign(design) {
    aiState.design = design;
    $('#ai-result-empty').hidden = true;
    $('#ai-card').hidden = false;
    $('#ai-name').textContent = design.name;
    $('#ai-summary').textContent = design.summary;
    $('#ai-top').src = `/api/ai/design/${design.id}/top.png`;
    $('#ai-front').src = `/api/ai/design/${design.id}/front.png`;
    const s = design.stats;
    const seconds = Math.max(5, Math.round(design.commands / 20) + 10);
    $('#ai-stats').innerHTML = `
        <span><b>${s.size.x} x ${s.size.z}</b> blocks on the ground, <b>${s.size.y}</b> tall</span>
        <span><b>${s.blocks.toLocaleString()}</b> blocks</span>
        <span>about <b>${seconds < 90 ? `${seconds} seconds` : `${Math.round(seconds / 60)} minutes`}</b> to build</span>
        <span class="ai-materials">${s.materials.slice(0, 5).map(m => escapeHtml(m.block.replace(/_/g, ' '))).join(', ')}</span>`;
    $('#ai-build-status').textContent = design.build_error || '';
    $$('#ai-recent .row-item').forEach(row => row.classList.toggle('active', row.dataset.design === design.id));
}

async function pollDesign(id, onDone) {
    clearTimeout(aiState.pollTimer);
    const data = await api(`ai/design/${id}`);
    const design = data && data.design;
    if (design && (design.status === 'designing' || design.status === 'building')) {
        aiState.pollTimer = setTimeout(() => pollDesign(id, onDone), 2000);
        return;
    }
    onDone(design);
}

function initAi() {
    $('#ai-ideas').addEventListener('click', (e) => {
        if (e.target.classList.contains('chip') && aiState.available) $('#ai-prompt').value = e.target.textContent;
    });

    $('#btn-ai-design').addEventListener('click', async () => {
        const prompt = $('#ai-prompt').value.trim();
        if (!prompt) { toast('Describe what to build first', 'error'); return; }
        const result = await post('ai/design', { prompt });
        if (!result.success) { toast(result.error, 'error'); return; }
        $('#btn-ai-design').disabled = true;
        $('#ai-status').textContent = 'Claude is designing it. Big builds take a few minutes...';
        pollDesign(result.design.id, (design) => {
            $('#btn-ai-design').disabled = !aiState.available;
            if (!design || design.status === 'error') {
                $('#ai-status').textContent = (design && design.error) || 'Something went wrong';
                toast('The design did not work out', 'error');
                return;
            }
            $('#ai-status').textContent = '';
            toast(`Design ready: ${design.name}`, 'success');
            showDesign(design);
            loadAi();
        });
    });

    $('#ai-recent').addEventListener('click', async (e) => {
        const row = e.target.closest('[data-design]');
        if (!row) return;
        const data = await api(`ai/design/${row.dataset.design}`);
        if (data && data.design) showDesign(data.design);
    });

    $('#btn-ai-build').addEventListener('click', async () => {
        const design = aiState.design;
        if (!design) return;
        const payload = { id: design.id, clear: $('#ai-clear').checked };
        const where = document.querySelector('input[name="ai-where"]:checked').value;
        if (where === 'player') {
            payload.player = $('#ai-player').value;
            if (!payload.player) { toast('Nobody is online to build next to', 'error'); return; }
        } else {
            if (!mapState.picked) { toast('Click the map to pick a spot first', 'error'); return; }
            if (mapState.picked.y === null) { toast('That spot has not been explored yet. Pick somewhere on the map.', 'error'); return; }
            payload.x = mapState.picked.x;
            payload.z = mapState.picked.z;
        }
        if (!confirm(`Build "${design.name}" in the world now?\n\nYou can remove it again with "Undo last build".`)) return;
        const result = await post('ai/build', payload);
        if (!result.success) { toast(result.error, 'error'); return; }
        $('#btn-ai-build').disabled = true;
        $('#ai-build-status').textContent = 'Building...';
        pollDesign(design.id, (done) => {
            $('#btn-ai-build').disabled = false;
            if (done && done.status === 'built') {
                const b = done.build;
                $('#ai-build-status').textContent = `Built at X ${b.from[0]}, Y ${b.from[1]}, Z ${b.from[2]}` +
                    (b.errors.length ? ` (${b.errors.length} parts could not be placed)` : '');
                toast(`${done.name} is in the world!`, 'success');
            } else {
                $('#ai-build-status').textContent = (done && done.build_error) || 'The build failed';
                toast('The build did not finish', 'error');
            }
            loadAi();
            loadMap();
        });
    });

    $('#btn-ai-undo').addEventListener('click', async () => {
        if (!confirm('Remove the last build and put the land back the way it was?')) return;
        toast('Undoing...', 'info');
        const result = await post('ai/undo');
        toast(result.success ? 'Build removed' : result.error, result.success ? 'success' : 'error');
        loadAi();
        loadMap();
    });

    document.addEventListener('players-changed', (e) => {
        const select = $('#ai-player');
        const current = select.value;
        select.innerHTML = e.detail.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join('');
        if (e.detail.includes(current)) select.value = current;
        renderPickedSpot();
    });
}

// ---------- Start ----------

document.addEventListener('DOMContentLoaded', () => {
    $('#btn-announce').addEventListener('click', () => announce($('#announce-input').value));
    $('#announce-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') announce(e.target.value); });
    $$('.announce .chip').forEach(chip => chip.addEventListener('click', () => announce(chip.dataset.msg)));

    initPlayerActions();
    initBackups();
    initWorlds();
    initMap();
    initAi();

    loadBackups();
    loadWorlds();
    loadMap();
    loadAi();
    setInterval(loadBackups, 60000);
    setInterval(loadWorlds, 30000);
    setInterval(loadMap, 15000);
    setInterval(updateMapPlayers, 5000);
});
