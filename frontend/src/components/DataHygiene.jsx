import { useEffect, useState } from "react";
import { getAudit } from "../api";
import WarningIcon from "./WarningIcon";

const SOURCE_LABELS = {
  "1_sfdc_pipeline_current.csv": "Salesforce · Current",
  "2_sfdc_pipeline_prior_week.csv": "Salesforce · Prior",
  "3_vp_deal_scorecard.xlsx": "VP Scorecard",
  "4_carebridge_hubspot_export.csv": "CareBridge · HubSpot",
};

const STATUS_STYLES = {
  resolved: "bg-emerald-50 text-emerald-800",
  accepted_assumption: "bg-violet-50 text-violet-800",
  business_review: "bg-amber-50 text-amber-900",
  baseline_rule_applied: "bg-blue-50 text-blue-800",
  excluded_from_forecast: "bg-slate-100 text-slate-700",
  requires_review: "bg-red-50 text-red-800",
};

function displayValue(value) {
  if (value == null || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function resolutionText(event) {
  return (
    event.resolution ||
    event.reason ||
    (event.status === "resolved"
      ? event.issue
      : "See source details and recorded status.")
  );
}

function EventDetails({ event }) {
  const fields = Object.entries(event).filter(
    ([key, value]) =>
      !["event_id", "issue", "status", "status_label"].includes(key) &&
      value != null &&
      value !== "",
  );

  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer font-medium text-cyan-800">
        Source details
      </summary>
      <dl className="mt-3 space-y-2 rounded-lg bg-slate-50 p-3">
        {fields.map(([key, value]) => (
          <div key={key}>
            <dt className="font-medium text-slate-500">
              {key.replaceAll("_", " ")}
            </dt>
            <dd className="mt-0.5 whitespace-pre-wrap break-words text-slate-700">
              {displayValue(value)}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export default function DataHygiene({ baselineRunId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    const controller = new AbortController();

    getAudit(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });

    return () => controller.abort();
  }, [attempt]);

  if (error) {
    return (
      <div role="alert" className="panel p-6">
        <p className="text-red-700">{error}</p>
        <button
          className="button mt-4"
          onClick={() => {
            setError("");
            setAttempt((value) => value + 1);
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div role="status" className="panel p-8 text-slate-500">
        Loading audit log…
      </div>
    );
  }

  const visible = data.events.filter((event) => {
    const searchable = [
      event.issue,
      event.raw_value,
      event.column,
      event.resolution,
      event.reason,
      event.event_id,
    ].map(displayValue).join(" ").toLowerCase();

    return (
      (!source || event.source_file === source) &&
      (!status || event.status === status) &&
      searchable.includes(search.toLowerCase())
    );
  });

  const cards = [
    {
      label: "Audit Events",
      value: data.summary.total_events,
      detail: "Includes detection and resolution events",
      color: "text-cyan-700",
    },
    {
      label: "Accepted Assumption Events",
      value: data.summary.accepted_assumption_events,
      detail: "Documented decisions—not verified facts",
      color: "text-violet-700",
    },
    {
      label: "Business Review Warnings",
      value: data.summary.business_review_count,
      detail: "Stale close dates and stage-age inconsistencies",
      color: "text-amber-700",
    },
  ];

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Data Hygiene & Audit Log
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          Traceable cleaning decisions across four weekly source files.
        </p>
      </div>

      {baselineRunId && baselineRunId !== data.run_id && (
        <p role="alert" className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">
          A newer cleaning run is available. Reload the app to align
          the forecast and audit views.
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {cards.map((card) => (
          <article key={card.label} className="panel p-5">
            <h2 className="text-sm font-medium text-slate-600">
              <span className="inline-flex items-center gap-2">
                {card.label === "Business Review Warnings" && card.value > 0 && (
                  <WarningIcon className="h-5 w-5 text-amber-600" />
                )}
                {card.label}
              </span>
            </h2>
            <p className={`mt-2 text-4xl font-bold ${card.color}`}>
              {card.value}
            </p>
            <p className="mt-2 text-xs text-slate-500">{card.detail}</p>
          </article>
        ))}
      </div>

      <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900">
        Cleaning is applied programmatically; original source files remain
        unchanged.{" "}
        <strong>
          {data.summary.requires_review_count} unresolved blocking events.
        </strong>
      </div>

      <section className="panel overflow-hidden">
        <div className="space-y-4 p-5">
          <h2 className="text-xl font-bold">Audit Log</h2>

          <div className="grid gap-3 md:grid-cols-3">
            <input
              className="control"
              aria-label="Search audit events"
              placeholder="Search issues, IDs, or resolutions…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />

            <select
              className="control"
              aria-label="Filter by source file"
              value={source}
              onChange={(event) => setSource(event.target.value)}
            >
              <option value="">All Source Files</option>
              {data.filters.source_files.map((file) => (
                <option key={file} value={file}>
                  {SOURCE_LABELS[file] || file}
                </option>
              ))}
            </select>

            <select
              className="control"
              aria-label="Filter by audit status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">All Statuses</option>
              {data.filters.statuses.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
            <p>
              Showing {visible.length} of {data.events.length} events.
              Counts describe events, not unique problems.
            </p>
            {(search || source || status) && (
              <button
                className="button shrink-0"
                onClick={() => {
                  setSearch("");
                  setSource("");
                  setStatus("");
                }}
              >
                Clear Filters
              </button>
            )}
          </div>
        </div>

        <div className="max-h-[650px] overflow-auto">
          <table className="w-full min-w-[1000px] text-left text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-xs text-slate-600">
              <tr>
                {[
                  "Source",
                  "Issue Detected",
                  "Original Value / Field",
                  "Resolution / Assumption",
                  "Status",
                ].map((label) => (
                  <th key={label} className="px-4 py-3 font-semibold">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {visible.map((event) => (
                <tr key={event.event_id} className="align-top hover:bg-slate-50">
                  <td className="w-48 px-4 py-4">
                    <p className="font-medium">
                      {SOURCE_LABELS[event.source_file] || event.source_file}
                    </p>
                    {event.source_sheet && (
                      <p className="mt-1 text-xs text-slate-500">
                        {event.source_sheet}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-slate-500">
                      {event.source_row != null
                        ? `Source row ${event.source_row}`
                        : "File-level event"}
                    </p>
                    <p className="mt-2 text-[10px] text-slate-400">
                      {event.event_id}
                    </p>
                  </td>

                  <td className="max-w-72 px-4 py-4">
                    <p className="font-medium">{event.issue}</p>
                    <EventDetails event={event} />
                  </td>

                  <td className="max-w-56 px-4 py-4">
                    <p className="break-words">
                      {displayValue(event.raw_value)}
                    </p>
                    {event.column && (
                      <p className="mt-1 break-words text-xs text-slate-500">
                        {event.column}
                      </p>
                    )}
                  </td>

                  <td className="max-w-80 px-4 py-4 text-slate-600">
                    <p>{resolutionText(event)}</p>
                    {event.resolution &&
                      event.reason &&
                      event.resolution !== event.reason && (
                        <p className="mt-2 text-xs">{event.reason}</p>
                      )}
                    {event.rows_removed != null && (
                      <p className="mt-2 text-xs">
                        Removed {event.rows_removed} empty rows
                        {event.columns_removed != null
                          ? ` and ${event.columns_removed} empty columns`
                          : ""}.
                      </p>
                    )}
                  </td>

                  <td className="px-4 py-4">
                    <span
                      className={`inline-block rounded-lg px-2 py-1 text-xs font-medium ${
                        STATUS_STYLES[event.status] ||
                        "bg-slate-100 text-slate-700"
                      }`}
                    >
                      <span className="inline-flex items-center gap-1.5">
                        {event.status === "business_review" && <WarningIcon />}
                        {event.status_label}
                      </span>
                    </span>
                  </td>
                </tr>
              ))}

              {visible.length === 0 && (
                <tr>
                  <td colSpan={5} className="p-10 text-center text-slate-500">
                    No audit events match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel p-5">
        <h2 className="text-lg font-bold">Pipeline Method</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          {[
            [
              "1. Four source files",
              "Current Salesforce, prior Salesforce, VP scorecard, and CareBridge HubSpot.",
            ],
            [
              "2. Validate & reconcile",
              "Check fields, resolve duplicates, match identities, and annualize amounts.",
            ],
            [
              "3. Prepared data & audit",
              "Export traceable records with explicit assumptions, warnings, and resolutions.",
            ],
          ].map(([title, description]) => (
            <div key={title} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
              <h3 className="text-sm font-semibold">{title}</h3>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                {description}
              </p>
            </div>
          ))}
        </div>
      </section>

      <div className="space-y-1 text-xs text-slate-500">
        {data.notes.map((note) => <p key={note}>{note}</p>)}
        <p className="pt-2 text-slate-400">Cleaning run: {data.run_id}</p>
      </div>
    </section>
  );
}
