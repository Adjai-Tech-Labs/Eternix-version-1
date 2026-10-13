from eternix.tools.registry import tool_registry


def _safe_import(module_name: str, register_func: str):
    try:
        module = __import__(f"eternix.tools.{module_name}", fromlist=[register_func])
        return getattr(module, register_func)
    except ImportError:
        def _noop():
            pass
        return _noop

register_audio_tools = _safe_import("audio", "register_audio_tools")
register_coding_tools = _safe_import("coding", "register_coding_tools")
register_command_tools = _safe_import("command", "register_command_tools")
register_data_tools = _safe_import("data", "register_data_tools")
register_document_tools = _safe_import("document", "register_document_tools")
register_filesystem_tools = _safe_import("filesystem", "register_filesystem_tools")
register_memory_tools = _safe_import("memory", "register_memory_tools")
register_vision_tools = _safe_import("vision", "register_vision_tools")
register_web_tools = _safe_import("web", "register_web_tools")
register_generation_tools = _safe_import("generation", "register_generation_tools")

__all__ = [
    "register_audio_tools",
    "register_coding_tools",
    "register_command_tools",
    "register_data_tools",
    "register_document_tools",
    "register_filesystem_tools",
    "register_generation_tools",
    "register_memory_tools",
    "register_vision_tools",
    "register_web_tools",
    "tool_registry",
]