"""Input plugins: OSC, WebSocket and MIDI."""
from .midi_in import MIDIInput
from .osc_in import OSCInput
from .websocket_in import WebSocketInput

INPUT_TYPES = {"osc": OSCInput, "websocket": WebSocketInput, "midi": MIDIInput}

__all__ = ["INPUT_TYPES", "MIDIInput", "OSCInput", "WebSocketInput"]
