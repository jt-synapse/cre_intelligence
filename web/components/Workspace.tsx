"use client";
import { useEffect, useMemo, useState } from "react";
import {
  accessToken,
  demoAvailable,
  getConfig,
  manager,
  type Config,
} from "../lib/auth";
import { ApiError, client, message } from "../lib/api";
import type { Member, Organization } from "../lib/types";
import Explorer from "./Explorer";
import { FieldSync } from "./FieldCapture";
import { clearFieldSession, pendingFieldCount } from "../lib/fieldQueue";

function Brand() {
  return (
    <div className="brand">
      <span className="brandmark" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span>CRE Intelligence</span>
    </div>
  );
}

export default function Workspace() {
  const [config, setConfig] = useState<Config | null>(null),
    [token, setToken] = useState<string | null>(null);
  const [member, setMember] = useState<Member | null>(null),
    [orgId, setOrgId] = useState("");
  const [pending, setPending] = useState(true),
    [error, setError] = useState("");
  async function start() {
    setPending(true);
    setError("");
    setMember(null);
    try {
      const settings = await getConfig();
      setConfig(settings);
      const t = await accessToken(settings);
      setToken(t);
      if (t) {
        const user = await client(t).get<Member>("me");
        setMember(user);
        const chosen =
          user.organizations.find(
            (o) => o.id === sessionStorage.getItem("cre.org"),
          ) || user.organizations[0];
        if (!chosen) await clearFieldSession().catch(() => {});
        setOrgId(chosen?.id || "");
      } else {
        await clearFieldSession().catch(() => {});
      }
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403))
        await clearFieldSession().catch(() => {});
      setError(message(e));
    } finally {
      setPending(false);
    }
  }
  useEffect(() => {
    void start();
  }, []);
  const api = useMemo(() => client(token || "", orgId), [token, orgId]);
  async function confirmLeaving() {
    const count = await pendingFieldCount().catch(() => null);
    if (count === null)
      return window.confirm(
        "Field storage is unavailable. Continuing will clear access to local drafts. Continue?",
      );
    return (
      count === 0 ||
      window.confirm(
        `Discard ${count} pending field capture(s) on this device and continue?`,
      )
    );
  }
  async function signOut() {
    if (!(await confirmLeaving())) return;
    await clearFieldSession().catch(() => {});
    sessionStorage.removeItem("cre.demo");
    sessionStorage.removeItem("cre.org");
    if (config?.issuer && config.clientId) await manager(config).removeUser();
    setToken(null);
    setMember(null);
    setOrgId("");
    setError("");
  }
  const organization: Organization | undefined = member?.organizations.find(
    (o) => o.id === orgId,
  );
  if (!config || !token || !member || !organization)
    return (
      <main className="gate">
        <Brand />
        <section className="gate-card">
          <div className="eyebrow">Research workspace</div>
          <h1>Property intelligence</h1>
          <p>
            Sign in to explore available parcels and manage property
            research with your team.
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {pending ? (
            <p role="status">Opening workspace…</p>
          ) : (
            <>
              {member && !organization && (
                <p role="status">
                  Your account has no organization membership. Contact your
                  workspace administrator.
                </p>
              )}
              {!token && config?.issuer && config.clientId && (
                <button
                  className="primary"
                  onClick={() =>
                    manager(config)
                      .signinRedirect()
                      .catch((e) => setError(message(e)))
                  }
                >
                  Sign in with your organization
                </button>
              )}
              {!token && config && demoAvailable(config) && (
                <button
                  className="secondary"
                  onClick={() => {
                    sessionStorage.setItem("cre.demo", "yes");
                    void start();
                  }}
                >
                  Open local demo
                </button>
              )}
              {!token && config && !config.issuer && !demoAvailable(config) && (
                <p role="status">
                  Organization sign-in is awaiting configuration.
                </p>
              )}
              {(error || !config) && (
                <button className="secondary" onClick={() => void start()}>
                  Retry connection
                </button>
              )}
              {token && (
                <button className="secondary" onClick={() => void signOut()}>
                  Sign out
                </button>
              )}
            </>
          )}
        </section>
      </main>
    );
  return (
    <div className="app">
      <a className="skip" href="#work">
        Skip to workspace
      </a>
      <header className="top">
        <Brand />
        <div className="account">
          {token === "local-demo" && (
            <span className="demo-badge">Local demo</span>
          )}
          <label htmlFor="org">Workspace</label>
          <select
            id="org"
            value={orgId}
            onChange={async (e) => {
              const nextOrg = e.target.value;
              if (!(await confirmLeaving())) return;
              await clearFieldSession().catch(() => {});
              sessionStorage.setItem("cre.org", nextOrg);
              setOrgId(nextOrg);
            }}
          >
            {member.organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
          <span className="role">{organization.role}</span>
          {organization.role === "admin" && (
            <details className="field-access">
              <summary>Offline access</summary>
              <small>
                Field drafts are available on this device for up to{" "}
                {config.fieldGrantHours ?? 12} hours after workspace
                verification.
              </small>
            </details>
          )}
          <button className="text-button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <FieldSync
        grantHours={config.fieldGrantHours}
        key={"field:" + JSON.stringify([member.subject, orgId])}
        api={api}
        orgId={orgId}
        subject={member.subject}
        role={organization.role}
      />
      <Explorer
        key={JSON.stringify([member.subject, orgId])}
        orgId={orgId}
        subject={member.subject}
        tileHeaders={{
          Authorization: "Bearer " + token,
          "X-Organization-ID": orgId,
        }}
        api={api}
        role={organization.role}
        curator={Boolean(member.can_curate)}
        basemap={config.basemap}
      />
    </div>
  );
}
