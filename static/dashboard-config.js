// Dashboard Configuration with Production/Local Detection
const DashboardConfig = {
    // Detect if running on Cloud Run
    isProduction: window.location.hostname.includes('run.app'),
    
    // Get appropriate WebSocket configuration
    getWebSocketConfig: function() {
        if (this.isProduction) {
            // Disable WebSocket for Cloud Run deployments
            return {
                enabled: false,
                fallbackToPolling: true,
                pollingInterval: 5000  // Poll every 5 seconds for updates
            };
        } else {
            // Enable WebSocket for local development
            return {
                enabled: true,
                fallbackToPolling: true,
                url: `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/portfolio`
            };
        }
    },
    
    // Log current configuration
    logConfig: function() {
        console.log(`[Dashboard Config] Environment: ${this.isProduction ? 'PRODUCTION (Cloud Run)' : 'LOCAL'}`);
        const wsConfig = this.getWebSocketConfig();
        console.log(`[Dashboard Config] WebSocket: ${wsConfig.enabled ? 'ENABLED' : 'DISABLED (using polling)'}`);
        if (!wsConfig.enabled) {
            console.log(`[Dashboard Config] Polling interval: ${wsConfig.pollingInterval}ms`);
        }
    }
};

// Export for use in dashboard.js
window.DashboardConfig = DashboardConfig;