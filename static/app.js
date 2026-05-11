/* ============================================================
   LangGraph Agent Lab — Dashboard App
   Vanilla JS application with Chart.js & Mermaid integration
   ============================================================ */

const API = '';
let allResults = [];
let scenariosList = [];
let routeChart = null;
let latencyChart = null;
let pendingHitl = null;

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
    loadScenarios();
    loadDiagram();
    initCharts();
});

// ---- Scenarios ----
async function loadScenarios() {
    try {
        const res = await fetch(`${API}/api/scenarios`);
        scenariosList = await res.json();
        const select = document.getElementById('scenarioSelect');
        select.innerHTML = '<option value="">— Select a scenario —</option>';
        scenariosList.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = `${s.id} — "${s.query}" [${s.expected_route}]`;
            select.appendChild(opt);
        });
    } catch (e) {
        showToast('Failed to load scenarios: ' + e.message, 'error');
    }
}

// ---- Run Single ----
async function runSelected() {
    const scenarioId = document.getElementById('scenarioSelect').value;
    if (!scenarioId) { showToast('Select a scenario first', 'info'); return; }
    await runScenario({ scenario_id: scenarioId });
}

async function runCustom() {
    const query = document.getElementById('customQuery').value.trim();
    if (!query) { showToast('Enter a query first', 'info'); return; }
    await runScenario({ query, scenario_id: 'custom_' + Date.now() });
}

