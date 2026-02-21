/**
 * WebSocket Manager for Kraken Trading Dashboard
 * Handles real-time portfolio updates with auto-reconnect
 */

import store from './store.js';

class WebSocketManager {
    constructor() {
        this.ws = null;
        this.listeners = new Map();
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 5000;
        this.maxReconnectDelay = 30000;
        this.pingInterval = null;
        this.isConnecting = false;
        this.shouldReconnect = true;
    }

    /**
     * Get WebSocket URL based on current location
     */
    getWsUrl() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        return `${protocol}//${host}/ws/portfolio`;
    }

    /**
     * Connect to WebSocket server
     */
    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            console.log('WebSocket already connected or connecting');
            return;
        }

        if (this.isConnecting) {
            return;
        }

        this.isConnecting = true;
        this.shouldReconnect = true;
        store.set('wsReconnecting', this.reconnectAttempts > 0);

        try {
            const wsUrl = this.getWsUrl();
            console.log('Connecting to WebSocket:', wsUrl);

            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.isConnecting = false;
                this.reconnectAttempts = 0;
                store.set('wsConnected', true);
                store.set('wsReconnecting', false);

                // Start ping interval
                this.startPing();

                // Notify listeners
                this.emit('connected', null);
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (e) {
                    console.warn('Failed to parse WebSocket message:', e);
                }
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket closed:', event.code, event.reason);
                this.isConnecting = false;
                this.stopPing();
                store.set('wsConnected', false);

                // Notify listeners
                this.emit('disconnected', { code: event.code, reason: event.reason });

                // Attempt reconnect
                if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.scheduleReconnect();
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.isConnecting = false;
                this.emit('error', error);
            };

        } catch (e) {
            console.error('WebSocket connection error:', e);
            this.isConnecting = false;
            this.scheduleReconnect();
        }
    }

    /**
     * Disconnect from WebSocket
     */
    disconnect() {
        this.shouldReconnect = false;
        this.stopPing();

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        store.set('wsConnected', false);
    }

    /**
     * Schedule reconnection with exponential backoff
     */
    scheduleReconnect() {
        if (!this.shouldReconnect) return;

        this.reconnectAttempts++;
        store.set('wsReconnecting', true);

        // Exponential backoff
        const delay = Math.min(
            this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
            this.maxReconnectDelay
        );

        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

        setTimeout(() => {
            if (this.shouldReconnect) {
                this.connect();
            }
        }, delay);
    }

    /**
     * Start ping interval to keep connection alive
     */
    startPing() {
        this.stopPing();
        this.pingInterval = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);
    }

    /**
     * Stop ping interval
     */
    stopPing() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    /**
     * Handle incoming WebSocket message
     */
    handleMessage(data) {
        // Update store with portfolio data
        if (data.portfolio || data.total_value !== undefined) {
            this.updateStoreFromPortfolio(data);
        }

        // Emit to listeners
        this.emit('message', data);
        this.emit('portfolio', data);
    }

    /**
     * Update store from portfolio data
     */
    updateStoreFromPortfolio(data) {
        store.update({
            portfolio: data,
            totalValue: data.total_value || 0,
            availableQuote: data.available_quote || 0,
            totalPnL: data.total_pnl || 0,
            pnlPercent: data.pnl_percent || 0,
            progressToTarget: data.progress_to_target || 0,
            positions: data.positions || []
        });
    }

    /**
     * Subscribe to WebSocket events
     * @param {string} event - Event type ('connected', 'disconnected', 'message', 'portfolio', 'error')
     * @param {function} callback - Callback function
     * @returns {function} - Unsubscribe function
     */
    subscribe(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, new Set());
        }
        this.listeners.get(event).add(callback);

        return () => {
            const eventListeners = this.listeners.get(event);
            if (eventListeners) {
                eventListeners.delete(callback);
            }
        };
    }

    /**
     * Emit event to listeners
     */
    emit(event, data) {
        const eventListeners = this.listeners.get(event);
        if (eventListeners) {
            eventListeners.forEach(callback => {
                try {
                    callback(data);
                } catch (e) {
                    console.error(`WebSocket listener error [${event}]:`, e);
                }
            });
        }
    }

    /**
     * Send message to server
     */
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            console.warn('WebSocket not connected, cannot send message');
        }
    }

    /**
     * Check if connected
     */
    isConnected() {
        return this.ws && this.ws.readyState === WebSocket.OPEN;
    }
}

// Export singleton instance
const wsManager = new WebSocketManager();
export default wsManager;
