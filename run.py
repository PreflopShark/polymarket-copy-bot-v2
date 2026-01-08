"""
Startup script for Polymarket Copy Bot Web App.

Usage:
    python run.py

Opens the web interface at http://localhost:8000
"""

import os
import sys
import webbrowser
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Change to project directory to ensure .env is loaded correctly
os.chdir(project_root)


def main():
    import uvicorn

    print("=" * 50)
    print("POLYMARKET COPY BOT WEB APP")
    print("=" * 50)
    print("Starting server...")
    print("Open http://localhost:8000 in your browser")
    print("=" * 50)

    # Open browser after a short delay
    import threading
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=open_browser, daemon=True).start()

    # Start the server
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    main()
