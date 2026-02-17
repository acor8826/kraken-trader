"""
Quick test script to verify WebSocket portfolio updates work.

Run this while the trading agent is running to see live portfolio updates.
"""

import asyncio
import websockets
import json


async def test_websocket():
    """Connect to WebSocket and listen for portfolio updates."""
    uri = "ws://localhost:8080/ws/portfolio"

    print(f"Connecting to {uri}...")

    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected to portfolio WebSocket!")

            # Receive messages
            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "connection":
                    print(f"\n📡 Connection established: {data.get('message')}")
                    print(f"   Connection ID: {data.get('connection_id')}")
                    if "initial_portfolio" in data:
                        portfolio = data["initial_portfolio"]
                        print(f"   Initial Portfolio Value: ${portfolio.get('total_value', 0):,.2f}")

                elif msg_type == "portfolio_update":
                    print(f"\n📊 Portfolio Update Received:")
                    print(f"   Total Value: ${data.get('total_value', 0):,.2f}")
                    print(f"   Holdings: {data.get('holdings', {})}")
                    print(f"   Timestamp: {data.get('timestamp')}")

                else:
                    print(f"\n📨 Received: {data}")

    except websockets.exceptions.WebSocketException as e:
        print(f"❌ WebSocket error: {e}")
        print("\nMake sure the trading agent is running:")
        print("   python main.py")

    except KeyboardInterrupt:
        print("\n\n👋 Disconnected")


if __name__ == "__main__":
    print("=" * 60)
    print("WebSocket Portfolio Update Tester")
    print("=" * 60)
    print("\nThis will connect to the live portfolio WebSocket endpoint")
    print("and display real-time updates as they occur.\n")

    asyncio.run(test_websocket())