async function runScenario(body) {
    setStatus('running', 'Running...');
    const btn = document.getElementById('btnRun');
    btn.disabled = true;

    try {
        const res = await fetch(`${API}/api/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Run failed');

        if (data.status === 'interrupted') {
            pendingHitl = { thread_id: data.thread_id, scenario_id: data.scenario_id };
            document.getElementById('hitlMessage').textContent = data.message || "Risky action requires human approval before proceeding.";
            document.getElementById('hitlModal').style.display = 'flex';
            setStatus('ready', 'Waiting for human approval...');
            return; // Wait for submitHitl
        }

        renderSingleResult(data);
        animateFlow(data.state);
        addToThreadSelect(data.state.thread_id);
        showToast(`${data.scenario_id}: ${data.metric.success ? '✅ PASS' : '❌ FAIL'}`, data.metric.success ? 'success' : 'error');
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    } finally {
        if (!pendingHitl) {
            btn.disabled = false;
            setStatus('ready', 'Ready');
        }
    }
}

// ---- HITL Resume ----
async function submitHitl(approved) {
    if (!pendingHitl) return;
    document.getElementById('hitlModal').style.display = 'none';
    setStatus('running', 'Resuming...');
    
    try {
        const res = await fetch(`${API}/api/resume`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: pendingHitl.thread_id,
                scenario_id: pendingHitl.scenario_id,
                approved: approved
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Resume failed');

        renderSingleResult(data);
        animateFlow(data.state);
        addToThreadSelect(data.state.thread_id);
        showToast(`Resumed. ${data.scenario_id}: ${data.metric.success ? '✅ PASS' : '❌ FAIL'}`, data.metric.success ? 'success' : 'error');
    } catch (e) {
        showToast('Error resuming: ' + e.message, 'error');
    } finally {
        pendingHitl = null;
        document.getElementById('btnRun').disabled = false;
        setStatus('ready', 'Ready');
    }
}

// ---- Run All ----
async function runAllScenarios() {
    setStatus('running', 'Running all scenarios...');
    const btn = document.getElementById('btnRunAll');
    btn.disabled = true;

    try {
        const res = await fetch(`${API}/api/run-all`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Run failed');

        allResults = data.results;
        updateStats(data.report);
        renderResultsTable(data.results);
        updateCharts(data.report);

        // Add all threads
        data.results.forEach(r => addToThreadSelect(r.state.thread_id));

        const passed = data.report.scenario_metrics.filter(m => m.success).length;
        const total = data.report.total_scenarios;
        showToast(`All scenarios complete: ${passed}/${total} passed (${(data.report.success_rate * 100).toFixed(0)}%)`, passed === total ? 'success' : 'error');
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        setStatus('ready', 'Ready');
    }
}

// ---- Render Single Result ----
function renderSingleResult(data) {
    const container = document.getElementById('scenarioResults');
    const m = data.metric;
    const s = data.state;
    const card = document.createElement('div');
    card.className = `result-card ${m.success ? 'success' : 'failure'}`;
    card.innerHTML = `
        <div class="result-header">
            <span class="result-id">${m.scenario_id}</span>
            <span class="result-badge ${m.success ? 'pass' : 'fail'}">${m.success ? 'PASS' : 'FAIL'}</span>
        </div>
        <div class="result-route">
            <span class="route-tag route-${m.expected_route}">${m.expected_route}</span>
            → <span class="route-tag route-${m.actual_route || 'unknown'}">${m.actual_route || '?'}</span>
            ${m.expected_route === m.actual_route ? '✅' : '❌'}
        </div>
        <div class="result-meta">
            <span>🔄 ${m.retry_count} retries</span>
            <span>👤 ${m.interrupt_count} HITL</span>
            <span>📊 ${m.nodes_visited} nodes</span>
            <span>⏱ ${data.latency_ms}ms</span>
        </div>
        ${s.final_answer ? `<div style="margin-top:8px;font-size:0.75rem;color:var(--text-muted);font-family:var(--font-mono);word-break:break-all;">${truncate(s.final_answer, 200)}</div>` : ''}
    `;

    // Remove empty state
    const empty = container.querySelector('.empty-state');
    if (empty) empty.remove();

    container.prepend(card);

    // Keep max 10 cards
    while (container.children.length > 10) {
        container.removeChild(container.lastChild);
    }
}

// ---- Render Results Table ----
function renderResultsTable(results) {
    const tbody = document.getElementById('resultsBody');
    if (!results.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-cell">No results yet</td></tr>';
        return;
    }

    tbody.innerHTML = results.map(r => {
        const m = r.metric;
        const scenario = scenariosList.find(s => s.id === m.scenario_id);
        const query = scenario ? scenario.query : m.scenario_id;
        return `
            <tr>
                <td><strong>${m.scenario_id}</strong></td>
                <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(query)}">${escHtml(truncate(query, 40))}</td>
                <td><span class="route-tag route-${m.expected_route}">${m.expected_route}</span></td>
                <td><span class="route-tag route-${m.actual_route}">${m.actual_route}</span></td>
                <td>${m.success ? '✅' : '❌'}</td>
                <td>${m.retry_count}</td>
                <td>${m.interrupt_count}</td>
                <td>${m.latency_ms}ms</td>
            </tr>
        `;
    }).join('');
}

// ---- Stats ----
function updateStats(report) {
    document.getElementById('statTotal').textContent = report.total_scenarios;
    document.getElementById('statSuccess').textContent = (report.success_rate * 100).toFixed(0) + '%';
    document.getElementById('statRetries').textContent = report.total_retries;
    document.getElementById('statInterrupts').textContent = report.total_interrupts;
    document.getElementById('statNodes').textContent = report.avg_nodes_visited.toFixed(1);
}

// ---- Charts ----
function initCharts() {
    const defaults = Chart.defaults;
    defaults.color = '#94a3b8';
    defaults.borderColor = 'rgba(99, 102, 241, 0.1)';
    defaults.font.family = "'Inter', sans-serif";

    routeChart = new Chart(document.getElementById('routeChart'), {
        type: 'doughnut',
        data: {
            labels: ['simple', 'tool', 'missing_info', 'risky', 'error'],
            datasets: [{
                data: [0, 0, 0, 0, 0],
                backgroundColor: [
                    'rgba(96, 165, 250, 0.7)',
                    'rgba(34, 211, 238, 0.7)',
                    'rgba(251, 191, 36, 0.7)',
                    'rgba(248, 113, 113, 0.7)',
                    'rgba(167, 139, 250, 0.7)',
                ],
                borderWidth: 0,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { padding: 12, usePointStyle: true, pointStyleWidth: 8 } },
                title: { display: true, text: 'Route Distribution', padding: { bottom: 8 } },
            },
        },
    });

    latencyChart = new Chart(document.getElementById('latencyChart'), {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'Latency (ms)',
                data: [],
                backgroundColor: 'rgba(129, 140, 248, 0.5)',
                borderColor: 'rgba(129, 140, 248, 0.8)',
                borderWidth: 1,
                borderRadius: 4,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                title: { display: true, text: 'Latency per Scenario', padding: { bottom: 8 } },
            },
            scales: {
                x: { ticks: { maxRotation: 45, font: { size: 9 } } },
                y: { beginAtZero: true, ticks: { callback: v => v + 'ms' } },
            },
        },
    });
}

function updateCharts(report) {
    if (!report || !report.scenario_metrics) return;

    // Route distribution
    const routeCounts = { simple: 0, tool: 0, missing_info: 0, risky: 0, error: 0 };
    report.scenario_metrics.forEach(m => {
        if (routeCounts[m.actual_route] !== undefined) routeCounts[m.actual_route]++;
    });
    routeChart.data.datasets[0].data = Object.values(routeCounts);
    routeChart.update('none');

    // Latency chart
    latencyChart.data.labels = report.scenario_metrics.map(m => m.scenario_id.replace('S', '').replace('_', '\n'));
    latencyChart.data.datasets[0].data = report.scenario_metrics.map(m => m.latency_ms);
    // Color bars by success
    latencyChart.data.datasets[0].backgroundColor = report.scenario_metrics.map(m =>
        m.success ? 'rgba(52, 211, 153, 0.5)' : 'rgba(248, 113, 113, 0.5)'
    );
    latencyChart.data.datasets[0].borderColor = report.scenario_metrics.map(m =>
        m.success ? 'rgba(52, 211, 153, 0.8)' : 'rgba(248, 113, 113, 0.8)'
    );
    latencyChart.update('none');
}

// ---- Graph Diagram ----
const CUSTOM_MERMAID = `graph TD
    START(["⬤ START"]):::startEnd --> intake["🔽 intake\\nNormalize & sanitize query"]
    intake --> classify["🧠 classify\\nKeyword priority routing"]

    classify -->|"route = simple"| answer["💬 answer\\nGenerate response"]
    classify -->|"route = tool"| tool["🔧 tool\\nExecute mock API call"]
    classify -->|"route = missing_info"| clarify["❓ clarify\\nAsk for more details"]
    classify -->|"route = risky"| risky_action["⚠️ risky_action\\nPrepare for approval"]
    classify -->|"route = error"| retry["🔄 retry\\nIncrement attempt counter"]

    tool --> evaluate["✅ evaluate\\nCheck tool result"]
    evaluate -->|"success"| answer
    evaluate -->|"needs_retry"| retry

    clarify --> finalize["🏁 finalize\\nEmit audit event"]

    risky_action --> approval["👤 approval\\nHITL: Human decides"]
    approval -->|"approved ✓"| tool
    approval -->|"rejected ✗"| clarify

    retry -->|"attempt < max"| tool
    retry -->|"attempt ≥ max"| dead_letter["📮 dead_letter\\nEscalate for manual review"]

    answer --> finalize
    dead_letter --> finalize
    finalize --> END(["⬤ END"]):::startEnd

    classDef startEnd fill:#0ea5e9,stroke:#0284c7,color:#fff,font-weight:bold,rx:20
    classDef default fill:#1e1b4b,stroke:#818cf8,color:#e2e8f0,rx:8,font-size:14px
`;

async function loadDiagram() {
    try {
        const container = document.getElementById('mermaidDiagram');
        mermaid.initialize({
            startOnLoad: false,
            theme: 'dark',
            flowchart: {
                useMaxWidth: true,
                htmlLabels: true,
                curve: 'basis',
                rankSpacing: 70,
                nodeSpacing: 50,
                padding: 20,
                defaultRenderer: 'dagre-wrapper',
            },
            themeVariables: {
                darkMode: true,
                background: '#0a0c14',
                primaryColor: '#1e1b4b',
                primaryBorderColor: '#818cf8',
                primaryTextColor: '#e2e8f0',
                lineColor: '#6366f1',
                secondaryColor: '#1a1a2e',
                tertiaryColor: '#0d0f17',
                fontSize: '15px',
                fontFamily: "'Inter', sans-serif",
                edgeLabelBackground: '#1a1a2e',
            },
        });
        const { svg } = await mermaid.render('graphSvg', CUSTOM_MERMAID);
        container.innerHTML = svg;

        // Ensure SVG fills container nicely
        const svgEl = container.querySelector('svg');
        if (svgEl) {
            svgEl.style.width = '100%';
            svgEl.style.minHeight = '400px';
            svgEl.removeAttribute('height');
        }
    } catch (e) {
        console.log('Diagram render error:', e.message);
        // Fallback: try API-generated diagram
        try {
            const res = await fetch(`${API}/api/graph-diagram`);
            if (res.ok) {
                const data = await res.json();
                const container = document.getElementById('mermaidDiagram');
                const { svg } = await mermaid.render('graphSvgFallback', data.mermaid);
                container.innerHTML = svg;
            }
        } catch (e2) {
            console.log('Fallback diagram also failed:', e2.message);
        }
    }
}

// ---- Flow Animation ----
function animateFlow(state) {
    const events = state.events || [];
    const nodes = events.map(e => e.node);
    const route = state.route || '?';

    // Update route display
    const flowRoute = document.getElementById('flowRoute');
    flowRoute.textContent = route;
    flowRoute.className = `flow-node route-${route}`;

    // Determine process nodes
    const processNodes = nodes.filter(n => !['intake', 'classify', 'finalize'].includes(n));
    const flowProcess = document.getElementById('flowProcess');
    flowProcess.textContent = processNodes.join(' → ') || '—';

    // Animate flow nodes
    const allFlowNodes = document.querySelectorAll('.flow-node');
    allFlowNodes.forEach(n => n.classList.remove('active', 'done', 'error-node'));

    let i = 0;
    const animate = () => {
        if (i > 0) {
            allFlowNodes.forEach(n => {
                if (n.dataset.node) n.classList.add('done');
            });
        }
        if (i < allFlowNodes.length) {
            allFlowNodes[i].classList.add('active');
            allFlowNodes[i].classList.remove('done');
            i++;
            setTimeout(animate, 300);
        }
    };
    animate();
}

// ---- State History / Time Travel ----
function addToThreadSelect(threadId) {
    const select = document.getElementById('threadSelect');
    if ([...select.options].some(o => o.value === threadId)) return;
    const opt = document.createElement('option');
    opt.value = threadId;
    opt.textContent = threadId;
    select.appendChild(opt);
}

async function loadStateHistory() {
    const threadId = document.getElementById('threadSelect').value;
    if (!threadId) return;

    try {
        const res = await fetch(`${API}/api/state-history/${threadId}`);
        const history = await res.json();

        const timeline = document.getElementById('stateTimeline');
        if (!history.length) {
            timeline.innerHTML = '<div class="empty-state"><p>No history found</p></div>';
            return;
        }

        timeline.innerHTML = history.map((h, i) => `
            <div class="timeline-item" onclick="showState(${i}, '${threadId}')">
                <span class="timeline-step">${i}</span>
                <span>Step ${i}</span>
                <span class="timeline-next">${h.next.length ? '→ ' + h.next.join(', ') : '(end)'}</span>
            </div>
        `).join('');

        // Show first state
        showState(0, threadId);

        window._stateHistory = history;
    } catch (e) {
        showToast('Failed to load state history: ' + e.message, 'error');
    }
}

function showState(index, threadId) {
    if (!window._stateHistory) return;
    const h = window._stateHistory[index];
    if (!h) return;

    // Highlight selected
    document.querySelectorAll('.timeline-item').forEach((el, i) => {
        el.classList.toggle('selected', i === index);
    });

    const json = document.getElementById('stateJson');
    json.textContent = JSON.stringify(h.values, null, 2);
}

// ---- Crash Resume ----
async function testCrashResume() {
    const btn = document.getElementById('btnCrashResume');
    btn.disabled = true;
    setStatus('running', 'Testing crash-resume...');

    try {
        const res = await fetch(`${API}/api/crash-resume`, { method: 'POST' });
        const data = await res.json();

        const result = document.getElementById('persistResult');
        result.innerHTML = `
            <div class="persist-card ${data.success ? 'success' : 'failure'}">
                <strong>${data.success ? '✅ Crash-Resume Verified' : '❌ Crash-Resume Failed'}</strong>
                <p style="margin-top:8px;font-size:0.8rem;color:var(--text-secondary)">${data.message}</p>
                ${data.success ? `
                    <div style="margin-top:8px;font-size:0.75rem;">
                        <div><strong>Original answer:</strong> ${truncate(data.original_answer || '', 100)}</div>
                        <div><strong>Recovered answer:</strong> ${truncate(data.recovered_answer || '', 100)}</div>
                        <div><strong>State matches:</strong> ${data.state_matches ? '✅ Yes' : '❌ No'}</div>
                    </div>
                ` : ''}
            </div>
        `;

        showToast(data.success ? 'Crash-resume test passed!' : 'Crash-resume test failed', data.success ? 'success' : 'error');
    } catch (e) {
        showToast('Error: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        setStatus('ready', 'Ready');
    }
}

// ---- Helpers ----
function setStatus(state, text) {
    const indicator = document.getElementById('statusIndicator');
    indicator.className = `status-indicator ${state}`;
    indicator.querySelector('span').textContent = text;
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

function truncate(str, max) {
    if (!str) return '';
    return str.length > max ? str.slice(0, max) + '...' : str;
}

function escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
