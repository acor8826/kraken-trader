// ============================================================================
// Dashboard Configuration
// ============================================================================

const CONFIG = {
    API_BASE: '',
    REFRESH_INTERVAL: 30000,
    INITIAL_CAPITAL: 1000,
    TARGET_CAPITAL: 5000,
    CHART_MAX_POINTS: 100,
    WS_URL: 'ws://localhost:8080/ws/portfolio',
    WS_RECONNECT_INTERVAL: 5000,
    TOAST_DURATION: 4000,
    ANIMATION_DURATION: 300,
    // Auth configuration
    AUTH_ENABLED: true,  // Auth enabled with PostgreSQL
    AUTH_CHECK_INTERVAL: 300000  // Check token validity every 5 minutes
};

// ============================================================================
// Authentication Check
// ============================================================================

async function checkAuthAndInit() {
    // Skip auth check if disabled
    if (!CONFIG.AUTH_ENABLED) {
        console.log('[AUTH] Auth check disabled');
        return true;
    }

    // Check if AuthManager is available (auth.js loaded)
    if (typeof AuthManager === 'undefined') {
        console.warn('[AUTH] AuthManager not loaded, skipping auth check');
        return true;
    }

    // Check if we have a valid token
    const isAuthenticated = await AuthManager.checkAuth();

    if (isAuthenticated) {
        console.log('[AUTH] User authenticated');
        updateUserMenu();
        return true;
    }

    console.log('[AUTH] User not authenticated');
    return false;
}

function updateUserMenu() {
    // Update header to show user info if authenticated
    const user = typeof AuthManager !== 'undefined' ? AuthManager.getUser() : null;
    if (!user) return;

    // Add user menu to header if not already present
    const headerRight = document.querySelector('.header-right');
    if (headerRight && !document.getElementById('userMenu')) {
        const userMenu = document.createElement('div');
        userMenu.id = 'userMenu';
        userMenu.className = 'user-menu';
        userMenu.innerHTML = `
            <button class="user-menu-btn" aria-haspopup="true" aria-expanded="false">
                <i data-lucide="user" style="width: 18px; height: 18px;"></i>
                <span class="user-email">${user.email.split('@')[0]}</span>
                <i data-lucide="chevron-down" style="width: 14px; height: 14px;"></i>
            </button>
            <div class="user-menu-dropdown" role="menu">
                <button class="user-menu-item" role="menuitem" onclick="showChangePasswordModal()">
                    <i data-lucide="key" style="width: 16px; height: 16px;"></i>
                    Change Password
                </button>
                <button class="user-menu-item danger" role="menuitem" onclick="AuthManager.signOut()">
                    <i data-lucide="log-out" style="width: 16px; height: 16px;"></i>
                    Sign Out
                </button>
            </div>
        `;
        headerRight.insertBefore(userMenu, headerRight.firstChild);

        // Add click handler for dropdown
        const menuBtn = userMenu.querySelector('.user-menu-btn');
        const dropdown = userMenu.querySelector('.user-menu-dropdown');

        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = dropdown.classList.contains('active');
            dropdown.classList.toggle('active');
            menuBtn.setAttribute('aria-expanded', !isOpen);
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', () => {
            dropdown.classList.remove('active');
            menuBtn.setAttribute('aria-expanded', 'false');
        });

        // Re-render lucide icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

// ============================================================================
// State Management
// ============================================================================

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
    sidebarOpen: false,
    fabOpen: false,
    notificationPanelOpen: false,
    collapsedSections: new Set(),
    activeNavSection: 'metrics',
    notifications: [],
    phase2: {
        enabled: false,
        info: null,
        breakers: null,
        sentiment: null,
        fusion: null,
        executionStats: null
    },
    phase3: {
        enabled: false,
        regime: null,
        correlation: null,
        analystPerformance: null,
        alerting: null,
        anomaly: null
    },
    costOptimization: {
        enabled: false,
        stats: null,
        config: null
    },
    pnlData: {
        realizedPnl: 0,
        unrealizedPnl: 0,
        totalPnl: 0,
        netProfit: 0,
        apiCosts: 0,
        byPair: {}
    },
    apiUsage: {
        totalCalls: 0,
        totalTokens: 0,
        totalCost: 0,
        costToday: 0
    }
};

// ============================================================================
// Toast Notification System
// ============================================================================

class ToastManager {
    constructor(containerId = 'toastContainer') {
        this.container = document.getElementById(containerId);
        this.queue = [];
        this.isShowing = false;
    }

    show(message, type = 'info', duration = CONFIG.TOAST_DURATION) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        const iconMap = {
            success: 'check-circle',
            error: 'x-circle',
            warning: 'alert-triangle',
            info: 'info'
        };

        toast.innerHTML = `
            <i data-lucide="${iconMap[type] || 'info'}" class="toast-icon" aria-hidden="true"></i>
            <span class="toast-message">${message}</span>
            <button class="toast-close" aria-label="Close notification">
                <i data-lucide="x" aria-hidden="true"></i>
            </button>
        `;

        // Initialize icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons({ icons: toast.querySelectorAll('[data-lucide]') });
        }

        // Close button handler
        toast.querySelector('.toast-close').addEventListener('click', () => {
            this.dismiss(toast);
        });

        this.container.appendChild(toast);

        // Trigger enter animation
        requestAnimationFrame(() => {
            toast.classList.add('toast-enter');
        });

        // Auto dismiss
        setTimeout(() => this.dismiss(toast), duration);

        // Haptic feedback on mobile
        if ('vibrate' in navigator && type === 'success') {
            navigator.vibrate(50);
        }

        return toast;
    }

    dismiss(toast) {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), CONFIG.ANIMATION_DURATION);
    }

    success(message) { return this.show(message, 'success'); }
    error(message) { return this.show(message, 'error'); }
    warning(message) { return this.show(message, 'warning'); }
    info(message) { return this.show(message, 'info'); }
}

const toast = new ToastManager();

// ============================================================================
// Theme Management
// ============================================================================

function initTheme() {
    // Check localStorage first, then system preference
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        document.documentElement.setAttribute('data-theme', 'light');
    }
    // Default is dark (no attribute needed)
}

function initThemeToggle() {
    const themeToggle = document.getElementById('themeToggle');
    if (!themeToggle) return;

    themeToggle.addEventListener('click', toggleTheme);

    // Listen for system theme changes
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
            if (!localStorage.getItem('theme')) {
                document.documentElement.setAttribute('data-theme', e.matches ? 'light' : 'dark');
                updateLucideIcons();
            }
        });
    }
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';

    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);

    // Re-initialize Lucide icons to update
    updateLucideIcons();

    // Show feedback
    toast.info(`Switched to ${newTheme} mode`);
}

function updateLucideIcons() {
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// ============================================================================
// Skeleton Loading System
// ============================================================================

function showSkeletons() {
    document.querySelectorAll('.skeleton').forEach(el => {
        el.style.display = 'block';
    });
    document.querySelectorAll('[data-skeleton-target]').forEach(el => {
        el.style.visibility = 'hidden';
    });
}

function hideSkeletons() {
    document.querySelectorAll('.skeleton').forEach(el => {
        el.style.display = 'none';
    });
    document.querySelectorAll('[data-skeleton-target]').forEach(el => {
        el.style.visibility = 'visible';
    });

    // Hide chart loading
    const chartLoading = document.getElementById('chartLoading');
    if (chartLoading) chartLoading.style.display = 'none';
}

// ============================================================================
// CountUp Animation
// ============================================================================

function animateValue(element, start, end, duration = 500) {
    if (!element || typeof end !== 'number') return;

    // Check for reduced motion preference
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        element.textContent = formatNumber(end);
        return;
    }

    const startTime = performance.now();
    const startVal = parseFloat(start) || 0;

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);

        // Ease out quad
        const eased = 1 - (1 - progress) * (1 - progress);
        const current = startVal + (end - startVal) * eased;

        element.textContent = formatNumber(current);

        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }

    requestAnimationFrame(update);
}

function formatNumber(num) {
    if (Math.abs(num) >= 1000000) {
        return (num / 1000000).toFixed(2) + 'M';
    } else if (Math.abs(num) >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    } else if (Math.abs(num) < 1) {
        return num.toFixed(4);
    }
    return num.toFixed(2);
}

// ============================================================================
// Sidebar Management
// ============================================================================

function initSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const menuToggle = document.getElementById('menuToggle');
    const closeSidebar = document.getElementById('closeSidebar');

    if (menuToggle) {
        menuToggle.addEventListener('click', () => toggleSidebar(true));
    }

    if (closeSidebar) {
        closeSidebar.addEventListener('click', () => toggleSidebar(false));
    }

    if (overlay) {
        overlay.addEventListener('click', () => toggleSidebar(false));
    }

    // Sidebar navigation links
    document.querySelectorAll('.sidebar-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const section = link.dataset.section;
            navigateToSection(section);
            toggleSidebar(false);
        });
    });

    // Close on escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && state.sidebarOpen) {
            toggleSidebar(false);
        }
    });
}

function toggleSidebar(open) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const menuToggle = document.getElementById('menuToggle');

    state.sidebarOpen = open;

    if (open) {
        sidebar.classList.add('open');
        overlay.classList.add('active');
        menuToggle.setAttribute('aria-expanded', 'true');
        document.body.style.overflow = 'hidden';
    } else {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
        menuToggle.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
    }
}

// ============================================================================
// Bottom Navigation
// ============================================================================

function initBottomNav() {
    document.querySelectorAll('.bottom-nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const section = item.dataset.section;
            navigateToSection(section);
            updateActiveNav(section);

            // Haptic feedback
            if ('vibrate' in navigator) {
                navigator.vibrate(10);
            }
        });
    });
}

function updateActiveNav(section) {
    state.activeNavSection = section;

    // Update bottom nav
    document.querySelectorAll('.bottom-nav-item').forEach(item => {
        if (item.dataset.section === section) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    // Update sidebar nav
    document.querySelectorAll('.sidebar-link').forEach(link => {
        if (link.dataset.section === section) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
}

function navigateToSection(section) {
    const sectionMap = {
        'metrics': 'metrics-section',
        'pnl': 'pnl-section',
        'chart': 'chart-section',
        'trades': 'trades-section',
        'status': 'status-section',
        'phase2': 'phase2-section',
        'intel': 'phase2-section',
        'cost': 'cost-section'
    };

    const targetId = sectionMap[section] || `${section}-section`;
    const target = document.getElementById(targetId);

    if (target) {
        // Expand section if collapsed
        const content = target.querySelector('.section-content');
        if (content && state.collapsedSections.has(section)) {
            toggleSection(section, true);
        }

        // Smooth scroll
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// ============================================================================
// Section Collapse/Expand
// ============================================================================

function initSectionCollapse() {
    document.querySelectorAll('.section-header.collapsible').forEach(header => {
        header.addEventListener('click', (e) => {
            if (e.target.closest('.section-toggle')) {
                const section = header.dataset.section;
                toggleSection(section);
            }
        });

        const toggleBtn = header.querySelector('.section-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const section = header.dataset.section;
                toggleSection(section);
            });
        }
    });
}

function toggleSection(section, forceOpen = null) {
    const header = document.querySelector(`.section-header[data-section="${section}"]`);
    if (!header) return;

    const content = header.nextElementSibling;
    const toggle = header.querySelector('.section-toggle');
    const isCollapsed = forceOpen === null ? !state.collapsedSections.has(section) : !forceOpen;

    if (isCollapsed) {
        state.collapsedSections.add(section);
        content.classList.add('collapsed');
        toggle.setAttribute('aria-expanded', 'false');
        header.classList.add('collapsed');
    } else {
        state.collapsedSections.delete(section);
        content.classList.remove('collapsed');
        toggle.setAttribute('aria-expanded', 'true');
        header.classList.remove('collapsed');
    }
}

// ============================================================================
// Floating Action Button (FAB)
// ============================================================================

function initFAB() {
    const fab = document.getElementById('fabButton');
    const fabMenu = document.getElementById('fabMenu');

    if (!fab || !fabMenu) return;

    fab.addEventListener('click', () => toggleFAB());

    // FAB menu items
    const fabTrigger = document.getElementById('fabTrigger');
    const fabPause = document.getElementById('fabPause');
    const fabRefresh = document.getElementById('fabRefresh');

    if (fabTrigger) {
        fabTrigger.addEventListener('click', () => {
            toggleFAB(false);
            triggerTradingCycle();
        });
    }

    if (fabPause) {
        fabPause.addEventListener('click', () => {
            toggleFAB(false);
            if (state.paused) {
                resumeTrading();
            } else {
                pauseTrading();
            }
        });
    }

    if (fabRefresh) {
        fabRefresh.addEventListener('click', () => {
            toggleFAB(false);
            loadDashboard();
        });
    }

    // Close on outside click
    document.addEventListener('click', (e) => {
        if (state.fabOpen && !e.target.closest('.fab') && !e.target.closest('.fab-menu')) {
            toggleFAB(false);
        }
    });

    // Close on escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && state.fabOpen) {
            toggleFAB(false);
        }
    });
}

function toggleFAB(open = null) {
    const fab = document.getElementById('fabButton');
    const fabMenu = document.getElementById('fabMenu');

    state.fabOpen = open === null ? !state.fabOpen : open;

    if (state.fabOpen) {
        fab.classList.add('active');
        fabMenu.classList.add('open');
        fab.setAttribute('aria-expanded', 'true');
        fabMenu.setAttribute('aria-hidden', 'false');
    } else {
        fab.classList.remove('active');
        fabMenu.classList.remove('open');
        fab.setAttribute('aria-expanded', 'false');
        fabMenu.setAttribute('aria-hidden', 'true');
    }
}

// ============================================================================
// Notification Panel
// ============================================================================

function initNotificationPanel() {
    const btn = document.getElementById('notificationBtn');
    const panel = document.getElementById('notificationPanel');
    const clearBtn = document.getElementById('clearNotifications');

    if (!btn || !panel) return;

    btn.addEventListener('click', () => toggleNotificationPanel());

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            state.notifications = [];
            updateNotificationList();
            updateNotificationBadge();
        });
    }

    // Close on outside click
    document.addEventListener('click', (e) => {
        if (state.notificationPanelOpen &&
            !e.target.closest('.notification-panel') &&
            !e.target.closest('#notificationBtn')) {
            toggleNotificationPanel(false);
        }
    });
}

