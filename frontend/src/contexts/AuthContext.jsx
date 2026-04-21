import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "../lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("gheras_token");
    // eslint-disable-next-line no-console
    console.debug("[auth] startup: token present?", !!token);
    if (!token) {
      setLoading(false);
      return;
    }
    // Safety timeout — if /auth/me hangs, don't block the app forever.
    const safety = setTimeout(() => {
      // eslint-disable-next-line no-console
      console.debug("[auth] /auth/me safety timeout reached");
      setLoading(false);
    }, 15000);
    api
      .get("/auth/me")
      .then((r) => {
        // eslint-disable-next-line no-console
        console.debug("[auth] session restored for:", r.data?.email);
        setUser(r.data);
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.debug("[auth] /auth/me failed:", err?.response?.status);
        // Only wipe the token when the server explicitly rejects it.
        // For transient network/5xx errors, keep the token so a later retry succeeds.
        if (err?.response?.status === 401 || err?.response?.status === 403) {
          localStorage.removeItem("gheras_token");
        }
      })
      .finally(() => {
        clearTimeout(safety);
        setLoading(false);
      });
    return () => clearTimeout(safety);
  }, []);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    localStorage.setItem("gheras_token", data.access_token);
    setUser(data.user);
    // eslint-disable-next-line no-console
    console.debug("[auth] login success:", data.user?.email);
    return data.user;
  };

  const register = async (payload) => {
    const { data } = await api.post("/auth/register", payload);
    localStorage.setItem("gheras_token", data.access_token);
    setUser(data.user);
    // eslint-disable-next-line no-console
    console.debug("[auth] register success:", data.user?.email);
    return data.user;
  };

  const logout = () => {
    localStorage.removeItem("gheras_token");
    setUser(null);
  };

  const refresh = async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      logout();
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
