import { useState } from "react";
import type { OutreachPlan } from "./types";

export default function OutreachPanel({ plan }: { plan?: OutreachPlan | null }) {
  const [copyNote, setCopyNote] = useState("");
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopyNote("Copied. Review and personalize before sending.");
    } catch {
      setCopyNote("Select and copy the draft text below.");
    }
  }
  if (!plan) return <p>No outreach research yet. Generate or regenerate this application to find contacts and create drafts.</p>;
  return <div>
    <p>{plan.notes}</p>
    {plan.checked_at && <p className="muted">Sources checked {new Date(plan.checked_at).toLocaleString()}</p>}
    <p className="muted">Drafts only. No email, LinkedIn message, or connection request has been sent.</p>
    <p role="status">{copyNote}</p>
    {plan.contacts.map((contact, index) => <article className="card" key={`${contact.name}-${index}`}>
      <h3>{contact.name}</h3>
      <p>{contact.role} at {contact.company}</p>
      <p>{contact.relevance}</p>
      {contact.email ? <p>Published work email: <span className="mono">{contact.email}</span></p>
        : <p>No published work email confirmed. Use LinkedIn.</p>}
      {contact.linkedin_url && <p><a href={contact.linkedin_url} target="_blank" rel="noreferrer">LinkedIn profile</a></p>}
      <details><summary>Contact evidence</summary>
        <blockquote>{contact.evidence_quote}</blockquote>
        <p><a href={contact.source_url} target="_blank" rel="noreferrer">Employment source</a></p>
        {contact.email_source_url && <p><a href={contact.email_source_url} target="_blank" rel="noreferrer">Email source</a></p>}
      </details>
      {contact.email && <>
        <h4>Email draft</h4>
        <p><strong>Subject:</strong> {contact.email_subject}</p>
        <textarea className="textarea" rows={6} readOnly aria-label={`Email draft for ${contact.name}`} value={contact.email_body} />
        <button className="btn" onClick={() => copy(`To: ${contact.email}\nSubject: ${contact.email_subject}\n\n${contact.email_body}`)}>Copy email draft for {contact.name}</button>
      </>}
      {contact.linkedin_url && <>
        <h4>LinkedIn connection draft</h4>
        <textarea className="textarea" rows={3} readOnly aria-label={`LinkedIn draft for ${contact.name}`} value={contact.linkedin_message} />
        <button className="btn" onClick={() => copy(contact.linkedin_message)}>Copy LinkedIn draft for {contact.name}</button>
      </>}
    </article>)}
  </div>;
}
