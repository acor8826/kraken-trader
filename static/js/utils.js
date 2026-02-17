/**
 * Utility Functions for Kraken Trading Dashboard
 * Formatting, helpers, and common operations
 */

// ========================================
// Number Formatting
// ========================================

/**
 * Format number as currency
 * @param {number} value - Value to format
 * @param {string} currency - Currency code (default: AUD)
 * @param {number} decimals - Decimal places (default: 2)
 * @returns {string} - Formatted currency string
 */
export function formatCurrency(value, currency = 'AUD', decimals = 2) {
    if (value === null || value === undefined || isNaN(value)) {
        return '$0.00';
    }

    const absValue = Math.abs(value);
    const sign = value < 0 ? '-' : '';

    // Use compact notation for large numbers
    if (absValue >= 1000000) {
        return `${sign}$${(absValue / 1000000).toFixed(2)}M`;
    }
    if (absValue >= 10000) {
        return `${sign}$${(absValue / 1000).toFixed(1)}K`;
    }

    return `${sign}$${absValue.toFixed(decimals)}`;
}

/**
 * Format number as percentage
 * @param {number} value - Value (0.05 = 5%)
 * @param {number} decimals - Decimal places
 * @returns {string} - Formatted percentage
 */
export function formatPercent(value, decimals = 1) {
    if (value === null || value === undefined || isNaN(value)) {
        return '0%';
    }

    const sign = value > 0 ? '+' : '';
    return `${sign}${(value * 100).toFixed(decimals)}%`;
}

/**
 * Format number with commas
 * @param {number} value - Value to format
 * @param {number} decimals - Decimal places
 * @returns {string} - Formatted number
 */
