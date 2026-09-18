"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, ArrowUp, BookOpen, Network, PanelsTopLeft, GraduationCap } from "lucide-react";
import { LanguagePicker, useLocale } from "./locale-provider";
import { creationHref } from "@/lib/locale";
import { HOME_COPY } from "./home-copy";
import { WorkspacePreview } from "./workspace-preview";
import "./home.css";

export function Home() {
 const { locale } = useLocale(); const t = HOME_COPY[locale]; const [topic,setTopic]=useState(""); const icons=[BookOpen,Network,PanelsTopLeft];
 return <div className="n-home"><header className="home-nav"><Link href="/" className="home-brand"><span>n</span>Nashr</Link><nav aria-label={t.nav[0]}>{["workspace","workflow","education"].map((id,index)=><a key={id} href={`#${id}`}>{t.nav[index]}</a>)}</nav><div className="home-nav-actions"><LanguagePicker/><Link href="/login" className="home-login">{t.signIn}</Link><Link href={creationHref(locale)} className="home-button small">{t.start}<ArrowRight size={15}/></Link></div></header>
 <main><section className="home-hero"><div className="home-eyebrow"><GraduationCap size={16}/>{t.eyebrow}</div><h1>{t.title}<br/><span>{t.accent}</span></h1><p className="home-lede">{t.description}</p>
 <form className="home-composer" onSubmit={event=>{event.preventDefault();window.location.assign(creationHref(locale,topic));}}><label htmlFor="home-topic" className="sr-only">{t.placeholder}</label><textarea id="home-topic" placeholder={t.placeholder} value={topic} onChange={event=>setTopic(event.target.value)} maxLength={2000}/><div><span>{t.promptHint}</span><button type="submit" aria-label={t.start}><ArrowUp size={20}/></button></div></form><div className="home-examples">{t.examples.map(example=><button key={example} onClick={()=>{setTopic(example);document.getElementById("home-topic")?.focus();}}>{example}<ArrowRight size={12}/></button>)}</div></section>
 <section id="workspace" className="home-product"><WorkspacePreview/></section><section id="education" className="home-audience"><p>{t.audience}</p><div>{t.roles.map(role=><span key={role}>{role}</span>)}</div></section>
 <section id="workflow" className="home-workflow"><h2>{t.heading}</h2><div className="home-cards">{t.cards.map((card,index)=>{const Icon=icons[index];return <article key={card.title}><div className={`home-card-icon tone-${index}`}><Icon size={23}/></div><h3>{card.title}</h3><p>{card.text}</p></article>;})}</div></section>
 <section className="home-closing"><div><h2>{t.closing}</h2><p>{t.closingSub}</p></div><Link href={creationHref(locale)} className="home-button">{t.start}<ArrowRight size={18}/></Link></section></main>
 <footer className="home-footer"><div><Link href="/" className="home-brand">Nashr</Link><p>{t.footer}</p></div><nav><Link href="/maxfiylik">{t.privacy}</Link><Link href="/shartlar">{t.terms}</Link><Link href="/yordam">{t.help}</Link></nav><LanguagePicker/></footer></div>;
}
