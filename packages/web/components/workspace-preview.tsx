"use client";
import { useState } from "react";
import { FileText, Network, PanelLeft, BookOpen, ArrowUp, MessageSquare, Circle } from "lucide-react";
import { useLocale } from "./locale-provider";
import { HOME_COPY } from "./home-copy";

/** Labelled illustration, not fabricated account or research data. */
export function WorkspacePreview() {
 const { locale } = useLocale(); const t = HOME_COPY[locale];
 const [mode, setMode] = useState<"document" | "graph">("document");
 return <div className="home-workspace">
 <div className="home-workspace-bar"><span className="home-mini-brand">n</span><strong>{t.project}</strong><span className="home-demo-label">{t.preview}</span><PanelLeft size={16}/></div>
 <div className="home-workspace-body">
 <aside className="home-outline"><small>{t.document}</small>{t.outline.map((item,index)=><div className={index===1?"chosen":""} key={item}><FileText size={14}/>{item}</div>)}<small>{t.sources}</small>{t.sourceNames.map(source=><div key={source}><BookOpen size={14}/>{source}</div>)}</aside>
 <div className="home-editor"><div className="home-editor-tabs"><button aria-pressed={mode==="document"} onClick={()=>setMode("document")}><FileText size={14}/>{t.document}</button><button aria-pressed={mode==="graph"} onClick={()=>setMode("graph")}><Network size={14}/>{t.graph}</button></div>
 {mode==="document"?<div className="home-manuscript"><small>{t.project}</small><h3>{t.section}</h3><p>{t.paragraph}</p><div className="home-highlight">{t.note}</div><span className="home-review"><Circle size={10}/>{t.review}</span><div className="home-rule"/><div className="home-rule short"/></div>:<div className="home-map-preview"><svg viewBox="0 0 480 300" aria-hidden="true"><path d="M95 75 C230 75 230 130 330 130 M95 225 C230 225 230 130 330 130 M330 130 C410 130 340 250 410 250"/><circle cx="95" cy="75" r="31"/><circle cx="95" cy="225" r="25"/><circle cx="330" cy="130" r="45"/><circle cx="410" cy="250" r="17"/></svg><span className="map-label one">{t.sources}</span><span className="map-label two">{t.section}</span><p>{t.preview} · {t.graph}</p></div>}
 </div><aside className="home-assistant"><strong><MessageSquare size={15}/>{t.assistant}</strong><small>{t.selected}</small><div className="home-question">{t.ask}</div><p>{t.answer}</p><div className="home-mini-composer"><span>{t.ask}</span><ArrowUp size={16}/></div></aside>
 </div></div>;
}
