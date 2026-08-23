import Link from "next/link";
import "./doors.css";

export default function NotFound() {
  return (
    <div className="theme-light notfound-shell">
      <Link href="/" className="notfound-brand">
        Nashr
      </Link>
      <p className="notfound-code">404</p>
      <div className="notfound-rule" aria-hidden />
      <p className="notfound-msg">Bu sahifa nashrda yo&apos;q.</p>
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
