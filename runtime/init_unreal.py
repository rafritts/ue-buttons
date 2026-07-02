"""Auto-run by UE at editor startup (Content/Python/init_unreal.py).

Just makes `ue_buttons` importable and confirms it loaded. The MCP server drives
everything else by POSTing `import ue_buttons; ue_buttons.dispatch(...)` over Remote
Control, so there is nothing to register here — no addon install step (SPEC-00).
"""
import unreal

try:
    import ue_buttons  # noqa: F401  (import side effect: package ready for dispatch)
    unreal.log("[ue_buttons] runtime loaded — dispatch ready")
except Exception as e:
    unreal.log_error(f"[ue_buttons] failed to load: {e}")