function toggleNotificationPanel(open = null) {
    const panel = document.getElementById('notificationPanel');
    const btn = document.getElementById('notificationBtn');

    state.notificationPanelOpen = open === null ? !state.notificationPanelOpen : open;

    if (state.notificationPanelOpen) {
        panel.classList.add('open');
        panel.setAttribute('aria-hidden', 'false');
        btn.setAttribute('aria-expanded', 'true');
    } else {
        panel.classList.remove('open');
        panel.setAttribute('aria-hidden', 'true');
        btn.setAttribute('aria-expanded', 'false');
    }
}

function addNotification(message, type = 'info') {
    state.notifications.unshift({
        id: Date.now(),
        message,
        type,
        time: new Date()
    });

    // Keep only last 50
    if (state.notifications.length > 50) {
        state.notifications = state.notifications.slice(0, 50);
    }

    updateNotificationList();
    updateNotificationBadge();
}

function updateNotificationList() {
    const list = document.getElementById('notificationList');
    if (!list) return;

    if (state.notifications.length === 0) {
        list.innerHTML = `
            <div class="notification-empty">
                <i data-lucide="inbox" aria-hidden="true"></i>
                <p>No notifications</p>
            </div>
        `;
    } else {
        list.innerHTML = state.notifications.map(n => `
            <div class="notification-item notification-${n.type}">
                <div class="notification-content">
                    <p>${n.message}</p>
                    <span class="notification-time">${formatTimeAgo(n.time)}</span>
                </div>
            </div>
        `).join('');
    }

    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function updateNotificationBadge() {
    const badge = document.getElementById('notificationBadge');
    if (!badge) return;

    const count = state.notifications.length;
    if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.style.display = 'flex';
    } else {
        badge.style.display = 'none';
    }
}

function formatTimeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

// ============================================================================
// Circular Gauge Updates
// ============================================================================

function updateGauge(gaugeId, value, max = 100) {
    const gauge = document.getElementById(gaugeId);
    if (!gauge) return;

    const fill = gauge.querySelector('.gauge-fill');
    if (!fill) return;

    const percentage = Math.min(Math.max(value / max * 100, 0), 100);
    fill.setAttribute('stroke-dasharray', `${percentage}, 100`);

    // Color based on value
    if (percentage >= 80) {
        fill.style.stroke = 'var(--accent-magenta)';
    } else if (percentage >= 50) {
        fill.style.stroke = 'var(--accent-cyan)';
    } else {
        fill.style.stroke = 'var(--success)';
    }
}

// ============================================================================
// Quick Stats Bar Updates
// ============================================================================

function updateQuickStats() {
    if (!state.portfolio || !state.performance) return;

    const totalValue = state.portfolio.total_value || 0;
    const totalPnL = totalValue - CONFIG.INITIAL_CAPITAL;
    const winRate = state.performance.win_rate ? (state.performance.win_rate * 100) : 0;
    const totalTrades = state.performance.total_trades || 0;

    // Quick P&L
    const quickPnL = document.getElementById('quickPnL');
    if (quickPnL) {
        quickPnL.textContent = `${totalPnL >= 0 ? '+' : ''}${formatCurrency(totalPnL)}`;
        quickPnL.className = `quick-stat-value ${totalPnL >= 0 ? 'positive' : 'negative'}`;
    }

    // Quick Portfolio
    const quickPortfolio = document.getElementById('quickPortfolio');
    if (quickPortfolio) {
        quickPortfolio.textContent = formatCurrency(totalValue);
    }

    // Quick Win Rate
    const quickWinRate = document.getElementById('quickWinRate');
    if (quickWinRate) {
        quickWinRate.textContent = `${winRate.toFixed(0)}%`;
    }

    // Quick Trades
    const quickTrades = document.getElementById('quickTrades');
    if (quickTrades) {
        quickTrades.textContent = totalTrades;
    }

    // Update Hero Section
    updateHeroSection(totalValue, totalPnL, state.portfolio);
}

// ============================================================================
// Portfolio Hero Section Update
// ============================================================================

function updateHeroSection(totalValue, totalPnL, portfolio) {
    const availableQuote = portfolio?.available_quote || 0;
    const progressToTarget = portfolio?.progress_to_target || 0;
    const targetValue = CONFIG.TARGET_CAPITAL || 5000;
    const pnlPercent = totalValue > 0 ? ((totalPnL / CONFIG.INITIAL_CAPITAL) * 100) : 0;

    // Portfolio Value
    const heroPortfolioValue = document.getElementById('heroPortfolioValue');
    if (heroPortfolioValue) {
        heroPortfolioValue.textContent = formatCurrency(totalValue);
    }

    // Available Quote
    const heroAvailableQuote = document.getElementById('heroAvailableQuote');
    if (heroAvailableQuote) {
        heroAvailableQuote.innerHTML = `Available: <span class="font-mono">${formatCurrency(availableQuote)}</span>`;
    }

    // P&L Value
    const heroPnLValue = document.getElementById('heroPnLValue');
    if (heroPnLValue) {
        heroPnLValue.textContent = `${totalPnL >= 0 ? '+' : ''}${formatCurrency(totalPnL)}`;
        heroPnLValue.className = `hero-value font-mono ${totalPnL >= 0 ? 'positive' : 'negative'}`;
    }

    // P&L Percent Badge
    const heroPnLPercent = document.getElementById('heroPnLPercent');
    if (heroPnLPercent) {
        heroPnLPercent.textContent = `${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(1)}%`;
        heroPnLPercent.className = `hero-pnl-percent cyber-badge ${pnlPercent >= 0 ? 'success' : 'danger'}`;
    }

    // P&L Bar
    const heroPnLBar = document.getElementById('heroPnLBar');
    if (heroPnLBar) {
        // Scale: -100% to +100% maps to 0% to 100% width from center
        const barWidth = Math.min(Math.abs(pnlPercent) / 2, 50);
        if (pnlPercent >= 0) {
            heroPnLBar.style.width = `${barWidth}%`;
            heroPnLBar.style.display = 'block';
            const negBar = document.querySelector('.pnl-bar-negative');
            if (negBar) negBar.style.width = '0';
        } else {
            heroPnLBar.style.width = '0';
            const negBar = document.querySelector('.pnl-bar-negative');
            if (negBar) negBar.style.width = `${barWidth}%`;
        }
    }

    // Target Progress
    const heroTargetCurrent = document.getElementById('heroTargetCurrent');
    if (heroTargetCurrent) {
        heroTargetCurrent.textContent = formatCompactCurrency(totalValue);
    }

    const heroTargetGoal = document.getElementById('heroTargetGoal');
    if (heroTargetGoal) {
        heroTargetGoal.textContent = formatCompactCurrency(targetValue);
    }

    const heroTargetBar = document.getElementById('heroTargetBar');
    if (heroTargetBar) {
        heroTargetBar.style.width = `${Math.min(progressToTarget, 100)}%`;
    }

    const heroTargetPercent = document.getElementById('heroTargetPercent');
    if (heroTargetPercent) {
        heroTargetPercent.textContent = `${progressToTarget.toFixed(1)}%`;
    }
}

// Format currency in compact form (e.g., $1.5K, $2.3M)
function formatCompactCurrency(value) {
    if (value >= 1000000) {
        return `$${(value / 1000000).toFixed(1)}M`;
    } else if (value >= 1000) {
        return `$${(value / 1000).toFixed(1)}K`;
    }
    return `$${value.toFixed(0)}`;
}

// Update AI Status in Hero
async function updateHeroAIStatus() {
    try {
        const response = await fetch('/api/ai/cycle/current');
        if (!response.ok) return;

        const data = await response.json();

        // Cycle count
        const heroAiCycle = document.getElementById('heroAiCycle');
        if (heroAiCycle) {
            heroAiCycle.textContent = `#${data.cycle_count || 0}`;
        }

        // AI State
        const heroAiState = document.getElementById('heroAiState');
        const heroAiPulse = document.getElementById('heroAiPulse');
        if (heroAiState) {
            if (data.is_paused) {
                heroAiState.textContent = 'PAUSED';
                heroAiState.className = 'hero-ai-state font-mono paused';
                if (heroAiPulse) heroAiPulse.className = 'pulse-indicator danger';
            } else if (data.scheduler_running) {
                heroAiState.textContent = 'ACTIVE';
                heroAiState.className = 'hero-ai-state font-mono';
                if (heroAiPulse) heroAiPulse.className = 'pulse-indicator';
            } else {
                heroAiState.textContent = 'STOPPED';
                heroAiState.className = 'hero-ai-state font-mono error';
                if (heroAiPulse) heroAiPulse.className = 'pulse-indicator danger';
            }
        }

        // Next cycle countdown
        const heroAiNext = document.getElementById('heroAiNext');
        if (heroAiNext && data.seconds_until_next !== null) {
            const mins = Math.floor(data.seconds_until_next / 60);
            const secs = data.seconds_until_next % 60;
            heroAiNext.textContent = `${mins}m ${secs}s`;
        }
    } catch (e) {
        console.warn('Failed to update AI status:', e);
    }
}

// Update hero countdown tile
async function updateHeroCountdownTile() {
    try {
        const response = await fetch('/api/ai/cycle/current');
        if (!response.ok) return;

        const data = await response.json();
        const secondsUntilNext = data.seconds_until_next;

        if (secondsUntilNext === null || secondsUntilNext === undefined) return;

        // Update digital countdown
        const minsEl = document.getElementById('countdownMins');
        const secsEl = document.getElementById('countdownSecs');
        if (minsEl && secsEl) {
            const mins = Math.floor(secondsUntilNext / 60);
            const secs = secondsUntilNext % 60;
            minsEl.textContent = String(mins).padStart(2, '0');
            secsEl.textContent = String(secs).padStart(2, '0');
        }

        // Update progress ring (assuming 60 minute cycle)
        const totalSeconds = 60 * 60; // 1 hour
        const elapsed = totalSeconds - secondsUntilNext;
        const progress = Math.min(100, (elapsed / totalSeconds) * 100);
        const circumference = 2 * Math.PI * 16; // r=16
        const offset = circumference - (progress / 100) * circumference;

        const ring = document.getElementById('countdownRing');
        const percentEl = document.getElementById('countdownPercent');
        if (ring) {
            ring.style.strokeDasharray = `${circumference} ${circumference}`;
            ring.style.strokeDashoffset = offset;
        }
        if (percentEl) {
            percentEl.textContent = `${Math.round(progress)}%`;
        }

        // Update urgency state
        const countdownCard = document.querySelector('.hero-countdown');
        if (countdownCard) {
            countdownCard.classList.remove('urgent', 'imminent');
            if (secondsUntilNext <= 60) {
                countdownCard.classList.add('imminent');
            } else if (secondsUntilNext <= 300) {
                countdownCard.classList.add('urgent');
            }
        }
    } catch (e) {
        console.warn('Failed to update countdown tile:', e);
    }
}

// ============================================================================
// Holdings Sidebar
// ============================================================================

async function loadHoldingsSidebar() {
    try {
        const response = await fetch('/portfolio');
        if (!response.ok) return;

        const data = await response.json();
        renderHoldingsList(data);
        updateSidebarCountdown();
    } catch (e) {
        console.warn('Failed to load holdings sidebar:', e);
    }
}

function renderHoldingsList(portfolio) {
    const container = document.getElementById('holdingsList');
    if (!container) return;

    const holdings = [];

    // Add AUD (quote currency) first
    if (portfolio.available_quote > 0) {
        holdings.push({
            symbol: 'AUD',
            value: portfolio.available_quote,
            quantity: portfolio.available_quote,
            isQuote: true
        });
    }

    // Add crypto positions
    if (portfolio.positions) {
        for (const pos of portfolio.positions) {
            if (pos.quantity > 0) {
                const symbol = pos.pair ? pos.pair.replace('/AUD', '') : pos.asset;
                holdings.push({
                    symbol: symbol,
                    value: pos.current_value || pos.value || 0,
                    quantity: pos.quantity,
                    pnl: pos.unrealized_pnl || 0,
                    isQuote: false
                });
            }
        }
    }

    // Also check holdings object
    if (portfolio.holdings) {
        for (const [asset, qty] of Object.entries(portfolio.holdings)) {
            if (qty > 0 && asset !== 'AUD' && !holdings.find(h => h.symbol === asset)) {
                holdings.push({
                    symbol: asset,
                    value: qty, // Will show quantity as value if no price data
                    quantity: qty,
                    isQuote: false
                });
            }
        }
    }

    if (holdings.length === 0) {
        container.innerHTML = '<div class="holdings-empty">No holdings</div>';
        return;
    }

    container.innerHTML = holdings.map(h => {
        const pnlClass = h.pnl > 0 ? 'positive' : h.pnl < 0 ? 'negative' : '';
        const pnlStr = h.pnl ? `<span class="holding-pnl ${pnlClass}">${h.pnl >= 0 ? '+' : ''}${formatCurrency(h.pnl)}</span>` : '';

        return `
            <div class="holding-item ${h.isQuote ? 'quote-holding' : 'asset-holding'}">
                <span class="holding-symbol">${h.symbol}</span>
                <div class="holding-details">
                    <span class="holding-value">${formatCurrency(h.value)}</span>
                    ${!h.isQuote ? `<span class="holding-qty">${h.quantity.toFixed(6)}</span>` : ''}
                    ${pnlStr}
                </div>
            </div>
        `;
    }).join('');
}

