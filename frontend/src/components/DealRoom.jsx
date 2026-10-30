import { useState } from "react";
import { money, percent, signedMoney } from "../format";

const SCORE_FIELDS = [
  ["leadership", "Leadership · 20%"],
  ["commercial", "Commercial · 20%"],
  ["contractual", "Contractual · 60%"],
];

export default function DealRoom({
  data,
  busy,
  error,
  onChange,
  onReset,
}) {
  const [search, setSearch] = useState("");
  const [product, setProduct] = useState("");
  const [rep, setRep] = useState("");
  const [sort, setSort] = useState("strategic");
  const [promotion, setPromotion] = useState(null);
  const [replacement, setReplacement] = useState("");

  const strategic = data.deals.filter((deal) => deal.is_strategic);
  const impact = data.scenario?.impact ?? 0;

  function selection() {
    return strategic.map((deal) => ({
      deal_key: deal.deal_key,
      ...deal.scores,
    }));
  }

  function updateScore(deal, field, value) {
    onChange(
      selection().map((item) =>
        item.deal_key === deal.deal_key
          ? { ...item, [field]: Number(value) }
          : item,
      ),
    );
  }

  function demote(deal) {
    onChange(
      selection().filter((item) => item.deal_key !== deal.deal_key),
    );
  }

  function promote(deal, replaceKey = "") {
    const next = selection().filter(
      (item) => item.deal_key !== replaceKey,
    );

    next.push({
      deal_key: deal.deal_key,
      leadership: 3,
      commercial: 3,
      contractual: 3,
    });

    setPromotion(null);
    setReplacement("");
    onChange(next);
  }

  function startPromotion(deal) {
    if (strategic.length < 8) {
      promote(deal);
    } else {
      setPromotion(deal);
      setReplacement("");
    }
  }

  const visible = data.deals
    .filter(
      (deal) =>
        (!product || deal.product === product) &&
        (!rep || deal.sales_rep === rep) &&
        deal.customer.toLowerCase().includes(search.toLowerCase()),
    )
    .sort((a, b) => {
      if (sort === "customer") return a.customer.localeCompare(b.customer);
      if (sort === "acv") return b.annual_acv - a.annual_acv;
      if (sort === "strategic") {
        return (
          Number(b.is_strategic) - Number(a.is_strategic) ||
          b.expected_value - a.expected_value
        );
      }
      return b.expected_value - a.expected_value;
    });

  return (
    <section className="panel overflow-hidden">
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold">Interactive Deal Room</h2>
            <p className="mt-1 text-xs text-slate-500">
              Strategic slots: {strategic.length}/8 · Changes are temporary
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <span
              className={`rounded-lg px-3 py-2 text-sm font-medium ${
                impact < 0
                  ? "bg-red-50 text-red-700"
                  : "bg-cyan-50 text-cyan-800"
              }`}
            >
              Scenario impact {signedMoney(impact)}
            </span>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => {
                setPromotion(null);
                onReset();
              }}
            >
              Reset to Baseline
            </button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <input
            className="control"
            aria-label="Search customers"
            placeholder="Search deals or accounts…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />

          <select
            className="control"
            aria-label="Filter by product"
            value={product}
            onChange={(event) => setProduct(event.target.value)}
          >
            <option value="">All Products</option>
            {data.filters.products.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>

          <select
            className="control"
            aria-label="Filter by sales rep"
            value={rep}
            onChange={(event) => setRep(event.target.value)}
          >
            <option value="">All Sales Reps</option>
            {data.filters.sales_reps.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>

          <select
            className="control"
            aria-label="Sort deals"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="expected">Expected Value: High to Low</option>
            <option value="strategic">Strategic First</option>
            <option value="acv">Annual ACV: High to Low</option>
            <option value="customer">Customer: A–Z</option>
          </select>
        </div>

        <div className="flex flex-wrap justify-between gap-2 text-xs text-slate-500">
          <span>
            Showing {visible.length} of {data.deals.length} deals.
            Filters affect this table; KPIs show the full quarter.
          </span>
          <span role="status" aria-live="polite">
            {busy ? "Recalculating…" : "Up to date"}
          </span>
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
            {error} Your last successful scenario is still displayed.
          </p>
        )}

        {promotion && (
          <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-4">
            <p className="text-sm font-semibold">
              Promote {promotion.customer}
            </p>
            <p className="mt-1 text-sm text-slate-600">
              All eight slots are occupied. Choose a deal to move to
              longtail. The promoted deal starts at 3/3/3.
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              <select
                className="control max-w-md"
                aria-label="Strategic deal to replace"
                value={replacement}
                onChange={(event) => setReplacement(event.target.value)}
              >
                <option value="">Choose a deal to replace</option>
                {strategic.map((deal) => (
                  <option key={deal.deal_key} value={deal.deal_key}>
                    {deal.customer}
                  </option>
                ))}
              </select>
              <button
                className="button"
                disabled={!replacement || busy}
                onClick={() => promote(promotion, replacement)}
              >
                Replace & Promote
              </button>
              <button
                className="button"
                onClick={() => setPromotion(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="max-h-[620px] overflow-auto">
        <table className="w-full min-w-[1250px] text-left text-sm">
          <thead className="sticky top-0 z-10 bg-slate-50 text-xs text-slate-600">
            <tr>
              {[
                "Deal / Account",
                "Product / Rep",
                "Annual ACV",
                "Bucket",
                ...SCORE_FIELDS.map(([, label]) => label),
                "GPA",
                "Win %",
                "Expected Value",
                "Action",
              ].map((label) => (
                <th key={label} className="px-4 py-3 font-semibold">
                  {label}
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-100">
            {visible.map((deal) => (
              <tr
                key={deal.deal_key}
                className={deal.is_modified ? "bg-cyan-50/70" : "hover:bg-slate-50"}
              >
                <td className="max-w-64 px-4 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{deal.customer}</p>
                    {deal.is_strategic && (
                      <span className="inline-flex items-center rounded-full bg-[#174b70] px-2 py-0.5 text-[10px] font-bold tracking-wide text-white">
                        TOP 8
                      </span>
                    )}
                  </div>

                  {deal.is_modified && (
                    <span className="mt-1 inline-block rounded bg-cyan-100 px-2 py-0.5 text-xs text-cyan-800">
                      Modified
                    </span>
                  )}

                  {(deal.warnings.length > 0 || deal.vp_notes) && (
                    <details className="mt-2 text-xs text-slate-500">
                      <summary className="cursor-pointer">
                        Notes & warnings
                      </summary>
                      {deal.warnings.map((warning) => (
                        <p key={warning} className="mt-1 text-amber-800">
                          {warning}
                        </p>
                      ))}
                      {deal.vp_notes && (
                        <p className="mt-1">{deal.vp_notes}</p>
                      )}
                    </details>
                  )}
                </td>

                <td className="px-4 py-4">
                  <p>{deal.product}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {deal.sales_rep}
                  </p>
                </td>

                <td className="px-4 py-4 whitespace-nowrap">
                  {money(deal.annual_acv)}
                </td>

                <td className="px-4 py-4">
                  <span className="rounded bg-cyan-50 px-2 py-1 text-xs text-cyan-800">
                    {deal.is_strategic ? "Strategic" : "Longtail"}
                  </span>
                  {!deal.is_strategic && (
                    <p className="mt-1 text-xs text-slate-500">{deal.stage}</p>
                  )}
                </td>

                {SCORE_FIELDS.map(([field, label]) => (
                  <td key={field} className="px-4 py-4">
                    {deal.is_strategic ? (
                      <select
                        className="control w-16"
                        aria-label={`${deal.customer}: ${label}`}
                        value={deal.scores[field]}
                        disabled={busy}
                        onChange={(event) =>
                          updateScore(deal, field, event.target.value)
                        }
                      >
                        {[1, 2, 3, 4].map((score) => (
                          <option key={score} value={score}>{score}</option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                ))}

                <td className="px-4 py-4">
                  {deal.composite_gpa?.toFixed(2) ?? "—"}
                </td>
                <td className="px-4 py-4">{percent(deal.probability)}</td>
                <td className="px-4 py-4 font-semibold whitespace-nowrap">
                  {money(deal.expected_value)}
                </td>
                <td className="px-4 py-4">
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() =>
                      deal.is_strategic ? demote(deal) : startPromotion(deal)
                    }
                  >
                    {deal.is_strategic ? "Move to Longtail" : "Promote"}
                  </button>
                </td>
              </tr>
            ))}

            {visible.length === 0 && (
              <tr>
                <td colSpan={11} className="p-10 text-center text-slate-500">
                  No deals match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
