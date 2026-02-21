// Dashboard Configuration
const CONFIG = {
    API_BASE: '',
    REFRESH_INTERVAL: 30000, // 30 seconds
    INITIAL_CAPITAL: 1000,
    TARGET_CAPITAL: 5000,
    CHART_MAX_POINTS: 100,
    get WS_URL() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${window.location.host}/ws/portfolio`;
    },
    WS_RECONNECT_INTERVAL: 5000 // 5 seconds
};

// State Management
let state = {
    portfolio: null,
    trades: [],
    performance: null,
    status: null,
    paused: false,
    chart: null,
    chartData: {
        timestamps: [],
        portfolioValues: []
    },
    lastError: null,
    websocket: null,
    wsConnected: false,
    wsReconnectAttempts: 0,
    // Phase 2 state
    phase2: {
        enabled: false,
        info: null,
        breakers: null,
        sentiment: null,
        fusion: null,
        executionStats: null
    },
    // Phase 3 state
    phase3: {
        enabled: false,
        regime: null,
        correlation: null,
        analystPerformance: null,
        alerting: null,
        anomaly: null
    },
    // Cost Optimization state
    costOptimization: {
        enabled: false,
        stats: null,
        config: null
    }
};

// Check if Chart.js is loaded
window.addEventListener('load', () => {
    console.log('Dashboard initializing...');
    if (typeof Chart === 'undefined') {
        console.error('CRITICAL: Chart.js library not loaded! CDN may be blocked.');
        showError('Chart library failed to load. Check network tab and browser console.');
    } else {
        console.log('✓ Chart.js library loaded successfully');
    }
});

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM Content Loaded - Starting dashboard setup');
    setupEventListeners();
    loadDashboard();
    setInterval(loadDashboard, CONFIG.REFRESH_INTERVAL);

    // Connect WebSocket for live updates
    connectWebSocket();
});

// Event Listeners
function setupEventListeners() {
    document.getElementById('refreshBtn').addEventListener('click', loadDashboard);
    document.getElementById('triggerBtn').addEventListener('click', triggerTradingCycle);
    document.getElementById('pauseBtn').addEventListener('click', pauseTrading);
    document.getElementById('resumeBtn').addEventListener('click', resumeTrading);
}

// WebSocket Connection Management
function connectWebSocket() {
    console.log('[WebSocket] Attempting to connect to', CONFIG.WS_URL);

    try {
        state.websocket = new WebSocket(CONFIG.WS_URL);

        state.websocket.onopen = () => {
            console.log('[WebSocket] Connected successfully');
            state.wsConnected = true;
            state.wsReconnectAttempts = 0;
            updateWebSocketStatus(true);
        };

        state.websocket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log('[WebSocket] Message received:', data);
                handleWebSocketMessage(data);
            } catch (error) {
                console.error('[WebSocket] Failed to parse message:', error);
            }
        };

        state.websocket.onerror = (error) => {
            console.error('[WebSocket] Error:', error);
            state.wsConnected = false;
            updateWebSocketStatus(false);
        };

        state.websocket.onclose = () => {
            console.log('[WebSocket] Connection closed');
            state.wsConnected = false;
            updateWebSocketStatus(false);

            // Attempt to reconnect
            state.wsReconnectAttempts++;
            const delay = Math.min(CONFIG.WS_RECONNECT_INTERVAL * state.wsReconnectAttempts, 30000);
            console.log(`[WebSocket] Reconnecting in ${delay / 1000}s (attempt ${state.wsReconnectAttempts})`);

            setTimeout(() => {
                if (!state.wsConnected) {
                    connectWebSocket();
                }
            }, delay);
        };

        // Keep connection alive with ping/pong
        setInterval(() => {
            if (state.websocket && state.websocket.readyState === WebSocket.OPEN) {
                state.websocket.send('ping');
            }
        }, 30000);

    } catch (error) {
        console.error('[WebSocket] Connection failed:', error);
        state.wsConnected = false;
        updateWebSocketStatus(false);
    }
}

function handleWebSocketMessage(data) {
    const msgType = data.type;

    if (msgType === 'connection') {
        console.log('[WebSocket] Connection established:', data.message);
        console.log('[WebSocket] Connection ID:', data.connection_id);

        // Handle initial portfolio state
        if (data.initial_portfolio) {
            const portfolio = data.initial_portfolio;
            console.log('[WebSocket] Initial portfolio value:', portfolio.total_value);

            // Add initial data point to chart
            updateLiveChartData(portfolio.total_value);
        }

    } else if (msgType === 'portfolio_update') {
        console.log('[WebSocket] Portfolio update received');
        console.log(`[WebSocket] Total Value: ${data.total_value} AUD`);
        console.log('[WebSocket] Holdings:', data.holdings);
        console.log('[WebSocket] Timestamp:', data.timestamp);

        // Update chart with new portfolio value
        updateLiveChartData(data.total_value, data.timestamp);

        // Update metrics display
        updatePortfolioMetricsFromWebSocket(data);

    } else {
        console.log('[WebSocket] Unknown message type:', data);
    }
}

function updateLiveChartData(portfolioValue, timestamp) {
    // Format timestamp
    let timeLabel;
    if (timestamp) {
        const date = new Date(timestamp);
        timeLabel = date.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } else {
        const now = new Date();
        timeLabel = now.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    // Add new data point
    state.chartData.timestamps.push(timeLabel);
    state.chartData.portfolioValues.push(portfolioValue);

    // Keep only last N points
    if (state.chartData.timestamps.length > CONFIG.CHART_MAX_POINTS) {
        state.chartData.timestamps.shift();
        state.chartData.portfolioValues.shift();
    }

    // Update chart if it exists
    if (state.chart) {
        state.chart.data.labels = state.chartData.timestamps;
        state.chart.data.datasets[0].data = state.chartData.portfolioValues;

        // Update reference lines
        state.chart.data.datasets[1].data = Array(state.chartData.timestamps.length).fill(CONFIG.INITIAL_CAPITAL);
        state.chart.data.datasets[2].data = Array(state.chartData.timestamps.length).fill(CONFIG.TARGET_CAPITAL);

        // Smooth animation
        state.chart.update('none'); // Use 'none' mode for instant update, or 'default' for animation
    }

    console.log(`[Chart] Updated with value ${portfolioValue} at ${timeLabel}`);
}

function updatePortfolioMetricsFromWebSocket(data) {
    // Update portfolio value metric card
    const totalValue = data.total_value || 0;
    document.getElementById('portfolioValue').textContent = formatCurrency(totalValue);

    const portfolioPercent = ((totalValue - CONFIG.INITIAL_CAPITAL) / CONFIG.INITIAL_CAPITAL) * 100;
    const percentElement = document.getElementById('portfolioPercent');
    percentElement.textContent = `${portfolioPercent >= 0 ? '+' : ''}${portfolioPercent.toFixed(2)}%`;
    percentElement.className = `metric-change ${portfolioPercent >= 0 ? 'positive' : 'negative'}`;

    // Update P&L
    const totalPnL = totalValue - CONFIG.INITIAL_CAPITAL;
    const pnlPercent = (totalPnL / CONFIG.INITIAL_CAPITAL) * 100;

    const pnlElement = document.getElementById('totalPnL');
    pnlElement.textContent = formatCurrency(totalPnL);
    pnlElement.className = totalPnL >= 0 ? 'metric-value positive' : 'metric-value negative';

    const pnlPercentElement = document.getElementById('totalPnLPercent');
    pnlPercentElement.textContent = `${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%`;
    pnlPercentElement.className = `metric-change ${pnlPercent >= 0 ? 'positive' : 'negative'}`;

    // Update target progress
    const progress = ((totalValue - CONFIG.INITIAL_CAPITAL) / (CONFIG.TARGET_CAPITAL - CONFIG.INITIAL_CAPITAL)) * 100;
    const cappedProgress = Math.min(progress, 100);
    document.getElementById('targetProgress').textContent = `${cappedProgress.toFixed(1)}%`;
}

function updateWebSocketStatus(connected) {
    // Only update the chart live/polling indicator — NOT the main connection status.
    // The main status is driven by HTTP polling success in updateConnectionStatus().
    const chartStatus = document.getElementById('chartStatus');

    if (connected) {
        if (chartStatus) {
            chartStatus.className = 'chart-status';
            chartStatus.innerHTML = `
                <span class="live-indicator"></span>
                Live Updates
            `;
        }
    } else {
        if (chartStatus) {
            chartStatus.className = 'chart-status offline';
            chartStatus.innerHTML = `
                <span class="live-indicator"></span>
                Polling Mode
            `;
        }
    }
}

// Main Dashboard Load
async function loadDashboard() {
    console.log('[Dashboard] Starting load cycle...');

    // Use allSettled so one failing endpoint doesn't block the entire dashboard
    const results = await Promise.allSettled([
        fetchPortfolio(),
        fetchTradeHistory(),
        fetchPerformance(),
        fetchStatus(),
        fetchPhase2Info()
    ]);

    const portfolio = results[0].status === 'fulfilled' ? results[0].value : null;
    const history   = results[1].status === 'fulfilled' ? results[1].value : null;
    const performance = results[2].status === 'fulfilled' ? results[2].value : null;
    const status    = results[3].status === 'fulfilled' ? results[3].value : null;
    const phase2Info = results[4].status === 'fulfilled' ? results[4].value : null;

    // Log any individual failures without blocking the dashboard
    results.forEach((r, i) => {
        if (r.status === 'rejected') {
            const names = ['portfolio', 'history', 'performance', 'status', 'phase2Info'];
            console.warn(`[Dashboard] ${names[i]} fetch failed:`, r.reason?.message || r.reason);
        }
    });

    // Only show connection error if BOTH critical endpoints failed
    if (!portfolio && !status) {
        const error = results[0].reason || results[3].reason || new Error('All endpoints failed');
        console.error('[Dashboard] Critical endpoints failed:', error);
        state.lastError = error;
        updateConnectionStatus(error);
        showError(`Connection Error: ${error.message || error}`);
        return;
    }

    // Update state with whatever data we have
    if (portfolio) state.portfolio = portfolio;
    if (history) state.trades = history.trades || [];
    if (performance) state.performance = performance;
    if (status) state.status = status;
    state.phase2.info = phase2Info;
    state.phase2.enabled = phase2Info && phase2Info.is_phase2;
    state.lastError = null;

    console.log('[Dashboard] Data loaded, updating UI...');

    // Update UI
    updateMetrics();
    updateTradesTable();
    updateStatusPanel();
    updateChart();
    updateConnectionStatus();

    // Update Phase 2 UI if enabled
    await updatePhase2Section();

    // Update Phase 3 UI if enabled
    await updatePhase3Section();

    // Update Cost Optimization section
    await updateCostSection();

    console.log('[Dashboard] Load cycle completed successfully');
}

// API Calls with Detailed Logging
async function fetchPortfolio() {
    const url = `${CONFIG.API_BASE}/portfolio`;
    console.log(`[API] Fetching portfolio from: ${url}`);
    try {
        const response = await fetch(url);
        console.log(`[API] Portfolio response: ${response.status} ${response.statusText}`);
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Portfolio endpoint returned ${response.status}: ${text}`);
        }
        const data = await response.json();
        console.log(`[API] Portfolio data received:`, data);
        return data;
    } catch (error) {
        console.error(`[API] Portfolio fetch failed:`, error);
        throw new Error(`Portfolio: ${error.message}`);
    }
}

