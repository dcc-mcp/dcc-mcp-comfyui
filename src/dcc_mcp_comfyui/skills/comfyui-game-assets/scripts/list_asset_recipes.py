"""Offline game-asset recipe discovery."""

from dcc_mcp_core.skill import run_main, skill_entry, skill_success

from dcc_mcp_comfyui.game_assets import list_asset_recipes


@skill_entry
def main(kind: str = "all") -> dict:
    return skill_success("Choose a recipe with the user before generation.", recipes=list_asset_recipes(kind))


if __name__ == "__main__":
    run_main(main)