async function updateSidebarCountdown() {
    try {
        const response = await fetch('/api/ai/cycle/current');
        if (!response.ok) return;

        const data = await response.json();

        // Update countdown timer
        const timerEl = document.getElementById('sidebarCountdown');
        if (timerEl && data.seconds_until_next !== null && data.seconds_until_next !== undefined) {
            const mins = Math.floor(data.seconds_until_next / 60);
            const secs = data.seconds_until_next % 60;
            timerEl.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
        }

        // Update status
        const statusEl = document.getElementById('sidebarStatus');
        if (statusEl) {
            if (data.is_paused) {
                statusEl.innerHTML = '<span class="pulse-indicator danger"></span><span>PAUSED</span>';
                statusEl.className = 'countdown-status paused';
            } else if (data.scheduler_running) {
                statusEl.innerHTML = '<span class="pulse-indicator"></span><span>ACTIVE</span>';
                statusEl.className = 'countdown-status';
            } else {
                statusEl.innerHTML = '<span class="pulse-indicator danger"></span><span>STOPPED</span>';
                statusEl.className = 'countdown-status stopped';
            }
        }
    } catch (e) {
        console.warn('Failed to update sidebar countdown:', e);
    }
}

// ============================================================================
// AI Activity Feed
// ============================================================================

async function loadAIActivity() {
    try {
        const response = await fetch('/api/ai/activity?limit=10');
        if (!response.ok) return;

        const data = await response.json();
        renderAIActivityFeed(data.cycles || []);

        // Update the next cycle timer in the section header
        updateAINextCycleTimer();
    } catch (e) {
        console.warn('Failed to load AI activity:', e);
    }
}

function renderAIActivityFeed(cycles) {
    const feed = document.getElementById('aiActivityFeed');
    if (!feed) return;

    if (!cycles || cycles.length === 0) {
        feed.innerHTML = `
            <div class="ai-activity-empty">
                <i data-lucide="brain" aria-hidden="true"></i>
                <p>No AI activity yet. Waiting for first trading cycle...</p>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    feed.innerHTML = cycles.map((cycle, index) => {
        const timestamp = new Date(cycle.timestamp);
        const timeStr = timestamp.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' });
        const dateStr = timestamp.toLocaleDateString('en-AU', { month: 'short', day: 'numeric' });
        const isExpanded = index === 0; // First entry expanded by default

        return `
            <div class="ai-cycle-entry ${isExpanded ? 'expanded' : ''}" data-cycle-id="${cycle.cycle_id || index}">
                <div class="cycle-header" onclick="toggleCycleExpand(this.parentElement)">
                    <div class="cycle-info">
                        <div class="cycle-icon">
                            <i data-lucide="activity" aria-hidden="true"></i>
                        </div>
                        <div>
                            <div class="cycle-time">${timeStr} · ${dateStr}</div>
                            <div class="cycle-number">Cycle #${cycle.cycle_count || (cycles.length - index)}</div>
                        </div>
                    </div>
                    <div class="cycle-status">
                        <span class="cycle-status-badge ${cycle.status || 'completed'}">${(cycle.status || 'completed').toUpperCase()}</span>
                        <i data-lucide="chevron-down" class="cycle-expand-icon" aria-hidden="true"></i>
                    </div>
                </div>
                <div class="cycle-body">
                    <div class="cycle-decisions">
                        ${renderCycleDecisions(cycle.decisions || [])}
                    </div>
                    ${cycle.portfolio_value_after ? `
                        <div class="cycle-summary">
                            <span class="cycle-summary-label">Portfolio After</span>
                            <span class="cycle-summary-value ${(cycle.portfolio_change || 0) >= 0 ? 'positive' : 'negative'}">
                                ${formatCurrency(cycle.portfolio_value_after)}
                                (${cycle.portfolio_change >= 0 ? '+' : ''}${(cycle.portfolio_change || 0).toFixed(2)}%)
                            </span>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderCycleDecisions(decisions) {
    if (!decisions || decisions.length === 0) {
        return '<div class="decision-reasoning">No trading decisions in this cycle.</div>';
    }

    return decisions.map(decision => {
        const confidencePercent = Math.round((decision.confidence || 0) * 100);
        const action = decision.action || 'HOLD';

        return `
            <div class="cycle-decision action-${action}">
                <div class="decision-header">
                    <span class="decision-pair">${decision.pair || 'Unknown'}</span>
                    <div class="decision-action">
                        <span class="decision-action-badge ${action}">${action}</span>
                        <span class="decision-confidence">${confidencePercent}%</span>
                    </div>
                </div>
                ${decision.reasoning ? `
                    <div class="decision-reasoning">"${decision.reasoning}"</div>
                ` : ''}
                ${decision.analysts ? renderAnalystChips(decision.analysts) : ''}
            </div>
        `;
    }).join('');
}

function renderAnalystChips(analysts) {
    if (!analysts || Object.keys(analysts).length === 0) return '';

    const chips = Object.entries(analysts).map(([name, data]) => {
        const direction = data.direction || 0;
        const directionClass = direction > 0.1 ? 'positive' : direction < -0.1 ? 'negative' : 'neutral';
        const directionStr = direction > 0 ? `+${direction.toFixed(2)}` : direction.toFixed(2);

        return `
            <span class="analyst-chip">
                <span class="analyst-name">${name}</span>
                <span class="analyst-direction ${directionClass}">${directionStr}</span>
            </span>
        `;
    }).join('');

    return `<div class="decision-analysts">${chips}</div>`;
}

function toggleCycleExpand(entry) {
    if (!entry) return;
    entry.classList.toggle('expanded');
}

async function updateAINextCycleTimer() {
    try {
        const response = await fetch('/api/ai/cycle/current');
        if (!response.ok) return;

        const data = await response.json();
        const timer = document.getElementById('aiNextCycleTimer');

        if (timer && data.seconds_until_next !== null && data.seconds_until_next !== undefined) {
            const mins = Math.floor(data.seconds_until_next / 60);
            const secs = data.seconds_until_next % 60;
            timer.textContent = `Next: ${mins}m ${secs}s`;
        }
    } catch (e) {
        console.warn('Failed to update AI timer:', e);
    }
}

// ============================================================================
// Trading Pair Cards with Mini Charts
// ============================================================================

// Store mini chart instances
const miniCharts = {};

async function loadPairCards() {
    try {
        // Fetch positions and market data
        const [positionsRes, statusRes] = await Promise.all([
            fetch('/api/positions/detailed'),
            fetch('/status')
        ]);

        const positionsData = positionsRes.ok ? await positionsRes.json() : { positions: [] };
        const statusData = statusRes.ok ? await statusRes.json() : {};

        // Get trading pairs from config or default
        const pairs = ['BTC/AUD', 'ETH/AUD', 'SOL/AUD', 'LINK/AUD', 'DOT/AUD', 'AVAX/AUD', 'ADA/AUD', 'ATOM/AUD', 'XRP/AUD'];

        // Build positions map
        const positionsMap = {};
        if (positionsData.positions) {
            for (const pos of positionsData.positions) {
                positionsMap[pos.pair] = pos;
            }
        }

        renderPairCards(pairs, positionsMap);
    } catch (e) {
        console.warn('Failed to load pair cards:', e);
    }
}

function renderPairCards(pairs, positionsMap) {
    const grid = document.getElementById('pairsGrid');
    if (!grid) return;

    grid.innerHTML = pairs.map(pair => {
        const position = positionsMap[pair];
        const hasPosition = position && position.quantity > 0;
        const symbol = pair.replace('/AUD', '');

        return `
            <div class="pair-card ${hasPosition ? 'has-position' : ''}" data-pair="${pair}" onclick="openChartModal('${pair}')">
                <div class="pair-header">
                    <div class="pair-info">
                        <span class="pair-symbol">${symbol}</span>
                        <span class="pair-price" id="price-${symbol}">--</span>
                    </div>
                    <span class="pair-change neutral" id="change-${symbol}">0.0%</span>
                </div>
                <div class="pair-chart-container" id="chart-${symbol}"></div>
                ${hasPosition ? `
                    <div class="pair-position">
                        <span class="position-badge">POSITION</span>
                        <div class="position-info">
                            <span class="position-size">${position.quantity.toFixed(6)} ${symbol}</span>
                            <span class="position-pnl ${position.unrealized_pnl >= 0 ? 'positive' : 'negative'}">
                                ${position.unrealized_pnl >= 0 ? '+' : ''}${formatCurrency(position.unrealized_pnl)}
                            </span>
                        </div>
                    </div>
                ` : `
                    <div class="pair-footer">
                        <span class="pair-footer-text">No Position</span>
                    </div>
                `}
            </div>
        `;
    }).join('');

    // Initialize mini charts for each pair
    pairs.forEach(pair => {
        initMiniChart(pair, positionsMap[pair]);
    });

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function initMiniChart(pair, position) {
    const symbol = pair.replace('/AUD', '');
    const container = document.getElementById(`chart-${symbol}`);
    if (!container) return;

    // Check if TradingView Lightweight Charts is available
    if (typeof LightweightCharts === 'undefined') {
        console.warn('LightweightCharts not loaded');
        return;
    }

    // Fetch OHLCV data
    try {
        const response = await fetch(`/api/market/ohlcv/${encodeURIComponent(pair)}?interval=60&limit=48`);
        if (!response.ok) return;

        const data = await response.json();
        if (!data.candles || data.candles.length === 0) return;

        // Clear container
        container.innerHTML = '';

        // Get computed styles for theme colors
        const computedStyle = getComputedStyle(document.documentElement);
        const bgColor = computedStyle.getPropertyValue('--bg-secondary').trim() || '#FFFFFF';
        const textColor = computedStyle.getPropertyValue('--text-muted').trim() || '#6B7280';
        const successColor = computedStyle.getPropertyValue('--success').trim() || '#00FF88';
        const dangerColor = computedStyle.getPropertyValue('--danger').trim() || '#FF4757';
        const cyanColor = computedStyle.getPropertyValue('--accent-cyan').trim() || '#00D4FF';

        // Create chart
        const chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: container.clientHeight,
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: textColor
            },
            grid: {
                vertLines: { visible: false },
                horzLines: { visible: false }
            },
            timeScale: {
                visible: false,
                borderVisible: false
            },
            rightPriceScale: {
                visible: false,
                borderVisible: false
            },
            leftPriceScale: {
                visible: false
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Hidden
            },
            handleScroll: false,
            handleScale: false
        });

        // Add area series for the price line
        const areaSeries = chart.addAreaSeries({
            lineColor: cyanColor,
            topColor: `${cyanColor}40`,
            bottomColor: `${cyanColor}05`,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false
        });

        // Format data for TradingView
        // Candles are [time, open, high, low, close, volume]
        const chartData = data.candles.map(candle => ({
            time: candle[0],
            value: candle[4]  // close price
        }));

        areaSeries.setData(chartData);

        // Add entry price line if position exists
        if (position && position.entry_price) {
            areaSeries.createPriceLine({
                price: position.entry_price,
                color: successColor,
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: false
            });
        }

        // Add stop-loss line if exists
        if (position && position.stop_loss_price) {
            areaSeries.createPriceLine({
                price: position.stop_loss_price,
                color: dangerColor,
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: false
            });
        }

        // Fit content
        chart.timeScale().fitContent();

        // Store chart instance
        miniCharts[pair] = chart;

        // Update price display
        // Candles are [time, open, high, low, close, volume]
        const lastCandle = data.candles[data.candles.length - 1];
        const firstCandle = data.candles[0];
        updatePairPriceDisplay(symbol, lastCandle[4], firstCandle[4]);  // close prices

        // Handle resize
        const resizeObserver = new ResizeObserver(() => {
            chart.applyOptions({
                width: container.clientWidth,
                height: container.clientHeight
            });
        });
        resizeObserver.observe(container);

    } catch (e) {
        console.warn(`Failed to load chart for ${pair}:`, e);
    }
}

function updatePairPriceDisplay(symbol, currentPrice, openPrice) {
    const priceEl = document.getElementById(`price-${symbol}`);
    const changeEl = document.getElementById(`change-${symbol}`);

    if (priceEl) {
        priceEl.textContent = formatCurrency(currentPrice);
    }

    if (changeEl && openPrice) {
        const change = ((currentPrice - openPrice) / openPrice) * 100;
        const changeClass = change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral';
        changeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(1)}%`;
        changeEl.className = `pair-change ${changeClass}`;
    }
}

// Chart modal state
let fullChart = null;
let volumeChart = null;
let currentChartPair = null;
let currentChartInterval = 1440; // Default 1D

async function openChartModal(pair) {
    const modal = document.getElementById('chartModal');
    if (!modal) return;

    currentChartPair = pair;
    currentChartInterval = 1440;

    // Update modal header
    document.getElementById('chartModalPair').textContent = pair;

    // Show modal
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';

    // Load chart data
    await loadFullChart(pair, currentChartInterval);

    // Load sidebar data
    loadChartSidebar(pair);

    // Set up time selector
    setupChartTimeSelector();

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function closeChartModal() {
    const modal = document.getElementById('chartModal');
    if (!modal) return;

    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';

    // Cleanup charts
    if (fullChart) {
        fullChart.remove();
        fullChart = null;
    }
    if (volumeChart) {
        volumeChart.remove();
        volumeChart = null;
    }

    currentChartPair = null;
}

async function loadFullChart(pair, interval) {
    const container = document.getElementById('chartFullContainer');
    const volumeContainer = document.getElementById('chartVolumeContainer');
    if (!container || !LightweightCharts) return;

    // Cleanup existing charts
    if (fullChart) {
        fullChart.remove();
        fullChart = null;
    }
    if (volumeChart) {
        volumeChart.remove();
        volumeChart = null;
    }

    try {
        const response = await fetch(`/api/market/ohlcv/${encodeURIComponent(pair)}?interval=${interval}&limit=200`);
        if (!response.ok) return;

        const data = await response.json();
        if (!data.candles || data.candles.length === 0) return;

        // Get theme colors
        const computedStyle = getComputedStyle(document.documentElement);
        const bgColor = computedStyle.getPropertyValue('--bg-primary').trim() || '#F8F9FC';
        const textColor = computedStyle.getPropertyValue('--text-muted').trim() || '#6B7280';
        const successColor = computedStyle.getPropertyValue('--success').trim() || '#00FF88';
        const dangerColor = computedStyle.getPropertyValue('--danger').trim() || '#FF4757';
        const cyanColor = computedStyle.getPropertyValue('--accent-cyan').trim() || '#00D4FF';
        const gridColor = computedStyle.getPropertyValue('--border-color').trim() || '#E5E7EB';

        // Create main chart
        fullChart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: container.clientHeight,
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: textColor
            },
            grid: {
                vertLines: { color: `${gridColor}40` },
                horzLines: { color: `${gridColor}40` }
            },
            timeScale: {
                borderColor: gridColor,
                timeVisible: true,
                secondsVisible: false
            },
            rightPriceScale: {
                borderColor: gridColor
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    color: cyanColor,
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed
                },
                horzLine: {
                    color: cyanColor,
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed
                }
            }
        });

        // Add candlestick series
        const candleSeries = fullChart.addCandlestickSeries({
            upColor: successColor,
            downColor: dangerColor,
            borderUpColor: successColor,
            borderDownColor: dangerColor,
            wickUpColor: successColor,
            wickDownColor: dangerColor
        });

        // Format candle data [time, open, high, low, close, volume]
        const candleData = data.candles.map(c => ({
            time: c[0],
            open: c[1],
            high: c[2],
            low: c[3],
            close: c[4]
        }));

        candleSeries.setData(candleData);

        // Get position data for price lines
        try {
            const posResponse = await fetch('/api/positions/detailed');
            if (posResponse.ok) {
                const posData = await posResponse.json();
                const position = posData.positions?.find(p => p.pair === pair);

                if (position && position.entry_price) {
                    candleSeries.createPriceLine({
                        price: position.entry_price,
                        color: successColor,
                        lineWidth: 2,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title: 'Entry'
                    });
                }

                if (position && position.stop_loss_price) {
                    candleSeries.createPriceLine({
                        price: position.stop_loss_price,
                        color: dangerColor,
                        lineWidth: 2,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title: 'Stop'
                    });
                }
            }
        } catch (e) {
            console.warn('Failed to load position for chart lines:', e);
        }

        // Create volume chart
        volumeChart = LightweightCharts.createChart(volumeContainer, {
            width: volumeContainer.clientWidth,
            height: volumeContainer.clientHeight,
            layout: {
                background: { type: 'solid', color: 'transparent' },
                textColor: textColor
            },
            grid: {
                vertLines: { visible: false },
                horzLines: { visible: false }
            },
            timeScale: {
                visible: false
            },
            rightPriceScale: {
                borderVisible: false
            }
        });

        const volumeSeries = volumeChart.addHistogramSeries({
            color: cyanColor,
            priceFormat: {
                type: 'volume'
            },
            priceScaleId: ''
        });

        const volumeData = data.candles.map(c => ({
            time: c[0],
            value: c[5],
            color: c[4] >= c[1] ? `${successColor}80` : `${dangerColor}80`
        }));

        volumeSeries.setData(volumeData);

        // Sync time scales
        fullChart.timeScale().subscribeVisibleTimeRangeChange(() => {
            volumeChart.timeScale().setVisibleRange(fullChart.timeScale().getVisibleRange());
        });

        fullChart.timeScale().fitContent();
        volumeChart.timeScale().fitContent();

        // Update price display
        const lastCandle = data.candles[data.candles.length - 1];
        const firstCandle = data.candles[0];
        updateChartModalPrice(lastCandle[4], firstCandle[4]);

        // Handle resize
        const resizeObserver = new ResizeObserver(() => {
            fullChart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
            volumeChart.applyOptions({ width: volumeContainer.clientWidth, height: volumeContainer.clientHeight });
        });
        resizeObserver.observe(container);

    } catch (e) {
        console.warn('Failed to load full chart:', e);
    }
}

