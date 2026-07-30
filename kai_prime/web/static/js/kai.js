/* Kai Prime — Frontend Controller */
(function() {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  // Tab navigation
  $$('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.nav-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      $$('.tab-content').forEach(t => t.classList.remove('active'));
      const tab = $(`#tab-${btn.dataset.tab}`);
      if (tab) tab.classList.add('active');
      if (btn.dataset.tab === 'network') loadDevices();
      if (btn.dataset.tab === 'tools') loadTools();
      if (btn.dataset.tab === 'settings') loadSettings();
      if (btn.dataset.tab === 'security') loadSecurity();
      if (btn.dataset.tab === 'dashboard') loadDashboard();
      if (btn.dataset.tab === 'life') loadLife();
    });
  });

  // Chat
  const chatInput = $('#chatInput');
  const chatMessages = $('#chatMessages');
  const chatSend = $('#chatSend');

  function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.textContent = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
  }

  async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    addMessage(text, 'user');
    chatInput.value = '';
    chatInput.style.height = 'auto';

    chatSend.disabled = true;
    chatInput.disabled = true;
    const thinking = addMessage('Thinking', 'system');
    thinking.classList.add('thinking');

    try {
      const t0 = performance.now();
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 60000);
      const resp = await fetch('/api/ask', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text}),
        signal: controller.signal
      });
      const t1 = performance.now();
      clearTimeout(timeout);
      const data = await resp.json();
      const t2 = performance.now();
      thinking.remove();
      console.log(`[Kai] fetch: ${(t1-t0).toFixed(0)}ms, json: ${(t2-t1).toFixed(0)}ms, total: ${(t2-t0).toFixed(0)}ms`);
      if (data.response) {
        addMessage(data.response, 'assistant');
      } else if (data.error) {
        addMessage(`Error: ${data.error}`, 'system');
      }
    } catch(e) {
      thinking.remove();
      if (e.name === 'AbortError') {
        addMessage('Request timed out. The LLM may be down.', 'system');
      } else {
        addMessage(`Connection error: ${e.message}`, 'system');
      }
    } finally {
      chatSend.disabled = false;
      chatInput.disabled = false;
      chatInput.focus();
    }
  }

  chatSend.addEventListener('click', sendMessage);
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + 'px';
  });

  // SSE stream — only active during chat requests
  let eventSource = null;
  let sseTimeout = null;

  function startSSE() {
    if (eventSource) { eventSource.close(); }
    eventSource = new EventSource('/api/stream');
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'tool_call' || data.type === 'tool_result') {
          addMessage(data.msg, 'system');
        }
      } catch(err) {}
    };
    eventSource.onerror = () => {
      if (eventSource) eventSource.close();
      eventSource = null;
    };
    if (sseTimeout) clearTimeout(sseTimeout);
    sseTimeout = setTimeout(() => {
      if (eventSource) eventSource.close();
      eventSource = null;
    }, 20000);
  }

  function stopSSE() {
    if (sseTimeout) { clearTimeout(sseTimeout); sseTimeout = null; }
    if (eventSource) { eventSource.close(); eventSource = null; }
  }

  // Desktop — activity log and screenshots
  function logActivity(msg, type) {
    const log = $('#activityLog');
    if (!log) return;
    const div = document.createElement('div');
    div.className = `activity-item ${type || 'system'}`;
    const now = new Date().toLocaleTimeString();
    div.textContent = `[${now}] ${msg}`;
    log.insertBefore(div, log.firstChild);
    if (log.children.length > 50) log.removeChild(log.lastChild);
  }

  $('#screenshotBtn').addEventListener('click', async () => {
    const area = $('#screenshotArea');
    logActivity('Taking screenshot...', 'action');
    try {
      const resp = await fetch('/api/desktop/screenshot', {method: 'POST'});
      const data = await resp.json();
      if (data.result && data.result.includes('saved')) {
        const pathMatch = data.result.match(/saved to (.+)/);
        if (pathMatch) {
          area.innerHTML = `<img src="/api/screenshots/${encodeURIComponent(pathMatch[1])}" alt="Screenshot" style="max-width:100%;border-radius:8px;">`;
          logActivity('Screenshot captured', 'result');
        } else {
          area.innerHTML = `<div class="placeholder-text">${data.result}</div>`;
        }
      } else {
        area.innerHTML = `<div class="placeholder-text">${data.result || 'Failed'}</div>`;
        logActivity('Screenshot failed', 'error');
      }
    } catch(e) {
      area.innerHTML = `<div class="placeholder-text">Error: ${e.message}</div>`;
      logActivity(`Screenshot error: ${e.message}`, 'error');
    }
  });

  $('#activeWindowBtn').addEventListener('click', async () => {
    logActivity('Checking active window...', 'action');
    try {
      const resp = await fetch('/api/tools/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tool: 'run_command', args: {command: 'powershell -command "(Get-Process | Where-Object {$_.MainWindowTitle}).MainWindowTitle | Select-Object -First 5 | ConvertTo-Json"'}})
      });
      const data = await resp.json();
      logActivity(`Active window: ${data.result || data.error || 'unknown'}`, 'result');
    } catch(e) {
      logActivity(`Error: ${e.message}`, 'error');
    }
  });

  $('#processesBtn').addEventListener('click', async () => {
    logActivity('Listing top processes...', 'action');
    try {
      const resp = await fetch('/api/tools/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tool: 'run_command', args: {command: 'powershell -command "Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name,CPU,WorkingSet | Format-Table -AutoSize"'}})
      });
      const data = await resp.json();
      logActivity(`Top processes:\n${data.result || data.error || 'unknown'}`, 'result');
    } catch(e) {
      logActivity(`Error: ${e.message}`, 'error');
    }
  });

  // Network — scan, fingerprint, gateway
  async function loadDevices() {
    try {
      const resp = await fetch('/api/network/devices');
      const data = await resp.json();
      const list = $('#deviceList');
      if (data.devices && data.devices.length > 0) {
        list.innerHTML = data.devices.map(d => `
          <div class="device-card">
            <div>
              <div class="device-ip">${d.ip}</div>
              <div class="device-vendor">${d.vendor || 'Unknown'} ${d.hostname ? '/ ' + d.hostname : ''}</div>
            </div>
            <div class="device-ports">${(d.ports || []).map(p => (p.port || p) + (p.service ? '/' + p.service : '')).join(', ')}</div>
          </div>
        `).join('');
      } else {
        list.innerHTML = '<div class="placeholder-text">No devices found. Click Scan.</div>';
      }
    } catch(e) {}
  }

  function appendNetOutput(msg) {
    const out = $('#netOutput');
    if (!out) return;
    const now = new Date().toLocaleTimeString();
    out.textContent += `\n[${now}] ${msg}`;
    out.scrollTop = out.scrollHeight;
  }

  $('#netScanBtn').addEventListener('click', async () => {
    $('#netStatus').textContent = 'Scanning...';
    $('#netOutput').textContent = 'Starting scan...';
    appendNetOutput('Sending scan request...');
    await fetch('/api/network/scan', {method: 'POST'});
    const poll = setInterval(async () => {
      const resp = await fetch('/api/network/status');
      const data = await resp.json();
      if (data.done) {
        clearInterval(poll);
        $('#netStatus').textContent = `Scan complete. ${data.count || 0} devices found.`;
        appendNetOutput(`Scan complete. ${data.count || 0} devices found.`);
        loadDevices();
      } else if (data.running) {
        $('#netStatus').textContent = `Scanning... ${data.count || 0} found.`;
      }
    }, 2000);
  });

  $('#netFingerprintBtn').addEventListener('click', async () => {
    appendNetOutput('Fingerprinting all devices...');
    try {
      const resp = await fetch('/api/network/devices');
      const data = await resp.json();
      for (const d of (data.devices || [])) {
        appendNetOutput(`${d.ip}: ${d.vendor || 'Unknown'} ${(d.ports || []).map(p => p.port || p).join(',') || 'no open ports'}`);
      }
      appendNetOutput('Fingerprint complete.');
    } catch(e) {
      appendNetOutput(`Error: ${e.message}`);
    }
  });

  $('#netGatewayBtn').addEventListener('click', async () => {
    appendNetOutput('Scanning gateway...');
    try {
      const resp = await fetch('/api/tools/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tool: 'run_command', args: {command: 'arp -a'}})
      });
      const data = await resp.json();
      appendNetOutput(`ARP table:\n${data.result || data.error}`);
    } catch(e) {
      appendNetOutput(`Error: ${e.message}`);
    }
  });

  // Tools — with input fields per tool
  const TOOL_INPUTS = {
    web_search: {label: 'Search query', placeholder: 'e.g. python websocket tutorial'},
    run_command: {label: 'Command', placeholder: 'e.g. ipconfig /all'},
    read_file: {label: 'File path', placeholder: 'e.g. C:\\Users\\file.txt'},
    write_file: {label: 'File path', placeholder: 'e.g. C:\\Users\\file.txt'},
    list_files: {label: 'Directory', placeholder: 'e.g. C:\\Users'},
    browse_url: {label: 'URL', placeholder: 'e.g. https://example.com'},
    click_at: {label: 'X, Y', placeholder: 'e.g. 500, 300'},
    type_text: {label: 'Text', placeholder: 'Text to type...'},
    open_browser: {label: 'URL', placeholder: 'e.g. https://chess.com'},
    open_app: {label: 'App name or path', placeholder: 'e.g. notepad or C:\\Program Files\\Mozilla Firefox\\firefox.exe'},
  };

  const WRITE_FILE_EXTRA = 'write_file_content';
  let currentTool = null;

  async function loadTools() {
    try {
      const resp = await fetch('/api/tools/list');
      const data = await resp.json();
      const grid = $('#toolGrid');
      if (data.tools) {
        grid.innerHTML = data.tools.map(t => `
          <div class="tool-card" data-tool="${t.name}">
            <div class="tool-name">${t.name}</div>
            <div class="tool-desc">${t.description}</div>
          </div>
        `).join('');
        grid.querySelectorAll('.tool-card').forEach(card => {
          card.addEventListener('click', () => selectTool(card.dataset.tool));
        });
      }
    } catch(e) {}
  }

  function selectTool(name) {
    currentTool = name;
    $$('.tool-card').forEach(c => c.classList.toggle('active', c.dataset.tool === name));
    const output = $('#toolOutput');
    const info = TOOL_INPUTS[name];
    let html = '';
    if (info) {
      html += `<div class="tool-input-row">
        <label>${info.label}</label>
        <input type="text" id="toolArgInput" class="ctrl-input wide" placeholder="${info.placeholder}">
      </div>`;
      if (name === 'write_file') {
        html += `<div class="tool-input-row">
          <label>Content</label>
          <textarea id="toolArgContent" class="ctrl-input wide" rows="6" placeholder="File content..."></textarea>
        </div>`;
      }
      html += `<button class="action-btn" id="toolRunBtn">Run ${name}</button>`;
    } else {
      html += `<button class="action-btn" id="toolRunBtn">Run ${name}</button>`;
    }
    output.innerHTML = html;
    $('#toolRunBtn').addEventListener('click', () => runCurrentTool());
    const inp = $('#toolArgInput');
    if (inp) inp.focus();
  }

  async function runCurrentTool() {
    if (!currentTool) return;
    const output = $('#toolOutput');
    const runBtn = $('#toolRunBtn');
    if (runBtn) { runBtn.textContent = 'Running...'; runBtn.disabled = true; }

    let args = {};
    const raw = ($('#toolArgInput') || {}).value || '';
    const info = TOOL_INPUTS[currentTool] || {};

    if (currentTool === 'killchain') {
      args = {target_ip: raw.trim()};
    } else if (currentTool === 'click_at') {
      const parts = raw.split(/[,\s]+/);
      args = {x: parseInt(parts[0]) || 0, y: parseInt(parts[1]) || 0};
    } else if (currentTool === 'write_file') {
      args = {path: raw.trim(), content: ($('#toolArgContent') || {}).value || ''};
    } else if (raw.trim()) {
      const param = info.label ? info.label.toLowerCase().replace(/\s+/g, '_') : 'arg';
      const paramMap = {
        'search_query': 'query', 'file_path': 'path', 'directory': 'path',
        'url': 'url', 'x,_y': 'x', 'text': 'text', 'target_ip': 'target_ip',
        'app_name_or_path': 'app',
      };
      const p = paramMap[param] || param;
      if (p === 'x') {
        const parts = raw.split(/[,\s]+/);
        args = {x: parseInt(parts[0]) || 0, y: parseInt(parts[1]) || 0};
      } else {
        args[p] = raw.trim();
      }
    }

    try {
      const resp = await fetch('/api/tools/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tool: currentTool, args})
      });
      const data = await resp.json();
      const resultText = data.result || data.error || 'No output';
      output.innerHTML += `<div class="tool-result">${typeof resultText === 'string' ? resultText : JSON.stringify(resultText, null, 2)}</div>`;
    } catch(e) {
      output.innerHTML += `<div class="tool-result error">Error: ${e.message}</div>`;
    }
    if (runBtn) { runBtn.textContent = `Run ${currentTool}`; runBtn.disabled = false; }
  }

  // Settings
  async function loadSettings() {
    try {
      const resp = await fetch('/api/supervisor/status');
      const data = await resp.json();
      const toggle = $('#supervisorToggle');
      toggle.textContent = data.active ? 'ACTIVE' : 'INACTIVE';
      toggle.classList.toggle('off', !data.active);
    } catch(e) {}

    try {
      const resp = await fetch('/api/state');
      const data = await resp.json();
      const list = $('#providerList');
      if (data.tools_registered) {
        list.innerHTML = data.tools_registered.map(t => `<span class="provider-badge">${t}</span>`).join('');
      }
    } catch(e) {}
  }

  $('#supervisorToggle').addEventListener('click', async () => {
    await fetch('/api/supervisor/toggle', {method: 'POST'});
    loadSettings();
  });

  // Initial state check
  fetch('/api/state').then(r => r.json()).then(data => {
    if (data.supervisor_active !== undefined) {
      $('#statusText').textContent = 'ONLINE';
    }
  }).catch(() => {
    $('#statusText').textContent = 'OFFLINE';
    $('#statusDot').style.background = 'var(--neon-red)';
  });

  // Security tab
  async function loadSecurity() {
    try {
      const resp = await fetch('/api/security/bouncer');
      const data = await resp.json();
      $('#bouncerStatus').innerHTML = `Known devices: <strong>${data.known_devices || 0}</strong> | Alerts: <strong>${data.total_alerts || 0}</strong> | Spoof: <strong>${data.spoof_alerts || 0}</strong>`;
    } catch(e) {
      $('#bouncerStatus').textContent = 'Bouncer offline';
    }
    try {
      const resp = await fetch('/api/security/butler');
      const data = await resp.json();
      $('#butlerStatus').innerHTML = `Patterns: <strong>${(data.status || {}).patterns_learned || 0}</strong>`;
      if (data.routine && data.routine.length) {
        $('#butlerRoutine').innerHTML = data.routine.map(r => `<div class="sec-item">${r}</div>`).join('');
      }
    } catch(e) {
      $('#butlerStatus').textContent = 'Butler offline';
    }
  }

  $('#scanRunBtn').addEventListener('click', async () => {
    const path = $('#scanPath').value.trim();
    if (!path) return;
    const results = $('#scanResults');
    results.innerHTML = '<div class="placeholder-text">Scanning...</div>';
    try {
      const resp = await fetch('/api/security/scan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path})
      });
      const data = await resp.json();
      if (data.findings && data.findings.length > 0) {
        results.innerHTML = data.findings.map(f => `
          <div class="sec-finding ${f.severity}">
            <div class="sec-finding-title">${f.title} (${f.severity})</div>
            <div class="sec-finding-detail">${f.detail}</div>
            <div class="sec-finding-loc">${f.location}</div>
          </div>
        `).join('');
      } else if (data.error) {
        results.innerHTML = `<div class="placeholder-text">${data.error}</div>`;
      } else {
        results.innerHTML = '<div class="placeholder-text">No vulnerabilities found</div>';
      }
    } catch(e) {
      results.innerHTML = `<div class="placeholder-text">Error: ${e.message}</div>`;
    }
  });

  // Dashboard tab
  async function loadDashboard() {
    try {
      const resp = await fetch('/api/state');
      const data = await resp.json();
      const emotion = data.emotion || {};
      $('#dashEmotion').textContent = emotion.current || 'neutral';
      $('#dashEmotion').className = `dash-stat ${emotion.current || 'neutral'}`;
      $('#dashMoodHistory').textContent = `Mood: ${emotion.current || 'neutral'} (${(emotion.intensity * 100 || 0).toFixed(0)}%)`;
      $('#dashMemoryTurns').textContent = data.memory_turns || 0;
      $('#dashSemantic').textContent = `${data.semantic_facts || 0} facts`;
      $('#dashKnowledge').textContent = data.knowledge_entries || 0;
      $('#dashFts').textContent = `${data.fts5_count || 0} entries`;
      $('#dashTools').textContent = (data.tools_registered || []).length;
      $('#dashProviders').textContent = data.provider_chain_active ? 'Groq → DeepSeek → Ollama' : 'Local only';
      if (data.tools_registered) {
        $('#dashToolsList').innerHTML = data.tools_registered.map(t => `<span class="provider-badge">${t}</span>`).join('');
      }
    } catch(e) {
      $('#dashEmotion').textContent = 'Error';
    }
  }

  $('#dashRefreshBtn').addEventListener('click', loadDashboard);

  $('#dashMemoryBtn').addEventListener('click', async () => {
    $('#dashActionResultTitle').textContent = 'Memory State';
    $('#dashActionResult').textContent = 'Loading...';
    try {
      const resp = await fetch('/api/state');
      const data = await resp.json();
      const mem = `Turns in buffer: ${data.memory_turns}
Semantic facts: ${data.semantic_facts}
Knowledge entries: ${data.knowledge_entries}
FTS5 entries: ${data.fts5_count}
Entities tracked: ${data.entity_count}`;
      $('#dashActionResult').textContent = mem;
    } catch(e) {
      $('#dashActionResult').textContent = `Error: ${e.message}`;
    }
  });

  $('#dashHealthBtn').addEventListener('click', async () => {
    $('#dashActionResultTitle').textContent = 'System Health';
    $('#dashActionResult').textContent = 'Loading...';
    try {
      const resp = await fetch('/api/health');
      const data = await resp.json();
      const health = `Status: ${data.status}
Uptime: ${data.uptime?.toFixed(0) || 0}s
CPU: ${data.cpu_percent}%
Memory: ${data.memory_mb} MB
Tools: ${data.tools}
Sessions: ${data.session_count}
Crashes: ${data.crash_count}
Recovery mode: ${data.was_crash_recovery}`;
      $('#dashActionResult').textContent = health;
    } catch(e) {
      $('#dashActionResult').textContent = `Error: ${e.message}`;
    }
  });

  $('#dashStateBtn').addEventListener('click', async () => {
    $('#dashActionResultTitle').textContent = 'Full State';
    $('#dashActionResult').textContent = 'Loading...';
    try {
      const resp = await fetch('/api/state');
      const data = await resp.json();
      $('#dashActionResult').textContent = JSON.stringify(data, null, 2);
    } catch(e) {
      $('#dashActionResult').textContent = `Error: ${e.message}`;
    }
  });

  $('#dashWatcherBtn').addEventListener('click', async () => {
    $('#dashActionResultTitle').textContent = 'Watcher Events';
    $('#dashActionResult').textContent = 'Loading...';
    try {
      const resp = await fetch('/api/watcher/events');
      const data = await resp.json();
      const events = data.events || [];
      if (events.length === 0) {
        $('#dashActionResult').textContent = 'No events recorded yet.';
      } else {
        $('#dashActionResult').textContent = events.map(e => `[${e.type}] ${e.message}`).join('\n');
      }
    } catch(e) {
      $('#dashActionResult').textContent = `Error: ${e.message}`;
    }
  });

  // Life tab
  async function loadLife() {
    try {
      const resp = await fetch('/api/life/reminders');
      const data = await resp.json();
      const list = $('#remindersList');
      if (data.reminders && data.reminders.length > 0) {
        list.innerHTML = data.reminders.map(r => `
          <div class="life-item">
            <div class="life-item-text">${r.text}</div>
            <div class="life-item-meta">${r.remind_at ? 'at ' + r.remind_at : 'no time set'}</div>
          </div>
        `).join('');
      } else {
        list.innerHTML = '<div class="placeholder-text">No reminders</div>';
      }
    } catch(e) {
      $('#remindersList').innerHTML = '<div class="placeholder-text">Error loading</div>';
    }
    try {
      const resp = await fetch('/api/life/tasks');
      const data = await resp.json();
      const list = $('#tasksList');
      if (data.tasks && data.tasks.length > 0) {
        list.innerHTML = data.tasks.map(t => `
          <div class="life-item">
            <div class="life-item-text">${t.title}</div>
            <div class="life-item-meta priority-${t.priority}">${t.priority}</div>
          </div>
        `).join('');
      } else {
        list.innerHTML = '<div class="placeholder-text">No tasks</div>';
      }
    } catch(e) {
      $('#tasksList').innerHTML = '<div class="placeholder-text">Error loading</div>';
    }
  }

  $('#addReminderBtn').addEventListener('click', async () => {
    const text = $('#reminderInput').value.trim();
    const timeStr = $('#reminderTime').value.trim();
    if (!text) return;
    await fetch('/api/life/reminders/add', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, time_str: timeStr})
    });
    $('#reminderInput').value = '';
    $('#reminderTime').value = '';
    loadLife();
  });

  $('#addTaskBtn').addEventListener('click', async () => {
    const title = $('#taskInput').value.trim();
    const priority = $('#taskPriority').value;
    if (!title) return;
    await fetch('/api/life/tasks/add', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, priority})
    });
    $('#taskInput').value = '';
    loadLife();
  });

  window.chessWatch = async function(action) {
    const res = await fetch('/api/chess/watch', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action})
    });
    const data = await res.json();
    if (data.watching !== undefined) {
      $('#chessWatchStatus').textContent = data.watching ? 'Watching...' : 'Not watching';
      $('#chessStatus').textContent = data.watching ? 'ACTIVE' : 'STOPPED';
      $('#chessStatus').style.color = data.watching ? '#00ff88' : '#ff4444';
      $('#chessStartBtn').disabled = data.watching;
      $('#chessStopBtn').disabled = !data.watching;
    }
    if (data.result) {
      const log = $('#chessLog');
      const entry = document.createElement('div');
      entry.className = 'log-entry';
      entry.textContent = `[${new Date().toLocaleTimeString()}] ${data.result}`;
      log.appendChild(entry);
      log.scrollTop = log.scrollHeight;
    }
  };

  async function pollChess() {
    try {
      const res = await fetch('/api/chess/status');
      const data = await res.json();
      if (data.watching !== undefined) {
        $('#chessWatchStatus').textContent = data.watching ? 'Watching...' : 'Not watching';
        $('#chessMoveCount').textContent = data.moves_seen || 0;
        $('#chessLastAdvice').textContent = data.last_advice || 'none';
        $('#chessStartBtn').disabled = data.watching;
        $('#chessStopBtn').disabled = !data.watching;
      }
    } catch(e) {}
  }
  setInterval(pollChess, 5000);

})();
