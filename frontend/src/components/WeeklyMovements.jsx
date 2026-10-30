import { useEffect, useState } from "react";
import { getMovements } from "../api";
import { money, signedMoney } from "../format";

const CATEGORIES = [
  {
    key: "New deal",
    label: "New Deals",
    icon: "+",
    color: "#0ea5c6",
    background: "#e0f5fe",
  },
  {
    key: "Slipped to Q1-2027",
    label: "Slipped to Q1",
    icon: "◷",
    color: "#d99121",
    background: "#fff3dc",
  },
  {
    key: "Closed Lost",
    label: "Closed Lost",
    icon: "×",
    color: "#e25360",
    background: "#ffe8eb",
  },
  {
    key: "Stage move",
    label: "Stage Moves",
    icon: "⇄",
    color: "#169e9a",
    background: "#dff7f3",
  },
  {
    key: "ACV change",
    label: "ACV Changes",
    icon: "↗",
    color: "#8b5bd6",
    background: "#f0e8ff",
  },
];

function beforeAfter(event) {
  if (event.category === "ACV change") {
    return [
      money(event.prior_acv, false),
      money(event.current_acv, false),
    ];
  }

  if (event.category === "Slipped to Q1-2027") {
    return [event.prior_period, event.current_period];
  }

  return [event.prior_stage || "—", event.current_stage || "—"];
}