async function fetchTradeHistory() {
    const url = `${CONFIG.API_BASE}/history?limit=50`;
    console.log(`[API] Fetching trade history from: ${url}`);
    try {
        const response = await fetch(url);
        console.log(`[API] History response: ${response.status} ${response.statusText}`);
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`History endpoint returned ${response.status}: ${text}`);
        }
        const data = await response.json();
        console.log(`[API] History data received (${data.trades ? data.trades.length : 0} trades):`, data);
        return data;
    } catch (error) {
        console.error(`[API] History fetch failed:`, error);
        throw new Error(`Trade History: ${error.message}`);
    }
}

async function fetchPerformance() {
    const url = `${CONFIG.API_BASE}/performance`;
    console.log(`[API] Fetching performance from: ${url}`);
    try {
        const response = await fetch(url);
        console.log(`[API] Performance response: ${response.status} ${response.statusText}`);
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Performance endpoint returned ${response.status}: ${text}`);
        }
        const data = await response.json();
        console.log(`[API] Performance data received:`, data);
        return data;
    } catch (error) {
        console.error(`[API] Performance fetch failed:`, error);
        throw new Error(`Performance: ${error.message}`);
    }
}

async function fetchStatus() {
    const url = `${CONFIG.API_BASE}/status`;
    console.log(`[API] Fetching status from: ${url}`);
    try {
        const response = await fetch(url);
        console.log(`[API] Status response: ${response.status} ${response.statusText}`);
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Status endpoint returned ${response.status}: ${text}`);
        }
        const data = await response.json();
        console.log(`[API] Status data received:`, data);
        return data;
    } catch (error) {
        console.error(`[API] Status fetch failed:`, error);
        throw new Error(`Status: ${error.message}`);
    }
}

