// The differentiator visual: one claim, the source bound to it. Designed in
// DOM and tokens — no canvas, no image, nothing to load. The example rows are
// the repository's own fixture data, not invented numbers.

export function ProvenanceFigure() {
  return (
    <figure className="mkt-prov">
      <div className="mkt-prov-card">
        <span className="mkt-prov-tag">Slayd 4</span>
        <p className="mkt-prov-claim">
          Volter matbuot erkinligini asosiy shart deb bilgan.
          <sup className="mkt-prov-mark">1</sup>
        </p>
      </div>

      <div className="mkt-prov-tie" aria-hidden>
        <span className="mkt-prov-node" />
      </div>

      <div className="mkt-prov-card mkt-prov-source">
        <span className="mkt-prov-tag">
          <span className="mkt-prov-mark">1</span> Manba
        </span>
        <p className="mkt-prov-quote">“Freedom of the press is the first of freedoms.”</p>
        <p className="mkt-prov-meta">volter-va-monteskye-tahlil.docx · bo‘lak 9</p>
      </div>

      <figcaption className="mkt-caption">
        Har bir da’vo shu qatorni olib yuradi. Qator bo‘sh bo‘lsa, da’vo chiqishga yetib bormaydi.
      </figcaption>
    </figure>
  );
}

export default ProvenanceFigure;
