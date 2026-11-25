"use client";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { message, rows, type Api } from "../lib/api";
import { display, title } from "../lib/types";
import type { Panel } from "./Explorer";

type Item = {
  id: string;
  name?: string;
  title?: string;
  status?: string;
  objective?: string;
  stage?: string;
  created_at?: string;
  assignee?: string;
  model_version?: string;
  currency?: string;
  outputs?: Record<string, unknown>;
  assumptions?: string;
  inputs?: Record<string, unknown>;
  outcome?: unknown;
  body?: string;
  kind?: string;
  filename?: string;
  activities?: Item[];
  steps?: Step[];
  findings?: Finding[];
  graph?: {
    nodes: Array<{ id: string; kind: string; name?: string; value?: string }>;
    edges: Array<{
      from: string;
      to: string;
      relationship: string;
      state: string;
      finding_id: string;
      reference: string;
      locator: string;
    }>;
  };
  drafts?: Draft[];
};
type Step = { created_at: string; name: string; detail: unknown };
type Draft = { id: string; channel: string; body: string; status: string };
type Finding = {
  id: string;
  kind: string;
  subject: string;
  assertion: string;
  reference: string;
  locator: string;
  state: string;
  current_assertion: string;
  review_reason?: string;
  channel_kind?: string;
  identity_finding_id?: string;
  channel_value?: string;
  relationship?: string;
  source_excerpt?: string;
  method?: string;
};
type List = Item[] | { items: Item[] };
const endpoints: Record<Exclude<Panel, "Record">, string> = {
  Investigations: "investigations",
  Opportunities: "opportunities",
  Financials: "analysis-scenarios",
  Reports: "reports",
};
const stages = [
  "prospect",
  "research",
  "contacted",
  "diligence",
  "under_contract",
  "closed",
  "passed",
];
const roles = [
  "authorized_owner_representative",
  "disclosed_manager",
  "asset_manager",
  "acquisitions_contact",
  "property_manager",
  "registered_agent",
  "officer",
  "other",
];
const field = (d: FormData, key: string) => String(d.get(key) || "").trim();
const optionals = (d: FormData, keys: string[]) =>
  Object.fromEntries(
    keys.filter((k) => field(d, k)).map((k) => [k, field(d, k)]),
  );