export function formatNumber(value, decimals = 2) {
    if (value === null || value === undefined || isNaN(value)) {
        return '0';
    }

    return value.toLocaleString('en-AU', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

/**
 * Format crypto amount (smart decimals based on size)
 * @param {number} value - Amount
 * @param {string} symbol - Crypto symbol
 * @returns {string} - Formatted amount
 */
export function formatCryptoAmount(value, symbol = '') {
    if (value === null || value === undefined || isNaN(value)) {
        return '0';
    }

    let decimals = 8;
    if (value >= 1) decimals = 4;
    if (value >= 100) decimals = 2;
    if (value >= 10000) decimals = 0;

    const formatted = value.toFixed(decimals);
    return symbol ? `${formatted} ${symbol}` : formatted;
}

// ========================================
// Time Formatting
// ========================================

/**
 * Format timestamp as relative time ("2 min ago")
 * @param {string|number|Date} timestamp - Timestamp
 * @returns {string} - Relative time string
 */
export function formatTimeAgo(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;

    return date.toLocaleDateString('en-AU', { month: 'short', day: 'numeric' });
}

/**
 * Format timestamp as time (HH:MM)
 * @param {string|number|Date} timestamp - Timestamp
 * @returns {string} - Time string
 */
export function formatTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' });
}

/**
 * Format timestamp as date/time
 * @param {string|number|Date} timestamp - Timestamp
 * @returns {string} - Date/time string
 */
export function formatDateTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleString('en-AU', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Format seconds as countdown (MM:SS)
 * @param {number} seconds - Seconds remaining
 * @returns {string} - Countdown string
 */
export function formatCountdown(seconds) {
    if (seconds === null || seconds === undefined || seconds < 0) {
        return '--:--';
    }

    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// ========================================
// Trading Helpers
// ========================================

/**
 * Get CSS class for P&L value
 * @param {number} value - P&L value
 * @returns {string} - CSS class
 */
export function getPnLClass(value) {
    if (value > 0) return 'profit';
    if (value < 0) return 'loss';
    return 'neutral';
}

/**
 * Get action badge class
 * @param {string} action - Trade action (BUY, SELL, HOLD)
 * @returns {string} - CSS class
 */
export function getActionClass(action) {
    switch (action?.toUpperCase()) {
        case 'BUY': return 'badge-success';
        case 'SELL': return 'badge-danger';
        case 'HOLD': return 'badge-neutral';
        default: return 'badge-neutral';
    }
}

/**
 * Get status badge class
 * @param {string} status - Status string
 * @returns {string} - CSS class
 */
export function getStatusClass(status) {
    switch (status?.toUpperCase()) {
        case 'ACTIVE':
        case 'RUNNING':
        case 'FILLED':
        case 'EXECUTED':
            return 'badge-success';
        case 'PAUSED':
        case 'PENDING':
            return 'badge-warning';
        case 'STOPPED':
        case 'ERROR':
        case 'FAILED':
        case 'REJECTED':
            return 'badge-danger';
        default:
            return 'badge-neutral';
    }
}

/**
 * Extract base currency from pair (e.g., "BTC/AUD" -> "BTC")
 * @param {string} pair - Trading pair
 * @returns {string} - Base currency
 */
export function getBaseCurrency(pair) {
    return pair?.split('/')[0] || '';
}

/**
 * Extract quote currency from pair (e.g., "BTC/AUD" -> "AUD")
 * @param {string} pair - Trading pair
 * @returns {string} - Quote currency
 */
export function getQuoteCurrency(pair) {
    return pair?.split('/')[1] || 'AUD';
}

// ========================================
// DOM Helpers
// ========================================

/**
 * Create element with attributes and children
 * @param {string} tag - Element tag
 * @param {object} attrs - Attributes
 * @param {array|string} children - Children
 * @returns {HTMLElement} - Created element
 */
export function createElement(tag, attrs = {}, children = []) {
    const el = document.createElement(tag);

    for (const [key, value] of Object.entries(attrs)) {
        if (key === 'class' || key === 'className') {
            el.className = value;
        } else if (key === 'style' && typeof value === 'object') {
            Object.assign(el.style, value);
        } else if (key.startsWith('on') && typeof value === 'function') {
            el.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (key === 'dataset') {
            Object.assign(el.dataset, value);
        } else {
            el.setAttribute(key, value);
        }
    }

    if (typeof children === 'string') {
        el.textContent = children;
    } else if (Array.isArray(children)) {
        children.forEach(child => {
            if (typeof child === 'string') {
                el.appendChild(document.createTextNode(child));
            } else if (child instanceof Node) {
                el.appendChild(child);
            }
        });
    }

    return el;
}

/**
 * Safely set innerHTML and re-init Lucide icons
 * @param {HTMLElement} element - Target element
 * @param {string} html - HTML content
 */
export function setHTML(element, html) {
    element.innerHTML = html;

    // Re-initialize Lucide icons
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

/**
 * Show toast notification
 * @param {string} message - Message to show
 * @param {string} type - Type: 'success', 'error', 'warning', 'info'
 * @param {number} duration - Duration in ms (default: 3000)
 */
export function showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toast-container') ||
                      createToastContainer();

    const toast = createElement('div', {
        class: `toast toast-${type}`,
    }, [
        createElement('span', { class: 'toast-message' }, message),
        createElement('button', {
            class: 'toast-close',
            onClick: () => toast.remove()
        }, '\u00D7')
    ]);

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => toast.classList.add('show'));

    // Auto-remove
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/**
 * Create toast container if not exists
 */
function createToastContainer() {
    const container = createElement('div', { id: 'toast-container', class: 'toast-container' });
    document.body.appendChild(container);
    return container;
}

// ========================================
// Utility Helpers
// ========================================

/**
 * Debounce function
 * @param {function} fn - Function to debounce
 * @param {number} delay - Delay in ms
 * @returns {function} - Debounced function
 */
export function debounce(fn, delay = 300) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delay);
    };
}

/**
 * Throttle function
 * @param {function} fn - Function to throttle
 * @param {number} limit - Limit in ms
 * @returns {function} - Throttled function
 */
export function throttle(fn, limit = 100) {
    let inThrottle;
    return (...args) => {
        if (!inThrottle) {
            fn(...args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Generate unique ID
 * @returns {string} - Unique ID
 */
export function generateId() {
    return `id_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Deep clone object
 * @param {object} obj - Object to clone
 * @returns {object} - Cloned object
 */
export function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}

/**
 * Check if value is empty (null, undefined, empty string/array/object)
 * @param {any} value - Value to check
 * @returns {boolean} - True if empty
 */
export function isEmpty(value) {
    if (value === null || value === undefined) return true;
    if (typeof value === 'string') return value.trim() === '';
    if (Array.isArray(value)) return value.length === 0;
    if (typeof value === 'object') return Object.keys(value).length === 0;
    return false;
}

/**
 * Escape HTML to prevent XSS
 * @param {string} str - String to escape
 * @returns {string} - Escaped string
 */
export function escapeHTML(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
