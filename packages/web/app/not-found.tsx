import Link from "next/link";

export default function NotFound() {
  return (
    <div className="dark notfound">
      <Link href="/" className="app-brand">
        Nashr
      </Link>
      <p className="notfound-folio">404</p>
      <p className="notfound-line">Bu sahifa nashrda yo&apos;q.</p>
      <div className="notfound-actions">
        <Link href="/projects" className="btn btn-primary">
          Loyihalarga qaytish
        </Link>
        <Link href="/" className="notfound-quiet">
          Bosh sahifa
        </Link>
      </div>
    </div>
  );
}
