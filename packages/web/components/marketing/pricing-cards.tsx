// Tier cards and the comparison table. Both read the one pricing source and
// state the same numbers, so the home summary can never drift from /narxlar.

import Link from "next/link";
import { startHref } from "./links";
import { TIERS, soum } from "./pricing-data";

export function TierCards({ ctaLabel = "Boshlash" }: { ctaLabel?: string }) {
  return (
    <div className="mkt-tiers">
      {TIERS.map((tier) => (
        <article key={tier.id} className="mkt-tier" data-featured={tier.featured ? "true" : "false"}>
          <h3 className="mkt-tier-name">
            {tier.name}
            {tier.featured ? <span className="mkt-tier-tag">Ko‘p tanlanadi</span> : null}
          </h3>
          <p className="mkt-tier-price">{soum(tier.price)}</p>
          <p className="mkt-tier-desc">{tier.desc}</p>
          <ul className="mkt-tier-list">
            {tier.includes.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <div className="mkt-tier-foot">
            <Link href={startHref()} className="mkt-btn mkt-btn-quiet">
              {ctaLabel}
            </Link>
          </div>
        </article>
      ))}
    </div>
  );
}

export function TierTable() {
  return (
    <div className="mkt-table-scroll">
      <table className="mkt-table">
        <caption className="mkt-caption" style={{ captionSide: "bottom", textAlign: "left" }}>
          Narxlar bitta taqdimot uchun. To‘lov hisobingizga tushadi va har bir buyurtma undan
          yechiladi.
        </caption>
        <thead>
          <tr>
            <th scope="col">Nima kiradi</th>
            {TIERS.map((tier) => (
              <th key={tier.id} scope="col">
                {tier.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Narx</th>
            {TIERS.map((tier) => (
              <td key={tier.id} className="mkt-num">
                {soum(tier.price)}
              </td>
            ))}
          </tr>
          <tr>
            <th scope="row">AI rasmlar</th>
            {TIERS.map((tier) => (
              <td key={tier.id} className="mkt-num">
                {tier.aiImages === 0 ? "yo‘q" : tier.aiImages}
              </td>
            ))}
          </tr>
          <tr>
            <th scope="row">Tahrirlar (bitta ish uchun)</th>
            {TIERS.map((tier) => (
              <td key={tier.id} className="mkt-num">
                {tier.fixes}
              </td>
            ))}
          </tr>
          <tr>
            <th scope="row">Formatlar</th>
            {TIERS.map((tier) => (
              <td key={tier.id}>HTML, PDF, PPTX</td>
            ))}
          </tr>
          <tr>
            <th scope="row">Manba bog‘lash va provenans</th>
            {TIERS.map((tier) => (
              <td key={tier.id}>Bor</td>
            ))}
          </tr>
          <tr>
            <th scope="row">Yuklab olish havolasi</th>
            {TIERS.map((tier) => (
              <td key={tier.id}>7 kun</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
