import { useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { createQueryClient } from "./api";
import { routes } from "./router";
import { theme } from "./theme";

export function App() {
  // Created per mount so every test render starts with an empty cache and fresh history state.
  const [queryClient] = useState(createQueryClient);
  const [router] = useState(() => createBrowserRouter(routes));
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