type Action = (
  e: FormEvent<HTMLFormElement>,
  fn: (d: FormData) => Promise<void>,
) => void;
function Input({
  label,
  name,
  required = false,
  type = "text",
  ...props
}: {
  label: string;
  name: string;
  required?: boolean;
  type?: string;
  defaultValue?: string | number;
  min?: string;
  max?: string;
  step?: string;
  placeholder?: string;
  maxLength?: number;
}) {
  return (
    <label>
      {label}
      <input name={name} type={type} required={required} {...props} />
    </label>
  );
}
function Select({
  label,
  name,
  values,
  initial = "",
  optional = false,
}: {
  label: string;
  name: string;
  values: string[];
  initial?: string;
  optional?: boolean;
}) {
  return (
    <label>
      {label}
      <select
        name={name}
        defaultValue={initial || (!optional ? values[0] : "")}
      >
        {optional && <option value="">Unspecified</option>}
        {values.map((s) => (
          <option key={s} value={s}>
            {title(s)}
          </option>
        ))}
      </select>
    </label>
  );
}
function Notes({
  name,
  label,
  required = false,
}: {
  name: string;
  label: string;
  required?: boolean;
}) {
  return (
    <label>
      {label}
      <textarea name={name} required={required} maxLength={4000} />
    </label>
  );
}
function Editor({ name, children }: { name: string; children: ReactNode }) {
  return (
    <details className="editor">
      <summary>{name}</summary>
      {children}
    </details>
  );
}
export default function Casework({
  panel,
  propertyId,
  api,
  role,
}: {
  panel: Exclude<Panel, "Record">;
  propertyId: string;
  api: Api;
  role: string;
}) {
  const endpoint = endpoints[panel],
    [items, setItems] = useState<Item[]>([]),
    [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Item | null>(null),
    [version, setVersion] = useState(0),
    [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [feedback, setFeedback] = useState("");
  const [documents, setDocuments] = useState<Item[]>([]),
    [links, setLinks] = useState<Record<string, Item[]>>({});
  const editable = role !== "viewer",
    research = ["admin", "researcher"].includes(role),
    analyze = ["admin", "analyst"].includes(role);
  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    const load = async () => {
      try {
        const list = rows(
          await api.get<List>(
            endpoint + "?property_id=" + propertyId,
            ctrl.signal,
          ),
        );
        if (!ctrl.signal.aborted) {
          setItems(list);
          setSelected((prev) =>
            list.some((i) => i.id === prev) ? prev : list[0]?.id || "",
          );
        }
        if (
          editable &&
          (panel === "Investigations" || panel === "Opportunities")
        ) {
          const docs = rows(
            await api.get<List>(
              "documents?property_id=" + propertyId,
              ctrl.signal,
            ),
          );
          if (!ctrl.signal.aborted) setDocuments(docs);
        }
        if (panel === "Reports") {
          const groups = await Promise.all(
            ["investigations", "opportunities", "analysis-scenarios"].map(
              async (k) => [
                k,
                rows(
                  await api.get<List>(
                    k + "?property_id=" + propertyId,
                    ctrl.signal,
                  ),
                ),
              ],
            ),
          );
          if (!ctrl.signal.aborted) setLinks(Object.fromEntries(groups));
        }
      } catch (e) {
        if (!ctrl.signal.aborted) setError(message(e));
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => ctrl.abort();
  }, [endpoint, propertyId, api, panel, version, editable]);
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const value = await api.get<Item>(
          endpoint + "/" + selected,
          ctrl.signal,
        );
        if (ctrl.signal.aborted) return;
        setDetail(value);
        if (
          ["queued", "running", "processing", "approved", "rendering"].includes(
            value.status || "",
          )
        )
          timer = setTimeout(() => void load(), 2200);
      } catch (e) {
        if (!ctrl.signal.aborted) setError(message(e));
      }
    }
    setDetail(null);
    void load();
    return () => {
      ctrl.abort();
      clearTimeout(timer);
    };
  }, [api, selected, endpoint, version]);
  const run: Action = (e, fn) => {
    e.preventDefault();
    if (pending) return;
    const form = e.currentTarget,
      data = new FormData(form);
    setPending(true);
    setError("");
    setFeedback("");
    fn(data)
      .then(() => {
        form.reset();
        setFeedback("Changes saved.");
        setVersion((v) => v + 1);
      })
      .catch((e) => setError(message(e)))
      .finally(() => setPending(false));
  };
  const create = async (body: Record<string, unknown>) => {
    const added = await api.send<Item>(endpoint, {
      property_id: propertyId,
      ...body,
    });
    setSelected(added.id);
  };
  async function download(path: string, filename: string) {
    setError("");
    try {
      const blob = await (await api.request(path)).blob();
      const url = URL.createObjectURL(blob),
        a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) {
      setError(message(e));
    }
  }
  const docPicker = (
    <label>
      Supporting document
      <select name="document_id" defaultValue="">
        <option value="">No attachment</option>
        {documents.map((d) => (
          <option key={d.id} value={d.id}>
            {d.filename || d.name || d.id}
          </option>
        ))}
      </select>
    </label>
  );
  const linkPicker = (key: string, label: string, group: string) => (
    <label>
      {label}
      <select name={key} defaultValue="">
        <option value="">Omit</option>
        {(links[group] || []).map((i) => (
          <option value={i.id} key={i.id}>
            {i.name || i.title || i.objective || i.id} · {i.id.slice(0, 8)}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <section className="casework">
      <div className="section-head">
        <h3>{panel}</h3>
        <button
          className="small"
          onClick={() => {
            setError("");
            setVersion((n) => n + 1);
          }}
        >
          Refresh
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {feedback && (
        <p role="status" className="success">
          {feedback}
        </p>
      )}
      <fieldset disabled={pending} className="forms">
        {panel === "Investigations" && research && (
          <Editor name="Start an investigation">
            <form
              onSubmit={(e) =>
                run(e, (d) =>
                  create({
                    objective: field(d, "objective"),
                    max_external_requests: Number(d.get("budget")),
                    preferred_roles: field(d, "preferred")
                      ? [field(d, "preferred")]
                      : [],
                  }),
                )
              }
            >
              <Input
                name="objective"
                label="Research objective"
                defaultValue="find_business_contact"
                required
                maxLength={200}
              />
              <Select
                name="preferred"
                label="Preferred role"
                values={roles}
                optional
              />
              <Input
                name="budget"
                label="External request limit"
                type="number"
                min="0"
                max="20"
                defaultValue="0"
                required
              />
              <button className="primary">Start investigation</button>
            </form>
          </Editor>
        )}
        {panel === "Opportunities" && editable && (
          <Editor name="Add an opportunity">
            <form
              onSubmit={(e) =>
                run(e, (d) =>
                  create({
                    title: field(d, "title"),
                    stage: field(d, "stage"),
                    ...optionals(d, ["assignee"]),
                  }),
                )
              }
            >
              <Input label="Opportunity title" name="title" required />
              <Select label="Stage" name="stage" values={stages} />
              <Input label="Assignee" name="assignee" />
              <button className="primary">Create opportunity</button>
            </form>
          </Editor>
        )}
        {panel === "Financials" && analyze && (
          <Editor name="Create a financial scenario">
            <form
              onSubmit={(e) =>
                run(e, (d) => {
                  const inputs = optionals(d, [
                    "effective_gross_income",
                    "operating_expenses",
                    "property_value",
                    "annual_debt_service",
                    "area_sqft",
                    "cash_invested",
                    "valuation_cap_rate",
                  ]);
                  const rates = field(d, "sensitivity")
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean);
                  return create({
                    name: field(d, "name"),
                    period: "Annual",
                    currency: field(d, "currency"),
                    assumptions: field(d, "assumptions"),
                    sources: field(d, "origin")
                      ? Object.fromEntries(
                          Object.keys(inputs).map((k) => [
                            k,
                            field(d, "origin"),
                          ]),
                        )
                      : {},
                    inputs: { ...inputs, sensitivity_rates: rates },
                  });
                })
              }
            >
              <Input label="Scenario name" name="name" required />
              <p>Annual cash flows and valuation assumptions</p>
              <Input
                label="Currency code"
                name="currency"
                defaultValue="USD"
                required
                maxLength={3}
              />
              {Object.entries({
                effective_gross_income: "Annual effective gross income",
                operating_expenses: "Annual operating expenses",
                property_value: "Property value",
                annual_debt_service: "Annual debt service",
                area_sqft: "Area in square feet",
                cash_invested: "Cash invested",
                valuation_cap_rate: "Valuation cap rate as a decimal",
              }).map(([k, v]) => (
                <Input
                  key={k}
                  label={v}
                  name={k}
                  type="number"
                  min="0"
                  step="any"
                  max={k === "valuation_cap_rate" ? "1" : undefined}
                />
              ))}
              <Input
                name="sensitivity"
                label="Sensitivity rates, comma-separated"
                placeholder="0.05, 0.06, 0.07"
              />
              <Notes name="assumptions" label="Model assumptions" />
              <Input name="origin" label="Input source or reference" />
              <button className="primary">Calculate and save</button>
            </form>
          </Editor>
        )}
        {panel === "Reports" && editable && (
          <Editor name="Prepare a dossier">
            <form
              onSubmit={(e) =>
                run(e, (d) =>
                  create(
                    optionals(d, [
                      "scenario_id",
                      "investigation_id",
                      "opportunity_id",
                    ]),
                  ),
                )
              }
            >
              {linkPicker(
                "investigation_id",
                "Research case",
                "investigations",
              )}
              {linkPicker("opportunity_id", "Opportunity", "opportunities")}
              {linkPicker(
                "scenario_id",
                "Financial scenario",
                "analysis-scenarios",
              )}
              <button className="primary">Prepare report for review</button>
            </form>
          </Editor>
        )}
        {(panel === "Investigations" || panel === "Opportunities") &&
          editable && (
            <Editor name="Property documents">
              <form
                onSubmit={(e) =>
                  run(e, async (d) => {
                    d.set("property_id", propertyId);
                    d.set("exportable", d.has("exportable") ? "true" : "false");
                    await api.send("documents", d);
                  })
                }
              >
                <Input
                  type="file"
                  label="PDF, TXT, CSV, or XLSX file (8 MiB maximum)"
                  name="file"
                  required
                />
                <Select
                  label="Document type"
                  name="kind"
                  values={[
                    "deed",
                    "filing",
                    "lease",
                    "rent_roll",
                    "research",
                    "other",
                  ]}
                />
                <label className="check">
                  <input type="checkbox" name="exportable" />
                  Permitted for dossier export
                </label>
                <label className="check">
                  <input type="checkbox" name="allow_ai" value="true" />
                  Permitted for model-assisted extraction
                </label>
                <button className="secondary">Upload document</button>
              </form>
              {documents.map((d) => (
                <button
                  type="button"
                  className="small"
                  key={d.id}
                  onClick={() =>
                    void download(
                      "documents/" + d.id + "/download",
                      d.filename || "document",
                    )
                  }
                >
                  {d.filename || d.name || d.id}
                </button>
              ))}
            </Editor>
          )}
      </fieldset>
      {!loading && !items.length && (
        <p>This property has no {panel.toLowerCase()} yet.</p>
      )}
      {items.length > 0 && (
        <label className="record-picker">
          Open record
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.title || i.name || i.objective || "Dossier"} ·{" "}
                {i.id.slice(0, 8)}
                {i.status ? " · " + title(i.status) : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {detail && detail.id === selected && (
        <fieldset disabled={pending} className="forms detail-card">
          {detail.status && (
            <div className="meta">
              Status <strong>{title(detail.status)}</strong>
            </div>
          )}
          {panel === "Investigations" && (
            <>
              <h4>Research outcome</h4>
              <p>
                {detail.outcome
                  ? title(display(detail.outcome))
                  : "Research pending."}
              </p>
              <details>
                <summary>Investigation history</summary>
                {detail.steps?.map((s) => (
                  <p key={s.created_at + s.name}>
                    <strong>{title(s.name)}</strong> {display(s.detail)}
                  </p>
                ))}
              </details>
              {research && (
                <Editor name="Record source evidence">
                  <form
                    onSubmit={(e) =>
                      run(e, async (d) => {
                        await api.send(
                          "investigations/" + selected + "/evidence",
                          {
                            ...optionals(d, [
                              "relationship",
                              "channel_kind",
                              "channel_value",
                              "identity_finding_id",
                              "document_id",
                              "effective_date",
                              "source_excerpt",
                            ]),
                            kind: field(d, "kind"),
                            assertion: field(d, "assertion"),
                            reference: field(d, "reference"),
                            locator: field(d, "locator"),
                            subject: field(d, "subject"),
                            exportable: d.has("exportable"),
                          },
                        );
                      })
                    }
                  >
                    <Select
                      name="kind"
                      label="Evidence type"
                      values={[
                        "entity_identity",
                        "property_role",
                        "business_channel",
                        "ownership",
                      ]}
                    />
                    <Input name="subject" label="Subject name" required />
                    <Notes
                      name="assertion"
                      label="Source-supported assertion"
                      required
                    />
                    <Input name="reference" label="Source reference" required />
                    <Input
                      name="locator"
                      label="Page, row, or field"
                      required
                    />
                    {docPicker}
                    <label>
                      Linked entity identity
                      <select name="identity_finding_id" defaultValue="">
                        <option value="">No linked identity</option>
                        {detail.findings
                          ?.filter((f) => f.kind === "entity_identity")
                          .map((f) => (
                            <option value={f.id} key={f.id}>
                              {f.subject} · {f.current_assertion}
                            </option>
                          ))}
                      </select>
                    </label>
                    <Input
                      name="channel_value"
                      label="Professional email or business phone"
                    />
                    <Select
                      name="relationship"
                      label="Documented role"
                      values={roles}
                      optional
                    />
                    <Select
                      name="channel_kind"
                      label="Business channel type"
                      values={[
                        "general_office",
                        "business_email",
                        "business_phone",
                      ]}
                      optional
                    />
                    <Input
                      type="date"
                      name="effective_date"
                      label="Effective date"
                    />
                    <Notes
                      label="Source excerpt (required for verification without a document)"
                      name="source_excerpt"
                    />
                    <label className="check">
                      <input type="checkbox" name="exportable" />
                      Permitted for dossier export
                    </label>
                    <button className="primary">Submit evidence</button>
                  </form>
                </Editor>
              )}
              {detail.graph && detail.graph.edges.length > 0 && (
                <section>
                  <h4>Documented relationships</h4>
                  {detail.graph.edges.map((edge) => {
                    const node = (id: string) => {
                      const n = detail.graph!.nodes.find((n) => n.id === id);
                      return (
                        n?.name ||
                        n?.value ||
                        (n?.kind === "property" ? "Selected property" : id)
                      );
                    };
                    return (
                      <article className="finding" key={edge.finding_id}>
                        <strong>
                          {node(edge.from)} · {title(edge.relationship)} ·{" "}
                          {node(edge.to)}
                        </strong>
                        <small>
                          {title(edge.state)} · {edge.reference} ·{" "}
                          {edge.locator}
                        </small>
                      </article>
                    );
                  })}
                </section>
              )}
              <h4>Findings and review</h4>
              {!detail.findings?.length && <p>No findings recorded.</p>}
              {detail.findings?.map((f) => (
                <article className="finding" key={f.id}>
                  <div className="meta">
                    {title(f.kind)} · {title(f.state)}
                  </div>
                  <strong>{f.current_assertion || f.assertion}</strong>
                  <p>
                    {f.subject} · {f.reference} · {f.locator}
                  </p>
                  {f.source_excerpt && (
                    <blockquote>{f.source_excerpt}</blockquote>
                  )}
                  {f.review_reason && <small>{f.review_reason}</small>}
                  {research && (
                    <Editor name="Review finding">
                      <form
                        onSubmit={(e) =>
                          run(e, async (d) => {
                            const enrichment = optionals(d, [
                              "relationship",
                              "identity_finding_id",
                              "channel_kind",
                              "channel_value",
                            ]);
                            await api.send(
                              "investigations/" + selected + "/reviews",
                              {
                                finding_id: f.id,
                                decision: field(d, "decision"),
                                reason: field(d, "reason"),
                                ...optionals(d, ["correction"]),
                                ...(field(d, "decision") === "accept" &&
                                Object.keys(enrichment).length
                                  ? { enrichment }
                                  : {}),
                              },
                            );
                          })
                        }
                      >
                        <Select
                          label="Decision"
                          name="decision"
                          values={[
                            "accept",
                            "reject",
                            "correct",
                            "conflict",
                            "stale",
                          ]}
                        />
                        {(f.kind === "business_channel" ||
                          f.kind === "property_role") &&
                          !f.identity_finding_id && (
                            <label>
                              Identity supported by this evidence
                              <select
                                name="identity_finding_id"
                                defaultValue=""
                              >
                                <option value="">Choose an identity</option>
                                {detail.findings
                                  ?.filter((i) => i.kind === "entity_identity")
                                  .map((i) => (
                                    <option value={i.id} key={i.id}>
                                      {i.subject} · {i.current_assertion}
                                    </option>
                                  ))}
                              </select>
                            </label>
                          )}
                        {f.kind === "property_role" && !f.relationship && (
                          <Select
                            label="Supported property role"
                            name="relationship"
                            values={roles}
                            optional
                          />
                        )}
                        {f.kind === "business_channel" && !f.channel_kind && (
                          <Select
                            label="Supported channel type"
                            name="channel_kind"
                            values={[
                              "general_office",
                              "business_email",
                              "business_phone",
                            ]}
                            optional
                          />
                        )}
                        {f.kind === "business_channel" && !f.channel_value && (
                          <Input
                            name="channel_value"
                            label="Verified professional channel"
                          />
                        )}
                        <Notes name="reason" label="Review reason" required />
                        <Notes
                          name="correction"
                          label="Replacement assertion for a correction"
                        />
                        <button className="primary">Record decision</button>
                      </form>
                    </Editor>
                  )}
                </article>
              ))}
            </>
          )}
          {panel === "Investigations" && research && (
            <>
              <Editor name="Prepare outreach draft">
                <form
                  onSubmit={(e) =>
                    run(e, async (d) => {
                      await api.send("investigations/" + selected + "/drafts", {
                        channel_finding_id: field(d, "channel_finding_id"),
                        body: field(d, "body"),
                      });
                    })
                  }
                >
                  <label>
                    Verified contact route
                    <select required name="channel_finding_id" defaultValue="">
                      <option value="">
                        Choose a verified business channel
                      </option>
                      {detail.findings
                        ?.filter(
                          (f) =>
                            f.kind === "business_channel" &&
                            f.state === "verified",
                        )
                        .map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.current_assertion}
                          </option>
                        ))}
                    </select>
                  </label>
                  <Notes label="Draft text" name="body" required />
                  <button className="primary">Prepare draft for review</button>
                </form>
              </Editor>
              <Editor name="Suppress a business channel">
                <form
                  onSubmit={(e) =>
                    run(e, async (d) => {
                      await api.send("suppressions", {
                        property_id: propertyId,
                        channel: field(d, "channel"),
                        reason: field(d, "reason"),
                      });
                    })
                  }
                >
                  <Input
                    name="channel"
                    label="Business email or phone"
                    required
                  />
                  <Notes name="reason" label="Suppression reason" required />
                  <button className="secondary">Suppress channel</button>
                </form>
              </Editor>
              {detail.drafts?.map((draft) => (
                <article className="finding" key={draft.id}>
                  <div className="meta">Outreach draft · {draft.status}</div>
                  <strong>{draft.channel}</strong>
                  <p>{draft.body}</p>
                  {draft.status === "draft" && (
                    <Editor name="Review draft">
                      <form
                        onSubmit={(e) =>
                          run(e, async (d) => {
                            await api.send("drafts/" + draft.id + "/reviews", {
                              decision: field(d, "decision"),
                              reason: field(d, "reason"),
                            });
                          })
                        }
                      >
                        <Select
                          label="Draft decision"
                          name="decision"
                          values={["approve", "reject"]}
                        />
                        <Notes
                          name="reason"
                          label="Draft review reason"
                          required
                        />
                        <button className="primary">Record draft review</button>
                      </form>
                    </Editor>
                  )}
                </article>
              ))}
            </>
          )}
          {panel === "Opportunities" && (
            <>
              <h4>{detail.title}</h4>
              <p>
                Stage · {title(detail.stage || "prospect")}{" "}
                {detail.assignee ? " · " + detail.assignee : ""}
              </p>
              {editable && (
                <Editor name="Update stage or assignee">
                  <form
                    onSubmit={(e) =>
                      run(e, async (d) => {
                        await api.send(
                          "opportunities/" + selected,
                          {
                            stage: field(d, "stage"),
                            assignee: field(d, "assignee") || null,
                          },
                          "PATCH",
                        );
                      })
                    }
                  >
                    <Select
                      name="stage"
                      label="Opportunity stage"
                      values={stages}
                      initial={detail.stage}
                    />
                    <Input
                      name="assignee"
                      label="Assigned to"
                      defaultValue={detail.assignee}
                    />
                    <button className="secondary">Save opportunity</button>
                  </form>
                </Editor>
              )}
              <h4>Activity</h4>
              {detail.activities?.map((a) => (
                <article className="finding" key={a.id}>
                  <small>
                    {title(a.kind || "note")} · {a.created_at?.slice(0, 10)}
                  </small>
                  <p>{a.body}</p>
                  {a.assignee && <small>Assigned to {a.assignee}</small>}
                </article>
              ))}
              {!detail.activities?.length && <p>No activity recorded.</p>}
              {editable && (
                <Editor name="Log an activity or task">
                  <form
                    onSubmit={(e) =>
                      run(e, async (d) => {
                        await api.send(
                          "opportunities/" + selected + "/activities",
                          {
                            kind: field(d, "kind"),
                            body: field(d, "body"),
                            ...optionals(d, ["assignee", "document_id"]),
                          },
                        );
                      })
                    }
                  >
                    <Select
                      name="kind"
                      label="Activity type"
                      values={[
                        "task",
                        "visit",
                        "note",
                        "contact_attempt",
                        "lease",
                      ]}
                    />
                    <Notes name="body" label="Activity details" required />
                    <Input name="assignee" label="Assignee" />
                    {docPicker}
                    <button className="primary">Add activity</button>
                  </form>
                </Editor>
              )}
            </>
          )}
          {panel === "Financials" && (
            <>
              <h4>{detail.name}</h4>
              <div className="meta">
                Modeled scenario · {detail.currency} · {detail.model_version}
              </div>
              <p>{detail.assumptions || "No assumptions entered."}</p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Measure</th>
                      <th>Model result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(detail.outputs || {}).map(([k, v]) => (
                      <tr key={k}>
                        <td>{title(k)}</td>
                        <td>{display(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <details>
                <summary>Scenario inputs</summary>
                {Object.entries(detail.inputs || {}).map(([k, v]) => (
                  <p key={k}>
                    {title(k)} · {display(v)}
                  </p>
                ))}
              </details>
            </>
          )}
          {panel === "Reports" && (
            <>
              <h4>Research dossier</h4>
              <p>
                Report {detail.id.slice(0, 8)} ·{" "}
                {detail.created_at?.slice(0, 10)}
              </p>
              {detail.status === "published" && (
                <button
                  className="primary"
                  onClick={() =>
                    void download(
                      "reports/" + selected + "/download",
                      "property-dossier-" + selected.slice(0, 8) + ".pdf",
                    )
                  }
                >
                  Download reviewed PDF
                </button>
              )}
              {editable &&
                [
                  "pending_review",
                  "awaiting_review",
                  "draft",
                  "review",
                ].includes(detail.status || "") && (
                  <Editor name="Review report for export">
                    <details>
                      <summary>Inspect pinned report inputs</summary>
                      <pre>
                        {JSON.stringify(
                          (detail as Item & { snapshot?: unknown }).snapshot,
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                    <form
                      onSubmit={(e) =>
                        run(e, async (d) => {
                          await api.send("reports/" + selected + "/reviews", {
                            decision: field(d, "decision"),
                            reason: field(d, "reason"),
                          });
                        })
                      }
                    >
                      <Select
                        name="decision"
                        label="Report decision"
                        values={["approve", "reject"]}
                      />
                      <Notes name="reason" label="Review notes" required />
                      <button className="primary">Submit report review</button>
                    </form>
                  </Editor>
                )}
            </>
          )}
        </fieldset>
      )}
    </section>
  );
}
