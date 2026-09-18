import type { Metadata } from "next";
import { Home } from "@/components/home";
export const metadata: Metadata = {
  title: "Nashr — ta’lim uchun ish maydoni",
  description: "Manbalarni jamlang, g‘oyalarni rivojlantiring va taqdimotlar yarating. O‘zbek, rus va ingliz tillarida.",
};
export default function Page() { return <Home />; }
