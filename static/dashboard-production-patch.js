// Production-compatible dashboard patch
// This file patches the existing dashboard.js to work on Cloud Run

// Override WebSocket connection function
const originalConnectWebSocket = window.connectWebSocket;

window.connectWebSocket = function() {
    const config = window.DashboardConfig.getWebSocketConfig();
    
    if (!config.enabled) {
        console.log('[WebSocket] Disabled for production - using polling instead');
        
        // Set up polling for portfolio updates
        if (!state.pollingInterval) {
            state.pollingInterval = setInterval(async () => {
                try {
                    const portfolio = await fetchPortfolio();
                    if (portfolio) {
                        handleWebSocketMessage({
                            type: 'portfolio_update',
                            total_value: portfolio.total_value,
                            holdings: portfolio.positions || {},
                            timestamp: new Date().toISOString()
                        });
                    }
                } catch (error) {
                    console.error('[Polling] Failed to fetch portfolio:', error);
                }
            }, config.pollingInterval);
            
            console.log(`[Polling] Started with ${config.pollingInterval}ms interval`);
        }
        
        // Mock connected state
        state.wsConnected = true;
        updateWebSocketStatus(true);
        return;
    }
    
    // Original WebSocket logic for local development
    if (originalConnectWebSocket) {
        originalConnectWebSocket();
    }
};

// Clean up polling on page unload
window.addEventListener('beforeunload', () => {
    if (state.pollingInterval) {
        clearInterval(state.pollingInterval);
    }
});

// Initialize configuration logging
window.DashboardConfig.logConfig();