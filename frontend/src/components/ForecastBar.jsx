import { money, percent } from "../format";

export default function ForecastBar({ summary }) {
  const segments = [
    {
      label: "Strategic",
      value: summary.strategic_expected_value,
      color: "#174b70",
    },
    {
      label: "Salesforce longtail",
      value: summary.salesforce_longtail_expected_value,
      color: "#00a8bd",
    },
    {
      label: "CareBridge longtail",
      value: summary.hubspot_longtail_expected_value,
      color: "#7bdce3",
    },
  ];

  const scale =
    Math.max(summary.total_expected_sales, summary.board_target) * 1.12;
  const targetPosition = (summary.board_target / scale) * 100;

  return (
    <section className="panel p-5" aria-label="Forecast versus target">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Q4 Forecast vs. Target</h2>
        <p className="text-sm text-slate-500">
          {money(summary.total_expected_sales)} ·{" "}
          {percent(summary.target_attainment)} of target
        </p>
      </div>

      <div className="relative mt-10">
        <div className="flex h-9 overflow-hidden rounded bg-slate-100">
          {segments.map((segment) => (
            <div
              key={segment.label}
              style={{
                width: `${(segment.value / scale) * 100}%`,
                backgroundColor: segment.color,
              }}
              title={`${segment.label}: ${money(segment.value, false)}`}
              className="flex items-center justify-center text-xs font-semibold text-white"
            >
              {segment.value / scale > 0.12 && money(segment.value)}
            </div>
          ))}
        </div>

        <div
          className="absolute -top-2 bottom-0 border-l-2 border-dashed border-slate-700"
          style={{ left: `${targetPosition}%` }}
        >
          <span className="absolute -top-6 -translate-x-1/2 whitespace-nowrap text-xs font-medium">
            Target {money(summary.board_target)}
          </span>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
        {segments.map((segment) => (
          <div key={segment.label} className="flex items-center gap-2 text-xs">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: segment.color }}
            />
            <span className="text-slate-600">{segment.label}</span>
            <span className="font-semibold">{money(segment.value)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}