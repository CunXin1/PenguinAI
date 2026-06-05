"""Real-time market-data ingestion (IBKR stream + Massive poller + after-close 30m).

Started as a subprocess by the FastAPI lifespan (see backend/app/main.py) when
REALTIME_ENABLED is true, so the live data layer comes up with the backend.
Entry point: ``python -m data.ingestion.realtime.supervisor``.
"""
