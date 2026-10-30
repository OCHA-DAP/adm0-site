"""Run the pipeline steps in order."""

from importlib import import_module

from .config import steps

for step in steps:
    import_module(f"pipeline.{step}").main()
