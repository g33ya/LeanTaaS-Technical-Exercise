import { useEffect, useRef, useState } from "react";
import { calculateScenario, getAudit, getBaseline } from "./api";
import { displayDate } from "./format";
import KpiSummary from "./components/KpiSummary";
import ForecastBar from "./components/ForecastBar";
import DealRoom from "./components/DealRoom";
import WeeklyMovements from "./components/WeeklyMovements";
import DataHygiene from "./components/DataHygiene";
import WarningIcon from "./components/WarningIcon";

export default function App() {
  const [baseline, setBaseline] = useState(null);
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [scenarioError, setScenarioError] = useState("");
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState("forecast");
  const [auditData, setAuditData] = useState(null);
  const [auditLoadError, setAuditLoadError] = useState(false);

  const requestLock = useRef(false);
  const scenarioController = useRef(null);

  useEffect(() => {
    const controller = new AbortController();

    getBaseline(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setBaseline(result);
        setData(result);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setLoadError(error.message);
      });

    getAudit(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setAuditData(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setAuditLoadError(true);
      });

    return () => {
      controller.abort();
      scenarioController.current?.abort();
    };
  }, []);

  async function updateScenario(strategicDeals) {
    if (requestLock.current || !baseline) return;

    requestLock.current = true;
    setBusy(true);
    setScenarioError("");

    const controller = new AbortController();
    scenarioController.current = controller;

    try {
      const result = await calculateScenario(
        baseline.run_id,
        strategicDeals,
        controller.signal,
      );

      if (!controller.signal.aborted) setData(result);
    } catch (error) {
      if (!controller.signal.aborted) setScenarioError(error.message);
    } finally {
      requestLock.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  function reset() {
    if (requestLock.current) return;
    setData(baseline);
    setScenarioError("");
  }

  const reviewCount = auditData?.run_id === baseline?.run_id
    ? auditData?.summary.business_review_count ?? 0
    : null;

  return (
    <div className="min-h-screen bg-[#f4f7fb] text-[#102f4f]">
      <aside className="bg-[#103653] text-white lg:fixed lg:inset-y-0 lg:w-56">
        <div className="flex items-center gap-3 px-6 py-6">
          <span className="text-3xl text-cyan-400" aria-hidden="true">⌁</span>
          <div className="text-xl font-bold leading-tight">
            PulseFlow
            <span className="block text-sm font-normal text-slate-300">
              Health
            </span>
          </div>
        </div>

        <nav aria-label="Main navigation" className="space-y-1 pb-4">
          {[
            ["forecast", "Forecast & Deal Room"],
            ["movements", "Weekly Movements"],
            ["hygiene", "Data Hygiene"],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-current={page === key ? "page" : undefined}
              onClick={() => setPage(key)}
              className={`block w-full border-l-4 px-5 py-4 text-left text-sm font-semibold ${
                page === key
                  ? "border-cyan-300 bg-cyan-600"
                  : "border-transparent text-slate-200 hover:bg-white/10"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                {label}
                {key === "hygiene" && reviewCount > 0 && (
                  <span
                    className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-bold text-amber-900"
                    title={`${reviewCount} business-review warnings`}
                    aria-label={`${reviewCount} business-review warnings`}
                  >
                    <WarningIcon />
                    {reviewCount}
                  </span>
                )}
                {key === "hygiene" && auditLoadError && (
                  <span title="Warning count unavailable; open Data Hygiene to retry">
                    <span className="sr-only">Warning count unavailable</span>
                    <WarningIcon className="h-4 w-4 text-amber-300" />
                  </span>
                )}
              </span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="lg:ml-56">
        <header className="flex min-h-14 items-center justify-end border-b border-slate-200 bg-white/70 px-6 text-sm text-slate-500">
          {data ? `As of ${displayDate(data.as_of_date)}` : "Q4 2026"}
        </header>

        <div
          hidden={page !== "forecast"}
          className="mx-auto max-w-[1800px] space-y-6 p-4 sm:p-7"
        >
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-3xl font-bold tracking-tight">
                Q4 Sales Forecast
              </h1>
              {data?.scenario?.is_modified && (
                <span className="rounded-full bg-cyan-100 px-3 py-1 text-xs font-semibold text-cyan-800">
                  Scenario modified
                </span>
              )}
            </div>
            <p className="mt-2 text-sm text-slate-500">
              Annual contract value forecast with deal-level scenario planning.
            </p>
          </div>

          {loadError ? (
            <div role="alert" className="panel p-6">
              <p className="text-red-700">{loadError}</p>
              <button
                className="button mt-4"
                onClick={() => window.location.reload()}
              >
                Retry loading data
              </button>
            </div>
          ) : !data ? (
            <div role="status" className="panel p-8 text-slate-500">
              Loading forecast…
            </div>
          ) : (
            <>
              <KpiSummary summary={data.summary} />
              <ForecastBar summary={data.summary} />
              <DealRoom
                data={data}
                busy={busy}
                error={scenarioError}
                onChange={updateScenario}
                onReset={reset}
              />
              <p className="text-xs text-slate-400">
                Cleaning run: {data.run_id}
              </p>
            </>
          )}
        </div>
        {page === "movements" && (
          <div className="mx-auto max-w-[1800px] p-4 sm:p-7">
            <WeeklyMovements baselineRunId={baseline?.run_id} />
          </div>
        )}
        {page === "hygiene" && (
          <div className="mx-auto max-w-[1800px] p-4 sm:p-7">
            <DataHygiene baselineRunId={baseline?.run_id} />
          </div>
        )}
      </main>
    </div>
  );
}
