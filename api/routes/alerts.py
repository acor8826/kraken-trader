"""
Alerts API Routes

Endpoints for viewing and managing alerts.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any, List

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Will be set by app.py during initialization
alert_manager = None


def set_alert_manager(manager) -> None:
    """Set the alert manager instance"""
    global alert_manager
    alert_manager = manager


@router.get("/recent")
async def get_recent_alerts(limit: int = 50) -> Dict[str, Any]:
    """
    Get recent alerts.

    Args:
        limit: Maximum number of alerts to return (default 50, max 100)

    Returns:
        List of recent alerts with metadata
    """
    if alert_manager is None:
        return {
            "alerts": [],
            "count": 0,
            "enabled": False,
            "message": "Alert manager not initialized"
        }

    # Clamp limit
    limit = max(1, min(limit, 100))

    alerts = alert_manager.get_recent(limit)

    return {
        "alerts": alerts,
        "count": len(alerts),
        "enabled": alert_manager._enabled,
        "total_history": len(alert_manager.alert_history)
    }


@router.get("/config")
async def get_alert_config() -> Dict[str, Any]:
    """
    Get alert configuration.

    Returns:
        Alert system configuration including enabled channels
    """
    if alert_manager is None:
        return {
            "enabled": False,
            "channels": [],
            "history_size": 0,
            "max_history": 0,
            "message": "Alert manager not initialized"
        }

    return alert_manager.get_config()


@router.post("/test")
async def send_test_alert() -> Dict[str, Any]:
    """
    Send a test alert to verify channels are working.

    Returns:
        Success status
    """
    if alert_manager is None:
        raise HTTPException(status_code=503, detail="Alert manager not initialized")

    try:
        await alert_manager.system_alert(
            "Test alert from Trading Agent",
            data={"test": True}
        )
        return {"success": True, "message": "Test alert sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/enable")
async def enable_alerts() -> Dict[str, Any]:
    """Enable the alert system"""
    if alert_manager is None:
        raise HTTPException(status_code=503, detail="Alert manager not initialized")

    alert_manager.enable()
    return {"enabled": True, "message": "Alerting enabled"}


@router.post("/disable")
async def disable_alerts() -> Dict[str, Any]:
    """Disable the alert system"""
    if alert_manager is None:
        raise HTTPException(status_code=503, detail="Alert manager not initialized")

    alert_manager.disable()
    return {"enabled": False, "message": "Alerting disabled"}


@router.get("/channels")
async def list_channels() -> Dict[str, Any]:
    """
    List all configured alert channels.

    Returns:
        List of channels with their status
    """
    if alert_manager is None:
        return {"channels": [], "message": "Alert manager not initialized"}

    channels = []
    for ch in alert_manager.channels:
        channel_info = {
            "name": ch.name,
            "type": ch.__class__.__name__,
            "enabled": ch.enabled
        }

        # Add channel-specific info
        if hasattr(ch, "file_path"):
            channel_info["file_path"] = str(ch.file_path)
        if hasattr(ch, "platform"):
            channel_info["platform"] = ch.platform
        if hasattr(ch, "url"):
            # Mask webhook URL for security
            channel_info["url_configured"] = bool(ch.url)

        channels.append(channel_info)

    return {"channels": channels}


@router.post("/channels/{channel_name}/enable")
async def enable_channel(channel_name: str) -> Dict[str, Any]:
    """Enable a specific channel"""
    if alert_manager is None:
        raise HTTPException(status_code=503, detail="Alert manager not initialized")

    for ch in alert_manager.channels:
        if ch.name == channel_name:
            ch.enable()
            return {"channel": channel_name, "enabled": True}

    raise HTTPException(status_code=404, detail=f"Channel '{channel_name}' not found")


@router.post("/channels/{channel_name}/disable")
async def disable_channel(channel_name: str) -> Dict[str, Any]:
    """Disable a specific channel"""
    if alert_manager is None:
        raise HTTPException(status_code=503, detail="Alert manager not initialized")

    for ch in alert_manager.channels:
        if ch.name == channel_name:
            ch.disable()
            return {"channel": channel_name, "enabled": False}

    raise HTTPException(status_code=404, detail=f"Channel '{channel_name}' not found")


@router.get("/stats")
async def get_alert_stats() -> Dict[str, Any]:
    """
    Get alert statistics.

    Returns:
        Statistics about alerts by type and level
    """
    if alert_manager is None:
        return {
            "total": 0,
            "by_type": {},
            "by_level": {},
            "message": "Alert manager not initialized"
        }

    alerts = list(alert_manager.alert_history)

    # Count by type
    by_type = {}
    for alert in alerts:
        type_name = alert.type.value
        by_type[type_name] = by_type.get(type_name, 0) + 1

    # Count by level
    by_level = {}
    for alert in alerts:
        level_name = alert.level.value
        by_level[level_name] = by_level.get(level_name, 0) + 1

    return {
        "total": len(alerts),
        "by_type": by_type,
        "by_level": by_level
    }