function updateChartModalPrice(currentPrice, openPrice) {
    const priceEl = document.getElementById('chartModalPrice');
    const changeEl = document.getElementById('chartModalChange');

    if (priceEl) {
        priceEl.textContent = formatCurrency(currentPrice);
    }

    if (changeEl && openPrice) {
        const change = ((currentPrice - openPrice) / openPrice) * 100;
        const changeClass = change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral';
        changeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`;
        changeEl.className = `chart-modal-change ${changeClass} font-mono`;
    }
}

async function loadChartSidebar(pair) {
    // Load position details
    await loadChartPositionDetails(pair);

    // Load AI analysis
    await loadChartAiAnalysis(pair);

    // Load recent trades
    await loadChartRecentTrades(pair);
}

async function loadChartPositionDetails(pair) {
    const container = document.getElementById('chartPositionDetails');
    if (!container) return;

    try {
        const response = await fetch('/api/positions/detailed');
        if (!response.ok) return;

        const data = await response.json();
        const position = data.positions?.find(p => p.pair === pair);

        if (!position || position.quantity <= 0) {
            container.innerHTML = '<div class="position-empty">No active position</div>';
            return;
        }

        const pnlClass = position.unrealized_pnl >= 0 ? 'pnl-positive' : 'pnl-negative';

        container.innerHTML = `
            <div class="position-row">
                <span class="position-label">Quantity</span>
                <span class="position-value">${position.quantity.toFixed(6)}</span>
            </div>
            <div class="position-row">
                <span class="position-label">Entry Price</span>
                <span class="position-value entry">${formatCurrency(position.entry_price)}</span>
            </div>
            <div class="position-row">
                <span class="position-label">Current Value</span>
                <span class="position-value">${formatCurrency(position.current_value)}</span>
            </div>
            <div class="position-row">
                <span class="position-label">Unrealized P&L</span>
                <span class="position-value ${pnlClass}">${position.unrealized_pnl >= 0 ? '+' : ''}${formatCurrency(position.unrealized_pnl)}</span>
            </div>
            ${position.stop_loss_price ? `
                <div class="position-row">
                    <span class="position-label">Stop Loss</span>
                    <span class="position-value stop-loss">${formatCurrency(position.stop_loss_price)}</span>
                </div>
            ` : ''}
        `;
    } catch (e) {
        container.innerHTML = '<div class="position-empty">Failed to load position</div>';
    }
}

async function loadChartAiAnalysis(pair) {
    const container = document.getElementById('chartAiAnalysis');
    if (!container) return;

    try {
        const response = await fetch('/api/ai/activity?limit=5');
        if (!response.ok) return;

        const data = await response.json();
        const relevantDecisions = [];

        // Find decisions for this pair from recent cycles
        for (const cycle of data.cycles || []) {
            for (const decision of cycle.decisions || []) {
                if (decision.pair === pair) {
                    relevantDecisions.push({
                        ...decision,
                        timestamp: cycle.timestamp
                    });
                }
            }
        }

        if (relevantDecisions.length === 0) {
            container.innerHTML = '<div class="analysis-empty">No recent analysis for this pair</div>';
            return;
        }

        container.innerHTML = relevantDecisions.slice(0, 3).map(decision => {
            const time = new Date(decision.timestamp).toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' });
            const confidence = Math.round((decision.confidence || 0) * 100);

            return `
                <div class="analysis-item">
                    <div class="analysis-header">
                        <span class="analysis-action ${decision.action}">${decision.action}</span>
                        <span class="analysis-confidence">${confidence}% @ ${time}</span>
                    </div>
                    <div class="analysis-reasoning">"${decision.reasoning || 'No reasoning provided'}"</div>
                </div>
            `;
        }).join('');

    } catch (e) {
        container.innerHTML = '<div class="analysis-empty">Failed to load analysis</div>';
    }
}

async function loadChartRecentTrades(pair) {
    const container = document.getElementById('chartRecentTrades');
    if (!container) return;

    try {
        const response = await fetch('/history?limit=50');
        if (!response.ok) return;

        const data = await response.json();
        const pairTrades = (data.trades || []).filter(t => t.pair === pair).slice(0, 5);

        if (pairTrades.length === 0) {
            container.innerHTML = '<div class="trades-empty">No trades on this pair</div>';
            return;
        }

        container.innerHTML = pairTrades.map(trade => {
            const time = new Date(trade.timestamp).toLocaleString('en-AU', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
            const action = trade.action.toLowerCase();

            return `
                <div class="trade-item">
                    <div class="trade-info">
                        <div class="trade-action-icon ${action}">
                            <i data-lucide="${action === 'buy' ? 'arrow-up' : 'arrow-down'}" style="width: 14px; height: 14px;"></i>
                        </div>
                        <div class="trade-details">
                            <span class="trade-action-text">${trade.action}</span>
                            <span class="trade-time">${time}</span>
                        </div>
                    </div>
                    <span class="trade-amount">${formatCurrency(trade.total_cost || trade.quantity * trade.price)}</span>
                </div>
            `;
        }).join('');

        if (typeof lucide !== 'undefined') lucide.createIcons();

    } catch (e) {
        container.innerHTML = '<div class="trades-empty">Failed to load trades</div>';
    }
}

function setupChartTimeSelector() {
    const buttons = document.querySelectorAll('.chart-time-btn');
    buttons.forEach(btn => {
        btn.classList.remove('active');
        if (parseInt(btn.dataset.interval) === currentChartInterval) {
            btn.classList.add('active');
        }

        btn.onclick = async () => {
            const interval = parseInt(btn.dataset.interval);
            if (interval === currentChartInterval) return;

            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentChartInterval = interval;

            if (currentChartPair) {
                await loadFullChart(currentChartPair, interval);
            }
        };
    });
}

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const chartModal = document.getElementById('chartModal');
        if (chartModal && chartModal.classList.contains('active')) {
            closeChartModal();
        }
    }
});

// Cleanup mini charts when page changes
function cleanupMiniCharts() {
    Object.values(miniCharts).forEach(chart => {
        if (chart && typeof chart.remove === 'function') {
            chart.remove();
        }
    });
    Object.keys(miniCharts).forEach(key => delete miniCharts[key]);
}

// ============================================================================
// Mobile Trades Card View
// ============================================================================

function updateTradesCards() {
    const container = document.getElementById('tradesCards');
    if (!container) return;

    if (!state.trades || state.trades.length === 0) {
        container.innerHTML = `
            <div class="trade-card empty">
                <p>No trades yet</p>
            </div>
        `;
        return;
    }

    const sortedTrades = [...state.trades].reverse().slice(0, 20);

    container.innerHTML = sortedTrades.map(trade => {
        const timestamp = new Date(trade.timestamp);
        const timeStr = timestamp.toLocaleString();
        const pnl = trade.realized_pnl || 0;
        const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : '';
        const actionClass = trade.action.toLowerCase();

        return `
            <div class="trade-card">
                <div class="trade-card-header">
                    <span class="trade-pair">${trade.pair}</span>
                    <span class="trade-action ${actionClass}">${trade.action}</span>
                </div>
                <div class="trade-card-body">
                    <div class="trade-detail">
                        <span class="trade-label">Price</span>
                        <span class="trade-value">${formatCurrency(trade.average_price)}</span>
                    </div>
                    <div class="trade-detail">
                        <span class="trade-label">Amount</span>
                        <span class="trade-value">${trade.filled_size_base.toFixed(6)}</span>
                    </div>
                    <div class="trade-detail">
                        <span class="trade-label">P&L</span>
                        <span class="trade-value ${pnlClass}">${pnl >= 0 ? '+' : ''}${formatCurrency(pnl)}</span>
                    </div>
                </div>
                <div class="trade-card-footer">
                    <span class="trade-time">${timeStr}</span>
                    <span class="trade-status status-${trade.status}">${trade.status}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ============================================================================
// Header Status Updates
// ============================================================================

function updateHeaderStatus() {
    // Connection status
    const connectionStatus = document.getElementById('connectionStatus');
    if (connectionStatus) {
        const dot = connectionStatus.querySelector('.status-dot');
        const label = connectionStatus.querySelector('.status-label');

        if (state.wsConnected) {
            connectionStatus.classList.add('connected');
            connectionStatus.classList.remove('disconnected');
            if (label) label.textContent = 'Live';
        } else {
            connectionStatus.classList.remove('connected');
            connectionStatus.classList.add('disconnected');
            if (label) label.textContent = 'Offline';
        }
    }

    // Mode chip
    const modeChip = document.getElementById('modeChip');
    if (modeChip && state.portfolio) {
        const span = modeChip.querySelector('span');
        if (span) {
            span.textContent = state.portfolio.simulation_mode ? 'Simulation' : 'Live';
        }
        if (state.portfolio.simulation_mode) {
            modeChip.classList.add('simulation');
            modeChip.classList.remove('live');
        } else {
            modeChip.classList.remove('simulation');
            modeChip.classList.add('live');
        }
    }

    // Sidebar status
    const sidebarStatusDot = document.getElementById('sidebarStatusDot');
    const sidebarStatusText = document.getElementById('sidebarStatusText');
    if (sidebarStatusDot && sidebarStatusText) {
        if (state.wsConnected) {
            sidebarStatusDot.classList.add('connected');
            sidebarStatusText.textContent = 'Connected';
        } else {
            sidebarStatusDot.classList.remove('connected');
            sidebarStatusText.textContent = 'Disconnected';
        }
    }
}

// ============================================================================
// Countdown Timer
// ============================================================================

let countdownInterval = null;

function startCountdown(targetTime) {
    if (countdownInterval) {
        clearInterval(countdownInterval);
    }

    const countdownEl = document.getElementById('nextCycleCountdown');
    if (!countdownEl) return;

    function update() {
        const now = new Date();
        const target = new Date(targetTime);
        const diff = Math.max(0, target - now);

        if (diff === 0) {
            countdownEl.textContent = 'Now';
            return;
        }

        const minutes = Math.floor(diff / 60000);
        const seconds = Math.floor((diff % 60000) / 1000);
        countdownEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }

    update();
    countdownInterval = setInterval(update, 1000);
}

// ============================================================================
// Time Range Selector
// ============================================================================

function initTimeRangeSelector() {
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active from all
            document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const range = btn.dataset.range;
            // Future: filter chart data by range
            console.log(`[Chart] Time range changed to: ${range}`);
        });
    });
}

