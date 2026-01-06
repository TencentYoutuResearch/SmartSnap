# pylint: disable=line-too-long, function-name-too-long
"""
SV-AGENT: A mobile automation and verification agent.

This package provides tools for mobile automation, testing, and verification.
"""

__version__ = "0.1.0"

# Import main modules for easier access
from . import link

# Docker managers for easier import
from .mobile_session import (
    DockerManagerInterface,
    AdvancedDockerManager,
    TioneDockerManager,
    LegacyDockerManager,
    MobileSession
)

# Factory for creating docker managers
from .docker_manager_factory import (
    DockerManagerFactory,
    create_advanced_manager,
    create_tione_manager,
    get_recommended_manager
)
from . import page_executor
from . import recorder
from . import templates
from . import utils_mobile

# Import commonly used classes for convenience
from .page_executor import TextOnlyExecutor
from .recorder.json_recorder import JSONRecorder

__all__ = [
    "link",
    "page_executor", 
    "recorder",
    "templates",
    "utils_mobile",
    "TextOnlyExecutor",
    "JSONRecorder",
]
