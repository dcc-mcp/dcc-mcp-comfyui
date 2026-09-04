"""Typed local game-asset prepare_asset_workflow entry point."""

from typing import Any

from dcc_mcp_core.skill import run_main, skill_entry, skill_error, skill_success

from dcc_mcp_comfyui.game_assets import prepare_asset_workflow
from dcc_mcp_comfyui.skill_runtime import connected_bridge


@skill_entry
def main(recipe_id: str, parameters: dict[str, Any] | None = None, models: dict[str, str] | None = None) -> dict:
    with connected_bridge() as bridge:
        result = prepare_asset_workflow(bridge, recipe_id, parameters, models)
    if not result["ready"]:
        return skill_error(
            "Recipe dependencies are not ready; no prompt submitted.", "Resolve the reported blockers.", **result
        )
    return skill_success("Recipe prepared; review readiness scope before generation.", **result)


if __name__ == "__main__":
    run_main(main)
