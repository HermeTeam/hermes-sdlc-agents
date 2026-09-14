import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App.tsx";
import { RiskGovernance } from "./RiskGovernance.tsx";
import "./styles.css";

const client = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <App />
      <div className="shell governance-shell">
        <RiskGovernance />
      </div>
    </QueryClientProvider>
  </StrictMode>,
);
