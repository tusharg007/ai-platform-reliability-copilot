"""Production Dockerfile for the AI Platform Reliability Copilot.

Multi-stage build:
  Stage 1 (builder): Install Python dependencies in a venv
  Stage 2 (runtime): Lean final image without build tools
"""
