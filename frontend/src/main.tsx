import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { MeProvider } from "./state";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <MeProvider>
        <App />
      </MeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
