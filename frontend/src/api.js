async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, options);
  const body = await response.json();

  if (!response.ok) {
    const detail = body.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join("; ")
          : detail?.message || "Request failed.";

    throw new Error(message);
  }

  return body;
}

export function getBaseline(signal) {
  return request("/baseline", { signal });
}

export function calculateScenario(runId, strategicDeals, signal) {
  return request("/scenario", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_id: runId,
      strategic_deals: strategicDeals,
    }),
  });
}

export function getMovements(signal) {
  return request("/movements", { signal });
}

export function getAudit(signal) {
  return request("/audit", { signal });
}