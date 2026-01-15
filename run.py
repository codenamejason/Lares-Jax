#!/usr/bin/env python3
"""Runner script for Jax Assistant - Phase 1 MCP Architecture.

This uses the main_mcp.py entry point which connects to the MCP server
for Discord I/O and executes tools client-side.
"""

import sys
import os

sys.path.insert(0, 'src')

# Load .env file first
from dotenv import load_dotenv
load_dotenv()

# Configure SSL certificates using certifi (fixes macOS certificate issues)
import certifi
import ssl
os.environ["SSL_CERT_FILE"] = certifi.where()
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

# Enable context monitoring if configured
if os.getenv("LARES_CONTEXT_MONITORING", "false").lower() == "true":
    try:
        from lares.monitoring_patch import apply_monitoring_patch
        analyzer = apply_monitoring_patch()
        print("[MAIN] Context monitoring activated", flush=True)
    except Exception as e:
        print(f"WARNING: Context monitoring failed: {e}", flush=True)

# Import and run the Phase 1 MCP entry point
from lares.main_mcp import main

if __name__ == "__main__":
    main()