// Metrics Updates
function updateMetrics() {
    if (!state.portfolio || !state.performance) return;

    const portfolio = state.portfolio;
    const perf = state.performance;

    // Total P&L Calculation
    const totalValue = (portfolio.total_value || 0);
    const totalPnL = totalValue - CONFIG.INITIAL_CAPITAL;
    const pnlPercent = (totalPnL / CONFIG.INITIAL_CAPITAL) * 100;

    // Update P&L metrics
    const pnlElement = document.getElementById('totalPnL');
    const pnlPercentElement = document.getElementById('totalPnLPercent');

    pnlElement.textContent = formatCurrency(totalPnL);
    pnlElement.className = totalPnL >= 0 ? 'metric-value positive' : 'metric-value negative';

    pnlPercentElement.textContent = `${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%`;
    pnlPercentElement.className = `metric-change ${pnlPercent >= 0 ? 'positive' : 'negative'}`;

    // Portfolio Value
    document.getElementById('portfolioValue').textContent = formatCurrency(totalValue);
    const portfolioPercent = ((totalValue - CONFIG.INITIAL_CAPITAL) / CONFIG.INITIAL_CAPITAL) * 100;
    document.getElementById('portfolioPercent').textContent = `${portfolioPercent >= 0 ? '+' : ''}${portfolioPercent.toFixed(2)}%`;
    document.getElementById('portfolioPercent').className = `metric-change ${portfolioPercent >= 0 ? 'positive' : 'negative'}`;

    // Win Rate
    const totalTrades = perf.total_trades || 0;
    const winRate = perf.win_rate ? (perf.win_rate * 100) : 0;
    const winningTrades = perf.winning_trades || 0;

    document.getElementById('winRate').textContent = `${winRate.toFixed(1)}%`;
    document.getElementById('winCount').textContent = `${winningTrades} / ${totalTrades} trades`;

    // Total Trades
    document.getElementById('totalTrades').textContent = totalTrades;

    // Active Positions
    const positionsObj = portfolio.positions || {};
    const positionsArray = Object.values(positionsObj);
    const activePositions = positionsArray.filter(p => p.amount > 0).length;
    document.getElementById('activePositions').textContent = `${activePositions} active positions`;

    // Current Exposure
    const totalQuote = portfolio.total_value || 0;
    const investedAmount = totalQuote - (portfolio.available_quote || 0);
    const exposure = totalQuote > 0 ? (investedAmount / totalQuote) * 100 : 0;

    document.getElementById('exposure').textContent = `${exposure.toFixed(1)}%`;

    // Target Progress
    const progress = ((totalValue - CONFIG.INITIAL_CAPITAL) / (CONFIG.TARGET_CAPITAL - CONFIG.INITIAL_CAPITAL)) * 100;
    const cappedProgress = Math.min(progress, 100);

    document.getElementById('targetProgress').textContent = `${cappedProgress.toFixed(1)}%`;

    // Store for chart
    updateChartData(totalValue);
}

// Chart Data Management
function updateChartData(portfolioValue) {
    const now = new Date();
    const timeLabel = now.toLocaleTimeString();

    // Add new data point
    state.chartData.timestamps.push(timeLabel);
    state.chartData.portfolioValues.push(portfolioValue);

    // Keep only last N points
    if (state.chartData.timestamps.length > CONFIG.CHART_MAX_POINTS) {
        state.chartData.timestamps.shift();
        state.chartData.portfolioValues.shift();
    }
}

// Chart Rendering
function updateChart() {
    const ctx = document.getElementById('performanceChart');
    if (!ctx) {
        console.warn('[Chart] Chart canvas element not found');
        return;
    }

    if (typeof Chart === 'undefined') {
        console.error('[Chart] Chart.js library not available');
        ctx.innerHTML = '<div style="padding: 20px; color: #ef4444;">Chart library not loaded</div>';
        return;
    }

    const chartData = {
        labels: state.chartData.timestamps,
        datasets: [
            {
                label: 'Portfolio Value (AUD)',
                data: state.chartData.portfolioValues,
                borderColor: '#00d4ff',
                backgroundColor: 'rgba(0, 212, 255, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#00d4ff',
                pointBorderColor: '#0f1419',
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6
            },
            {
                label: 'Initial Capital ($1,000)',
                data: Array(state.chartData.timestamps.length).fill(CONFIG.INITIAL_CAPITAL),
                borderColor: '#a0a9b8',
                borderWidth: 2,
                borderDash: [5, 5],
                fill: false,
                pointRadius: 0,
                tension: 0
            },
            {
                label: 'Target ($5,000)',
                data: Array(state.chartData.timestamps.length).fill(CONFIG.TARGET_CAPITAL),
                borderColor: '#10b981',
                borderWidth: 2,
                borderDash: [5, 5],
                fill: false,
                pointRadius: 0,
                tension: 0
            }
        ]
    };

    const options = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            mode: 'index',
            intersect: false
        },
        plugins: {
            legend: {
                labels: {
                    color: '#e0e6ed',
                    font: { size: 12, weight: '500' },
                    padding: 15,
                    usePointStyle: true
                },
                position: 'top'
            },
            tooltip: {
                backgroundColor: 'rgba(0, 0, 0, 0.8)',
                padding: 12,
                titleColor: '#00d4ff',
                bodyColor: '#e0e6ed',
                borderColor: '#374151',
                borderWidth: 1,
                cornerRadius: 6,
                callbacks: {
                    label: function(context) {
                        return `${context.dataset.label}: ${formatCurrency(context.parsed.y)}`;
                    }
                }
            }
        },
        scales: {
            y: {
                beginAtZero: false,
                ticks: {
                    color: '#a0a9b8',
                    font: { size: 12 },
                    callback: function(value) {
                        return formatCurrency(value);
                    }
                },
                grid: {
                    color: 'rgba(52, 65, 81, 0.3)',
                    drawBorder: false
                }
            },
            x: {
                ticks: {
                    color: '#a0a9b8',
                    font: { size: 12 }
                },
                grid: {
                    display: false,
                    drawBorder: false
                }
            }
        }
    };

    // Destroy old chart if exists
    if (state.chart) {
        state.chart.destroy();
    }

    // Create new chart
    state.chart = new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: options
    });
}

