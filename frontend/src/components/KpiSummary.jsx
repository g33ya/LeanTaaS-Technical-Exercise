import { money, percent, signedMoney } from "../format";

export default function KpiSummary({ summary }) {
  const cards = [
    {
      label: "Expected Q4 Sales",
      value: money(summary.total_expected_sales),
      detail: `${summary.eligible_deal_count} eligible deals`,
    },
    {
      label: "Strategic Deals",
      value: money(summary.strategic_expected_value),
      detail: `${summary.strategic_deal_count} of 8 slots used`,
    },
    {
      label: "Longtail",
      value: money(summary.longtail_expected_value),
      detail:
        `Salesforce ${money(summary.salesforce_longtail_expected_value)} · ` +
        `CareBridge (HubSpot) ${money(summary.hubspot_longtail_expected_value)}`,
    },
    {
      label: `Variance to ${money(summary.board_target)} Target`,
      value: signedMoney(summary.variance_to_target),
      detail: `${percent(summary.target_attainment)} of target`,
      color:
        summary.variance_to_target >= 0
          ? "text-emerald-700"
          : "text-red-600",
    },
  ];

  return (
    <section
      aria-label="Forecast summary"
      className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
    >
      {cards.map((card) => (
        <article key={card.label} className="panel p-5">
          <h2 className="text-sm font-medium text-slate-600">
            {card.label}
          </h2>
          <p className={`mt-2 text-3xl font-bold ${card.color || ""}`}>
            {card.value}
          </p>
          <p className="mt-2 text-xs text-slate-500">{card.detail}</p>
        </article>
      ))}
    </section>
  );
}
