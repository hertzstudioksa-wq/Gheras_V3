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

/** A wa.me link for the business phone (Saudi 05… numbers get +966), or "". */
export function whatsappLink(phone, text = "مرحباً، لدي سؤال عن غِراس") {
  let digits = String(phone || "").replace(/\D/g, "");
  if (digits.startsWith("00")) digits = digits.slice(2);
  else if (digits.startsWith("05")) digits = `966${digits.slice(1)}`;
  if (digits.length < 9) return "";
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
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
