"""Typed local game-asset generate_asset entry point."""

from typing import Any

from dcc_mcp_core.skill import run_main, skill_entry, skill_error, skill_success

from dcc_mcp_comfyui.game_assets import generate_asset
from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(recipe_id: str, parameters: dict[str, Any] | None = None, models: dict[str, str] | None = None) -> dict:
    with connected_bridge() as bridge:
        result = generate_asset(bridge, recipe_id, parameters, models)
    if not result["submitted"]:
        return skill_error(
            "Recipe dependencies are not ready; no prompt submitted.", "Resolve the reported blockers.", **result
        )
    return skill_success("Workflow submitted; poll prompt_id for completion.", **result)


if __name__ == "__main__":
    run_main(main)
