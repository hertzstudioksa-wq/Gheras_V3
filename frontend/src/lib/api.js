import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  headers: { "Content-Type": "application/json" },
  timeout: 20000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("gheras_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Global 401 handler: token invalid/expired anywhere in the app → clean logout.
// We DO NOT redirect for /auth/me probes (AuthContext handles those), nor for
// /auth/login (Login page handles those), nor for the file-download endpoint
// (that just fails the <img> tag silently; session stays intact).
api.interceptors.response.use(
  (r) => r,
  (error) => {
    const status = error?.response?.status;
    const url = error?.config?.url || "";
    const noResponse = !error?.response;
    // Distinguish transient network/5xx from real auth failures.
    if (noResponse) {
      // eslint-disable-next-line no-console
      console.debug("[auth] interceptor:network-error url=", url, "code=", error?.code);
      return Promise.reject(error);
    }
    if (status === 401) {
      const isAuthProbe =
        url.includes("/auth/me") ||
        url.includes("/auth/login") ||
        url.includes("/auth/register") ||
        url.includes("/uploads/file/"); // <img src=...> auth failures are silent
      // eslint-disable-next-line no-console
      console.debug("[auth] interceptor:401 url=", url, "action=", isAuthProbe ? "ignore" : "redirect");
      if (!isAuthProbe) {
        localStorage.removeItem("gheras_token");
        // eslint-disable-next-line no-console
        console.debug("[auth] token:cleared reason=401-from-app-endpoint");
        if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
          // eslint-disable-next-line no-console
          console.debug("[auth] redirect:login reason=401-from-app-endpoint");
          window.location.assign("/login");
        }
      }
    }
    return Promise.reject(error);
  }
);

/**
 * Build an <img>-friendly URL for backend-served files.
 * Uses ?auth= query param because <img> tags can't send headers.
 */
export function fileSrc(urlOrPath) {
  if (!urlOrPath) return "";
  const token = localStorage.getItem("gheras_token");
  // If it's a full URL already, return as-is
  if (/^https?:\/\//.test(urlOrPath)) return urlOrPath;
  // Ensure leading slash
  const path = urlOrPath.startsWith("/") ? urlOrPath : `/${urlOrPath}`;
  const sep = path.includes("?") ? "&" : "?";
  return `${BACKEND_URL}${path}${sep}auth=${encodeURIComponent(token || "")}`;
}

/** Upload an image and return {id, url}. Throws Error with a clear Arabic message on failure. */
export async function uploadImage(file, scope = "child") {
  const token = localStorage.getItem("gheras_token");
  if (!token) {
    const err = new Error("يرجى تسجيل الدخول أولاً لرفع الصورة");
    err.code = "AUTH_REQUIRED";
    throw err;
  }
  const form = new FormData();
  form.append("file", file);
  form.append("scope", scope);
  const res = await fetch(`${API}/uploads/image`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (res.ok) return res.json();
  // Map backend error detail → user-friendly Arabic message.
  let detail = "";
  try {
    const body = await res.json();
    detail = body?.detail || "";
  } catch { /* non-JSON body */ }
  if (res.status === 401 || res.status === 403) {
    const err = new Error("يرجى تسجيل الدخول أولاً لرفع الصورة");
    err.code = "AUTH_REQUIRED";
    throw err;
  }
  if (res.status === 413 || /كبير|حجم/i.test(detail)) {
    throw new Error(detail || "حجم الصورة كبير جداً (الحد الأقصى 6MB)");
  }
  if (res.status === 415 || /امتداد|نوع/i.test(detail)) {
    throw new Error(detail || "نوع الملف غير مدعوم. استخدم PNG أو JPG أو WEBP.");
  }
  if (res.status === 400) {
    throw new Error(detail || "الصورة غير صالحة");
  }
  throw new Error(detail || "تعذّر رفع الصورة، حاول مرة أخرى");
}
