import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";

// The flow traces (auth, polling) are for development: in production they
// flooded the console (10k+ lines on one order page) and printed emails.
// localStorage.gheras_debug = "1" turns them back on for a support session.
if (process.env.NODE_ENV === "production") {
  let debug = false;
  try { debug = localStorage.getItem("gheras_debug") === "1"; } catch { /* storage blocked */ }
  if (!debug) console.debug = () => {};
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
