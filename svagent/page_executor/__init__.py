"""
Page executor module for SV-AGENT.

This module provides page execution functionality for mobile automation.
"""

from .text_executor import TextOnlyExecutor
from . import utils

__all__ = ["TextOnlyExecutor", "utils"]
