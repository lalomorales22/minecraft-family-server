// ============================================
//  Minecraft Family Server Dashboard - JS
// ============================================

const REFRESH_INTERVAL = 5000; // 5 seconds
const SETUP_INTERVAL = 15000;  // setup check is slower (it pings each service)
let playerChart = null;

// ---------- Utility ----------

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

async function api(endpoint) {
    try {
        const res = await fetch(`/api/${endpoint}`);
        return await res.json();
    } catch (e) {
        console.error(`API error (${endpoint}):`, e);
        return null;
    }
}

async function apiPost(endpoint, body = {}) {
    try {
        const res = await fetch(`/api/${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return await res.json();
    } catch (e) {
        console.error(`API POST error (${endpoint}):`, e);
        return null;
    }
}

function toast(message, type = 'info') {
    const container = $('.toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
}

function formatUptime(startedAt) {
    if (!startedAt) return '--:--:--';
    const start = new Date(startedAt);
    const now = new Date();
    let diff = Math.floor((now - start) / 1000);
    if (diff < 0) return '--:--:--';
    const days = Math.floor(diff / 86400); diff %= 86400;
    const hrs = Math.floor(diff / 3600); diff %= 3600;
    const mins = Math.floor(diff / 60); diff %= 60;
    const secs = diff;
    if (days > 0) return `${days}d ${hrs}h ${mins}m`;
    return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// ---------- Player head via Crafatar-style pixel art ----------

function getPlayerColor(name) {
    // Generate a deterministic color from player name
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash) % 360;
    return `hsl(${hue}, 55%, 45%)`;
}

function makePlayerHead(name) {
    const color = getPlayerColor(name);
    return `<div class="player-head" style="background: ${color}; display:flex; align-items:center; justify-content:center; font-family:var(--font-pixel); font-size:14px; color:white; text-shadow:1px 1px 0 rgba(0,0,0,0.5);">${name[0].toUpperCase()}</div>`;
}

// ---------- Update Functions ----------

async function updateStatus() {
    const data = await api('status');
    if (!data) return;

    const dot = $('.beacon-dot');
    const label = $('.beacon-label');

    if (data.online) {
        dot.classList.add('online');
        label.textContent = 'ONLINE';
        label.style.color = 'var(--emerald)';
    } else {
        dot.classList.remove('online');
        label.textContent = 'OFFLINE';
        label.style.color = 'var(--redstone)';
    }

    // Stat cards
    $('#stat-players').textContent = `${data.players_online} / ${data.players_max}`;
    $('#stat-latency').textContent = `${data.latency}ms`;

    // Server info
    $('#info-version').textContent = data.version || '--';
    $('#info-gamemode').textContent = data.gamemode || '--';
    $('#info-world').textContent = data.map_name || '--';
    $('#info-motd').textContent = data.motd || '--';
}

async function updateStats() {
    const data = await api('stats');
    if (!data) return;

    if (data.running) {
        $('#stat-cpu').textContent = `${data.cpu_percent}%`;
        $('#stat-memory').textContent = `${data.memory_mb} MB`;
        $('#stat-uptime').textContent = formatUptime(data.started_at);

        // CPU bar
        const cpuFill = $('.resource-bar-fill.cpu');
        cpuFill.style.width = `${Math.min(data.cpu_percent, 100)}%`;
        cpuFill.parentElement.querySelector('.bar-label').textContent = `${data.cpu_percent}%`;

        // Memory bar
        const memFill = $('.resource-bar-fill.mem');
        memFill.style.width = `${Math.min(data.memory_percent, 100)}%`;
        memFill.parentElement.querySelector('.bar-label').textContent = `${data.memory_mb} MB`;

        // Network
        $('#info-net-rx').textContent = `${data.network_rx_mb} MB`;
        $('#info-net-tx').textContent = `${data.network_tx_mb} MB`;
    } else {
        $('#stat-cpu').textContent = '--';
        $('#stat-memory').textContent = '--';
        $('#stat-uptime').textContent = 'OFFLINE';
    }
}

async function updatePlayers() {
    const data = await api('players');
    if (!data) return;

    const listEl = $('#player-list');
    const connected = data.connected || [];

    if (connected.length === 0) {
        listEl.innerHTML = `
            <div class="no-players">
                <span class="big">&#9776;</span>
                No players online<br>
                Waiting for connections...
            </div>`;
    } else {
        listEl.innerHTML = connected.map(name => `
            <li class="player-item">
                ${makePlayerHead(name)}
                <div>
                    <div class="player-name">${escapeHtml(name)}</div>
                    <div class="player-status">Playing now</div>
                </div>
                <div class="player-dot"></div>
            </li>`).join('');
    }

    // Activity feed
    const feedEl = $('#activity-feed');
    const events = (data.recent_events || []).reverse().slice(0, 15);
    if (events.length === 0) {
        feedEl.innerHTML = '<div style="color:var(--text-dim); padding: 20px; text-align:center;">No recent activity</div>';
    } else {
        feedEl.innerHTML = events.map(e => `
            <div class="activity-item">
                <span class="tag ${e.action === 'joined' ? 'join' : 'leave'}">
                    ${e.action === 'joined' ? '+ JOIN' : '- LEFT'}
                </span>
                <span>${escapeHtml(e.player)}</span>
                <span class="time">${escapeHtml(e.time)}</span>
            </div>`).join('');
    }
}

async function updateHistory() {
    const data = await api('history');
    if (!data || !data.player_counts) return;

    $('#stat-peak').textContent = data.peak_players || 0;
    $('#stat-unique').textContent = data.total_unique || 0;

    // Update chart
    if (playerChart && data.player_counts.length > 0) {
        const labels = data.player_counts.map(p => {
            const d = new Date(p.time + 'Z');
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        });
        const counts = data.player_counts.map(p => p.count);
        playerChart.data.labels = labels;
        playerChart.data.datasets[0].data = counts;
        playerChart.update('none');
    }
}

async function updateLogs() {
    const data = await api('logs?lines=60');
    if (!data || !data.logs) return;

    const el = $('#console-output');
    el.innerHTML = data.logs.map(line => {
        let cls = '';
        if (/warn/i.test(line)) cls = 'warn';
        else if (/error|fail/i.test(line)) cls = 'error';
        else if (/info|start|running/i.test(line)) cls = 'info';
        return `<div class="log-line ${cls}">${escapeHtml(line)}</div>`;
    }).join('');

    // Auto-scroll to bottom
    el.scrollTop = el.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---------- Server Controls ----------

async function serverAction(action) {
    toast(`${action.charAt(0).toUpperCase() + action.slice(1)}ing server...`, 'info');
    const result = await apiPost(`server/${action}`);
    if (result && result.success) {
        toast(`Server ${action} successful!`, 'success');
    } else {
        toast(result?.error || `Failed to ${action} server`, 'error');
    }
    setTimeout(refreshAll, 2000);
}

async function sendCommand() {
    const input = $('#console-input');
    const cmd = input.value.trim();
    if (!cmd) return;
    input.value = '';
    toast(`Sent: ${cmd}`, 'info');
    await apiPost('command', { command: cmd });
    setTimeout(updateLogs, 1000);
}

// ---------- Chart Setup ----------

function initChart() {
    const ctx = document.getElementById('player-chart');
    if (!ctx) return;

    playerChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Players Online',
                data: [],
                borderColor: '#17DD62',
                backgroundColor: 'rgba(23, 221, 98, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHitRadius: 10,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(20,15,10,0.95)',
                    titleFont: { family: "'Press Start 2P'", size: 8 },
                    bodyFont: { family: "'VT323'", size: 16 },
                    borderColor: '#5C4033',
                    borderWidth: 2,
                    padding: 10,
                }
            },
            scales: {
                x: {
                    display: true,
                    ticks: {
                        color: '#6B6B6B',
                        font: { family: "'VT323'", size: 14 },
                        maxTicksLimit: 8,
                    },
                    grid: { color: 'rgba(255,255,255,0.03)' },
                },
                y: {
                    display: true,
                    beginAtZero: true,
                    ticks: {
                        color: '#6B6B6B',
                        font: { family: "'VT323'", size: 14 },
                        stepSize: 1,
                    },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                }
            },
            animation: false,
        }
    });
}

// ---------- Settings ----------

async function loadSettings() {
    const data = await api('settings');
    if (!data) return;

    if (data.gamemode) $('#set-gamemode').value = data.gamemode;
    if (data.difficulty) $('#set-difficulty').value = data.difficulty;

    const cheatsOn = data['allow-cheats'] === 'true';
    $('#set-cheats').checked = cheatsOn;
    $('#cheats-label').textContent = cheatsOn ? 'ON' : 'OFF';

    if (data['max-players']) $('#set-max-players').value = data['max-players'];
}

async function saveSettings() {
    const payload = {
        'gamemode': $('#set-gamemode').value,
        'difficulty': $('#set-difficulty').value,
        'allow-cheats': $('#set-cheats').checked ? 'true' : 'false',
        'max-players': parseInt($('#set-max-players').value, 10) || 10,
    };
    toast('Applying settings & restarting...', 'info');
    const result = await apiPost('settings', payload);
    if (result && result.success) {
        toast('Settings saved! Server restarting...', 'success');
        setTimeout(refreshAll, 5000);
    } else {
        toast(result?.error || 'Failed to save settings', 'error');
    }
}

async function quickAction(cmd) {
    toast(`Running: ${cmd}`, 'info');
    const result = await apiPost('command', { command: cmd });
    if (result && !result.error) {
        toast('Command sent!', 'success');
    } else {
        toast('Command failed', 'error');
    }
}

// ---------- How to Join / Setup Check ----------

async function updateSetup() {
    const data = await api('setup');
    if (!data) return;

    $$('.host-ip').forEach(el => { el.textContent = data.host_ip || 'unknown'; });

    const ready = $('#join-ready');
    ready.textContent = data.ready ? 'Ready for players' : 'Needs attention';
    ready.className = `join-ready ${data.ready ? 'ok' : 'bad'}`;

    $('#setup-checks').innerHTML = data.checks.map(c => `
        <li class="setup-check ${c.ok ? 'ok' : 'bad'}">
            <span class="check-mark">${c.ok ? '&#10004;' : '&#10008;'}</span>
            <span>${escapeHtml(c.label)}</span>
            ${c.ok ? '' : `<span class="check-detail">${escapeHtml(c.detail)}</span>`}
        </li>`).join('');

    // Something is broken: make sure the panel explaining it is visible
    if (!data.ready) setJoinCollapsed(false, false);
}

function setJoinCollapsed(collapsed, remember = true) {
    $('#join-panel').classList.toggle('collapsed', collapsed);
    $('#join-toggle').setAttribute('aria-expanded', String(!collapsed));
    if (remember) {
        try { localStorage.setItem('joinCollapsed', collapsed ? '1' : '0'); } catch (e) { /* private mode */ }
    }
}

function initJoinPanel() {
    let collapsed = false;
    try { collapsed = localStorage.getItem('joinCollapsed') === '1'; } catch (e) { /* private mode */ }
    setJoinCollapsed(collapsed, false);

    $('#join-toggle').addEventListener('click', () => {
        setJoinCollapsed(!$('#join-panel').classList.contains('collapsed'));
    });

    $$('.join-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const which = tab.dataset.console;
            $$('.join-tab').forEach(t => t.classList.toggle('active', t === tab));
            $$('.join-steps[data-console]').forEach(list => { list.hidden = list.dataset.console !== which; });
            // Phones and PCs connect straight to the server, no Featured Server trick
            $('#join-then').hidden = which === 'other';
        });
    });
}

// ---------- Main Loop ----------

async function refreshAll() {
    await Promise.all([
        updateStatus(),
        updateStats(),
        updatePlayers(),
        updateHistory(),
        updateLogs(),
    ]);
}

document.addEventListener('DOMContentLoaded', () => {
    initChart();
    initJoinPanel();
    refreshAll();
    setInterval(refreshAll, REFRESH_INTERVAL);
    updateSetup();
    setInterval(updateSetup, SETUP_INTERVAL);

    // Button handlers
    $('#btn-start')?.addEventListener('click', () => serverAction('start'));
    $('#btn-stop')?.addEventListener('click', () => serverAction('stop'));
    $('#btn-restart')?.addEventListener('click', () => serverAction('restart'));

    // Console input
    $('#console-input')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendCommand();
    });

    // Settings
    loadSettings();
    $('#btn-apply-settings')?.addEventListener('click', saveSettings);
    $('#set-cheats')?.addEventListener('change', (e) => {
        $('#cheats-label').textContent = e.target.checked ? 'ON' : 'OFF';
    });

    // Quick actions
    $$('.qa-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const cmd = btn.dataset.cmd;
            if (cmd) quickAction(cmd);
        });
    });
});