// ============================================================================
// Event Listeners Setup
// ============================================================================

function setupEventListeners() {
    // Desktop action buttons
    const refreshBtn = document.getElementById('refreshBtn');
    const triggerBtn = document.getElementById('triggerBtn');
    const pauseBtn = document.getElementById('pauseBtn');
    const resumeBtn = document.getElementById('resumeBtn');

    if (refreshBtn) refreshBtn.addEventListener('click', loadDashboard);
    if (triggerBtn) triggerBtn.addEventListener('click', triggerTradingCycle);
    if (pauseBtn) pauseBtn.addEventListener('click', pauseTrading);
    if (resumeBtn) resumeBtn.addEventListener('click', resumeTrading);

    // Mobile action buttons
    const pauseBtnMobile = document.getElementById('pauseBtnMobile');
    const resumeBtnMobile = document.getElementById('resumeBtnMobile');
    const triggerBtnMobile = document.getElementById('triggerBtnMobile');

    if (pauseBtnMobile) pauseBtnMobile.addEventListener('click', pauseTrading);
    if (resumeBtnMobile) resumeBtnMobile.addEventListener('click', resumeTrading);
    if (triggerBtnMobile) triggerBtnMobile.addEventListener('click', triggerTradingCycle);

    // Header refresh button
    const headerRefreshBtn = document.getElementById('refreshBtn');
    if (headerRefreshBtn) {
        headerRefreshBtn.addEventListener('click', () => {
            headerRefreshBtn.classList.add('spinning');
            loadDashboard().finally(() => {
                setTimeout(() => headerRefreshBtn.classList.remove('spinning'), 500);
            });
        });
    }
}

// ============================================================================
// Initialization
// ============================================================================

window.addEventListener('load', () => {
    console.log('Dashboard initializing...');
    if (typeof Chart === 'undefined') {
        console.error('CRITICAL: Chart.js library not loaded!');
        toast.error('Chart library failed to load');
    } else {
        console.log('Chart.js loaded successfully');
    }

    // Initialize Lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
});

document.addEventListener('DOMContentLoaded', async () => {
    console.log('DOM Content Loaded - Starting dashboard setup');

    // Initialize theme from localStorage or system preference
    initTheme();

    // Initialize UI components
    initSidebar();
    initBottomNav();
    initSectionCollapse();
    initFAB();
    initNotificationPanel();
    initTimeRangeSelector();
    initThemeToggle();
    setupEventListeners();

    // Check authentication
    const isAuthenticated = await checkAuthAndInit();
    if (!isAuthenticated) {
        // Show auth modal and wait for login
        if (typeof showAuthModal === 'function') {
            showAuthModal('signin');
        }
        return;
    }

    // Start dashboard
    initDashboard();
});

// Initialize dashboard after authentication
function initDashboard() {
    // Show loading state
    showSkeletons();

    // Load dashboard data
    loadDashboard();

    // Load AI status for hero section
    updateHeroAIStatus();
    updateHeroCountdownTile();

    // Load AI activity feed
    loadAIActivity();

    // Load pair cards with mini charts
    loadPairCards();

    // Load holdings sidebar
    loadHoldingsSidebar();

    // Set up refresh interval
    if (!window.dashboardInterval) {
        window.dashboardInterval = setInterval(loadDashboard, CONFIG.REFRESH_INTERVAL);
    }

    // Set up AI status refresh interval (every 10s for countdown accuracy)
    if (!window.aiStatusInterval) {
        window.aiStatusInterval = setInterval(() => {
            updateHeroAIStatus();
            updateHeroCountdownTile();
            updateAINextCycleTimer();
            updateSidebarCountdown();
        }, 10000);
    }

    // Set up holdings sidebar refresh interval (every 30s)
    if (!window.holdingsInterval) {
        window.holdingsInterval = setInterval(loadHoldingsSidebar, 30000);
    }

    // Set up AI activity refresh interval (every 60s)
    if (!window.aiActivityInterval) {
        window.aiActivityInterval = setInterval(loadAIActivity, 60000);
    }

    // Set up pair cards refresh interval (every 60s)
    if (!window.pairCardsInterval) {
        window.pairCardsInterval = setInterval(loadPairCards, 60000);
    }

    // Connect WebSocket
    connectWebSocket();

    // Handle scroll for sticky header
    let lastScrollY = window.scrollY;
    let ticking = false;

    window.addEventListener('scroll', () => {
        if (!ticking) {
            window.requestAnimationFrame(() => {
                handleScroll(lastScrollY);
                lastScrollY = window.scrollY;
                ticking = false;
            });
            ticking = true;
        }
    });
}

function handleScroll(lastY) {
    const header = document.querySelector('.header');
    if (!header) return;

    const currentY = window.scrollY;

    if (currentY > 100) {
        if (currentY > lastY) {
            header.classList.add('hidden');
        } else {
            header.classList.remove('hidden');
        }
    } else {
        header.classList.remove('hidden');
    }
}

// ============================================================================
// WebSocket Connection
// ============================================================================

function connectWebSocket() {
    console.log('[WebSocket] Attempting to connect to', CONFIG.WS_URL);

    try {
        state.websocket = new WebSocket(CONFIG.WS_URL);

        state.websocket.onopen = () => {
            console.log('[WebSocket] Connected successfully');
            state.wsConnected = true;
            state.wsReconnectAttempts = 0;
            updateWebSocketStatus(true);
            updateHeaderStatus();
            toast.success('Connected to trading server');
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
            updateHeaderStatus();
        };

        state.websocket.onclose = () => {
            console.log('[WebSocket] Connection closed');
            state.wsConnected = false;
            updateWebSocketStatus(false);
            updateHeaderStatus();

            state.wsReconnectAttempts++;
            const delay = Math.min(CONFIG.WS_RECONNECT_INTERVAL * state.wsReconnectAttempts, 30000);
            console.log(`[WebSocket] Reconnecting in ${delay / 1000}s (attempt ${state.wsReconnectAttempts})`);

            setTimeout(() => {
                if (!state.wsConnected) {
                    connectWebSocket();
                }
            }, delay);
        };

        // Keep connection alive
        setInterval(() => {
            if (state.websocket && state.websocket.readyState === WebSocket.OPEN) {
                state.websocket.send('ping');
            }
        }, 30000);

    } catch (error) {
        console.error('[WebSocket] Connection failed:', error);
        state.wsConnected = false;
        updateWebSocketStatus(false);
        updateHeaderStatus();
    }
}

function handleWebSocketMessage(data) {
    const msgType = data.type;

    if (msgType === 'connection') {
        console.log('[WebSocket] Connection established:', data.message);

        if (data.initial_portfolio) {
            updateLiveChartData(data.initial_portfolio.total_value);
        }

    } else if (msgType === 'portfolio_update') {
        console.log('[WebSocket] Portfolio update received');
        updateLiveChartData(data.total_value, data.timestamp);
        updatePortfolioMetricsFromWebSocket(data);

        // Refresh AI activity feed (cycle just completed)
        loadAIActivity();
        updateHeroAIStatus();

        // Refresh pair cards (positions may have changed)
        loadPairCards();

        // Add notification
        addNotification(`Portfolio updated: ${formatCurrency(data.total_value)}`, 'info');
    } else if (msgType === 'trade_executed') {
        const action = data.action || 'TRADE';
        const pair = data.pair || '';
        addNotification(`${action} executed: ${pair}`, action === 'BUY' ? 'success' : 'warning');
        toast.success(`Trade executed: ${action} ${pair}`);

        // Refresh pair cards after trade
        loadPairCards();
    }
}

function updateLiveChartData(portfolioValue, timestamp) {
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

    state.chartData.timestamps.push(timeLabel);
    state.chartData.portfolioValues.push(portfolioValue);

    if (state.chartData.timestamps.length > CONFIG.CHART_MAX_POINTS) {
        state.chartData.timestamps.shift();
        state.chartData.portfolioValues.shift();
    }

    if (state.chart) {
        state.chart.data.labels = state.chartData.timestamps;
        state.chart.data.datasets[0].data = state.chartData.portfolioValues;
        state.chart.data.datasets[1].data = Array(state.chartData.timestamps.length).fill(CONFIG.INITIAL_CAPITAL);
        state.chart.data.datasets[2].data = Array(state.chartData.timestamps.length).fill(CONFIG.TARGET_CAPITAL);
        state.chart.update('none');
    }
}

function updatePortfolioMetricsFromWebSocket(data) {
    const totalValue = data.total_value || 0;
    document.getElementById('portfolioValue').textContent = formatCurrency(totalValue);

    const portfolioPercent = ((totalValue - CONFIG.INITIAL_CAPITAL) / CONFIG.INITIAL_CAPITAL) * 100;
    const percentElement = document.getElementById('portfolioPercent');
    if (percentElement) {
        percentElement.textContent = `${portfolioPercent >= 0 ? '+' : ''}${portfolioPercent.toFixed(2)}%`;
        percentElement.className = `metric-change ${portfolioPercent >= 0 ? 'positive' : 'negative'}`;
    }

    const totalPnL = totalValue - CONFIG.INITIAL_CAPITAL;
    const pnlPercent = (totalPnL / CONFIG.INITIAL_CAPITAL) * 100;

    const pnlElement = document.getElementById('totalPnL');
    if (pnlElement) {
        pnlElement.textContent = formatCurrency(totalPnL);
        pnlElement.className = `metric-value ${totalPnL >= 0 ? 'positive' : 'negative'}`;
    }

    const pnlPercentElement = document.getElementById('totalPnLPercent');
    if (pnlPercentElement) {
        pnlPercentElement.textContent = `${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%`;
        pnlPercentElement.className = `metric-change ${pnlPercent >= 0 ? 'positive' : 'negative'}`;
    }

    const progress = ((totalValue - CONFIG.INITIAL_CAPITAL) / (CONFIG.TARGET_CAPITAL - CONFIG.INITIAL_CAPITAL)) * 100;
    const cappedProgress = Math.min(progress, 100);
    const targetProgressEl = document.getElementById('targetProgress');
    if (targetProgressEl) {
        targetProgressEl.textContent = `${cappedProgress.toFixed(1)}%`;
    }

    // Update quick stats
    updateQuickStats();
}

function updateWebSocketStatus(connected) {
    const chartStatus = document.getElementById('chartStatus');

    if (connected) {
        if (chartStatus) {
            chartStatus.classList.add('connected');
            chartStatus.classList.remove('disconnected');
        }
    } else {
        if (chartStatus) {
            chartStatus.classList.remove('connected');
            chartStatus.classList.add('disconnected');
        }
    }

    updateHeaderStatus();
}

// ============================================================================
// Main Dashboard Load
// ============================================================================

async function loadDashboard() {
    console.log('[Dashboard] Starting load cycle...');
    try {
        const results = await Promise.all([
            fetchPortfolio(),
            fetchTradeHistory(),
            fetchPerformance(),
            fetchStatus(),
            fetchPhase2Info()
        ]);

        const [portfolio, history, performance, status, phase2Info] = results;

        state.portfolio = portfolio;
        state.trades = history.trades || [];
        state.performance = performance;
        state.status = status;
        state.phase2.info = phase2Info;
        state.phase2.enabled = phase2Info && phase2Info.is_phase2;
        state.lastError = null;

        console.log('[Dashboard] Data loaded successfully, updating UI...');

        // Hide skeletons
        hideSkeletons();

        // Update all UI components
        updateMetrics();
        updateTradesTable();
        updateTradesCards();
        updateStatusPanel();
        updateChart();
        updateConnectionStatus();
        updateQuickStats();
        updateHeaderStatus();

        // Update gauges
        if (state.performance) {
            const winRate = state.performance.win_rate ? state.performance.win_rate * 100 : 0;
            updateGauge('winRateGauge', winRate);
        }

        if (state.portfolio) {
            const totalQuote = state.portfolio.total_value || 0;
            const investedAmount = totalQuote - (state.portfolio.available_quote || 0);
            const exposure = totalQuote > 0 ? (investedAmount / totalQuote) * 100 : 0;
            updateGauge('exposureGauge', exposure, 80);
        }

        // Update countdown
        if (status && status.next_cycle) {
            startCountdown(status.next_cycle);
        }

        // Update Phase 2/3 sections
        await updatePhase2Section();
        await updatePhase3Section();
        await updateCostSection();
        await updatePnLSection();

        console.log('[Dashboard] Load cycle completed successfully');
    } catch (error) {
        console.error('[Dashboard] Load error:', error);
        state.lastError = error;
        updateConnectionStatus(error);
        toast.error(`Connection Error: ${error.message}`);
    }
}

