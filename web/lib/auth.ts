import { UserManager, WebStorageStateStore } from "oidc-client-ts";
import { isLoopback } from "./proxy.mjs";

export interface Config {
  fieldGrantHours?: number;
  issuer: string | null;
  clientId: string | null;
  scope: string;
  audience: string | null;
  demo: boolean;
  basemap: string | null;
}
export const getConfig = async (): Promise<Config> => {
  const response = await fetch("/config", { cache: "no-store" });
  if (!response.ok) throw new Error("Cannot load workspace settings.");
  return response.json();
};
export function demoAvailable(config: Config) {
  return config.demo && isLoopback(window.location.hostname);
}
export function manager(config: Config) {
  if (!config.issuer || !config.clientId)
    throw new Error("Organization sign-in has not been configured.");
  return new UserManager({
    authority: config.issuer,
    client_id: config.clientId,
    response_type: "code",
    scope: config.scope,
    redirect_uri: window.location.origin + "/auth/callback",
    automaticSilentRenew: false,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    extraQueryParams: config.audience ? { audience: config.audience } : {},
  });
}
export async function accessToken(config: Config): Promise<string | null> {
  if (demoAvailable(config) && sessionStorage.getItem("cre.demo") === "yes")
    return "local-demo";
  if (!config.issuer || !config.clientId) return null;
  const user = await manager(config).getUser();
  return user && !user.expired ? user.access_token : null;
}
