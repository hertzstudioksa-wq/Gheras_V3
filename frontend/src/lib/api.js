import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("gheras_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

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

/** Upload an image and return {id, url}. */
export async function uploadImage(file, scope = "child") {
  const token = localStorage.getItem("gheras_token");
  const form = new FormData();
  form.append("file", file);
  form.append("scope", scope);
  const res = await fetch(`${API}/uploads/image`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "فشل الرفع" }));
    throw new Error(err.detail || "فشل الرفع");
  }
  return res.json();
}
