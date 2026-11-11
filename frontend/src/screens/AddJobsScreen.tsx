import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createApplications, getSettings, listTemplates } from "../api";
import { usePerson } from "../person";
import type { Depth, JobRequest, TemplateInfo, TemplateName } from "../types";

const DEPTHS: Depth[] = ["quick", "standard", "deep"];

interface RowOverride {
  depth?: Depth;
  template?: TemplateName;
}

export default function AddJobsScreen() {
  const navigate = useNavigate();
  const { person, people, loading, error: peopleError, labelFor } = usePerson();
  const personId = person?.id;
  // Whose settings the defaults below came from. Submit waits until this is
  // the current person, so jobs are never queued with someone else's defaults.
  const [settingsFor, setSettingsFor] = useState<number | null>(null);
  const [defaultDepth, setDefaultDepth] = useState<Depth>("standard");
  const [defaultTemplate, setDefaultTemplate] = useState<TemplateName>("slate");
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [apiKeySet, setApiKeySet] = useState(true);
  const [fakeMode, setFakeMode] = useState(false);
  const [text, setText] = useState("");
  const [inputMode, setInputMode] = useState<"urls" | "description">("urls");
  const [description, setDescription] = useState("");
  const [postingUrl, setPostingUrl] = useState("");
  const [generate, setGenerate] = useState(true);
  const [overrides, setOverrides] = useState<Record<number, RowOverride>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    setSettingsFor(null);
    setError(null);
    if (personId === undefined) return; // no person: nothing to load, submit stays disabled
    let current = true;
    getSettings(personId)
      .then((s) => {
        if (!current) return; // arrived after a switch: these are someone else's defaults
        setDefaultDepth(s.default_depth);
        setDefaultTemplate(s.default_template);
        setApiKeySet(s.api_key_set);
        setFakeMode(s.fake_mode);
        setSettingsFor(personId);
      })
      .catch((e) => {
        if (current) setError(String(e));
      });
    return () => {
      current = false;
    };
  }, [personId]);

  const noPeople = !loading && !peopleError && people.length === 0;
  const settingsReady = person !== null && settingsFor === person.id;

  const urls = useMemo(
    () =>
      text
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0),
    [text]
  );
  const entries = inputMode === "description"
    ? (description.trim() ? [postingUrl.trim() || "Pasted job description"] : [])
    : urls;

  function setOverride(idx: number, patch: RowOverride) {
    setOverrides((o) => ({ ...o, [idx]: { ...o[idx], ...patch } }));
  }

  async function handleSubmit() {
    if (person === null || !settingsReady || entries.length === 0) return;
    // Captured at click: the jobs belong to the person shown when Submit was
    // pressed, even if the picker changes while the request is in flight.
    const profileId = person.id;
    setSubmitting(true);
    setError(null);
    const jobs: JobRequest[] = entries.map((url, i) => ({
      url: inputMode === "description" ? postingUrl.trim() : url,
      ...(inputMode === "description" ? { posting_text: description.trim() } : {}),
      depth: overrides[i]?.depth ?? defaultDepth,
      template: overrides[i]?.template ?? defaultTemplate,
    }));
    try {
      const created = await createApplications(profileId, jobs, defaultDepth, defaultTemplate, generate);
      navigate(created.length === 1 ? `/applications/${created[0].id}` : "/");
    } catch (err) {
      setError(String(err));
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h1>Add Jobs</h1>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        {person !== null && (
          <div className="card-title">{`Adding jobs for ${labelFor(person)}`}</div>
        )}
        {noPeople && (
          <div className="callout">
            <Link to="/profiles?new=1">Add a person first</Link>
          </div>
        )}
        {peopleError && <div className="alert alert-error">{peopleError}</div>}
        <div className="row">
          <div className="field">
            <label className="field-label">Default depth</label>
            <select
              className="select"
              value={defaultDepth}
              onChange={(e) => setDefaultDepth(e.target.value as Depth)}
            >
              {DEPTHS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="default-template">
              Default template
            </label>
            <select
              id="default-template"
              className="select"
              value={defaultTemplate}
              onChange={(e) => setDefaultTemplate(e.target.value as TemplateName)}
            >
              {templates.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.label || t.name}
                </option>
              ))}
            </select>
            <Link to="/templates" className="muted-link">
              See template examples →
            </Link>
          </div>
        </div>

        <p className="muted">Resumes use your Headless template. The template selector controls cover-letter style.</p>
        <div className="field">
          <label className="field-label" htmlFor="job-input-mode">Job input</label>
          <select id="job-input-mode" className="select" value={inputMode}
            onChange={(e) => setInputMode(e.target.value as "urls" | "description")}>
            <option value="urls">Job URLs</option>
            <option value="description">Paste job description</option>
          </select>
        </div>
        {inputMode === "urls" ? <div className="field">
          <label className="field-label" htmlFor="job-urls">Job posting URLs — one per line</label>
          <textarea
            id="job-urls"
            className="textarea"
            placeholder="https://..."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div> : <>
          <div className="field">
            <label className="field-label" htmlFor="job-description">Job description</label>
            <textarea id="job-description" className="textarea" rows={12} maxLength={200000}
              placeholder="Paste the full job description, including company and qualifications."
              value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="posting-url">Original URL (optional)</label>
            <input id="posting-url" className="input" type="url" value={postingUrl}
              onChange={(e) => setPostingUrl(e.target.value)} />
          </div>
        </>}
        <p className="muted">Generation also looks for relevant company contacts and prepares short outreach drafts. Published work emails are preferred; LinkedIn is the fallback.</p>

        {!apiKeySet && !fakeMode ? (
          <div className="alert alert-error">
            No API key set — add DEEPSEEK_API_KEY to .env and restart, or{" "}
            <Link to="/getting-started">use MCP mode</Link>. Submitting now will fail at
            generation.
          </div>
        ) : (
          <p className="muted">
            Generated with your DeepSeek API key (estimated usage is tracked per application). Prefer
            your own Claude agent? <Link to="/getting-started">See MCP mode →</Link>
          </p>
        )}
      </div>

      {entries.length > 0 && (
        <div className="card">
          <div className="card-title">
            {entries.length} job{entries.length === 1 ? "" : "s"} to queue
          </div>
          {entries.map((url, i) => (
            <div className="row" data-testid="job-row" key={i}>
              <span className="mono" style={{ flex: "2 1 16rem", overflowWrap: "anywhere" }}>
                {url}
              </span>
              <select
                className="select"
                aria-label={`Depth for row ${i + 1}`}
                value={overrides[i]?.depth ?? defaultDepth}
                onChange={(e) => setOverride(i, { depth: e.target.value as Depth })}
              >
                {DEPTHS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              <select
                className="select"
                aria-label={`Template for row ${i + 1}`}
                value={overrides[i]?.template ?? defaultTemplate}
                onChange={(e) => setOverride(i, { template: e.target.value as TemplateName })}
              >
                {templates.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.label || t.name}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <label className="field-label" style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <input
              type="checkbox"
              checked={!generate}
              onChange={(e) => setGenerate(!e.target.checked)}
            />
            Save without generating (no AI cost)
          </label>
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={submitting || !settingsReady}
          >
            {noPeople
              ? "Add a person first"
              : submitting
                ? "Queueing..."
                : generate
                  ? "Add and generate"
                  : "Save for later"}
          </button>
        </div>
      )}
    </div>
  );
}
