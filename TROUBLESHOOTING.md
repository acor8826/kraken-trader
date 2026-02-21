# Kraken Trader Dashboard Troubleshooting

## WebSocket Connection Issues

### Problem: WebSocket connection fails repeatedly
**Symptoms:**
- Dashboard shows "WebSocket connection failed" errors
- Reconnection attempts with increasing delays (5s, 10s, 15s, etc.)

**Solution:**
1. **Start the server first** (use the fixed version):
   ```powershell
   # PowerShell - Recommended (handles Unicode properly)
   .\start-server-fixed.ps1
   
   # Or original scripts
   .\start-server.ps1  # May have Unicode issues
   start-server.bat    # Command Prompt version
   ```
   
   See [WEBSOCKET-FIX.md](./WEBSOCKET-FIX.md) for complete fix details.

2. **Verify server is running**:
   - Check if you see "Uvicorn running on http://0.0.0.0:8080"
   - Open http://localhost:8080/api/status in your browser
   - Should return JSON with status information

3. **Check port availability**:
   ```powershell
   netstat -ano | findstr :8080
   ```
   - Should show "LISTENING" state on port 8080

### Common Issues:

**1. Missing Dependencies**
```bash
pip install -r requirements.txt
```

**2. Port Already in Use**
- Change port in environment or kill existing process:
```powershell
# Find process using port 8080
netstat -ano | findstr :8080
# Kill process (replace PID with actual process ID)
taskkill /PID <PID> /F
```

**3. Missing API Keys**
- The server runs in SIMULATION_MODE by default
- For live trading, set KRAKEN_API_KEY and KRAKEN_API_SECRET

**4. Browser Console Warnings**
- `lockdown-install.js:1 SES Removing unpermitted intrinsics` - This is a security feature, safe to ignore
- `favicon.ico 404` - Cosmetic issue, doesn't affect functionality

## Dashboard Not Loading

1. **Clear browser cache**: Ctrl+Shift+R
2. **Check browser console**: F12 → Console tab
3. **Verify static files**: Check if `/dashboard/index.html` exists

## API Errors

**503 Service Unavailable**
- Server not fully initialized
- Wait a few seconds after starting

**500 Internal Server Error**
- Check server logs in terminal
- Usually indicates missing configuration

## Performance Issues

**Slow Updates**
- Portfolio data is cached for 30 seconds
- Manual refresh: Click "Refresh" button
- Force trading cycle: Click "Trigger Cycle"