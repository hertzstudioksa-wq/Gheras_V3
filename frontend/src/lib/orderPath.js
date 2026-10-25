// Where a story card or link takes the parent for each order status.
const SCENARIO_STATUSES = ["pending", "scenarios_generating", "scenarios_ready"];
const PRODUCTION_STATUSES = [
  "scenario_selected", "awaiting_payment", "ready_for_ai", "production_planning", "production_ready",
  "production_approved", "assets_generating", "assets_ready", "assembling", "delivered", "media_failed",
];

export function orderPath(o) {
  if (SCENARIO_STATUSES.includes(o.status)) return `/orders/${o.id}/scenarios`;
  if (PRODUCTION_STATUSES.includes(o.status)) return `/orders/${o.id}/production-ready`;
  // A failed order shows its retry on the page of the step that failed:
  // planning (a scenario was picked) or the scenario ideas.
  if (o.status === "failed") {
    return o.selected_scenario_id ? `/orders/${o.id}/production-ready` : `/orders/${o.id}/scenarios`;
  }
  return `/orders/${o.id}`;
}