// ============================================================================
// API Calls
// ============================================================================

async function fetchPortfolio() {
    const url = `${CONFIG.API_BASE}/portfolio`;
    console.log(`[API] Fetching portfolio from: ${url}`);
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Portfolio endpoint returned ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`[API] Portfolio fetch failed:`, error);
        throw new Error(`Portfolio: ${error.message}`);
    }
}

async function fetchTradeHistory() {
    const url = `${CONFIG.API_BASE}/history?limit=50`;
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`History endpoint returned ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`[API] History fetch failed:`, error);
        throw new Error(`Trade History: ${error.message}`);
    }
}

async function fetchPerformance() {
    const url = `${CONFIG.API_BASE}/performance`;
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Performance endpoint returned ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`[API] Performance fetch failed:`, error);
        throw new Error(`Performance: ${error.message}`);
    }
}

async function fetchStatus() {
    const url = `${CONFIG.API_BASE}/status`;
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Status endpoint returned ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`[API] Status fetch failed:`, error);
        throw new Error(`Status: ${error.message}`);
    }
}

// ============================================================================
// Metrics Updates
// ============================================================================

function updateMetrics() {
    if (!state.portfolio || !state.performance) return;

    const portfolio = state.portfolio;
    const perf = state.performance;

    const totalValue = portfolio.total_value || 0;
    const totalPnL = totalValue - CONFIG.INITIAL_CAPITAL;
    const pnlPercent = (totalPnL / CONFIG.INITIAL_CAPITAL) * 100;

    // P&L
    const pnlElement = document.getElementById('totalPnL');
    const pnlPercentElement = document.getElementById('totalPnLPercent');

    if (pnlElement) {
        pnlElement.textContent = formatCurrency(totalPnL);
        pnlElement.className = `metric-value ${totalPnL >= 0 ? 'positive' : 'negative'}`;
    }

    if (pnlPercentElement) {
        pnlPercentElement.textContent = `${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%`;
        pnlPercentElement.className = `metric-change ${pnlPercent >= 0 ? 'positive' : 'negative'}`;
    }

    // Portfolio Value
    const portfolioValueEl = document.getElementById('portfolioValue');
    if (portfolioValueEl) {
        portfolioValueEl.textContent = formatCurrency(totalValue);
    }

    const portfolioPercentEl = document.getElementById('portfolioPercent');
    if (portfolioPercentEl) {
        const portfolioPercent = ((totalValue - CONFIG.INITIAL_CAPITAL) / CONFIG.INITIAL_CAPITAL) * 100;
        portfolioPercentEl.textContent = `${portfolioPercent >= 0 ? '+' : ''}${portfolioPercent.toFixed(2)}%`;
        portfolioPercentEl.className = `metric-change ${portfolioPercent >= 0 ? 'positive' : 'negative'}`;
    }

    // Win Rate
    const totalTrades = perf.total_trades || 0;
    const winRate = perf.win_rate ? (perf.win_rate * 100) : 0;
    const winningTrades = perf.winning_trades || 0;

    const winRateEl = document.getElementById('winRate');
    if (winRateEl) winRateEl.textContent = `${winRate.toFixed(1)}%`;

    const winCountEl = document.getElementById('winCount');
    if (winCountEl) winCountEl.textContent = `${winningTrades} / ${totalTrades} trades`;

    // Total Trades
    const totalTradesEl = document.getElementById('totalTrades');
    if (totalTradesEl) totalTradesEl.textContent = totalTrades;

    // Active Positions
    const positionsObj = portfolio.positions || {};
    const positionsArray = Object.values(positionsObj);
    const activePositions = positionsArray.filter(p => p.amount > 0).length;

    const activePositionsEl = document.getElementById('activePositions');
    if (activePositionsEl) activePositionsEl.textContent = `${activePositions} active positions`;

    // Exposure
    const totalQuote = portfolio.total_value || 0;
    const investedAmount = totalQuote - (portfolio.available_quote || 0);
    const exposure = totalQuote > 0 ? (investedAmount / totalQuote) * 100 : 0;

    const exposureEl = document.getElementById('exposure');
    if (exposureEl) exposureEl.textContent = `${exposure.toFixed(1)}%`;

    // Target Progress
    const progress = ((totalValue - CONFIG.INITIAL_CAPITAL) / (CONFIG.TARGET_CAPITAL - CONFIG.INITIAL_CAPITAL)) * 100;
    const cappedProgress = Math.min(Math.max(progress, 0), 100);

    const targetProgressEl = document.getElementById('targetProgress');
    if (targetProgressEl) targetProgressEl.textContent = `${cappedProgress.toFixed(1)}%`;

    const targetProgressBar = document.getElementById('targetProgressBar');
    if (targetProgressBar) targetProgressBar.style.width = `${cappedProgress}%`;

    updateChartData(totalValue);
}

function updateChartData(portfolioValue) {
    const now = new Date();
    const timeLabel = now.toLocaleTimeString();

    state.chartData.timestamps.push(timeLabel);
    state.chartData.portfolioValues.push(portfolioValue);

    if (state.chartData.timestamps.length > CONFIG.CHART_MAX_POINTS) {
        state.chartData.timestamps.shift();
        state.chartData.portfolioValues.shift();
    }
}

// ============================================================================
// Chart Rendering
// ============================================================================

function updateChart() {
    const ctx = document.getElementById('performanceChart');
    if (!ctx) return;

    if (typeof Chart === 'undefined') {
        console.error('[Chart] Chart.js library not available');
        return;
    }

    // Hide loading
    const chartLoading = document.getElementById('chartLoading');
    if (chartLoading) chartLoading.style.display = 'none';

    const chartData = {
        labels: state.chartData.timestamps,
        datasets: [
            {
                label: 'Portfolio Value (AUD)',
                data: state.chartData.portfolioValues,
                borderColor: '#00f0ff',
                backgroundColor: 'rgba(0, 240, 255, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#00f0ff',
                pointBorderColor: '#050508',
                pointBorderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 6
            },
            {
                label: 'Initial ($1,000)',
                data: Array(state.chartData.timestamps.length).fill(CONFIG.INITIAL_CAPITAL),
                borderColor: 'rgba(255, 255, 255, 0.3)',
                borderWidth: 1,
                borderDash: [5, 5],
                fill: false,
                pointRadius: 0,
                tension: 0
            },
            {
                label: 'Target ($5,000)',
                data: Array(state.chartData.timestamps.length).fill(CONFIG.TARGET_CAPITAL),
                borderColor: '#10b981',
                borderWidth: 1,
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
                display: true,
                position: 'top',
                labels: {
                    color: 'rgba(255, 255, 255, 0.7)',
                    font: { size: 11, family: "'Inter', sans-serif" },
                    padding: 12,
                    usePointStyle: true,
                    boxWidth: 6
                }
            },
            tooltip: {
                backgroundColor: 'rgba(5, 5, 8, 0.95)',
                padding: 12,
                titleColor: '#00f0ff',
                bodyColor: 'rgba(255, 255, 255, 0.9)',
                borderColor: 'rgba(0, 240, 255, 0.3)',
                borderWidth: 1,
                cornerRadius: 8,
                displayColors: false,
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
                grid: {
                    color: 'rgba(255, 255, 255, 0.05)',
                    drawBorder: false
                },
                ticks: {
                    color: 'rgba(255, 255, 255, 0.5)',
                    font: { size: 11, family: "'JetBrains Mono', monospace" },
                    callback: function(value) {
                        return formatCurrency(value);
                    }
                }
            },
            x: {
                grid: {
                    display: false
                },
                ticks: {
                    color: 'rgba(255, 255, 255, 0.5)',
                    font: { size: 10, family: "'JetBrains Mono', monospace" },
                    maxRotation: 0,
                    autoSkip: true,
                    maxTicksLimit: 8
                }
            }
        }
    };

    if (state.chart) {
        state.chart.destroy();
    }

    state.chart = new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: options
    });
}

// ============================================================================
// Trades Table
// ============================================================================

function updateTradesTable() {
    const tbody = document.getElementById('tradesBody');
    if (!tbody) return;

    if (!state.trades || state.trades.length === 0) {
        tbody.innerHTML = '<tr class="empty-state"><td colspan="7">No trades yet</td></tr>';
        return;
    }

    const sortedTrades = [...state.trades].reverse();

    const html = sortedTrades.map(trade => {
        const timestamp = new Date(trade.timestamp);
        const timeStr = timestamp.toLocaleString();
        const actionClass = trade.action === 'BUY' ? 'buy' : trade.action === 'SELL' ? 'sell' : 'hold';
        const pnl = trade.realized_pnl || 0;
        const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : '';

        return `
            <tr>
                <td>${timeStr}</td>
                <td><span class="pair-badge">${trade.pair}</span></td>
                <td><span class="action-badge ${actionClass}">${trade.action}</span></td>
                <td class="tabular">${formatCurrency(trade.average_price)}</td>
                <td class="tabular">${trade.filled_size_base.toFixed(6)}</td>
                <td><span class="status-badge ${trade.status}">${trade.status}</span></td>
                <td class="tabular ${pnlClass}">${pnl >= 0 ? '+' : ''}${formatCurrency(pnl)}</td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = html;
}

// ============================================================================
// Status Panel
// ============================================================================

async function updateStatusPanel() {
    if (!state.status) return;

    const stageEl = document.getElementById('stage');
    if (stageEl) stageEl.textContent = state.phase2.info?.stage || 'Stage 1';

    const modeEl = document.getElementById('mode');
    if (modeEl) {
        modeEl.textContent = (state.portfolio && state.portfolio.simulation_mode) ? 'Simulation' : 'Live';
    }

    const nextCycleEl = document.getElementById('nextCycle');
    if (nextCycleEl) {
        const nextCycleTime = state.status.next_cycle ?
            new Date(state.status.next_cycle).toLocaleTimeString() : 'N/A';
        nextCycleEl.textContent = nextCycleTime;
    }

    const cycleCountEl = document.getElementById('cycleCount');
    if (cycleCountEl) cycleCountEl.textContent = state.status.cycle_count || 0;

    const tradingStatusEl = document.getElementById('tradingStatus');
    if (tradingStatusEl) {
        const tradingActive = !state.status.sentinel_paused;
        tradingStatusEl.textContent = tradingActive ? 'Active' : 'Paused';
        tradingStatusEl.className = `status-value ${tradingActive ? 'active' : 'paused'}`;
    }

    // Update button states
    state.paused = state.status.sentinel_paused;
    updatePauseButtons();
}

function updatePauseButtons() {
    const pauseBtn = document.getElementById('pauseBtn');
    const resumeBtn = document.getElementById('resumeBtn');
    const pauseBtnMobile = document.getElementById('pauseBtnMobile');
    const resumeBtnMobile = document.getElementById('resumeBtnMobile');
    const fabPause = document.getElementById('fabPause');

    if (pauseBtn) pauseBtn.style.display = state.paused ? 'none' : '';
    if (resumeBtn) resumeBtn.style.display = state.paused ? '' : 'none';
    if (pauseBtnMobile) pauseBtnMobile.style.display = state.paused ? 'none' : '';
    if (resumeBtnMobile) resumeBtnMobile.style.display = state.paused ? '' : 'none';

    if (fabPause) {
        const icon = fabPause.querySelector('i');
        const span = fabPause.querySelector('span');
        if (state.paused) {
            if (icon) icon.setAttribute('data-lucide', 'play');
            if (span) span.textContent = 'Resume Trading';
        } else {
            if (icon) icon.setAttribute('data-lucide', 'pause');
            if (span) span.textContent = 'Pause Trading';
        }
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

function updateConnectionStatus(error) {
    updateHeaderStatus();
}

// ============================================================================
// Action Handlers
// ============================================================================

async function triggerTradingCycle() {
    try {
        const triggerBtn = document.getElementById('triggerBtn');
        const triggerBtnMobile = document.getElementById('triggerBtnMobile');

        if (triggerBtn) triggerBtn.disabled = true;
        if (triggerBtnMobile) triggerBtnMobile.disabled = true;

        toast.info('Triggering trading cycle...');

        const response = await fetch(`${CONFIG.API_BASE}/trigger`, { method: 'POST' });
        if (!response.ok) throw new Error(`Trigger failed: ${response.status}`);

        toast.success('Trading cycle triggered');
        addNotification('Trading cycle triggered', 'success');

        setTimeout(loadDashboard, 1000);
    } catch (error) {
        console.error('Trigger error:', error);
        toast.error('Failed to trigger trading cycle');
    } finally {
        const triggerBtn = document.getElementById('triggerBtn');
        const triggerBtnMobile = document.getElementById('triggerBtnMobile');

        if (triggerBtn) triggerBtn.disabled = false;
        if (triggerBtnMobile) triggerBtnMobile.disabled = false;
    }
}

async function pauseTrading() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/pause`, { method: 'POST' });
        if (!response.ok) throw new Error(`Pause failed: ${response.status}`);

        state.paused = true;
        updatePauseButtons();

        toast.warning('Trading paused');
        addNotification('Trading paused', 'warning');
        updateStatusPanel();
    } catch (error) {
        console.error('Pause error:', error);
        toast.error('Failed to pause trading');
    }
}

async function resumeTrading() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/resume`, { method: 'POST' });
        if (!response.ok) throw new Error(`Resume failed: ${response.status}`);

        state.paused = false;
        updatePauseButtons();

        toast.success('Trading resumed');
        addNotification('Trading resumed', 'success');
        updateStatusPanel();
    } catch (error) {
        console.error('Resume error:', error);
        toast.error('Failed to resume trading');
    }
}

