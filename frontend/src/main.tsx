import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import App from "./App";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false
    }
  }
});

const theme = createTheme({
  palette: {
    mode: "light",
    primary: {
      main: "#2563eb",
      dark: "#1d4ed8",
      light: "#dbeafe",
      contrastText: "#ffffff"
    },
    secondary: {
      main: "#0284c7",
      dark: "#0369a1",
      light: "#e0f2fe",
      contrastText: "#ffffff"
    },
    success: {
      main: "#16a34a",
      dark: "#15803d",
      light: "#dcfce7"
    },
    error: {
      main: "#dc2626",
      dark: "#b91c1c",
      light: "#fee2e2"
    },
    warning: {
      main: "#eab308",
      dark: "#ca8a04",
      light: "#fef9c3",
      contrastText: "#1e293b"
    },
    background: {
      default: "#f8fbff",
      paper: "#ffffff"
    },
    text: {
      primary: "#0f172a",
      secondary: "#475569"
    },
    divider: "#bfdbfe",
    action: {
      hover: "#eff6ff",
      selected: "#dbeafe"
    }
  },
  shape: {
    borderRadius: 8
  },
  typography: {
    fontFamily: [
      "Inter",
      "ui-sans-serif",
      "system-ui",
      "-apple-system",
      "BlinkMacSystemFont",
      "Segoe UI",
      "sans-serif"
    ].join(",")
  },
  components: {
    MuiButton: {
      defaultProps: {
        disableElevation: true
      },
      styleOverrides: {
        root: {
          textTransform: "none",
          fontWeight: 700
        }
      }
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          borderColor: "#bfdbfe"
        }
      }
    },
    MuiTableCell: {
      styleOverrides: {
        head: {
          backgroundColor: "#eff6ff",
          color: "#1e3a8a",
          fontWeight: 800
        }
      }
    },
    MuiToggleButton: {
      styleOverrides: {
        root: {
          borderColor: "#bfdbfe",
          "&.Mui-selected": {
            backgroundColor: "#dbeafe",
            color: "#1d4ed8"
          },
          "&.Mui-selected:hover": {
            backgroundColor: "#bfdbfe"
          }
        }
      }
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 700
        }
      }
    }
  }
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <App />
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>
);
