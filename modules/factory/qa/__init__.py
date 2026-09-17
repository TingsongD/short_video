"""Isolated QA harness for factory modules (F01).

CLI: python -m modules.factory.qa init|cases|run|inspect|evidence
Workspaces live under data/factory-qa/ (git-ignored). A case exercises real
application services against fake external transports whose effects persist
independently of the application database.
"""