// ============================================================================
// Utility Functions
// ============================================================================

function formatCurrency(value) {
    return new Intl.NumberFormat('en-AU', {
        style: 'currency',
        currency: 'AUD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function showError(message) {
    console.error('[Error]', message);
    toast.error(message);
}

function showToast(message) {
    toast.info(message);
}

// ============================================================================
// Phase 2 Functions
// ============================================================================

async function fetchPhase2Info() {
    const url = `${CONFIG.API_BASE}/api/phase2/info`;
    try {
        const response = await fetch(url);
        if (!response.ok) return { is_phase2: false };
        return await response.json();
    } catch (error) {
        return { is_phase2: false };
    }
}

async function fetchCircuitBreakers() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/phase2/breakers`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        return null;
    }
}

async function fetchSentimentData() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/phase2/sentiment`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        return null;
    }
}

async function fetchFusionData() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/phase2/fusion`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        return null;
    }
}

async function fetchExecutionStats() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/phase2/execution`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        return null;
    }
}

async function updatePhase2Section() {
    const section = document.getElementById('phase2-section');
    if (!section) return;

    const info = state.phase2.info;

    const stageEl = document.getElementById('stage');
    if (stageEl && info) {
        stageEl.textContent = info.stage || 'Stage 1';
    }

    const analystCountEl = document.getElementById('analystCount');
    if (analystCountEl && info && info.features) {
        const count = info.features.analyst_count || 1;
        analystCountEl.textContent = `${count} analyst${count !== 1 ? 's' : ''}`;
    }

    const sentimentAnalystEl = document.getElementById('sentimentAnalyst');
    if (sentimentAnalystEl && info && info.features) {
        sentimentAnalystEl.style.display = info.features.sentiment_analyst ? 'flex' : 'none';
    }

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

    updateCircuitBreakersUI(breakers);
    updateSentimentUI(sentiment);
    updateFusionUI(fusion);
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
            if (text) text.textContent = 'TRIPPED';
        } else {
            if (indicator) indicator.className = 'status-indicator ok';
            if (text) text.textContent = 'OK';
        }
    }

    if (breakerStatus) {
        if (anyTripped) {
            breakerStatus.textContent = 'Tripped';
            breakerStatus.className = 'badge badge-error';
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

    const fgValueEl = document.getElementById('fearGreedValue');
    if (fgValueEl) {
        const value = fgData.value || 50;
        fgValueEl.textContent = `${value} - ${fgData.classification || 'Neutral'}`;

        if (value <= 25) {
            fgValueEl.className = 'badge badge-error';
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

    const fgMeter = document.getElementById('fgMeter');
    if (fgMeter && fgData.value !== undefined) {
        fgMeter.style.width = `${fgData.value}%`;
    }

    const fgSignal = document.getElementById('fgSignal');
    if (fgSignal && fgData.value !== undefined) {
        const value = fgData.value;
        if (value <= 25) {
            fgSignal.textContent = 'Bullish (Extreme Fear)';
            fgSignal.className = 'signal-value positive';
        } else if (value <= 45) {
            fgSignal.textContent = 'Slightly Bullish';
            fgSignal.className = 'signal-value positive';
        } else if (value <= 55) {
            fgSignal.textContent = 'Neutral';
            fgSignal.className = 'signal-value';
        } else if (value <= 75) {
            fgSignal.textContent = 'Slightly Bearish';
            fgSignal.className = 'signal-value negative';
        } else {
            fgSignal.textContent = 'Bearish (Extreme Greed)';
            fgSignal.className = 'signal-value negative';
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

        const fusedDirection = document.getElementById('fusedDirection');
        const fusedConfidence = document.getElementById('fusedConfidence');
        const fusionDisagreement = document.getElementById('fusionDisagreement');

        if (fusedDirection) fusedDirection.textContent = '0.00';
        if (fusedConfidence) fusedConfidence.textContent = '0%';
        if (fusionDisagreement) fusionDisagreement.textContent = '0%';

        const meter = document.getElementById('fusionMeter');
        if (meter) meter.style.left = '50%';
        return;
    }

    const fusion = data.latest || {};

    if (fusionStatus) {
        const direction = fusion.fused_direction || 0;
        if (direction > 0.3) {
            fusionStatus.textContent = 'Bullish';
            fusionStatus.className = 'badge badge-success';
        } else if (direction < -0.3) {
            fusionStatus.textContent = 'Bearish';
            fusionStatus.className = 'badge badge-error';
        } else {
            fusionStatus.textContent = 'Neutral';
            fusionStatus.className = 'badge badge-info';
        }
    }

    const meter = document.getElementById('fusionMeter');
    if (meter && fusion.fused_direction !== undefined) {
        const position = ((fusion.fused_direction + 1) / 2) * 100;
        meter.style.left = `${position}%`;
    }

    const directionEl = document.getElementById('fusedDirection');
    if (directionEl) {
        const dir = fusion.fused_direction || 0;
        directionEl.textContent = dir.toFixed(2);
        directionEl.className = `value ${dir > 0 ? 'positive' : dir < 0 ? 'negative' : ''}`;
    }

    const confidenceEl = document.getElementById('fusedConfidence');
    if (confidenceEl) {
        confidenceEl.textContent = `${((fusion.fused_confidence || 0) * 100).toFixed(0)}%`;
    }

    const disagreementEl = document.getElementById('fusionDisagreement');
    if (disagreementEl) {
        const disagreement = (fusion.disagreement || 0) * 100;
        disagreementEl.textContent = `${disagreement.toFixed(0)}%`;
    }

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
            dirEl.className = 'direction positive';
        } else if (dir < -0.2) {
            dirEl.textContent = dir.toFixed(2);
            dirEl.className = 'direction negative';
        } else {
            dirEl.textContent = dir.toFixed(2);
            dirEl.className = 'direction';
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

    const limitCount = document.getElementById('limitOrderCount');
    if (limitCount) limitCount.textContent = stats.limit_orders || 0;

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
    if (fallbacks) fallbacks.textContent = stats.market_fallbacks || 0;
}

// ============================================================================
// Phase 3 Functions
// ============================================================================

async function updatePhase3Section() {
    const section = document.getElementById('phase3-section');
    if (!section) return;

    const info = state.phase2.info;
    const isPhase3 = info && (info.stage === 'stage3' || info.stage === 'Stage 3');

    section.style.display = isPhase3 ? 'block' : 'none';

    if (!isPhase3) {
        section.style.display = 'block';
        updatePhase3WithSimulatedData();
        return;
    }

    state.phase3.enabled = true;
    showPhase3Analysts();
    updatePhase3WithSimulatedData();
}

function showPhase3Analysts() {
    const onchainEl = document.getElementById('onchainAnalyst');
    const macroEl = document.getElementById('macroAnalyst');
    const orderbookEl = document.getElementById('orderbookAnalyst');

    if (onchainEl) onchainEl.style.display = 'flex';
    if (macroEl) macroEl.style.display = 'flex';
    if (orderbookEl) orderbookEl.style.display = 'flex';

    const sentPerfEl = document.getElementById('sentPerfItem');
    const onchainPerfEl = document.getElementById('onchainPerfItem');
    const macroPerfEl = document.getElementById('macroPerfItem');
    const orderbookPerfEl = document.getElementById('orderbookPerfItem');

    if (sentPerfEl) sentPerfEl.style.display = 'flex';
    if (onchainPerfEl) onchainPerfEl.style.display = 'flex';
    if (macroPerfEl) macroPerfEl.style.display = 'flex';
    if (orderbookPerfEl) orderbookPerfEl.style.display = 'flex';

    const analystCountEl = document.getElementById('analystCount');
    if (analystCountEl) analystCountEl.textContent = '5 analysts';
}

async function updatePhase3WithSimulatedData() {
    updateRegimeUI({
        regime: 'RANGING',
        volatility: 0.023,
        trend_strength: 0.15,
        duration: '2h 15m'
    });

    // Fetch real correlation data from API
    try {
        const correlationResponse = await fetch(`${CONFIG.API_BASE}/api/correlation`);
        if (correlationResponse.ok) {
            const correlationData = await correlationResponse.json();
            updateCorrelationUI(correlationData);
        } else {
            // Fallback to placeholder if API fails
            updateCorrelationUI({
                pairs: ['BTC', 'ETH', 'SOL'],
                matrix: { BTC_BTC: 1, BTC_ETH: 0.85, BTC_SOL: 0.78, ETH_BTC: 0.85, ETH_ETH: 1, ETH_SOL: 0.82, SOL_BTC: 0.78, SOL_ETH: 0.82, SOL_SOL: 1 },
                high_correlation: false
            });
        }
    } catch (error) {
        console.warn('Could not fetch correlation data:', error);
        updateCorrelationUI({
            pairs: ['BTC', 'ETH', 'SOL'],
            matrix: { BTC_BTC: 1, BTC_ETH: 0.85, BTC_SOL: 0.78, ETH_BTC: 0.85, ETH_ETH: 1, ETH_SOL: 0.82, SOL_BTC: 0.78, SOL_ETH: 0.82, SOL_SOL: 1 },
            high_correlation: false
        });
    }

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

    updateAnalystSignal('onchain', { direction: 0.32, confidence: 0.68 });
    updateAnalystSignal('macro', { direction: -0.15, confidence: 0.55 });
    updateAnalystSignal('orderbook', { direction: 0.45, confidence: 0.72 });
}

function updateRegimeUI(data) {
    if (!data) return;

    const regimeStatus = document.getElementById('regimeStatus');
    const regimeName = document.getElementById('regimeName');
    const regimeVolatility = document.getElementById('regimeVolatility');
    const regimeTrend = document.getElementById('regimeTrend');
    const regimeDuration = document.getElementById('regimeDuration');

    const regime = data.regime || 'Unknown';

    if (regimeStatus) {
        regimeStatus.textContent = regime;
        if (regime.includes('UP') || regime.includes('BULL')) {
            regimeStatus.className = 'badge badge-success';
        } else if (regime.includes('DOWN') || regime.includes('BEAR')) {
            regimeStatus.className = 'badge badge-error';
        } else if (regime.includes('VOLATILE')) {
            regimeStatus.className = 'badge badge-warning';
        } else {
            regimeStatus.className = 'badge badge-info';
        }
    }

    if (regimeName) regimeName.textContent = regime;
    if (regimeVolatility) regimeVolatility.textContent = `${((data.volatility || 0) * 100).toFixed(1)}%`;
    if (regimeTrend) regimeTrend.textContent = (data.trend_strength || 0).toFixed(2);
    if (regimeDuration) regimeDuration.textContent = data.duration || '-';
}

function updateCorrelationUI(data) {
    if (!data) return;

    const container = document.getElementById('correlationMatrixContainer');
    const correlationStatus = document.getElementById('correlationStatus');
    const correlationWarning = document.getElementById('correlationWarning');

    // Get correlation class based on value
    function getCorrClass(value) {
        const absVal = Math.abs(value);
        if (absVal >= 0.99) return 'corr-high';      // Self-correlation (diagonal)
        if (absVal >= 0.8) return 'corr-danger';     // High correlation - risk
        if (absVal >= 0.5) return 'corr-med';        // Medium correlation
        return 'corr-low';                           // Low correlation - good
    }

    // Build dynamic table if we have pairs data
    if (container && data.pairs && data.matrix) {
        const pairs = data.pairs;

        // Create table HTML
        let tableHtml = '<table class="corr-table" role="table" aria-label="Asset correlation matrix">';

        // Header row
        tableHtml += '<thead><tr><th scope="col"></th>';
        pairs.forEach(pair => {
            tableHtml += `<th scope="col">${pair}</th>`;
        });
        tableHtml += '</tr></thead>';

        // Body rows
        tableHtml += '<tbody>';
        pairs.forEach(rowPair => {
            tableHtml += `<tr><th scope="row">${rowPair}</th>`;
            pairs.forEach(colPair => {
                const key = `${rowPair}_${colPair}`;
                const value = data.matrix[key] !== undefined ? data.matrix[key] : 0;
                const corrClass = getCorrClass(value);
                const displayValue = value.toFixed(2);
                tableHtml += `<td class="corr-cell ${corrClass}" title="${rowPair} vs ${colPair}">${displayValue}</td>`;
            });
            tableHtml += '</tr>';
        });
        tableHtml += '</tbody></table>';

        container.innerHTML = tableHtml;
    } else if (container) {
        container.innerHTML = '<div class="correlation-loading">No correlation data available</div>';
    }

    // Update status badge
    if (correlationStatus) {
        if (data.high_correlation) {
            correlationStatus.textContent = 'High Risk';
            correlationStatus.className = 'badge badge-error';
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

    if (alertingStatus) {
        const anyEnabled = data.slack || data.discord || data.email;
        alertingStatus.textContent = anyEnabled ? 'Active' : 'Disabled';
        alertingStatus.className = anyEnabled ? 'badge badge-success' : 'badge';
    }

    if (slackStatus) slackStatus.textContent = data.slack ? 'Enabled' : 'Disabled';
    if (discordStatus) discordStatus.textContent = data.discord ? 'Enabled' : 'Disabled';
    if (emailStatus) emailStatus.textContent = data.email ? 'Enabled' : 'Disabled';
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
            anomalyScore.className = 'badge badge-error';
        }
    }

    if (anomalyMeter) anomalyMeter.style.width = `${score * 100}%`;
    if (anomalyValue) anomalyValue.textContent = score.toFixed(2);
    if (lastAnomalyAlert) lastAnomalyAlert.textContent = data.last_alert || 'Never';
}

// ============================================================================
// Cost Optimization Functions
// ============================================================================

async function fetchCostStats() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/cost/stats`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        return null;
    }
}

async function updateCostSection() {
    const section = document.getElementById('cost-section');
    if (!section) return;

    const costData = await fetchCostStats();

    if (!costData || !costData.enabled) {
        updateCostUI(null);
        return;
    }

    state.costOptimization.enabled = true;
    state.costOptimization.stats = costData.stats;
    state.costOptimization.config = costData.config;

    updateCostUI(costData);
}

function updateCostUI(data) {
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

    const savingsPercent = parseFloat(stats.savings_pct) || 0;

    const costSavingsMeter = document.getElementById('costSavingsMeter');
    if (costSavingsMeter) costSavingsMeter.style.width = `${Math.min(savingsPercent, 100)}%`;

    const costSavingsPercent = document.getElementById('costSavingsPercent');
    if (costSavingsPercent) {
        costSavingsPercent.textContent = `${savingsPercent.toFixed(0)}%`;
        costSavingsPercent.className = savingsPercent >= 50 ? 'badge badge-success' : 'badge badge-info';
    }

    const estimatedSavings = document.getElementById('estimatedSavings');
    if (estimatedSavings) estimatedSavings.textContent = stats.estimated_savings || '$0.00';

    const projectedMonthlyCost = document.getElementById('projectedMonthlyCost');
    if (projectedMonthlyCost) {
        const baselineMonthlyCost = 12;
        const optimizedCost = baselineMonthlyCost * (1 - savingsPercent / 100);
        projectedMonthlyCost.textContent = `$${optimizedCost.toFixed(2)}/mo`;
    }

    updateMethodStatus('batch', config.batch_analysis);
    updateMethodStatus('hybrid', config.hybrid_mode);
    updateMethodStatus('cache', config.decision_cache);
    updateMethodStatus('adaptive', config.adaptive_schedule);

    const optimizationStatus = document.getElementById('optimizationStatus');
    if (optimizationStatus) {
        const anyEnabled = config.batch_analysis || config.hybrid_mode || config.decision_cache || config.adaptive_schedule;
        optimizationStatus.textContent = anyEnabled ? 'Active' : 'Disabled';
        optimizationStatus.className = anyEnabled ? 'badge badge-success' : 'badge';
    }

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

    const hybridTotal = hybrid.total_decisions || 0;
    const hybridRules = hybrid.rule_based || 0;
    const hybridClaude = hybrid.claude || 0;

    const rulesPercent = hybridTotal > 0 ? (hybridRules / hybridTotal) * 100 : 0;
    const claudePercent = hybridTotal > 0 ? (hybridClaude / hybridTotal) * 100 : 100;

    const hybridRulesBar = document.getElementById('hybridRulesBar');
    const hybridClaudeBar = document.getElementById('hybridClaudeBar');
    const hybridRulesPercentEl = document.getElementById('hybridRulesPercent');
    const hybridClaudePercentEl = document.getElementById('hybridClaudePercent');
    const hybridRuleCount = document.getElementById('hybridRuleCount');
    const hybridClaudeCount = document.getElementById('hybridClaudeCount');
    const hybridRatio = document.getElementById('hybridRatio');

    if (hybridRulesBar) hybridRulesBar.style.width = `${rulesPercent}%`;
    if (hybridClaudeBar) hybridClaudeBar.style.width = `${claudePercent}%`;
    if (hybridRulesPercentEl) hybridRulesPercentEl.textContent = `${rulesPercent.toFixed(0)}%`;
    if (hybridClaudePercentEl) hybridClaudePercentEl.textContent = `${claudePercent.toFixed(0)}%`;
    if (hybridRuleCount) hybridRuleCount.textContent = hybridRules;
    if (hybridClaudeCount) hybridClaudeCount.textContent = hybridClaude;
    if (hybridRatio) {
        hybridRatio.textContent = `${rulesPercent.toFixed(0)}% Rules`;
        hybridRatio.className = rulesPercent >= 50 ? 'badge badge-success' : 'badge badge-info';
    }

    const baselineCost = document.getElementById('baselineCost');
    const optimizedCostEl = document.getElementById('optimizedCost');
    const monthlySavings = document.getElementById('monthlySavings');
    const costComparisonBadge = document.getElementById('costComparisonBadge');

    const baselineMonthly = 12;
    const optimizedMonthly = baselineMonthly * (1 - savingsPercent / 100);
    const savings = baselineMonthly - optimizedMonthly;

    if (baselineCost) baselineCost.textContent = `$${baselineMonthly.toFixed(2)}/month`;
    if (optimizedCostEl) optimizedCostEl.textContent = `$${optimizedMonthly.toFixed(2)}/month`;
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
    }
}

// ============================================================================
// P&L Section Functions
// ============================================================================

async function fetchPnLSummary() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/pnl/summary`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        return null;
    }
}

async function fetchApiUsage() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/costs/usage`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        return null;
    }
}

async function fetchCostBreakdown() {
    try {
        const response = await fetch(`${CONFIG.API_BASE}/api/costs/breakdown`);
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        return null;
    }
}

async function updatePnLSection() {
    const [pnlData, apiUsage, costBreakdown] = await Promise.all([
        fetchPnLSummary(),
        fetchApiUsage(),
        fetchCostBreakdown()
    ]);

    if (pnlData) {
        state.pnlData = {
            realizedPnl: pnlData.realized_pnl || 0,
            unrealizedPnl: pnlData.unrealized_pnl || 0,
            totalPnl: pnlData.total_pnl || 0,
            netProfit: pnlData.net_profit || 0,
            apiCosts: pnlData.api_costs?.total_usd || 0
        };
    }

    if (apiUsage && apiUsage.usage) {
        state.apiUsage = {
            totalCalls: apiUsage.usage.total_calls || 0,
            totalTokens: (apiUsage.usage.total_input_tokens || 0) + (apiUsage.usage.total_output_tokens || 0),
            totalCost: apiUsage.usage.total_cost_usd || 0,
            costToday: apiUsage.usage.cost_today_usd || 0
        };
    }

    updatePnLUI(pnlData, apiUsage, costBreakdown);
}

function updatePnLUI(pnlData, apiUsage, costBreakdown) {
    const netProfitEl = document.getElementById('netProfit');
    if (netProfitEl && pnlData) {
        const netProfit = pnlData.net_profit || 0;
        netProfitEl.textContent = formatCurrency(netProfit);
        netProfitEl.className = `pnl-value ${netProfit >= 0 ? 'positive' : 'negative'}`;
    }

    const realizedPnlEl = document.getElementById('realizedPnL');
    if (realizedPnlEl && pnlData) {
        realizedPnlEl.textContent = formatCurrency(pnlData.realized_pnl || 0);
        realizedPnlEl.className = `pnl-value ${(pnlData.realized_pnl || 0) >= 0 ? 'positive' : 'negative'}`;
    }

    const unrealizedPnlEl = document.getElementById('unrealizedPnL');
    if (unrealizedPnlEl && pnlData) {
        unrealizedPnlEl.textContent = formatCurrency(pnlData.unrealized_pnl || 0);
        unrealizedPnlEl.className = `pnl-value ${(pnlData.unrealized_pnl || 0) >= 0 ? 'positive' : 'negative'}`;
    }

    const apiCostsEl = document.getElementById('actualApiCosts');
    const apiCostsTodayEl = document.getElementById('apiCostsToday');

    if (apiCostsEl && apiUsage && apiUsage.usage) {
        apiCostsEl.textContent = `$${(apiUsage.usage.total_cost_usd || 0).toFixed(4)}`;
    }

    if (apiCostsTodayEl && apiUsage && apiUsage.usage) {
        apiCostsTodayEl.textContent = `$${(apiUsage.usage.cost_today_usd || 0).toFixed(4)}`;
    }

    const totalTokensEl = document.getElementById('totalTokens');
    const inputTokensEl = document.getElementById('inputTokens');
    const outputTokensEl = document.getElementById('outputTokens');

    if (apiUsage && apiUsage.usage) {
        const inputTokens = apiUsage.usage.total_input_tokens || 0;
        const outputTokens = apiUsage.usage.total_output_tokens || 0;

        if (totalTokensEl) totalTokensEl.textContent = (inputTokens + outputTokens).toLocaleString();
        if (inputTokensEl) inputTokensEl.textContent = inputTokens.toLocaleString();
        if (outputTokensEl) outputTokensEl.textContent = outputTokens.toLocaleString();
    }

    const breakEvenEl = document.getElementById('breakEvenStatus');
    if (breakEvenEl && costBreakdown) {
        if (costBreakdown.break_even_achieved) {
            breakEvenEl.textContent = 'Profitable';
            breakEvenEl.className = 'badge badge-success';
        } else {
            breakEvenEl.textContent = 'Below Break-Even';
            breakEvenEl.className = 'badge badge-warning';
        }
    }

    const profitMarginEl = document.getElementById('profitMargin');
    if (profitMarginEl && costBreakdown) {
        const margin = costBreakdown.profit_margin_pct || 0;
        profitMarginEl.textContent = `${margin.toFixed(1)}%`;
    }

    const tradesToBreakevenEl = document.getElementById('tradesToBreakeven');
    if (tradesToBreakevenEl && costBreakdown) {
        const trades = costBreakdown.trades_to_breakeven || 0;
        tradesToBreakevenEl.textContent = trades <= 0 ? 'N/A' : trades.toString();
    }

    const costPerTradeEl = document.getElementById('costPerTrade');
    if (costPerTradeEl && apiUsage && apiUsage.usage) {
        const totalCalls = apiUsage.usage.total_calls || 1;
        const totalCost = apiUsage.usage.total_cost_usd || 0;
        costPerTradeEl.textContent = `$${(totalCost / totalCalls).toFixed(4)}`;
    }

    const avgProfitPerTradeEl = document.getElementById('avgProfitPerTrade');
    if (avgProfitPerTradeEl && pnlData) {
        const avgProfit = pnlData.avg_profit_per_trade || 0;
        avgProfitPerTradeEl.textContent = formatCurrency(avgProfit);
    }

    const apiCallCountEl = document.getElementById('apiCallCount');
    if (apiCallCountEl && apiUsage && apiUsage.usage) {
        apiCallCountEl.textContent = (apiUsage.usage.total_calls || 0).toLocaleString();
    }

    const realizedPnLPctEl = document.getElementById('realizedPnLPct');
    if (realizedPnLPctEl && pnlData) {
        const pct = ((pnlData.realized_pnl || 0) / CONFIG.INITIAL_CAPITAL) * 100;
        realizedPnLPctEl.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
    }

    const unrealizedPnLPctEl = document.getElementById('unrealizedPnLPct');
    if (unrealizedPnLPctEl && pnlData) {
        const pct = ((pnlData.unrealized_pnl || 0) / CONFIG.INITIAL_CAPITAL) * 100;
        unrealizedPnLPctEl.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
    }

    const profitProgressBar = document.getElementById('profitProgressBar');
    if (profitProgressBar && pnlData) {
        const netProfit = pnlData.net_profit || 0;
        const pct = (netProfit / CONFIG.INITIAL_CAPITAL) * 100;
        const position = Math.max(0, Math.min(100, 50 + (pct * 2.5)));
        profitProgressBar.style.width = `${position}%`;
    }

    const pairPnLList = document.getElementById('pairPnLList');
    if (pairPnLList && pnlData && pnlData.by_pair) {
        pairPnLList.innerHTML = '';
        const pairs = Object.entries(pnlData.by_pair);

        if (pairs.length === 0) {
            pairPnLList.innerHTML = `
                <div class="pair-pnl-item">
                    <span class="pair-name">No trades yet</span>
                    <span class="pair-value">--</span>
                </div>
            `;
        } else {
            pairs.sort((a, b) => (b[1].pnl || 0) - (a[1].pnl || 0));

            pairs.forEach(([pair, data]) => {
                const pnl = data.pnl || 0;
                const pnlClass = pnl >= 0 ? 'positive' : 'negative';
                pairPnLList.innerHTML += `
                    <div class="pair-pnl-item">
                        <span class="pair-name">${pair}</span>
                        <span class="pair-value ${pnlClass}">${formatCurrency(pnl)}</span>
                    </div>
                `;
            });
        }
    }

    const apiCostsTrend = document.getElementById('apiCostsTrend');
    if (apiCostsTrend && apiUsage && apiUsage.usage) {
        const totalCost = apiUsage.usage.total_cost_usd || 0;
        if (totalCost < 0.01) {
            apiCostsTrend.textContent = 'Low';
            apiCostsTrend.className = 'badge badge-success';
        } else if (totalCost < 0.10) {
            apiCostsTrend.textContent = 'Normal';
            apiCostsTrend.className = 'badge badge-neutral';
        } else {
            apiCostsTrend.textContent = 'High';
            apiCostsTrend.className = 'badge badge-warning';
        }
    }
}
