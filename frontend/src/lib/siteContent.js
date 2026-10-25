import { useEffect, useState } from "react";
import { api } from "./api";

// The admin-edited site texts (/public/content), fetched once per page load and
// shared by the navbar, footer and pages that show them.
let pending = null;

export function loadSiteContent() {
  if (!pending) {
    pending = api.get("/public/content")
      .then((r) => r.data || {})
      .catch(() => {
        pending = null; // the next page asks again
        return {};
      });
  }
  return pending;
}

export function useSiteContent() {
  const [content, setContent] = useState({});
  useEffect(() => {
    let alive = true;
    loadSiteContent().then((c) => alive && setContent(c));
    return () => { alive = false; };
  }, []);
  return content;
}

/** The registered business details an admin filled in (empty ones dropped). */
export function businessDetails(content) {
  return [
    ["الاسم التجاري", content["business.legal_name"]],
    ["السجل التجاري", content["business.cr_number"]],
    ["الرقم الضريبي", content["business.vat_number"]],
    ["العنوان", content["business.address"]],
    ["الهاتف", content["business.phone"]],
    ["البريد الإلكتروني", content["footer.contact_email"]],
  ].filter(([, v]) => typeof v === "string" && v.trim());
}
