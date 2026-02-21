# Kraken Trader WebSocket Connection Fix

## Problem
The dashboard was showing WebSocket connection failures with repeated reconnection attempts because the server wasn't running.

## Root Cause Analysis
1. **Server Not Running**: The primary issue was that the Kraken Trader server wasn't running at all
2. **Unicode Encoding Issues**: When starting the server, Unicode characters (→, ✓, 🚀) in log messages caused crashes on Windows
3. **No Auto-Start**: Server needed to be manually started each time

## Solution Implemented

### 1. Fixed Server Startup
Created `start-server-fixed.ps1` that:
- Sets proper UTF-8 encoding for Python and console
- Checks if server is already running before starting
- Provides clear status messages

### 2. Test Script
Created `test-connection.ps1` to verify:
- REST API endpoints are responding
- Portfolio data is accessible
- WebSocket endpoint is available

### 3. Auto-Start Option
Created `setup-autostart.ps1` that:
- Creates a Windows scheduled task
- Starts server 30 seconds after system boot
- Includes retry logic if server crashes

## Usage

### Manual Start
```powershell
# From kraken-trader directory
.\start-server-fixed.ps1
```

### Auto-Start Setup
```powershell
# Enable auto-start
.\setup-autostart.ps1

# Remove auto-start
.\setup-autostart.ps1 -Remove
```

### Testing Connections
```powershell
.\test-connection.ps1
```

## Dashboard Access
Once the server is running:
- Dashboard: http://localhost:8080/dashboard/index.html
- API Status: http://localhost:8080/api/status
- WebSocket: ws://localhost:8080/ws/portfolio

## Verification
1. Server is running: Check for "Uvicorn running on http://0.0.0.0:8080"
2. API responds: `test-connection.ps1` shows all green
3. Dashboard loads: No more WebSocket errors in console
4. Real-time updates: Portfolio values update automatically

## Technical Details
- The server runs in simulation mode by default (no real trades)
- WebSocket provides real-time portfolio updates to the dashboard
- Redis cache is optional (falls back to in-memory if not available)
- All API endpoints support CORS for browser access