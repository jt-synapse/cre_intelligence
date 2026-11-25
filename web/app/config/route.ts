export const dynamic = "force-dynamic";
export async function GET() {
  const configuredHours = Number(process.env.CRE_FIELD_GRANT_HOURS || 12);
  const fieldGrantHours = Number.isFinite(configuredHours)
    ? Math.min(12, Math.max(1, Math.floor(configuredHours)))
    : 12;
  return Response.json(
    {
      fieldGrantHours,
      issuer: process.env.CRE_OIDC_ISSUER || null,
      clientId: process.env.CRE_OIDC_CLIENT_ID || null,
      scope: process.env.CRE_OIDC_SCOPE || "openid profile email",
      audience: process.env.CRE_OIDC_AUDIENCE || null,
      demo: process.env.CRE_DEMO_MODE === "true",
      basemap: process.env.CRE_BASEMAP_STYLE_URL || null,
    },
    { headers: { "cache-control": "no-store" } },
  );
}
