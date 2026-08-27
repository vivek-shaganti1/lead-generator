"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, login } from "@/lib/api";
import { Banner } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setHint(null);
    try {
      await login(email.trim(), password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
      if (err instanceof ApiError && err.status === 401) {
        setHint(
          "This dashboard has no sign-up. The only account is the one seeded from " +
            "ADMIN_EMAIL and ADMIN_PASSWORD in your .env — a saved password for another " +
            "site will not work here.",
        );
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <div className="login-panel">
        <div className="login-brand">
          <div className="login-mark" aria-hidden>
            ◈
          </div>
          <h1>Lead Generator</h1>
          <p className="subtitle">
            Finds local businesses with no working website, and runs compliant outreach
            offering to build one.
          </p>
        </div>

        <div className="card login-card">
          <h2 className="login-heading">Sign in</h2>

          {error && <Banner kind="error">{error}</Banner>}
          {hint && <p className="login-hint">{hint}</p>}

          <form onSubmit={submit} noValidate>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                required
                placeholder="you@yourdomain.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            <div className="field">
              <div className="label-row">
                <label htmlFor="password">Password</label>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => setReveal((v) => !v)}
                  aria-pressed={reveal}
                >
                  {reveal ? "Hide" : "Show"}
                </button>
              </div>
              <input
                id="password"
                type={reveal ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <button
              className="btn-primary login-submit"
              type="submit"
              disabled={busy || !email.trim() || !password}
            >
              {busy ? <span className="spinner spinner-sm" /> : null}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>

        <p className="login-foot">
          Credentials come from <code>ADMIN_EMAIL</code> / <code>ADMIN_PASSWORD</code>,
          read once at boot.
        </p>
      </div>
    </div>
  );
}
