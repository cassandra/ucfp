from dataclasses import dataclass, asdict
import json


@dataclass
class ClientConfig:
    """Structured client-side configuration object.  Provides type safety
    and clear field definitions for server-to-client communication: the base
    template emits this as the ``window.__APP_CONFIG__`` JS global. Consumed
    only by main.js, which relays it via ``App.config``; all other JS modules
    read ``App.config`` rather than the raw global.
    """
    DEBUG                : bool
    ENVIRONMENT          : str
    VERSION              : str
    
    def to_json_dict(self) -> dict:
        """
        Convert to dictionary suitable for JSON serialization in templates.
        Ensures proper JavaScript boolean/null handling.
        """
        return json.dumps({
            key: (value if value is not None else 'null')
            for key, value in asdict(self).items()
        }, indent=4 )
