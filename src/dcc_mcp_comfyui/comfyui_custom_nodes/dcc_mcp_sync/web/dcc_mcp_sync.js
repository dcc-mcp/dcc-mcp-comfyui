import { app } from "../../scripts/app.js";

const CHANNEL_PROPERTY = "DCC MCP Channel ID";
const ASSET_PROPERTY = "DCC MCP Asset ID";

function findModelWidget(node) {
  return node.widgets?.find((widget) => widget.name === "model_file");
}

function ensureOption(widget, inputName) {
  const values = widget?.options?.values;
  if (Array.isArray(values) && !values.includes(inputName)) values.push(inputName);
}

app.registerExtension({
  name: "dcc-mcp.asset-sync",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "Load3D") return;

    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = originalCreated?.apply(this, arguments);
      this.properties ??= {};
      this.properties[CHANNEL_PROPERTY] ??= "dcc-mcp-showcase";
      this.properties[ASSET_PROPERTY] ??= "model";

      this.addWidget("button", "Update to latest DCC revision", null, async () => {
        const channelId = String(this.properties[CHANNEL_PROPERTY] ?? "").trim();
        const assetId = String(this.properties[ASSET_PROPERTY] ?? "").trim();
        if (!channelId || !assetId) {
          app.extensionManager.toast.add({
            severity: "error",
            summary: "DCC-MCP Sync",
            detail: "Set the DCC MCP Channel ID and Asset ID node properties first.",
          });
          return;
        }

        try {
          const query = new URLSearchParams({ channel_id: channelId, asset_id: assetId });
          const response = await fetch(`/dcc-mcp-sync/latest?${query}`);
          if (!response.ok) throw new Error(await response.text());
          const latest = await response.json();
          const modelWidget = findModelWidget(this);
          if (!modelWidget) throw new Error("Load3D model_file widget is unavailable");
          ensureOption(modelWidget, latest.input_name);
          this.properties["Last Time Model File"] = latest.input_name;
          modelWidget.value = latest.input_name;
          this.setDirtyCanvas(true, true);
          app.extensionManager.toast.add({
            severity: "success",
            summary: "DCC-MCP Sync",
            detail: `Loaded revision ${latest.revision}`,
          });
        } catch (error) {
          app.extensionManager.toast.add({
            severity: "error",
            summary: "DCC-MCP Sync",
            detail: String(error?.message ?? error),
          });
        }
      });
      return result;
    };
  },
});
