"use client";
import { useEffect, useState } from "react";
import { getConfig, manager } from "../../../lib/auth";

let exchange: Promise<void> | undefined;
export default function Callback() {
  const [error, setError] = useState("");
  useEffect(() => {
    exchange ??= getConfig()
      .then((c) => manager(c).signinRedirectCallback())
      .then(() => {
        history.replaceState({}, "", "/auth/callback");
        location.replace("/");
      });
    exchange.catch(() =>
      setError(
        "The sign-in response could not be verified. Please sign in again.",
      ),
    );
  }, []);
  return (
    <main className="auth">
      <h1>Organization sign-in</h1>
      <p role="status">{error || "Verifying your session…"}</p>
      {error && <a href="/">Return to sign-in</a>}
    </main>
  );
}