// Trades Table Update
function updateTradesTable() {
    const tbody = document.getElementById('tradesBody');

    if (!state.trades || state.trades.length === 0) {
        tbody.innerHTML = '<tr class="empty-state"><td colspan="7">No trades yet</td></tr>';
        return;
    }

    // Sort trades by timestamp descending (most recent first)
    const sortedTrades = [...state.trades].reverse();

    const html = sortedTrades.map(trade => {
        const timestamp = new Date(trade.timestamp);
        const timeStr = timestamp.toLocaleString();

        const actionClass = trade.action === 'BUY' ? 'action-buy' :
                          trade.action === 'SELL' ? 'action-sell' : 'action-hold';

        const pnl = trade.realized_pnl || 0;
        const pnlClass = pnl > 0 ? 'pnl-positive' : pnl < 0 ? 'pnl-negative' : '';
        const pnlSign = pnl > 0 ? '+' : '';

        const statusClass = trade.status === 'filled' ? 'status-filled' :
                          trade.status === 'pending' ? 'status-pending' : 'status-failed';

        return `
            <tr>
                <td class="time">${timeStr}</td>
                <td class="pair">${trade.pair}</td>
                <td class="${actionClass}">${trade.action}</td>
                <td>${formatCurrency(trade.average_price)}</td>
                <td>${trade.filled_size_base.toFixed(8)}</td>
                <td class="${statusClass}">${trade.status}</td>
                <td class="${pnlClass}">${pnlSign}${formatCurrency(pnl)}</td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = html;
}

// Status Panel Update
async function updateStatusPanel() {
    if (!state.status) return;

    document.getElementById('stage').textContent = 'Stage 1';
    document.getElementById('mode').textContent = (state.portfolio && state.portfolio.simulation_mode) ? 'Simulation' : 'Live';

    const nextCycleTime = state.status.next_cycle ?
        new Date(state.status.next_cycle).toLocaleTimeString() : 'N/A';
    document.getElementById('nextCycle').textContent = nextCycleTime;

    document.getElementById('cycleCount').textContent = state.status.cycle_count || 0;

    const tradingActive = !state.status.sentinel_paused;
    document.getElementById('tradingStatus').textContent = tradingActive ? 'Active' : 'Paused';
    document.getElementById('tradingStatus').style.color = tradingActive ? '#10b981' : '#f59e0b';

    // Update button states
    const pauseBtn = document.getElementById('pauseBtn');
    const resumeBtn = document.getElementById('resumeBtn');

    state.paused = state.status.sentinel_paused;
    pauseBtn.style.display = state.paused ? 'none' : 'block';
    resumeBtn.style.display = state.paused ? 'block' : 'none';
}

// Connection Status Indicator
function updateConnectionStatus(error) {
    const statusDot = document.getElementById('statusIndicator');
    const statusText = document.getElementById('statusText');

    if (error) {
        statusDot.className = 'status-dot error';
        statusText.textContent = 'Connection Error';
    } else {
        statusDot.className = 'status-dot active';
        statusText.textContent = 'Connected';
    }
}

// Action Handlers
async function triggerTradingCycle() {
    try {
        const btn = document.getElementById('triggerBtn');
        btn.disabled = true;

        const response = await fetch(`${CONFIG.API_BASE}/trigger`, { method: 'POST' });
        if (!response.ok) throw new Error(`Trigger failed: ${response.status}`);

        showToast('Trading cycle triggered');

        // Reload dashboard after a short delay
        setTimeout(loadDashboard, 1000);
    } catch (error) {
        console.error('Trigger error:', error);
        showError('Failed to trigger trading cycle');
    } finally {
        document.getElementById('triggerBtn').disabled = false;
    }
}

async function pauseTrading() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/pause`, { method: 'POST' });
        if (!response.ok) throw new Error(`Pause failed: ${response.status}`);

        state.paused = true;
        document.getElementById('pauseBtn').style.display = 'none';
        document.getElementById('resumeBtn').style.display = 'block';

        showToast('Trading paused');
        updateStatusPanel();
    } catch (error) {
        console.error('Pause error:', error);
        showError('Failed to pause trading');
    }
}

