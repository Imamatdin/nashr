import Link from "next/link";

export default function Home() {
  return (
    <main>
      <h1>Nashr</h1>
      <p>Manbaga asoslangan akademik taqdimotlar va maqolalar.</p>
      <p>
        <Link href="/login">Kirish</Link>
      </p>
    </main>
  );
}
