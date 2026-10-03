"""
FastAPI application package. The app lives in src.api.app, and this package imports nothing: Vercel's runtime
loads src/api/app.py before the package, so an import of the app here would meet it half-loaded
(tests/test_vercel_config.py).
"""