export default function WeeklyMovements({ baselineRunId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [category, setCategory] = useState("All");

  useEffect(() => {
    const controller = new AbortController();

    getMovements(controller.signal)
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
        Loading weekly movements…
      </div>
    );
  }

  const visible = data.events.filter(
    (event) => category === "All" || event.category === category,
  );

  const uniqueDeals = new Set(
    data.events.map((event) => event.sf_match_key),
  ).size;

  const maxCount = Math.max(1, ...Object.values(data.counts));

  function toggleCategory(value) {
    setCategory((current) => current === value ? "All" : value);
  }

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Week-over-Week Pipeline Movements
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          Salesforce · Prior week vs. current week
        </p>
      </div>

      {baselineRunId && baselineRunId !== data.run_id && (
        <p role="alert" className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">
          A newer cleaning run is available. Reload the app to align
          the forecast and movement views.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {CATEGORIES.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-pressed={category === item.key}
            onClick={() => toggleCategory(item.key)}
            className={`panel flex items-center gap-4 p-5 text-left transition ${
              category === item.key
                ? "ring-2 ring-cyan-500"
                : "hover:border-cyan-400"
            }`}
          >
            <span
              aria-hidden="true"
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-3xl"
              style={{
                backgroundColor: item.background,
                color: item.color,
              }}
            >
              {item.icon}
            </span>
            <span>
              <span className="block text-sm text-slate-600">
                {item.label}
              </span>
              <span className="mt-1 block text-3xl font-bold">
                {data.counts[item.key] ?? 0}
              </span>
            </span>
          </button>
        ))}
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
        <section className="panel p-5">
          <h2 className="text-lg font-bold">What Changed This Week</h2>

          <div className="mt-6 space-y-5">
            {CATEGORIES.map((item) => {
              const count = data.counts[item.key] ?? 0;

              return (
                <button
                  type="button"
                  key={item.key}
                  aria-label={`${item.label}: ${count} events`}
                  aria-pressed={category === item.key}
                  onClick={() => toggleCategory(item.key)}
                  className="block w-full text-left"
                >
                  <div className="mb-2 flex justify-between text-sm">
                    <span>{item.label}</span>
                    <span className="font-semibold">{count}</span>
                  </div>
                  <div className="h-6 overflow-hidden rounded bg-slate-100">
                    <div
                      className="h-full rounded"
                      style={{
                        width: `${(count / maxCount) * 100}%`,
                        backgroundColor: item.color,
                      }}
                    />
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mt-6 border-t border-slate-100 pt-4">
            <p className="text-xs text-slate-500">
              Net ACV change on existing active Q4 deals
            </p>
            <p
              className={`mt-1 text-2xl font-bold ${
                data.net_acv_change >= 0
                  ? "text-emerald-700"
                  : "text-red-600"
              }`}
            >
              {signedMoney(data.net_acv_change)}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Unweighted contract value—not the change in forecast.
            </p>
          </div>
        </section>

        <section className="panel min-w-0 overflow-hidden">
          <div className="space-y-4 p-5">
            <div>
              <h2 className="text-lg font-bold">Movement Details</h2>
              <p className="mt-1 text-xs text-slate-500">
                {data.events.length} events across {uniqueDeals} deals.
                A deal can appear in multiple categories.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {[
                { key: "All", label: "All" },
                ...CATEGORIES,
              ].map((item) => (
                <button
                  type="button"
                  key={item.key}
                  aria-pressed={category === item.key}
                  onClick={() => setCategory(item.key)}
                  className={`rounded-md border px-3 py-2 text-xs font-medium ${
                    category === item.key
                      ? "border-cyan-300 bg-cyan-50 text-cyan-800"
                      : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {item.label} (
                  {item.key === "All"
                    ? data.events.length
                    : data.counts[item.key] ?? 0}
                  )
                </button>
              ))}
            </div>
          </div>

          <div className="max-h-[650px] overflow-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="sticky top-0 bg-slate-50 text-xs text-slate-600">
                <tr>
                  {[
                    "Deal",
                    "Category",
                    "Prior Week",
                    "Current Week",
                    "Current ACV",
                    "Change",
                  ].map((label) => (
                    <th key={label} className="px-4 py-3 font-semibold">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody className="divide-y divide-slate-100">
                {visible.map((event) => {
                  const item = CATEGORIES.find(
                    (entry) => entry.key === event.category,
                  );
                  const [before, after] = beforeAfter(event);

                  return (
                    <tr
                      key={`${event.sf_match_key}:${event.category}`}
                      className="hover:bg-slate-50"
                    >
                      <td className="max-w-64 px-4 py-4">
                        <p className="font-semibold">{event.customer}</p>
                        <p className="mt-1 text-[10px] text-slate-400">
                          {event.sf_match_key}
                        </p>
                      </td>

                      <td className="px-4 py-4">
                        <span
                          className="inline-block whitespace-nowrap rounded-full px-2 py-1 text-xs font-medium"
                          style={{
                            backgroundColor: item.background,
                            color: item.color,
                          }}
                        >
                          {item.label}
                        </span>
                      </td>

                      <td className="px-4 py-4 text-slate-600">
                        {before}
                      </td>
                      <td className="px-4 py-4">{after}</td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        {event.current_acv == null
                          ? "—"
                          : money(event.current_acv, false)}
                      </td>

                      <td className="px-4 py-4">
                        {event.category === "ACV change" ? (
                          <span
                            className={`whitespace-nowrap font-semibold ${
                              event.acv_change >= 0
                                ? "text-emerald-700"
                                : "text-red-600"
                            }`}
                          >
                            {signedMoney(event.acv_change)}
                          </span>
                        ) : (
                          event.direction || "—"
                        )}
                      </td>
                    </tr>
                  );
                })}

                {visible.length === 0 && (
                  <tr>
                    <td colSpan={6} className="p-10 text-center text-slate-500">
                      No movements in this category.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {data.missing_from_current.length > 0 && (
        <section className="panel border-amber-200 p-5">
          <h2 className="font-semibold text-amber-900">
            Review: deals missing from the current export
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Missing records are not automatically classified as Closed Lost.
          </p>
          <ul className="mt-3 space-y-1 text-sm">
            {data.missing_from_current.map((event) => (
              <li key={event.sf_match_key}>
                {event.customer} · {event.sf_match_key}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="space-y-1 text-xs text-slate-500">
        {data.notes.map((note) => <p key={note}>{note}</p>)}
        <p className="pt-2 text-slate-400">Cleaning run: {data.run_id}</p>
      </div>
    </section>
  );
}