import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "../lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("gheras_token");
    // eslint-disable-next-line no-console
    console.debug("[auth] token:loaded present=", !!token);
    if (!token) {
      setLoading(false);
      return;
    }
    // Safety timeout — if /auth/me hangs, don't block the app forever.
    const safety = setTimeout(() => {
      // eslint-disable-next-line no-console
      console.debug("[auth] me:failure timeout=true — releasing loading, keeping token");
      setLoading(false);
    }, 15000);
    // eslint-disable-next-line no-console
    console.debug("[auth] me:start");
    api
      .get("/auth/me")
      .then((r) => {
        // eslint-disable-next-line no-console
        console.debug("[auth] me:success email=", r.data?.email, "role=", r.data?.role);
        setUser(r.data);
      })
      .catch((err) => {
        const status = err?.response?.status;
        // eslint-disable-next-line no-console
        console.debug("[auth] me:failure status=", status, "code=", err?.code, "msg=", err?.message);
        // Only wipe the token when the server explicitly rejects it.
        // For transient network/5xx errors, keep the token so a later retry succeeds.
        if (status === 401 || status === 403) {
          localStorage.removeItem("gheras_token");
          // eslint-disable-next-line no-console
          console.debug("[auth] token:cleared reason=me-", status);
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
    // eslint-disable-next-line no-console
    console.debug("[auth] token:saved key=gheras_token");
    setUser(data.user);
    return data.user;
  };

  const register = async (payload) => {
    const { data } = await api.post("/auth/register", payload);
    localStorage.setItem("gheras_token", data.access_token);
    // eslint-disable-next-line no-console
    console.debug("[auth] token:saved key=gheras_token (register)");
    setUser(data.user);
    return data.user;
  };

  const logout = () => {
    localStorage.removeItem("gheras_token");
    // eslint-disable-next-line no-console
    console.debug("[auth] token:cleared reason=logout");
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
