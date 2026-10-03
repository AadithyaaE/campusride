import "leaflet/dist/leaflet.css";
import "./styles.css";
import "./dashboard.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ApiClient } from "./api/client";
import { App } from "./App";
import { config } from "./config";
import { browserStorage, SessionStore } from "./session/sessionStore";

const storage = browserStorage();
const store = new SessionStore(storage);
const api = new ApiClient({
  baseUrl: config.apiBaseUrl,
  getToken: () => store.get()?.token ?? null,
  onUnauthorized: () => store.clear(),
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App api={api} store={store} />
  </StrictMode>,
);