async function resumeTrading() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/resume`, { method: 'POST' });
        if (!response.ok) throw new Error(`Resume failed: ${response.status}`);

        state.paused = false;
        document.getElementById('pauseBtn').style.display = 'block';
        document.getElementById('resumeBtn').style.display = 'none';

        showToast('Trading resumed');
        updateStatusPanel();
    } catch (error) {
        console.error('Resume error:', error);
        showError('Failed to resume trading');
    }
}

// Utility Functions
function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function showError(message) {
    console.error('[Error Display] Showing error:', message);
    const container = document.querySelector('.container');

    if (!container) {
        console.warn('[Error Display] Container not found, creating alert');
        alert(`Dashboard Error:\n${message}\n\nCheck browser console (F12) for more details.`);
        return;
    }

    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-banner';
    errorDiv.style.cssText = `
        background-color: #ef4444;
        color: white;
        padding: 16px;
        margin-bottom: 16px;
        border-radius: 8px;
        font-weight: 500;
        display: flex;
        justify-content: space-between;
        align-items: center;
    `;

    const text = document.createElement('div');
    text.innerHTML = `
        <div><strong>Connection Error</strong></div>
        <div style="font-size: 12px; margin-top: 4px;">${message}</div>
        <div style="font-size: 11px; margin-top: 8px; opacity: 0.9;">Open browser console (F12) for debugging details</div>
    `;

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '✕';
    closeBtn.style.cssText = `
        background: none;
        border: none;
        color: white;
        font-size: 18px;
        cursor: pointer;
        padding: 0;
        margin-left: 16px;
    `;
    closeBtn.addEventListener('click', () => errorDiv.remove());

    errorDiv.appendChild(text);
    errorDiv.appendChild(closeBtn);
    container.insertBefore(errorDiv, container.firstChild);

    // Don't auto-remove - keep visible until user closes or page reloads
}

function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Format timestamp to readable format
function formatTimestamp(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleString();
    } catch {
        return isoString;
    }
}

// =============================================================================
// PHASE 2 FUNCTIONS
// =============================================================================

async function fetchPhase2Info() {
    const url = `${CONFIG.API_BASE}/api/phase2/info`;
    console.log(`[API] Fetching Phase 2 info from: ${url}`);
    try {
        const response = await fetch(url);
        if (!response.ok) {
            console.log('[API] Phase 2 info not available (Stage 1 mode)');
            return { is_phase2: false };
        }
        const data = await response.json();
        console.log('[API] Phase 2 info received:', data);
        return data;
    } catch (error) {
        console.log('[API] Phase 2 info fetch failed (likely Stage 1):', error.message);
        return { is_phase2: false };
    }
}

async function fetchCircuitBreakers() {
    const url = `${CONFIG.API_BASE}/api/phase2/breakers`;
    console.log(`[API] Fetching circuit breakers from: ${url}`);
    try {
        const response = await fetch(url);
        if (!response.ok) return null;
        const data = await response.json();
        console.log('[API] Circuit breakers data:', data);
        return data;
    } catch (error) {
        console.log('[API] Circuit breakers fetch failed:', error.message);
        return null;
    }
}

async function fetchSentimentData() {
    const url = `${CONFIG.API_BASE}/api/phase2/sentiment`;
    console.log(`[API] Fetching sentiment data from: ${url}`);
    try {
        const response = await fetch(url);
        if (!response.ok) return null;
        const data = await response.json();
        console.log('[API] Sentiment data:', data);
        return data;
    } catch (error) {
        console.log('[API] Sentiment fetch failed:', error.message);
        return null;
    }
}

async function fetchFusionData() {
    const url = `${CONFIG.API_BASE}/api/phase2/fusion`;
    console.log(`[API] Fetching fusion data from: ${url}`);
    try {
        const response = await fetch(url);
        if (!response.ok) return null;
        const data = await response.json();
        console.log('[API] Fusion data:', data);
        return data;
    } catch (error) {
        console.log('[API] Fusion fetch failed:', error.message);
        return null;
    }
}

async function fetchExecutionStats() {
    const url = `${CONFIG.API_BASE}/api/phase2/execution`;
    console.log(`[API] Fetching execution stats from: ${url}`);
    try {
        const response = await fetch(url);
        if (!response.ok) return null;
        const data = await response.json();
        console.log('[API] Execution stats:', data);
        return data;
    } catch (error) {
        console.log('[API] Execution stats fetch failed:', error.message);
        return null;
    }
}

async function updatePhase2Section() {
    const section = document.getElementById('phase2Section');
    if (!section) return;

    // Get Phase 2 info
    const info = state.phase2.info;

    // Update stage display
    const stageEl = document.getElementById('stage');
    if (stageEl && info) {
        stageEl.textContent = info.stage || 'Stage 1';
    }

    // Update analyst count
    const analystCountEl = document.getElementById('analystCount');
    if (analystCountEl && info && info.features) {
        const count = info.features.analyst_count || 1;
        analystCountEl.textContent = `${count} analyst${count !== 1 ? 's' : ''}`;
    }

    // Show/hide sentiment analyst
    const sentimentAnalystEl = document.getElementById('sentimentAnalyst');
    if (sentimentAnalystEl && info && info.features) {
        sentimentAnalystEl.style.display = info.features.sentiment_analyst ? 'flex' : 'none';
    }

    // Fetch additional Phase 2 data in parallel
    const [breakers, sentiment, fusion, execution] = await Promise.all([
        fetchCircuitBreakers(),
        fetchSentimentData(),
        fetchFusionData(),
        fetchExecutionStats()
    ]);

    state.phase2.breakers = breakers;
    state.phase2.sentiment = sentiment;
    state.phase2.fusion = fusion;
    state.phase2.executionStats = execution;

    // Update Circuit Breakers
    updateCircuitBreakersUI(breakers);

    // Update Sentiment / Fear & Greed
    updateSentimentUI(sentiment);

    // Update Intelligence Fusion
    updateFusionUI(fusion);

    // Update Execution Stats
    updateExecutionStatsUI(execution);
}

function updateCircuitBreakersUI(data) {
    const breakerStatus = document.getElementById('breakerStatus');

    if (!data || !data.enabled) {
        if (breakerStatus) {
            breakerStatus.textContent = 'Disabled';
            breakerStatus.className = 'badge';
        }
        return;
    }

    const status = data.status || {};
    const breakers = status.breakers || {};
    let anyTripped = false;

    // Update each breaker
    const breakerMap = {
        'daily_loss': 'dailyLossBreaker',
        'trade_frequency': 'tradeFreqBreaker',
        'volatility': 'volatilityBreaker',
        'consecutive_loss': 'consLossBreaker'
    };

    for (const [key, elementId] of Object.entries(breakerMap)) {
        const el = document.getElementById(elementId);
        if (!el) continue;

        const breaker = breakers[key];
        const indicator = el.querySelector('.status-indicator');
        const text = el.querySelector('.status-text');

        if (breaker && breaker.tripped) {
            anyTripped = true;
            if (indicator) indicator.className = 'status-indicator tripped';
            if (text) {
                text.textContent = 'TRIPPED';
                text.className = 'status-text tripped';
            }
        } else {
            if (indicator) indicator.className = 'status-indicator ok';
            if (text) {
                text.textContent = 'OK';
                text.className = 'status-text ok';
            }
        }
    }

    // Update overall status
    if (breakerStatus) {
        if (anyTripped) {
            breakerStatus.textContent = 'Tripped';
            breakerStatus.className = 'badge badge-danger';
        } else {
            breakerStatus.textContent = 'Active';
            breakerStatus.className = 'badge badge-success';
        }
    }
}

function updateSentimentUI(data) {
    const fearGreedCard = document.getElementById('fearGreedCard');
    if (!fearGreedCard) return;

    if (!data || !data.enabled) {
        fearGreedCard.style.display = 'none';
        return;
    }

    fearGreedCard.style.display = 'block';

    const fgData = data.fear_greed;
    if (!fgData) return;

    // Update Fear & Greed value badge
    const fgValueEl = document.getElementById('fearGreedValue');
    if (fgValueEl) {
        const value = fgData.value || 50;
        fgValueEl.textContent = `${value} - ${fgData.classification || 'Neutral'}`;

        // Set badge color based on value
        if (value <= 25) {
            fgValueEl.className = 'badge badge-danger';
        } else if (value <= 45) {
            fgValueEl.className = 'badge badge-warning';
        } else if (value <= 55) {
            fgValueEl.className = 'badge';
        } else if (value <= 75) {
            fgValueEl.className = 'badge badge-info';
        } else {
            fgValueEl.className = 'badge badge-success';
        }
    }

    // Update meter position
    const fgMeter = document.getElementById('fgMeter');
    if (fgMeter && fgData.value !== undefined) {
        fgMeter.style.left = `${fgData.value}%`;
    }

    // Update signal interpretation (contrarian)
    const fgSignal = document.getElementById('fgSignal');
    if (fgSignal && fgData.value !== undefined) {
        const value = fgData.value;
        if (value <= 25) {
            fgSignal.textContent = 'Bullish (Extreme Fear = Buy)';
            fgSignal.style.color = 'var(--success)';
        } else if (value <= 45) {
            fgSignal.textContent = 'Slightly Bullish (Fear)';
            fgSignal.style.color = 'var(--success)';
        } else if (value <= 55) {
            fgSignal.textContent = 'Neutral';
            fgSignal.style.color = 'var(--text-secondary)';
        } else if (value <= 75) {
            fgSignal.textContent = 'Slightly Bearish (Greed)';
            fgSignal.style.color = 'var(--warning)';
        } else {
            fgSignal.textContent = 'Bearish (Extreme Greed = Sell)';
            fgSignal.style.color = 'var(--danger)';
        }
    }
}

function updateFusionUI(data) {
    const fusionStatus = document.getElementById('fusionStatus');

    if (!data || !data.enabled) {
        if (fusionStatus) {
            fusionStatus.textContent = 'Stage 1';
            fusionStatus.className = 'badge';
        }

        // Set default neutral values
        document.getElementById('fusedDirection').textContent = '0.00';
        document.getElementById('fusedConfidence').textContent = '0%';
        document.getElementById('fusionDisagreement').textContent = '0%';

        const meter = document.getElementById('fusionMeter');
        if (meter) meter.style.left = '50%';
        return;
    }

    const fusion = data.latest || {};

    // Update status badge
    if (fusionStatus) {
        const direction = fusion.fused_direction || 0;
        if (direction > 0.3) {
            fusionStatus.textContent = 'Bullish';
            fusionStatus.className = 'badge badge-success';
        } else if (direction < -0.3) {
            fusionStatus.textContent = 'Bearish';
            fusionStatus.className = 'badge badge-danger';
        } else {
            fusionStatus.textContent = 'Neutral';
            fusionStatus.className = 'badge badge-info';
        }
    }

    // Update fusion meter (direction -1 to 1 maps to 0% to 100%)
    const meter = document.getElementById('fusionMeter');
    if (meter && fusion.fused_direction !== undefined) {
        const position = ((fusion.fused_direction + 1) / 2) * 100;
        meter.style.left = `${position}%`;
    }

    // Update stats
    const directionEl = document.getElementById('fusedDirection');
    if (directionEl) {
        const dir = fusion.fused_direction || 0;
        directionEl.textContent = dir.toFixed(2);
        directionEl.style.color = dir > 0 ? 'var(--success)' : dir < 0 ? 'var(--danger)' : 'var(--text-primary)';
    }

    const confidenceEl = document.getElementById('fusedConfidence');
    if (confidenceEl) {
        confidenceEl.textContent = `${((fusion.fused_confidence || 0) * 100).toFixed(0)}%`;
    }

    const disagreementEl = document.getElementById('fusionDisagreement');
    if (disagreementEl) {
        const disagreement = (fusion.disagreement || 0) * 100;
        disagreementEl.textContent = `${disagreement.toFixed(0)}%`;
        disagreementEl.style.color = disagreement > 50 ? 'var(--warning)' : 'var(--text-primary)';
    }

    // Update individual analyst signals if available
    if (fusion.signals) {
        for (const signal of fusion.signals) {
            if (signal.source === 'technical') {
                updateAnalystSignal('tech', signal);
            } else if (signal.source === 'sentiment') {
                updateAnalystSignal('sent', signal);
            }
        }
    }
}

function updateAnalystSignal(prefix, signal) {
    const dirEl = document.getElementById(`${prefix}Direction`);
    const confEl = document.getElementById(`${prefix}Confidence`);

    if (dirEl) {
        const dir = signal.direction || 0;
        if (dir > 0.2) {
            dirEl.textContent = `+${dir.toFixed(2)}`;
            dirEl.className = 'direction bullish';
        } else if (dir < -0.2) {
            dirEl.textContent = dir.toFixed(2);
            dirEl.className = 'direction bearish';
        } else {
            dirEl.textContent = dir.toFixed(2);
            dirEl.className = 'direction neutral';
        }
    }

    if (confEl) {
        confEl.textContent = `${((signal.confidence || 0) * 100).toFixed(0)}%`;
    }
}

function updateExecutionStatsUI(data) {
    const execMode = document.getElementById('execMode');

    if (!data || !data.enabled) {
        if (execMode) {
            execMode.textContent = 'Market Orders';
            execMode.className = 'badge';
        }
        return;
    }

    const stats = data.stats || {};

    if (execMode) {
        execMode.textContent = 'Limit Orders';
        execMode.className = 'badge badge-info';
    }

    // Update stats
    const limitCount = document.getElementById('limitOrderCount');
    if (limitCount) {
        limitCount.textContent = stats.limit_orders || 0;
    }

    const fillRate = document.getElementById('limitFillRate');
    if (fillRate) {
        const rate = stats.fill_rate;
        fillRate.textContent = rate !== undefined ? `${(rate * 100).toFixed(0)}%` : '-';
    }

    const slippage = document.getElementById('avgSlippage');
    if (slippage) {
        const slip = stats.avg_slippage;
        slippage.textContent = slip !== undefined ? `${(slip * 100).toFixed(2)}%` : '-';
    }

    const fallbacks = document.getElementById('marketFallbacks');
    if (fallbacks) {
        fallbacks.textContent = stats.market_fallbacks || 0;
    }
}

// =============================================================================
// PHASE 3 SECTION
// =============================================================================

async function updatePhase3Section() {
    const section = document.getElementById('phase3Section');
    if (!section) return;

    // Get Phase info to determine if we're in Stage 3
    const info = state.phase2.info;
    const isPhase3 = info && (info.stage === 'stage3' || info.stage === 'Stage 3');

    // Show/hide Phase 3 section
    section.style.display = isPhase3 ? 'block' : 'none';

    if (!isPhase3) {
        // Even if not in Phase 3, show section with simulated data for demo
        section.style.display = 'block';
        updatePhase3WithSimulatedData();
        return;
    }

    state.phase3.enabled = true;

    // Show additional analysts in Phase 2 section
    showPhase3Analysts();

    // Update Phase 3 components with real data when available
    // For now, use simulated data
    updatePhase3WithSimulatedData();
}

function showPhase3Analysts() {
    // Show Phase 3 analysts in the analyst list
    const onchainEl = document.getElementById('onchainAnalyst');
    const macroEl = document.getElementById('macroAnalyst');
    const orderbookEl = document.getElementById('orderbookAnalyst');

    if (onchainEl) onchainEl.style.display = 'flex';
    if (macroEl) macroEl.style.display = 'flex';
    if (orderbookEl) orderbookEl.style.display = 'flex';

    // Show performance items
    const sentPerfEl = document.getElementById('sentPerfItem');
    const onchainPerfEl = document.getElementById('onchainPerfItem');
    const macroPerfEl = document.getElementById('macroPerfItem');
    const orderbookPerfEl = document.getElementById('orderbookPerfItem');

    if (sentPerfEl) sentPerfEl.style.display = 'flex';
    if (onchainPerfEl) onchainPerfEl.style.display = 'flex';
    if (macroPerfEl) macroPerfEl.style.display = 'flex';
    if (orderbookPerfEl) orderbookPerfEl.style.display = 'flex';

    // Update analyst count
    const analystCountEl = document.getElementById('analystCount');
    if (analystCountEl) {
        analystCountEl.textContent = '5 analysts';
    }
}

function updatePhase3WithSimulatedData() {
    // Simulate Phase 3 data for demonstration
    updateRegimeUI({
        regime: 'RANGING',
        volatility: 0.023,
        trend_strength: 0.15,
        duration: '2h 15m'
    });

    updateCorrelationUI({
        btc_eth: 0.85,
        btc_sol: 0.78,
        eth_sol: 0.82,
        high_correlation: false
    });

    updateAnalystPerformanceUI({
        technical: 0.62,
        sentiment: 0.58,
        onchain: 0.55,
        macro: 0.52,
        orderbook: 0.60
    });

    updateAlertingUI({
        slack: true,
        discord: false,
        email: false,
        recent: []
    });

    updateAnomalyUI({
        score: 0.15,
        threshold: 0.70,
        status: 'Normal',
        last_alert: 'Never'
    });

    // Update analyst signals with simulated data
    updateAnalystSignal('onchain', { direction: 0.32, confidence: 0.68 });
    updateAnalystSignal('macro', { direction: -0.15, confidence: 0.55 });
    updateAnalystSignal('orderbook', { direction: 0.45, confidence: 0.72 });
}

function updateRegimeUI(data) {
    if (!data) return;

    const regimeStatus = document.getElementById('regimeStatus');
    const regimeIcon = document.getElementById('regimeIcon');
    const regimeName = document.getElementById('regimeName');
    const regimeVolatility = document.getElementById('regimeVolatility');
    const regimeTrend = document.getElementById('regimeTrend');
    const regimeDuration = document.getElementById('regimeDuration');

    const regime = data.regime || 'Unknown';

    // Update status badge
    if (regimeStatus) {
        regimeStatus.textContent = regime;
        if (regime.includes('UP') || regime.includes('BULL')) {
            regimeStatus.className = 'badge badge-success';
        } else if (regime.includes('DOWN') || regime.includes('BEAR')) {
            regimeStatus.className = 'badge badge-danger';
        } else if (regime.includes('VOLATILE')) {
            regimeStatus.className = 'badge badge-warning';
        } else {
            regimeStatus.className = 'badge badge-info';
        }
    }

    // Update icon
    if (regimeIcon) {
        if (regime.includes('UP') || regime.includes('BULL')) {
            regimeIcon.textContent = '\u2191'; // Up arrow
        } else if (regime.includes('DOWN') || regime.includes('BEAR')) {
            regimeIcon.textContent = '\u2193'; // Down arrow
        } else if (regime.includes('VOLATILE')) {
            regimeIcon.textContent = '\u26A1'; // Lightning
        } else {
            regimeIcon.textContent = '\u2194'; // Side arrow
        }
    }

    if (regimeName) regimeName.textContent = regime;
    if (regimeVolatility) regimeVolatility.textContent = `${((data.volatility || 0) * 100).toFixed(1)}%`;
    if (regimeTrend) regimeTrend.textContent = (data.trend_strength || 0).toFixed(2);
    if (regimeDuration) regimeDuration.textContent = data.duration || '-';
}

function updateCorrelationUI(data) {
    if (!data) return;

    const correlationStatus = document.getElementById('correlationStatus');
    const correlationWarning = document.getElementById('correlationWarning');

    // Update correlation values
    const corrBtcEth = document.getElementById('corrBtcEth');
    const corrBtcSol = document.getElementById('corrBtcSol');
    const corrEthBtc = document.getElementById('corrEthBtc');
    const corrEthSol = document.getElementById('corrEthSol');
    const corrSolBtc = document.getElementById('corrSolBtc');
    const corrSolEth = document.getElementById('corrSolEth');

    function updateCorrCell(el, value) {
        if (!el) return;
        el.textContent = value.toFixed(2);
        if (value >= 0.9) {
            el.className = 'corr-cell corr-high';
        } else if (value >= 0.7) {
            el.className = 'corr-cell corr-med';
        } else {
            el.className = 'corr-cell corr-low';
        }
    }

    updateCorrCell(corrBtcEth, data.btc_eth || 0.85);
    updateCorrCell(corrBtcSol, data.btc_sol || 0.78);
    updateCorrCell(corrEthBtc, data.btc_eth || 0.85);
    updateCorrCell(corrEthSol, data.eth_sol || 0.82);
    updateCorrCell(corrSolBtc, data.btc_sol || 0.78);
    updateCorrCell(corrSolEth, data.eth_sol || 0.82);

    // Update status
    if (correlationStatus) {
        if (data.high_correlation) {
            correlationStatus.textContent = 'High Risk';
            correlationStatus.className = 'badge badge-danger';
        } else {
            correlationStatus.textContent = 'Diversified';
            correlationStatus.className = 'badge badge-success';
        }
    }

    // Show/hide warning
    if (correlationWarning) {
        correlationWarning.style.display = data.high_correlation ? 'flex' : 'none';
    }
}

function updateAnalystPerformanceUI(data) {
    if (!data) return;

    function updatePerfItem(prefix, accuracy) {
        const bar = document.getElementById(`${prefix}PerfBar`);
        const value = document.getElementById(`${prefix}Accuracy`);

        if (bar) bar.style.width = `${accuracy * 100}%`;
        if (value) value.textContent = `${(accuracy * 100).toFixed(0)}%`;
    }

    updatePerfItem('tech', data.technical || 0.5);
    updatePerfItem('sent', data.sentiment || 0.5);
    updatePerfItem('onchain', data.onchain || 0.5);
    updatePerfItem('macro', data.macro || 0.5);
    updatePerfItem('orderbook', data.orderbook || 0.5);
}

function updateAlertingUI(data) {
    if (!data) return;

    const alertingStatus = document.getElementById('alertingStatus');
    const slackStatus = document.getElementById('slackStatus');
    const discordStatus = document.getElementById('discordStatus');
    const emailStatus = document.getElementById('emailStatus');
    const recentAlerts = document.getElementById('recentAlerts');

    if (alertingStatus) {
        const anyEnabled = data.slack || data.discord || data.email;
        alertingStatus.textContent = anyEnabled ? 'Active' : 'Disabled';
        alertingStatus.className = anyEnabled ? 'badge badge-success' : 'badge';
    }

    if (slackStatus) {
        slackStatus.textContent = data.slack ? 'Enabled' : 'Disabled';
        slackStatus.className = data.slack ? 'channel-status' : 'channel-status disabled';
    }

    if (discordStatus) {
        discordStatus.textContent = data.discord ? 'Enabled' : 'Disabled';
        discordStatus.className = data.discord ? 'channel-status' : 'channel-status disabled';
    }

    if (emailStatus) {
        emailStatus.textContent = data.email ? 'Enabled' : 'Disabled';
        emailStatus.className = data.email ? 'channel-status' : 'channel-status disabled';
    }

    if (recentAlerts && data.recent) {
        if (data.recent.length === 0) {
            recentAlerts.innerHTML = '<div class="alert-item">No recent alerts</div>';
        } else {
            recentAlerts.innerHTML = data.recent.map(alert =>
                `<div class="alert-item">${alert.time}: ${alert.message}</div>`
            ).join('');
        }
    }
}

function updateAnomalyUI(data) {
    if (!data) return;

    const anomalyScore = document.getElementById('anomalyScore');
    const anomalyMeter = document.getElementById('anomalyMeter');
    const anomalyValue = document.getElementById('anomalyValue');
    const lastAnomalyAlert = document.getElementById('lastAnomalyAlert');

    const score = data.score || 0;

    if (anomalyScore) {
        if (score < 0.3) {
            anomalyScore.textContent = 'Normal';
            anomalyScore.className = 'badge badge-success';
        } else if (score < 0.5) {
            anomalyScore.textContent = 'Elevated';
            anomalyScore.className = 'badge badge-info';
        } else if (score < 0.7) {
            anomalyScore.textContent = 'High';
            anomalyScore.className = 'badge badge-warning';
        } else {
            anomalyScore.textContent = 'Critical';
            anomalyScore.className = 'badge badge-danger';
        }
    }

    if (anomalyMeter) {
        anomalyMeter.style.left = `${score * 100}%`;
    }

    if (anomalyValue) {
        anomalyValue.textContent = score.toFixed(2);
    }

    if (lastAnomalyAlert) {
        lastAnomalyAlert.textContent = data.last_alert || 'Never';
    }
}

// =============================================================================
// COST OPTIMIZATION SECTION
// =============================================================================

async function fetchCostStats() {
    const url = `${CONFIG.API_BASE}/api/cost/stats`;
    console.log(`[API] Fetching cost stats from: ${url}`);
    try {
        const response = await fetch(url);
        if (!response.ok) {
            console.log('[API] Cost stats not available');
            return null;
        }
        const data = await response.json();
        console.log('[API] Cost stats received:', data);
        return data;
    } catch (error) {
        console.log('[API] Cost stats fetch failed:', error.message);
        return null;
    }
}

async function updateCostSection() {
    const section = document.getElementById('costSection');
    if (!section) return;

    // Fetch cost stats
    const costData = await fetchCostStats();

    if (!costData || !costData.enabled) {
        // Show section with default/zero values
        updateCostUI(null);
        return;
    }

    state.costOptimization.enabled = true;
    state.costOptimization.stats = costData.stats;
    state.costOptimization.config = costData.config;

    updateCostUI(costData);
}

function updateCostUI(data) {
    // Default values if no data
    const stats = data?.stats || {
        total_calls: 0,
        cache_hits: 0,
        rule_decisions: 0,
        claude_decisions: 0,
        batch_calls: 0,
        savings_pct: '0%',
        estimated_savings: '$0.00'
    };

    const config = data?.config || {
        batch_analysis: false,
        hybrid_mode: false,
        decision_cache: false,
        adaptive_schedule: false
    };

    const hybrid = stats.hybrid || {
        total_decisions: 0,
        rule_based: 0,
        claude: 0,
        rule_based_pct: '0%'
    };

    // Update savings meter and badge
    const savingsPercent = parseFloat(stats.savings_pct) || 0;
    const costSavingsMeter = document.getElementById('costSavingsMeter');
    const costSavingsPercent = document.getElementById('costSavingsPercent');

    if (costSavingsMeter) {
        costSavingsMeter.style.width = `${Math.min(savingsPercent, 100)}%`;
    }

    if (costSavingsPercent) {
        costSavingsPercent.textContent = `${savingsPercent.toFixed(0)}%`;
        if (savingsPercent >= 50) {
            costSavingsPercent.className = 'badge badge-success';
        } else if (savingsPercent >= 25) {
            costSavingsPercent.className = 'badge badge-info';
        } else {
            costSavingsPercent.className = 'badge';
        }
    }

    // Update estimated savings
    const estimatedSavings = document.getElementById('estimatedSavings');
    if (estimatedSavings) {
        estimatedSavings.textContent = stats.estimated_savings || '$0.00';
    }

    // Calculate and update projected monthly cost
    const projectedMonthlyCost = document.getElementById('projectedMonthlyCost');
    if (projectedMonthlyCost) {
        // Estimate based on current usage
        // Baseline: ~72 calls/day = ~$0.40/day = ~$12/month
        // With optimization: reduced by savings_pct
        const baselineMonthlyCost = 12;
        const optimizedCost = baselineMonthlyCost * (1 - savingsPercent / 100);
        projectedMonthlyCost.textContent = `$${optimizedCost.toFixed(2)}/mo`;
    }

    // Update optimization methods status
    updateMethodStatus('batch', config.batch_analysis);
    updateMethodStatus('hybrid', config.hybrid_mode);
    updateMethodStatus('cache', config.decision_cache);
    updateMethodStatus('adaptive', config.adaptive_schedule);

    // Update optimization status badge
    const optimizationStatus = document.getElementById('optimizationStatus');
    if (optimizationStatus) {
        const anyEnabled = config.batch_analysis || config.hybrid_mode || config.decision_cache || config.adaptive_schedule;
        optimizationStatus.textContent = anyEnabled ? 'Active' : 'Disabled';
        optimizationStatus.className = anyEnabled ? 'badge badge-success' : 'badge';
    }

    // Update API call statistics
    const totalApiCalls = document.getElementById('totalApiCalls');
    const claudeDecisions = document.getElementById('claudeDecisions');
    const ruleDecisions = document.getElementById('ruleDecisions');
    const cacheHits = document.getElementById('cacheHits');
    const totalCallsBadge = document.getElementById('totalCallsBadge');

    if (totalApiCalls) totalApiCalls.textContent = stats.total_calls || 0;
    if (claudeDecisions) claudeDecisions.textContent = stats.claude_decisions || 0;
    if (ruleDecisions) ruleDecisions.textContent = stats.rule_decisions || 0;
    if (cacheHits) cacheHits.textContent = stats.cache_hits || 0;
    if (totalCallsBadge) totalCallsBadge.textContent = `${stats.total_calls || 0} calls`;

    // Update hybrid mode breakdown
    const hybridTotal = hybrid.total_decisions || 0;
    const hybridRules = hybrid.rule_based || 0;
    const hybridClaude = hybrid.claude || 0;

    const rulesPercent = hybridTotal > 0 ? (hybridRules / hybridTotal) * 100 : 0;
    const claudePercent = hybridTotal > 0 ? (hybridClaude / hybridTotal) * 100 : 100;

    const hybridRulesBar = document.getElementById('hybridRulesBar');
    const hybridClaudeBar = document.getElementById('hybridClaudeBar');
    const hybridRulesPercent = document.getElementById('hybridRulesPercent');
    const hybridClaudePercent = document.getElementById('hybridClaudePercent');
    const hybridRuleCount = document.getElementById('hybridRuleCount');
    const hybridClaudeCount = document.getElementById('hybridClaudeCount');
    const hybridRatio = document.getElementById('hybridRatio');

    if (hybridRulesBar) hybridRulesBar.style.width = `${rulesPercent}%`;
    if (hybridClaudeBar) hybridClaudeBar.style.width = `${claudePercent}%`;
    if (hybridRulesPercent) hybridRulesPercent.textContent = `${rulesPercent.toFixed(0)}%`;
    if (hybridClaudePercent) hybridClaudePercent.textContent = `${claudePercent.toFixed(0)}%`;
    if (hybridRuleCount) hybridRuleCount.textContent = hybridRules;
    if (hybridClaudeCount) hybridClaudeCount.textContent = hybridClaude;
    if (hybridRatio) {
        hybridRatio.textContent = `${rulesPercent.toFixed(0)}% Rules`;
        hybridRatio.className = rulesPercent >= 50 ? 'badge badge-success' : 'badge badge-info';
    }

    // Update cost comparison
    const baselineCost = document.getElementById('baselineCost');
    const optimizedCost = document.getElementById('optimizedCost');
    const monthlySavings = document.getElementById('monthlySavings');
    const costComparisonBadge = document.getElementById('costComparisonBadge');

    const baselineMonthly = 12; // $12/month without optimization
    const optimizedMonthly = baselineMonthly * (1 - savingsPercent / 100);
    const savings = baselineMonthly - optimizedMonthly;

    if (baselineCost) baselineCost.textContent = `$${baselineMonthly.toFixed(2)}/month`;
    if (optimizedCost) optimizedCost.textContent = `$${optimizedMonthly.toFixed(2)}/month`;
    if (monthlySavings) monthlySavings.textContent = `$${savings.toFixed(2)}`;

    if (costComparisonBadge) {
        if (savingsPercent >= 70) {
            costComparisonBadge.textContent = 'Highly Optimized';
            costComparisonBadge.className = 'badge badge-success';
        } else if (savingsPercent >= 40) {
            costComparisonBadge.textContent = 'Optimized';
            costComparisonBadge.className = 'badge badge-info';
        } else {
            costComparisonBadge.textContent = 'Basic';
            costComparisonBadge.className = 'badge';
        }
    }
}

function updateMethodStatus(method, enabled) {
    const statusIndicator = document.getElementById(`${method}Status`);
    const statusText = document.getElementById(`${method}StatusText`);

    if (statusIndicator) {
        statusIndicator.className = enabled ? 'status-indicator enabled' : 'status-indicator disabled';
    }

    if (statusText) {
        statusText.textContent = enabled ? 'Enabled' : 'Disabled';
        statusText.className = enabled ? 'status-text enabled' : 'status-text';
    }
}
