"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearToken, get, getToken } from "@/lib/api";
import type { AppConfig } from "@/lib/types";

const NAV = [
  { href: "/", label: "Dashboard", icon: "◈" },
  { href: "/leads", label: "Leads", icon: "◆" },
  { href: "/crm", label: "CRM Pipeline", icon: "▤" },
  { href: "/discovery", label: "Discovery", icon: "◎" },
  { href: "/campaigns", label: "Campaigns", icon: "✉" },
  { href: "/deliverability", label: "Deliverability", icon: "🛡" },
  { href: "/learning", label: "AI Insights", icon: "✦" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [config, setConfig] = useState<AppConfig | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setReady(true);
    get<AppConfig>("/api/system/config").then(setConfig).catch(() => undefined);
  }, [router]);

  if (!ready) {
    return (
      <div className="login-shell">
        <span className="spinner" />
      </div>
    );
  }

  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand">
          Lead Generator
          <small>{config?.company.name ?? ""}</small>
        </div>
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link key={item.href} href={item.href} className={`navlink ${active ? "active" : ""}`}>
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
        <div className="sidebar-footer">
          {config?.dry_run && (
            <div className="badge badge-amber mb" title="No mail is actually delivered">
              DRY RUN
            </div>
          )}
          <button
            className="btn-sm"
            style={{ width: "100%" }}
            onClick={() => {
              clearToken();
              router.replace("/login");
            }}
          >
            Sign out
          </button>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
