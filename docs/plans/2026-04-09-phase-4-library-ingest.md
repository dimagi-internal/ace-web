# Phase 4: Library & Ingest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a design-system foundation (shadcn/ui, dark/light toggle), a basic session library page, and a JSONL ingest system (CLI + endpoint + personal tokens) so the team can find past sessions and import local CLI transcripts.

**Architecture:** Three independent workstreams that share a design-system foundation. The foundation (CSS-variable tokens, shadcn primitives, theme toggle, 22-file refactor) lands first. The library page and ingest system build on the new primitives and can proceed in parallel after the foundation.

**Tech Stack:** Django 5, DRF, pytest, React 19, Vite 5, TypeScript 5, Tailwind 3.4 + CSS variables, shadcn/ui (New York style), lucide-react, class-variance-authority, clsx, tailwind-merge, @radix-ui/react-dialog, @radix-ui/react-dropdown-menu, sonner, httpx, argparse.

**Spec reference:** `docs/specs/2026-04-09-phase-4-library-ingest-design.md`.

---

## File structure (created across all tasks)

```
frontend/
├── index.html                              # MODIFIED: dark class support on <html>
├── tailwind.config.js                      # MODIFIED: darkMode + semantic color tokens
├── package.json                            # MODIFIED: new deps
├── src/
│   ├── styles/globals.css                  # MODIFIED: CSS variable token blocks
│   ├── lib/utils.ts                        # NEW: cn() helper (shadcn)
│   ├── App.tsx                             # MODIFIED: wrap with ThemeProvider + Toaster
│   ├── router.tsx                          # MODIFIED: /library, /settings routes
│   ├── api/
│   │   ├── sessions.ts                     # MODIFIED: listSessions pagination + delete
│   │   ├── tokens.ts                       # NEW: personal token CRUD
│   │   ├── ingest.ts                       # NEW: uploadSession()
│   │   └── types.ts                        # MODIFIED: SessionListPage, PersonalToken types
│   ├── components/
│   │   ├── ui/                             # NEW: ~7 shadcn component files
│   │   │   ├── button.tsx
│   │   │   ├── input.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── dropdown-menu.tsx
│   │   │   ├── skeleton.tsx
│   │   │   └── sonner.tsx
│   │   ├── ThemeProvider.tsx               # NEW: context + localStorage
│   │   ├── ThemeToggle.tsx                 # NEW: sun/moon toggle
│   │   ├── TopNav.tsx                      # NEW: shared top nav bar
│   │   ├── RecentSessionsSidebar.tsx       # MODIFIED: "View all" link
│   │   ├── SendBox.tsx                     # MODIFIED: imported session hint
│   │   ├── CliAuthBanner.tsx               # MODIFIED: tokens refactor
│   │   ├── InlineTitleEdit.tsx             # MODIFIED: tokens refactor
│   │   ├── MessageItem.tsx                 # MODIFIED: tokens refactor
│   │   ├── MessageList.tsx                 # MODIFIED: tokens refactor
│   │   └── opps/ (14 files)               # MODIFIED: tokens refactor
│   └── pages/
│       ├── LibraryPage.tsx                 # NEW
│       ├── SettingsPage.tsx                # NEW: token management
│       ├── ChatPage.tsx                    # MODIFIED: tokens refactor
│       ├── ChatRedirectPage.tsx            # MODIFIED: tokens refactor
│       ├── AuthCliPage.tsx                 # MODIFIED: tokens refactor
│       ├── HomePage.tsx                    # MODIFIED: tokens refactor
│       ├── HealthPage.tsx                  # MODIFIED: tokens refactor
│       ├── OppListPage.tsx                 # MODIFIED: tokens refactor
│       ├── OppWorkbenchPage.tsx            # MODIFIED: tokens refactor
│       └── OppComparePage.tsx              # MODIFIED: tokens refactor

apps/
├── auth/
│   ├── models.py                           # MODIFIED: add PersonalToken
│   ├── token_views.py                      # NEW: CRUD endpoints
│   ├── token_backend.py                    # NEW: BearerTokenAuthBackend
│   ├── urls.py                             # MODIFIED: token routes
│   └── tests/test_tokens.py               # NEW
├── ingest/
│   ├── __init__.py                         # NEW
│   ├── apps.py                             # NEW
│   ├── parser.py                           # NEW: JSONL → Message rows
│   ├── views.py                            # NEW: upload endpoint
│   ├── urls.py                             # NEW
│   ├── tests/__init__.py                   # NEW
│   ├── tests/test_parser.py               # NEW
│   ├── tests/test_views.py                # NEW
│   ├── tests/test_cli.py                  # NEW
│   ├── tests/fixtures/                    # NEW: test JSONL files
│   │   ├── simple_session.jsonl
│   │   ├── tool_use_session.jsonl
│   │   └── multi_turn_session.jsonl
│   └── cli.py                             # NEW: ace-upload entrypoint
├── sessions/
│   ├── views.py                           # MODIFIED: delete, search, pagination
│   └── tests/test_views.py               # MODIFIED: new test cases

config/
├── settings/base.py                       # MODIFIED: INSTALLED_APPS, AUTHENTICATION_BACKENDS
├── urls.py                                # MODIFIED: ingest + token URLs

pyproject.toml                             # MODIFIED: [project.scripts] ace-upload
```

---

## Task 1: shadcn/ui initialization and Tailwind token configuration

**Files:**
- Modify: `frontend/package.json` (new deps)
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/styles/globals.css`
- Create: `frontend/src/lib/utils.ts`
- Create: `frontend/components.json` (shadcn config)

- [ ] **Step 1: Install frontend dependencies**

```bash
cd frontend
bun add lucide-react clsx tailwind-merge class-variance-authority sonner
bun add -d @types/node
```

- [ ] **Step 2: Create the shadcn `components.json` config**

Create `frontend/components.json`:

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.js",
    "css": "src/styles/globals.css",
    "baseColor": "zinc",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 3: Configure path aliases in `tsconfig.json` and `vite.config.ts`**

Update `frontend/tsconfig.json` — add to `compilerOptions`:

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

Update `frontend/vite.config.ts` — add `resolve.alias`:

```typescript
import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
```

- [ ] **Step 4: Create `cn()` utility**

Create `frontend/src/lib/utils.ts`:

```typescript
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 5: Update `tailwind.config.js` with darkMode and semantic tokens**

Replace `frontend/tailwind.config.js`:

```javascript
import { fontFamily } from "tailwindcss/defaultTheme";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", ...fontFamily.sans],
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Status colors for row glyphs (custom extension)
        status: {
          ok: "hsl(var(--status-ok))",
          warn: "hsl(var(--status-warn))",
          error: "hsl(var(--status-error))",
          info: "hsl(var(--status-info))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 6: Write CSS variable token blocks in `globals.css`**

Replace `frontend/src/styles/globals.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 98%;          /* zinc-50 */
    --foreground: 240 10% 3.9%;       /* zinc-950 */
    --card: 0 0% 100%;                /* white */
    --card-foreground: 240 10% 3.9%;
    --popover: 0 0% 100%;
    --popover-foreground: 240 10% 3.9%;
    --primary: 32 95% 44%;            /* amber-700 for light mode contrast */
    --primary-foreground: 0 0% 100%;
    --secondary: 240 4.8% 95.9%;
    --secondary-foreground: 240 5.9% 10%;
    --muted: 240 4.8% 95.9%;          /* zinc-100 */
    --muted-foreground: 240 3.8% 46.1%; /* zinc-500 */
    --accent: 240 4.8% 95.9%;
    --accent-foreground: 240 5.9% 10%;
    --destructive: 0 84.2% 60.2%;     /* red-500 */
    --destructive-foreground: 0 0% 98%;
    --border: 240 5.9% 90%;           /* zinc-200 */
    --input: 240 5.9% 90%;
    --ring: 32 95% 44%;
    --radius: 0.375rem;

    /* Status colors */
    --status-ok: 142 71% 45%;         /* green-500 */
    --status-warn: 32 95% 44%;        /* amber-700 */
    --status-error: 0 84% 60%;        /* red-500 */
    --status-info: 217 91% 60%;       /* blue-500 */
  }

  .dark {
    --background: 240 10% 3.9%;        /* zinc-950 */
    --foreground: 240 5% 96%;          /* zinc-100 */
    --card: 240 6% 10%;                /* zinc-900 */
    --card-foreground: 240 5% 96%;
    --popover: 240 6% 10%;
    --popover-foreground: 240 5% 96%;
    --primary: 36 77% 49%;             /* amber-600 for dark mode */
    --primary-foreground: 0 0% 100%;
    --secondary: 240 4% 16%;           /* zinc-800 */
    --secondary-foreground: 240 5% 96%;
    --muted: 240 4% 16%;
    --muted-foreground: 240 5% 64.9%;  /* zinc-400 */
    --accent: 240 4% 16%;
    --accent-foreground: 240 5% 96%;
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 4% 16%;              /* zinc-800 */
    --input: 240 4% 16%;
    --ring: 36 77% 49%;
    --radius: 0.375rem;

    /* Status colors (dark mode — brighter for contrast) */
    --status-ok: 142 71% 45%;
    --status-warn: 45 93% 47%;
    --status-error: 0 84% 60%;
    --status-info: 217 91% 70%;
  }
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-foreground;
  }
}
```

- [ ] **Step 7: Update `index.html` body class**

Replace in `frontend/index.html`:

```html
<body class="bg-gray-50 text-gray-900">
```

with:

```html
<body class="min-h-screen font-sans antialiased">
```

The body colors now come from the CSS variables via the `@layer base` rule.

- [ ] **Step 8: Verify the app builds**

```bash
cd frontend && bun run build
```

Expected: build succeeds. No errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/
git commit -m "feat: shadcn/ui init — Tailwind tokens, CSS variables, cn() helper"
```

---

## Task 2: Install shadcn UI components

**Files:**
- Create: `frontend/src/components/ui/button.tsx`
- Create: `frontend/src/components/ui/input.tsx`
- Create: `frontend/src/components/ui/badge.tsx`
- Create: `frontend/src/components/ui/dialog.tsx`
- Create: `frontend/src/components/ui/dropdown-menu.tsx`
- Create: `frontend/src/components/ui/skeleton.tsx`
- Create: `frontend/src/components/ui/sonner.tsx`

- [ ] **Step 1: Install Radix primitives needed by shadcn components**

```bash
cd frontend
bun add @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-slot
```

- [ ] **Step 2: Add shadcn components via the CLI**

```bash
cd frontend
npx shadcn@latest add button input badge dialog dropdown-menu skeleton --yes
```

If the `shadcn` CLI does not work with the current project structure (no `src/` alias resolution at CLI time), manually copy each component from the shadcn/ui GitHub repo (`apps/www/registry/new-york/ui/`) into `frontend/src/components/ui/`. Each file uses `@/lib/utils` for `cn()` and Tailwind semantic tokens.

- [ ] **Step 3: Create the Sonner toast wrapper**

Create `frontend/src/components/ui/sonner.tsx`:

```tsx
import { Toaster as SonnerToaster } from "sonner";

import { cn } from "@/lib/utils";

type ToasterProps = React.ComponentProps<typeof SonnerToaster>;

export function Toaster({ className, ...props }: ToasterProps) {
  return (
    <SonnerToaster
      className={cn(className)}
      toastOptions={{
        classNames: {
          toast:
            "group toast bg-card text-card-foreground border-border shadow-lg",
          description: "text-muted-foreground",
          actionButton: "bg-primary text-primary-foreground",
          cancelButton: "bg-muted text-muted-foreground",
        },
      }}
      {...props}
    />
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd frontend && bun run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: add shadcn button, input, badge, dialog, dropdown-menu, skeleton, sonner"
```

---

## Task 3: ThemeProvider and ThemeToggle

**Files:**
- Create: `frontend/src/components/ThemeProvider.tsx`
- Create: `frontend/src/components/ThemeToggle.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create ThemeProvider**

Create `frontend/src/components/ThemeProvider.tsx`:

```tsx
import { createContext, useContext, useEffect, useState } from "react";

type Theme = "dark" | "light" | "system";

interface ThemeProviderState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

const ThemeProviderContext = createContext<ThemeProviderState>({
  theme: "system",
  setTheme: () => null,
});

const STORAGE_KEY = "ace-ui-theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem(STORAGE_KEY) as Theme) || "system",
  );

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");

    if (theme === "system") {
      const systemTheme = window.matchMedia("(prefers-color-scheme: dark)")
        .matches
        ? "dark"
        : "light";
      root.classList.add(systemTheme);
    } else {
      root.classList.add(theme);
    }
  }, [theme]);

  const value = {
    theme,
    setTheme: (t: Theme) => {
      localStorage.setItem(STORAGE_KEY, t);
      setTheme(t);
    },
  };

  return (
    <ThemeProviderContext.Provider value={value}>
      {children}
    </ThemeProviderContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeProviderContext);
```

- [ ] **Step 2: Create ThemeToggle**

Create `frontend/src/components/ThemeToggle.tsx`:

```tsx
import { Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/components/ThemeProvider";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  const toggleTheme = () => {
    if (theme === "dark") {
      setTheme("light");
    } else {
      setTheme("dark");
    }
  };

  return (
    <Button variant="ghost" size="icon" onClick={toggleTheme}>
      <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
      <span className="sr-only">Toggle theme</span>
    </Button>
  );
}
```

- [ ] **Step 3: Wire ThemeProvider and Toaster into App**

Replace `frontend/src/App.tsx`:

```tsx
import { Outlet } from "react-router-dom";

import { ThemeProvider } from "@/components/ThemeProvider";
import { Toaster } from "@/components/ui/sonner";

export function App() {
  return (
    <ThemeProvider>
      <Outlet />
      <Toaster />
    </ThemeProvider>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd frontend && bun run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: ThemeProvider + ThemeToggle with dark/light/system support"
```

---

## Task 4: Create shared TopNav component

**Files:**
- Create: `frontend/src/components/TopNav.tsx`
- Modify: `frontend/src/pages/OppListPage.tsx` (extract header into TopNav)
- Modify: `frontend/src/pages/ChatPage.tsx` (add TopNav)
- Modify: `frontend/src/pages/HomePage.tsx` (add TopNav)

- [ ] **Step 1: Create TopNav**

Create `frontend/src/components/TopNav.tsx`:

```tsx
import { Link, useLocation } from "react-router-dom";

import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV_ITEMS = [
  { label: "Library", path: "/library" },
  { label: "Chat", path: "/chat" },
  { label: "Opps", path: "/opps" },
];

export function TopNav() {
  const { pathname } = useLocation();

  return (
    <nav className="flex items-center gap-6 border-b border-border bg-card px-4 py-2 text-sm">
      <Link to="/" className="font-semibold text-foreground">
        ACE
      </Link>
      <div className="flex items-center gap-4">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                "text-muted-foreground hover:text-foreground",
                isActive && "text-foreground font-medium",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
      <div className="ml-auto">
        <ThemeToggle />
      </div>
    </nav>
  );
}
```

- [ ] **Step 2: Add TopNav to the App layout**

Update `frontend/src/App.tsx`:

```tsx
import { Outlet } from "react-router-dom";

import { ThemeProvider } from "@/components/ThemeProvider";
import { TopNav } from "@/components/TopNav";
import { Toaster } from "@/components/ui/sonner";

export function App() {
  return (
    <ThemeProvider>
      <div className="flex h-screen flex-col">
        <TopNav />
        <div className="flex-1 overflow-hidden">
          <Outlet />
        </div>
      </div>
      <Toaster />
    </ThemeProvider>
  );
}
```

- [ ] **Step 3: Remove duplicate headers from OppListPage**

In `frontend/src/pages/OppListPage.tsx`, the top-level header row (`<header className="flex items-center gap-4 border-b ...">`) should be kept for the page-specific controls (title + count + filter input) but should no longer act as the app-level nav. Remove any "ACE Opportunities" title since the TopNav now handles navigation context. Adjust to use semantic tokens:

```tsx
<header className="flex items-center gap-4 border-b border-border px-6 py-4">
  <h1 className="text-xl font-semibold text-foreground">Opportunities</h1>
  <span className="text-sm text-muted-foreground">{state.opps.length} total</span>
  <input
    type="text"
    placeholder="Filter by slug, name, or label…"
    value={filter}
    onChange={(e) => setFilter(e.target.value)}
    className="ml-auto w-64 rounded border border-input bg-card px-3 py-1 text-sm text-foreground placeholder-muted-foreground focus:border-ring focus:outline-none"
  />
</header>
```

- [ ] **Step 4: Verify build and visual check**

```bash
cd frontend && bun run build
```

Expected: build succeeds. Run `bun run dev` and verify TopNav renders on all pages with working links and theme toggle.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: shared TopNav with Library/Chat/Opps links and theme toggle"
```

---

## Task 5: Refactor existing files to semantic tokens

**Files:**
- Modify: all 22 files listed in the spec §3.4 token mapping table
- Modify: `frontend/index.html`

This is a mechanical refactor. The mapping is:

| Old | New |
|---|---|
| `bg-zinc-950` | `bg-background` |
| `bg-zinc-900` | `bg-card` |
| `bg-zinc-800` | `bg-muted` or `bg-secondary` |
| `bg-white` | `bg-card` |
| `text-zinc-100`, `text-zinc-200` | `text-foreground` |
| `text-zinc-300`, `text-zinc-400` | `text-muted-foreground` |
| `text-zinc-500`, `text-zinc-600` | `text-muted-foreground` |
| `border-zinc-800`, `border-zinc-200`, `border-zinc-700` | `border-border` |
| `bg-amber-600` | `bg-primary` |
| `hover:bg-amber-700` | `hover:bg-primary/90` |
| `border-amber-600` | `border-primary` |
| `bg-amber-950/40` | `bg-primary/10` |
| `text-amber-400` | `text-primary` |
| `bg-blue-600` | `bg-primary` (in non-Workbench context) or keep as explicit blue |
| `hover:bg-blue-700` | `hover:bg-primary/90` |
| `bg-blue-100 text-blue-900` | `bg-accent text-accent-foreground` |
| `text-blue-600` | `text-primary` |
| `placeholder-zinc-500`, `placeholder-zinc-600` | `placeholder:text-muted-foreground` |
| `focus:border-blue-500` | `focus:border-ring` |

**Status-color classes stay explicit** — `text-green-500`, `text-red-500`, `bg-green-900`, `bg-red-900`, etc. used in `SkillRow`, `StatusBadge`, `JudgeBar`, `GateBadge` stay as-is because they are semantic (pass/fail/warning) and the same in both themes. They use the `text-status-ok`, `text-status-error`, `text-status-warn`, `text-status-info` tokens only where it reads more clearly.

- [ ] **Step 1: Refactor chat-related components (5 files)**

Refactor these files using the mapping above:
- `frontend/src/pages/ChatPage.tsx`
- `frontend/src/pages/ChatRedirectPage.tsx`
- `frontend/src/components/RecentSessionsSidebar.tsx`
- `frontend/src/components/MessageItem.tsx`
- `frontend/src/components/MessageList.tsx`

For `ChatPage.tsx`, the key change is:
```tsx
// Before
<div className="flex h-screen">
// After
<div className="flex h-full">
```
(The TopNav now owns the top chrome; ChatPage fills the remaining space.)

For `RecentSessionsSidebar.tsx`, add the "View all" footer:
```tsx
<Link
  to="/library"
  className="block border-t border-border px-3 py-2 text-center text-xs text-muted-foreground hover:text-foreground"
>
  View all sessions →
</Link>
```

- [ ] **Step 2: Refactor auth-related components (2 files)**

- `frontend/src/pages/AuthCliPage.tsx`
- `frontend/src/components/CliAuthBanner.tsx`

- [ ] **Step 3: Refactor opps components (14 files)**

All files in `frontend/src/components/opps/` and `frontend/src/pages/Opp*.tsx`:
- `OppListPage.tsx`, `OppWorkbenchPage.tsx`, `OppComparePage.tsx`
- `ArtifactPreview.tsx`, `CompareTable.tsx`, `DiscussInChatButton.tsx`, `DriveReconnectGuard.tsx`, `GateHistory.tsx`, `JudgeVerdict.tsx`, `LinkedChats.tsx`, `LoadingStates.tsx`, `OppSidebar.tsx`, `RunSwitcher.tsx`, `SkillList.tsx`, `SkillRow.tsx`, `StepDetailPane.tsx`, `WorkbenchHeader.tsx`

For `OppWorkbenchPage.tsx`, the outer div changes:
```tsx
// Before
<div className="flex h-full flex-col bg-zinc-950 text-zinc-100">
// After
<div className="flex h-full flex-col bg-background text-foreground">
```

Same pattern for all opps files. Status-color classes (`text-green-500`, `bg-red-900 text-red-300`, etc.) stay explicit.

- [ ] **Step 4: Refactor remaining pages (3 files)**

- `frontend/src/pages/HomePage.tsx`
- `frontend/src/pages/HealthPage.tsx`
- `frontend/src/components/InlineTitleEdit.tsx`

- [ ] **Step 5: Verify build**

```bash
cd frontend && bun run build
```

Expected: build succeeds with no errors.

- [ ] **Step 6: Manual visual walkthrough**

Run `bun run dev` and check every page in both light and dark mode (use the ThemeToggle):
- `/` (HomePage)
- `/chat` (ChatRedirectPage → ChatPage)
- `/auth/cli` (AuthCliPage)
- `/opps` (OppListPage)
- `/opps/<any-slug>` (OppWorkbenchPage)
- `/health` (HealthPage)

Confirm: no hardcoded white-on-dark or dark-on-white text. Borders visible in both themes. Primary accent (amber) consistent. Status colors readable in both themes.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "refactor: migrate all 22 frontend files from hardcoded zinc to semantic tokens

Enables dark/light theme switching across the entire app."
```

---

## Task 6: Library backend — search, pagination, delete

**Files:**
- Modify: `apps/sessions/views.py`
- Modify: `apps/sessions/urls.py`
- Modify: `apps/sessions/serializers.py`
- Test: `apps/sessions/tests/test_views.py`

- [ ] **Step 1: Write tests for title search**

Add to `apps/sessions/tests/test_views.py`:

```python
def test_list_sessions_search_by_title(client, user):
    Session.objects.create(owner=user, title="Phase 4 library design")
    Session.objects.create(owner=user, title="CLI debugging session")
    Session.objects.create(owner=user, title="Another Phase 4 chat")

    resp = client.get("/api/sessions?q=phase+4")
    body = resp.json()["data"]
    assert body["total"] == 2
    titles = [s["title"] for s in body["items"]]
    assert "Phase 4 library design" in titles
    assert "Another Phase 4 chat" in titles
    assert "CLI debugging session" not in titles


def test_list_sessions_search_is_case_insensitive(client, user):
    Session.objects.create(owner=user, title="UPPERCASE Title")

    resp = client.get("/api/sessions?q=uppercase")
    assert resp.json()["data"]["total"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest apps/sessions/tests/test_views.py::test_list_sessions_search_by_title -v
pytest apps/sessions/tests/test_views.py::test_list_sessions_search_is_case_insensitive -v
```

Expected: FAIL — response shape is a list, not `{items, total}`.

- [ ] **Step 3: Write tests for source filter and pagination**

Add to `apps/sessions/tests/test_views.py`:

```python
def test_list_sessions_filter_by_source(client, user):
    Session.objects.create(owner=user, title="web1", source="web")
    Session.objects.create(owner=user, title="upload1", source="upload")

    resp = client.get("/api/sessions?source=upload")
    body = resp.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["title"] == "upload1"


def test_list_sessions_pagination(client, user):
    for i in range(25):
        Session.objects.create(owner=user, title=f"s{i:02d}")

    resp = client.get("/api/sessions?page=2&page_size=10")
    body = resp.json()["data"]
    assert body["total"] == 25
    assert body["page"] == 2
    assert body["page_size"] == 10
    assert len(body["items"]) == 10


def test_list_sessions_pagination_last_page(client, user):
    for i in range(25):
        Session.objects.create(owner=user, title=f"s{i:02d}")

    resp = client.get("/api/sessions?page=3&page_size=10")
    body = resp.json()["data"]
    assert len(body["items"]) == 5


def test_list_sessions_pagination_defaults(client, user):
    Session.objects.create(owner=user, title="x")

    resp = client.get("/api/sessions")
    body = resp.json()["data"]
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 1
    assert len(body["items"]) == 1
```

- [ ] **Step 4: Write tests for session deletion**

Add to `apps/sessions/tests/test_views.py`:

```python
def test_delete_session_by_owner(client, user):
    s = Session.objects.create(owner=user, title="to delete")
    resp = client.delete(f"/api/sessions/{s.slug}")
    assert resp.status_code == 204
    assert not Session.objects.filter(slug=s.slug).exists()


def test_delete_session_cascades_messages(client, user):
    s = Session.objects.create(owner=user, title="has msgs")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    client.delete(f"/api/sessions/{s.slug}")
    assert Message.objects.count() == 0


def test_delete_session_403_for_non_owner(client, user, other_user):
    s = Session.objects.create(owner=other_user, title="not mine")
    resp = client.delete(f"/api/sessions/{s.slug}")
    assert resp.status_code == 404  # owner-scoped query returns 404
    assert Session.objects.filter(slug=s.slug).exists()


def test_delete_session_404_for_missing(client):
    resp = client.delete("/api/sessions/no-such-slug")
    assert resp.status_code == 404
```

- [ ] **Step 5: Run all new tests to confirm they fail**

```bash
pytest apps/sessions/tests/test_views.py -v -k "search or source or pagination or delete"
```

Expected: all FAIL.

- [ ] **Step 6: Implement the updated `_list_sessions` and new `_delete_session`**

Replace `_list_sessions` in `apps/sessions/views.py`:

```python
def _list_sessions(request: Request) -> Response:
    qs = Session.objects.filter(owner=request.user)

    # Filters
    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)

    source_filter = request.query_params.get("source")
    if source_filter:
        qs = qs.filter(source=source_filter)

    q = request.query_params.get("q", "").strip()
    if q:
        qs = qs.filter(title__icontains=q)

    # Pagination
    total = qs.count()
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(100, int(request.query_params.get("page_size", "20"))))
    except ValueError:
        page_size = 20

    offset = (page - 1) * page_size
    qs = qs.order_by("-updated_at")[offset : offset + page_size]

    return Response(
        success_response({
            "items": SessionSerializer(qs, many=True).data,
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    )
```

Add `_delete_session` and update the `session_detail` view to handle DELETE:

```python
@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def session_detail(request: Request, slug: str) -> Response:
    try:
        session = Session.objects.get(slug=slug, owner=request.user)
    except Session.DoesNotExist:
        return Response(
            error_response(message="session not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == "GET":
        return Response(success_response(SessionDetailSerializer(session).data))

    if request.method == "DELETE":
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH
    allowed = {"title", "status"}
    updates = {k: v for k, v in (request.data or {}).items() if k in allowed}
    if "status" in updates and updates["status"] not in {"active", "archived"}:
        return Response(
            error_response(message="invalid status", code="validation_error"),
            status=400,
        )
    for k, v in updates.items():
        setattr(session, k, v)
    if updates:
        session.save(update_fields=list(updates.keys()) + ["updated_at"])
    return Response(success_response(SessionSerializer(session).data))
```

- [ ] **Step 7: Update existing tests for new response shape**

The `_list_sessions` response shape changed from `{data: [...]}` to `{data: {items: [...], total, page, page_size}}`. Update existing tests:

In `test_list_sessions_only_returns_current_user`:
```python
titles = [s["title"] for s in resp.json()["data"]["items"]]
```

In `test_list_sessions_filters_by_status`:
```python
titles = [s["title"] for s in resp.json()["data"]["items"]]
```

In `test_list_sessions_respects_limit`:
```python
resp = client.get("/api/sessions?page_size=5")
assert len(resp.json()["data"]["items"]) == 5
```

- [ ] **Step 8: Run all session view tests**

```bash
pytest apps/sessions/tests/test_views.py -v
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/sessions/
git commit -m "feat: session list search, source filter, pagination, and DELETE endpoint"
```

---

## Task 7: Library frontend page

**Files:**
- Create: `frontend/src/pages/LibraryPage.tsx`
- Modify: `frontend/src/api/sessions.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/router.tsx`

- [ ] **Step 1: Add types for paginated session list**

Add to `frontend/src/api/types.ts`:

```typescript
export interface SessionListPage {
  items: Session[];
  total: number;
  page: number;
  page_size: number;
}
```

- [ ] **Step 2: Update session API functions**

Replace `frontend/src/api/sessions.ts`:

```typescript
import { apiFetch } from "./client";
import type { Session, SessionDetail, SessionListPage } from "./types";

export interface ListSessionsParams {
  q?: string;
  status?: string;
  source?: string;
  page?: number;
  pageSize?: number;
}

export const listSessions = (params: ListSessionsParams = {}) => {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.status) qs.set("status", params.status);
  if (params.source) qs.set("source", params.source);
  if (params.page) qs.set("page", String(params.page));
  if (params.pageSize) qs.set("page_size", String(params.pageSize));
  return apiFetch<SessionListPage>(`/api/sessions?${qs}`);
};

export const createSession = () =>
  apiFetch<Session>("/api/sessions", { method: "POST", body: "{}" });

export const getSession = (slug: string) =>
  apiFetch<SessionDetail>(`/api/sessions/${slug}`);

export const updateSession = (slug: string, updates: Partial<Session>) =>
  apiFetch<Session>(`/api/sessions/${slug}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });

export const deleteSession = async (slug: string): Promise<void> => {
  // DELETE returns 204 with no body — can't use apiFetch which expects JSON
  const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const resp = await fetch(`${API_PREFIX}/api/sessions/${slug}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!resp.ok) {
    throw new Error(`Delete failed: ${resp.status}`);
  }
};
```

- [ ] **Step 3: Update `useRecentSessions` hook to use new API signature and response shape**

Replace `frontend/src/hooks/useRecentSessions.ts`:

```typescript
import { useCallback, useEffect, useState } from "react";

import { listSessions } from "../api/sessions";
import type { Session } from "../api/types";

export function useRecentSessions(limit = 10) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const data = await listSessions({ pageSize: limit, status: "active" });
    setSessions(data.items);
    setLoading(false);
  }, [limit]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { sessions, loading, refresh };
}
```

- [ ] **Step 4: Create LibraryPage**

Create `frontend/src/pages/LibraryPage.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Archive, ArchiveRestore, MoreHorizontal, Pencil, Plus, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  createSession,
  deleteSession,
  listSessions,
  updateSession,
  type ListSessionsParams,
} from "@/api/sessions";
import type { Session, SessionListPage } from "@/api/types";

type StatusFilter = "active" | "archived" | "imported" | "";

const STATUS_FILTERS: { label: string; value: StatusFilter }[] = [
  { label: "Active", value: "active" },
  { label: "Archived", value: "archived" },
  { label: "Imported", value: "imported" },
  { label: "All", value: "" },
];

export default function LibraryPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<SessionListPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const params: ListSessionsParams = { page, pageSize: 20 };
    if (query.trim()) params.q = query.trim();
    if (statusFilter) params.status = statusFilter;
    listSessions(params)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((err) => {
        setError(String(err?.message ?? err));
        setLoading(false);
      });
  }, [query, statusFilter, page]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  const handleNewChat = async () => {
    const s = await createSession();
    navigate(`/chat/${s.slug}`);
  };

  const handleArchiveToggle = async (s: Session) => {
    const newStatus = s.status === "archived" ? "active" : "archived";
    await updateSession(s.slug, { status: newStatus } as Partial<Session>);
    toast.success(newStatus === "archived" ? "Session archived" : "Session restored");
    load();
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    await deleteSession(deleteTarget.slug);
    toast.success("Session deleted");
    setDeleteTarget(null);
    load();
  };

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      {/* Header */}
      <header className="flex items-center gap-4 border-b border-border px-6 py-3">
        <h1 className="text-lg font-semibold">Library</h1>
        {data && (
          <span className="text-sm text-muted-foreground">
            · {data.total} sessions
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Input
            placeholder="Search titles…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            className="w-56"
          />
          <Button variant="outline" size="sm" asChild>
            <Link to="/settings">
              <Upload className="mr-1.5 h-3.5 w-3.5" />
              Upload
            </Link>
          </Button>
          <Button size="sm" onClick={handleNewChat}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            New chat
          </Button>
        </div>
      </header>

      {/* Filters */}
      <div className="flex items-center gap-1 border-b border-border px-6 py-2">
        {STATUS_FILTERS.map((f) => (
          <Button
            key={f.value}
            variant={statusFilter === f.value ? "default" : "ghost"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => {
              setStatusFilter(f.value);
              setPage(1);
            }}
          >
            {f.label}
          </Button>
        ))}
      </div>

      {/* List */}
      <main className="flex-1 overflow-y-auto">
        {loading && (
          <div className="space-y-2 p-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}

        {error && (
          <div className="p-6 text-center">
            <p className="text-destructive">{error}</p>
            <Button variant="outline" size="sm" className="mt-2" onClick={load}>
              Retry
            </Button>
          </div>
        )}

        {!loading && !error && data && data.items.length === 0 && (
          <div className="p-12 text-center">
            <p className="text-muted-foreground">
              {query ? "No sessions match your search." : "No sessions yet — start a chat."}
            </p>
          </div>
        )}

        {!loading && !error && data && data.items.length > 0 && (
          <div className="divide-y divide-border">
            {data.items.map((s) => (
              <div
                key={s.slug}
                className="group flex items-center gap-3 px-6 py-2.5 hover:bg-muted/50"
              >
                <Link
                  to={`/chat/${s.slug}`}
                  className="flex min-w-0 flex-1 items-center gap-3"
                >
                  <span className="truncate font-medium text-foreground">
                    {s.title || "Untitled"}
                  </span>
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    {s.source}
                  </Badge>
                  {s.status === "archived" && (
                    <Badge variant="secondary" className="shrink-0 text-[10px]">
                      archived
                    </Badge>
                  )}
                </Link>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {new Date(s.updated_at).toLocaleDateString()}
                </span>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 opacity-0 group-hover:opacity-100"
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem asChild>
                      <Link to={`/chat/${s.slug}`}>Open</Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => handleArchiveToggle(s)}
                    >
                      {s.status === "archived" ? (
                        <>
                          <ArchiveRestore className="mr-2 h-4 w-4" />
                          Restore
                        </>
                      ) : (
                        <>
                          <Archive className="mr-2 h-4 w-4" />
                          Archive
                        </>
                      )}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className="text-destructive"
                      onClick={() => setDeleteTarget(s)}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Pagination */}
      {data && totalPages > 1 && (
        <footer className="flex items-center justify-between border-t border-border px-6 py-2 text-xs text-muted-foreground">
          <span>
            Page {data.page} of {totalPages} · {data.total} sessions
          </span>
          <div className="flex gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-7"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              ← Prev
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next →
            </Button>
          </div>
        </footer>
      )}

      {/* Delete confirmation dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete session?</DialogTitle>
            <DialogDescription>
              This will permanently delete &ldquo;{deleteTarget?.title || "Untitled"}&rdquo;
              and all its messages. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 5: Add routes**

In `frontend/src/router.tsx`, add the import and route:

```tsx
import LibraryPage from "./pages/LibraryPage";

// In the children array, add:
{ path: "library", element: <LibraryPage /> },
```

- [ ] **Step 6: Verify build**

```bash
cd frontend && bun run build
```

Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat: basic library page with search, filters, pagination, delete"
```

---

## Task 8: PersonalToken model and migration

**Files:**
- Modify: `apps/auth/models.py`
- Create: `apps/auth/migrations/0003_personaltoken.py` (auto-generated)

- [ ] **Step 1: Write tests for PersonalToken model**

Create `apps/auth/tests/test_tokens.py`:

```python
import hashlib

import pytest

from apps.auth.models import PersonalToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )


def test_create_token_returns_raw(user):
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    assert raw.startswith("")  # any non-empty string
    assert len(raw) >= 32
    assert token.pk is not None
    assert token.user == user
    assert token.label == "test"
    assert token.revoked_at is None


def test_raw_token_is_not_stored(user):
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    # The stored token_hash should be the sha256 of the raw token
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()
    assert token.token_hash == expected_hash


def test_lookup_by_raw_token(user):
    raw, created = PersonalToken.create_for_user(user=user, label="test")
    found = PersonalToken.lookup(raw)
    assert found is not None
    assert found.pk == created.pk


def test_lookup_returns_none_for_bad_token(user):
    PersonalToken.create_for_user(user=user, label="test")
    assert PersonalToken.lookup("bad-token-value") is None


def test_lookup_returns_none_for_revoked(user):
    from django.utils import timezone
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    token.revoked_at = timezone.now()
    token.save()
    assert PersonalToken.lookup(raw) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest apps/auth/tests/test_tokens.py -v
```

Expected: FAIL — `PersonalToken` does not exist.

- [ ] **Step 3: Implement PersonalToken model**

Add to `apps/auth/models.py`:

```python
import hashlib
import secrets


class PersonalToken(models.Model):
    """Long-lived bearer token for CLI tools (e.g., ace-upload).

    The raw token is shown once at creation. Only the sha256 hash is stored.
    """

    user = models.ForeignKey(
        "ace_auth.User", on_delete=models.CASCADE, related_name="personal_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_tokens"

    def __str__(self):
        return f"Token {self.label!r} for {self.user_id}"

    @classmethod
    def create_for_user(cls, *, user, label: str) -> tuple[str, "PersonalToken"]:
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        token = cls.objects.create(user=user, token_hash=token_hash, label=label)
        return raw, token

    @classmethod
    def lookup(cls, raw: str) -> "PersonalToken | None":
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        try:
            token = cls.objects.select_related("user").get(
                token_hash=token_hash, revoked_at__isnull=True
            )
            return token
        except cls.DoesNotExist:
            return None
```

- [ ] **Step 4: Create and run migration**

```bash
python manage.py makemigrations ace_auth --name personaltoken
pytest apps/auth/tests/test_tokens.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/auth/
git commit -m "feat: PersonalToken model with hashed storage and lookup"
```

---

## Task 9: Personal token API endpoints

**Files:**
- Create: `apps/auth/token_views.py`
- Modify: `apps/auth/urls.py`
- Modify: `config/urls.py` (if needed)
- Test: `apps/auth/tests/test_tokens.py`

- [ ] **Step 1: Write endpoint tests**

Add to `apps/auth/tests/test_tokens.py`:

```python
from rest_framework.test import APIClient


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_create_token_endpoint(client):
    resp = client.post(
        "/api/auth/tokens", {"label": "my laptop"}, format="json"
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "raw_token" in body
    assert body["label"] == "my laptop"
    assert len(body["raw_token"]) >= 32


def test_list_tokens_endpoint(client, user):
    PersonalToken.create_for_user(user=user, label="token1")
    PersonalToken.create_for_user(user=user, label="token2")

    resp = client.get("/api/auth/tokens")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 2
    # Raw token must NOT be in the list response
    for item in items:
        assert "raw_token" not in item
        assert "token_hash" not in item
        assert "label" in item


def test_delete_token_endpoint(client, user):
    _, token = PersonalToken.create_for_user(user=user, label="to delete")

    resp = client.delete(f"/api/auth/tokens/{token.pk}")
    assert resp.status_code == 204

    token.refresh_from_db()
    assert token.revoked_at is not None


def test_delete_token_404_for_other_user(client, django_user_model):
    other = django_user_model.objects.create_user(
        email="other@example.com", display_name="other"
    )
    _, token = PersonalToken.create_for_user(user=other, label="theirs")

    resp = client.delete(f"/api/auth/tokens/{token.pk}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest apps/auth/tests/test_tokens.py -v -k "endpoint"
```

Expected: FAIL — 404 (no URL route).

- [ ] **Step 3: Implement token views**

Create `apps/auth/token_views.py`:

```python
"""REST endpoints for personal token management."""
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response

from .models import PersonalToken


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def token_collection(request: Request) -> Response:
    if request.method == "POST":
        return _create_token(request)
    return _list_tokens(request)


def _create_token(request: Request) -> Response:
    label = (request.data or {}).get("label", "").strip()
    if not label:
        return Response(
            error_response(message="label is required", code="validation_error"),
            status=400,
        )
    raw, token = PersonalToken.create_for_user(user=request.user, label=label)
    return Response(
        success_response({
            "id": token.pk,
            "label": token.label,
            "raw_token": raw,
            "created_at": token.created_at.isoformat(),
        }),
        status=status.HTTP_201_CREATED,
    )


def _list_tokens(request: Request) -> Response:
    tokens = PersonalToken.objects.filter(
        user=request.user, revoked_at__isnull=True
    ).order_by("-created_at")
    items = [
        {
            "id": t.pk,
            "label": t.label,
            "created_at": t.created_at.isoformat(),
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in tokens
    ]
    return Response(success_response(items))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def token_detail(request: Request, pk: int) -> Response:
    try:
        token = PersonalToken.objects.get(
            pk=pk, user=request.user, revoked_at__isnull=True
        )
    except PersonalToken.DoesNotExist:
        return Response(
            error_response(message="token not found", code="not_found"),
            status=404,
        )
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
    return Response(status=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Wire URLs**

Add to `apps/auth/urls.py`:

```python
from . import token_views

# Add to urlpatterns:
path("api/auth/tokens", token_views.token_collection, name="token_collection"),
path("api/auth/tokens/<int:pk>", token_views.token_detail, name="token_detail"),
```

- [ ] **Step 5: Run tests**

```bash
pytest apps/auth/tests/test_tokens.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/auth/
git commit -m "feat: personal token CRUD endpoints (create/list/revoke)"
```

---

## Task 10: BearerTokenAuthBackend

**Files:**
- Create: `apps/auth/token_backend.py`
- Modify: `config/settings/base.py`
- Test: `apps/auth/tests/test_tokens.py`

- [ ] **Step 1: Write tests for bearer auth**

Add to `apps/auth/tests/test_tokens.py`:

```python
def test_bearer_auth_resolves_user(user):
    raw, _ = PersonalToken.create_for_user(user=user, label="test")
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    resp = c.get("/api/sessions")
    assert resp.status_code == 200


def test_bearer_auth_rejects_revoked(user):
    from django.utils import timezone
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    token.revoked_at = timezone.now()
    token.save()
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    resp = c.get("/api/sessions")
    assert resp.status_code == 403


def test_bearer_auth_rejects_bad_token():
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer bad-token-value")
    resp = c.get("/api/sessions")
    assert resp.status_code == 403


def test_bearer_auth_updates_last_used(user):
    raw, token = PersonalToken.create_for_user(user=user, label="test")
    assert token.last_used_at is None
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    c.get("/api/sessions")
    token.refresh_from_db()
    assert token.last_used_at is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest apps/auth/tests/test_tokens.py -v -k "bearer"
```

Expected: FAIL — 403 (no bearer backend configured).

- [ ] **Step 3: Implement BearerTokenAuthBackend**

Create `apps/auth/token_backend.py`:

```python
"""DRF authentication backend for personal bearer tokens."""
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import PersonalToken


class BearerTokenAuthentication(BaseAuthentication):
    """Authenticate via `Authorization: Bearer <token>`.

    Only runs when no session cookie is present (session auth takes precedence
    in the DRF DEFAULT_AUTHENTICATION_CLASSES ordering).
    """

    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(f"{self.keyword} "):
            return None

        raw = auth_header[len(self.keyword) + 1 :]
        token = PersonalToken.lookup(raw)
        if token is None:
            raise AuthenticationFailed("Invalid or revoked token.")

        # Update last_used_at (fire-and-forget, no transaction needed)
        PersonalToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())

        return (token.user, token)
```

- [ ] **Step 4: Register in DRF settings**

Add to `config/settings/base.py`:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "apps.auth.token_backend.BearerTokenAuthentication",
    ],
}
```

- [ ] **Step 5: Run tests**

```bash
pytest apps/auth/tests/test_tokens.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/auth/ config/settings/base.py
git commit -m "feat: BearerTokenAuthentication backend for CLI/API access"
```

---

## Task 11: Settings page (token management UI)

**Files:**
- Create: `frontend/src/api/tokens.ts`
- Create: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/router.tsx`

- [ ] **Step 1: Add types and API functions**

Add to `frontend/src/api/types.ts`:

```typescript
export interface PersonalToken {
  id: number;
  label: string;
  created_at: string;
  last_used_at: string | null;
}

export interface PersonalTokenCreated extends PersonalToken {
  raw_token: string;
}
```

Create `frontend/src/api/tokens.ts`:

```typescript
import { apiFetch } from "./client";
import type { PersonalToken, PersonalTokenCreated } from "./types";

export const listTokens = () =>
  apiFetch<PersonalToken[]>("/api/auth/tokens");

export const createToken = (label: string) =>
  apiFetch<PersonalTokenCreated>("/api/auth/tokens", {
    method: "POST",
    body: JSON.stringify({ label }),
  });

export const revokeToken = (id: number) =>
  apiFetch<void>(`/api/auth/tokens/${id}`, { method: "DELETE" });
```

- [ ] **Step 2: Create SettingsPage**

Create `frontend/src/pages/SettingsPage.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { Copy, Key, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { createToken, listTokens, revokeToken } from "@/api/tokens";
import type { PersonalToken } from "@/api/types";

export default function SettingsPage() {
  const [tokens, setTokens] = useState<PersonalToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const [rawToken, setRawToken] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    listTokens()
      .then(setTokens)
      .catch(() => toast.error("Failed to load tokens"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const handleCreate = async () => {
    if (!newLabel.trim()) return;
    const result = await createToken(newLabel.trim());
    setRawToken(result.raw_token);
    setNewLabel("");
    load();
  };

  const handleRevoke = async (id: number) => {
    await revokeToken(id);
    toast.success("Token revoked");
    load();
  };

  const handleCopy = () => {
    if (rawToken) {
      navigator.clipboard.writeText(rawToken);
      toast.success("Copied to clipboard");
    }
  };

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="flex items-center gap-4 border-b border-border px-6 py-3">
        <h1 className="text-lg font-semibold">Settings</h1>
      </header>

      <main className="flex-1 overflow-y-auto p-6">
        <section className="max-w-2xl">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold">Upload tokens</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Personal tokens for the <code>ace-upload</code> CLI.
                Paste into <code>~/.ace/config.toml</code>.
              </p>
            </div>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              Create token
            </Button>
          </div>

          {loading && (
            <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
          )}

          {!loading && tokens.length === 0 && (
            <p className="mt-4 text-sm text-muted-foreground">
              No tokens yet.
            </p>
          )}

          {!loading && tokens.length > 0 && (
            <div className="mt-4 divide-y divide-border rounded border border-border">
              {tokens.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between px-4 py-3"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <Key className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium">{t.label}</span>
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      Created {new Date(t.created_at).toLocaleDateString()}
                      {t.last_used_at &&
                        ` · Last used ${new Date(t.last_used_at).toLocaleDateString()}`}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive"
                    onClick={() => handleRevoke(t.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>

      {/* Create token dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create upload token</DialogTitle>
            <DialogDescription>
              Give this token a label (e.g., &ldquo;laptop&rdquo;).
            </DialogDescription>
          </DialogHeader>
          <Input
            placeholder="Token label"
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={!newLabel.trim()}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Show raw token once */}
      <Dialog open={!!rawToken} onOpenChange={() => setRawToken(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Token created</DialogTitle>
            <DialogDescription>
              Copy this token now — it won&apos;t be shown again.
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-muted px-3 py-2 text-sm">
              {rawToken}
            </code>
            <Button variant="outline" size="icon" onClick={handleCopy}>
              <Copy className="h-4 w-4" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setRawToken(null)}>
              I&apos;ve saved this
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 3: Add route**

In `frontend/src/router.tsx`:

```tsx
import SettingsPage from "./pages/SettingsPage";

// In the children array:
{ path: "settings", element: <SettingsPage /> },
```

- [ ] **Step 4: Verify build**

```bash
cd frontend && bun run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: settings page with personal token management"
```

---

## Task 12: Ingest JSONL parser

**Files:**
- Create: `apps/ingest/__init__.py`
- Create: `apps/ingest/apps.py`
- Create: `apps/ingest/parser.py`
- Create: `apps/ingest/tests/__init__.py`
- Create: `apps/ingest/tests/test_parser.py`
- Create: `apps/ingest/tests/fixtures/simple_session.jsonl`
- Create: `apps/ingest/tests/fixtures/tool_use_session.jsonl`
- Create: `apps/ingest/tests/fixtures/multi_turn_session.jsonl`

- [ ] **Step 1: Create the ingest app boilerplate**

Create `apps/ingest/__init__.py` (empty).

Create `apps/ingest/apps.py`:

```python
from django.apps import AppConfig


class IngestConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ingest"
    label = "ingest"
```

Create `apps/ingest/tests/__init__.py` (empty).

- [ ] **Step 2: Register the app**

Add to `INSTALLED_APPS` in `config/settings/base.py`:

```python
"apps.ingest.apps.IngestConfig",
```

- [ ] **Step 3: Create test fixtures**

Create `apps/ingest/tests/fixtures/simple_session.jsonl`:

```
{"type":"system","subtype":"init","session_id":"sess_simple_001","cwd":"/tmp","tools":[]}
{"type":"assistant","message":{"id":"msg_01","content":[{"type":"text","text":"Hello, "}]}}
{"type":"assistant","message":{"id":"msg_01","content":[{"type":"text","text":"world!"}]}}
{"type":"result","subtype":"success","duration_ms":500,"num_turns":1}
```

Create `apps/ingest/tests/fixtures/tool_use_session.jsonl`:

```
{"type":"system","subtype":"init","session_id":"sess_tool_001","cwd":"/home/user","tools":["Read","Edit"]}
{"type":"assistant","message":{"id":"msg_01","content":[{"type":"text","text":"Let me check."}]}}
{"type":"assistant","message":{"id":"msg_01","content":[{"type":"tool_use","id":"toolu_01","name":"Read","input":{"file_path":"/etc/hosts"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_01","content":"127.0.0.1 localhost"}]}}
{"type":"assistant","message":{"id":"msg_02","content":[{"type":"text","text":"It has localhost."}]}}
{"type":"result","subtype":"success","duration_ms":2000,"num_turns":1}
```

Create `apps/ingest/tests/fixtures/multi_turn_session.jsonl`:

```
{"type":"system","subtype":"init","session_id":"sess_multi_001","cwd":"/tmp","tools":[]}
{"type":"assistant","message":{"id":"msg_01","content":[{"type":"text","text":"Hi there!"}]}}
{"type":"result","subtype":"success","duration_ms":300,"num_turns":1}
{"type":"assistant","message":{"id":"msg_02","content":[{"type":"text","text":"Sure, I can help."}]}}
{"type":"result","subtype":"success","duration_ms":400,"num_turns":2}
```

- [ ] **Step 4: Write parser tests**

Create `apps/ingest/tests/test_parser.py`:

```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_simple_session():
    from apps.ingest.parser import parse_session_file

    result = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.cli_session_id == "sess_simple_001"
    assert len(result.turns) == 1
    turn = result.turns[0]
    assert turn.role == "assistant"
    assert turn.plaintext == "Hello, world!"


def test_parse_tool_use_session():
    from apps.ingest.parser import parse_session_file

    result = parse_session_file(FIXTURES / "tool_use_session.jsonl")
    assert result.cli_session_id == "sess_tool_001"
    # assistant text + tool_use + tool_result + assistant text = 4 turns
    assert len(result.turns) == 4
    assert result.turns[0].role == "assistant"
    assert result.turns[0].plaintext == "Let me check."
    assert result.turns[1].role == "tool_use"
    assert result.turns[2].role == "tool_result"
    assert result.turns[3].role == "assistant"
    assert result.turns[3].plaintext == "It has localhost."


def test_parse_multi_turn_session():
    from apps.ingest.parser import parse_session_file

    result = parse_session_file(FIXTURES / "multi_turn_session.jsonl")
    assert result.cli_session_id == "sess_multi_001"
    assert len(result.turns) == 2
    assert result.turns[0].plaintext == "Hi there!"
    assert result.turns[1].plaintext == "Sure, I can help."


def test_parse_returns_byte_count():
    from apps.ingest.parser import parse_session_file

    result = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.raw_bytes > 0


def test_parse_returns_line_count():
    from apps.ingest.parser import parse_session_file

    result = parse_session_file(FIXTURES / "simple_session.jsonl")
    assert result.line_count == 4
```

- [ ] **Step 5: Run tests to verify they fail**

```bash
pytest apps/ingest/tests/test_parser.py -v
```

Expected: FAIL — `parse_session_file` not found.

- [ ] **Step 6: Implement the parser**

Create `apps/ingest/parser.py`:

```python
"""Parse a Claude CLI .jsonl session file into structured turn data.

This is a standalone file parser, NOT a streaming event handler. It reads
the complete file and returns a ParsedSession with all turns extracted.
The event format matches docs/learnings/cli-stream-json-format.md.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedTurn:
    role: str  # "user", "assistant", "tool_use", "tool_result"
    content: dict[str, Any]
    plaintext: str


@dataclass
class ParsedSession:
    cli_session_id: str
    turns: list[ParsedTurn] = field(default_factory=list)
    raw_bytes: int = 0
    line_count: int = 0


def parse_session_file(path: Path) -> ParsedSession:
    """Parse a .jsonl session file and return structured turn data."""
    raw = path.read_bytes()
    lines = raw.decode("utf-8", errors="replace").splitlines()

    session = ParsedSession(
        cli_session_id="",
        raw_bytes=len(raw),
        line_count=len(lines),
    )

    # Accumulate text deltas per assistant message id
    current_assistant_text: list[str] = []
    current_msg_id: str | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping invalid JSON line: %r", line[:200])
            continue

        kind = payload.get("type")

        if kind == "system" and payload.get("subtype") == "init":
            session.cli_session_id = payload.get("session_id", "")
            continue

        if kind == "assistant":
            msg_id = payload.get("message", {}).get("id")
            blocks = payload.get("message", {}).get("content", [])

            # If this is a new message id, flush the previous one
            if msg_id != current_msg_id and current_assistant_text:
                session.turns.append(ParsedTurn(
                    role="assistant",
                    content={"text": "".join(current_assistant_text)},
                    plaintext="".join(current_assistant_text),
                ))
                current_assistant_text = []
            current_msg_id = msg_id

            for block in blocks:
                block_type = block.get("type")
                if block_type == "text":
                    current_assistant_text.append(block.get("text", ""))
                elif block_type == "tool_use":
                    # Flush accumulated text first
                    if current_assistant_text:
                        session.turns.append(ParsedTurn(
                            role="assistant",
                            content={"text": "".join(current_assistant_text)},
                            plaintext="".join(current_assistant_text),
                        ))
                        current_assistant_text = []
                        current_msg_id = None
                    session.turns.append(ParsedTurn(
                        role="tool_use",
                        content=block,
                        plaintext=f"Tool: {block.get('name', 'unknown')}",
                    ))
            continue

        if kind == "user":
            # Flush any pending assistant text
            if current_assistant_text:
                session.turns.append(ParsedTurn(
                    role="assistant",
                    content={"text": "".join(current_assistant_text)},
                    plaintext="".join(current_assistant_text),
                ))
                current_assistant_text = []
                current_msg_id = None

            blocks = payload.get("message", {}).get("content", [])
            for block in blocks:
                if block.get("type") == "tool_result":
                    session.turns.append(ParsedTurn(
                        role="tool_result",
                        content=block,
                        plaintext=str(block.get("content", ""))[:500],
                    ))
            continue

        if kind == "result":
            # Flush any pending assistant text
            if current_assistant_text:
                session.turns.append(ParsedTurn(
                    role="assistant",
                    content={"text": "".join(current_assistant_text)},
                    plaintext="".join(current_assistant_text),
                ))
                current_assistant_text = []
                current_msg_id = None
            continue

    # Final flush
    if current_assistant_text:
        session.turns.append(ParsedTurn(
            role="assistant",
            content={"text": "".join(current_assistant_text)},
            plaintext="".join(current_assistant_text),
        ))

    return session
```

- [ ] **Step 7: Run tests**

```bash
pytest apps/ingest/tests/test_parser.py -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/ingest/ config/settings/base.py
git commit -m "feat: JSONL session parser for ingest"
```

---

## Task 13: Ingest upload endpoint

**Files:**
- Create: `apps/ingest/views.py`
- Create: `apps/ingest/urls.py`
- Modify: `config/urls.py`
- Create: `apps/ingest/tests/test_views.py`

- [ ] **Step 1: Write endpoint tests**

Create `apps/ingest/tests/test_views.py`:

```python
from io import BytesIO
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from apps.sessions.models import IngestUpload, Message, Session

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _upload_fixture(client, filename="simple_session.jsonl"):
    content = (FIXTURES / filename).read_bytes()
    file = BytesIO(content)
    file.name = filename
    return client.post(
        "/api/ingest/upload",
        {"file": file},
        format="multipart",
    )


def test_upload_creates_session(client, user):
    resp = _upload_fixture(client)
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "session_slug" in body
    assert body["message_count"] > 0
    assert body["cli_session_id"] == "sess_simple_001"

    session = Session.objects.get(slug=body["session_slug"])
    assert session.source == "upload"
    assert session.status == "imported"
    assert session.owner == user


def test_upload_creates_messages(client):
    resp = _upload_fixture(client)
    slug = resp.json()["data"]["session_slug"]
    messages = Message.objects.filter(session__slug=slug).order_by("turn_index")
    assert messages.count() >= 1
    assert messages.first().role == "assistant"


def test_upload_creates_ingest_record(client):
    resp = _upload_fixture(client)
    slug = resp.json()["data"]["session_slug"]
    record = IngestUpload.objects.get(session__slug=slug)
    assert record.cli_session_id == "sess_simple_001"
    assert record.raw_bytes > 0
    assert record.line_count == 4


def test_upload_duplicate_returns_409(client):
    resp1 = _upload_fixture(client)
    assert resp1.status_code == 201
    resp2 = _upload_fixture(client)
    assert resp2.status_code == 409


def test_upload_missing_file_returns_400(client):
    resp = client.post("/api/ingest/upload", {}, format="multipart")
    assert resp.status_code == 400


def test_upload_tool_use_session(client):
    resp = _upload_fixture(client, "tool_use_session.jsonl")
    assert resp.status_code == 201
    slug = resp.json()["data"]["session_slug"]
    messages = Message.objects.filter(session__slug=slug).order_by("turn_index")
    roles = list(messages.values_list("role", flat=True))
    assert "tool_use" in roles
    assert "tool_result" in roles


def test_upload_with_bearer_token(user):
    from apps.auth.models import PersonalToken
    raw, _ = PersonalToken.create_for_user(user=user, label="test")
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    content = (FIXTURES / "simple_session.jsonl").read_bytes()
    file = BytesIO(content)
    file.name = "simple_session.jsonl"
    resp = c.post("/api/ingest/upload", {"file": file}, format="multipart")
    assert resp.status_code == 201
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest apps/ingest/tests/test_views.py -v
```

Expected: FAIL — 404 (no URL).

- [ ] **Step 3: Implement the upload view**

Create `apps/ingest/views.py`:

```python
"""Upload endpoint for JSONL session files."""
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.sessions.models import IngestUpload, Message, Session, SessionParticipant

from .parser import parse_session_file


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def upload(request: Request) -> Response:
    file = request.FILES.get("file")
    if not file:
        return Response(
            error_response(message="file is required", code="validation_error"),
            status=400,
        )

    # Write to a temp file so the parser can read it
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        for chunk in file.chunks():
            tmp.write(chunk)
        tmp_path = Path(tmp.name)

    try:
        parsed = parse_session_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    # Duplicate guard
    if parsed.cli_session_id and IngestUpload.objects.filter(
        cli_session_id=parsed.cli_session_id
    ).exists():
        return Response(
            error_response(
                message=f"Session {parsed.cli_session_id} already uploaded",
                code="duplicate",
            ),
            status=409,
        )

    # Create session + messages + ingest record
    session = Session.objects.create(
        owner=request.user,
        source="upload",
        status="imported",
        cli_session_id=parsed.cli_session_id or "",
        title=f"Imported: {file.name}",
    )
    SessionParticipant.objects.create(
        session=session, user=request.user, role="owner"
    )

    messages = []
    for idx, turn in enumerate(parsed.turns, start=1):
        messages.append(
            Message(
                session=session,
                turn_index=idx,
                role=turn.role,
                content=turn.content,
                plaintext=turn.plaintext,
                status="complete",
            )
        )
    Message.objects.bulk_create(messages)

    IngestUpload.objects.create(
        session=session,
        uploaded_by=request.user,
        source_path=file.name,
        raw_bytes=parsed.raw_bytes,
        line_count=parsed.line_count,
        cli_session_id=parsed.cli_session_id or "",
    )

    return Response(
        success_response({
            "session_slug": session.slug,
            "message_count": len(messages),
            "cli_session_id": parsed.cli_session_id,
        }),
        status=status.HTTP_201_CREATED,
    )
```

- [ ] **Step 4: Create URLs**

Create `apps/ingest/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("upload", views.upload, name="ingest_upload"),
]
```

Add to `config/urls.py`:

```python
path("api/ingest/", include("apps.ingest.urls")),
```

- [ ] **Step 5: Run tests**

```bash
pytest apps/ingest/tests/test_views.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/ingest/ config/urls.py
git commit -m "feat: ingest upload endpoint — JSONL to Session + Messages"
```

---

## Task 14: `ace-upload` CLI

**Files:**
- Create: `apps/ingest/cli.py`
- Modify: `pyproject.toml`
- Test: `apps/ingest/tests/test_cli.py`

- [ ] **Step 1: Write CLI tests**

Create `apps/ingest/tests/test_cli.py`:

```python
"""Tests for the ace-upload CLI. These mock httpx — no Django needed."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def config_file(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        'server = "http://localhost:8000/ace"\ntoken = "test-token-123"\n'
    )
    return config


def test_upload_single_file(config_file, tmp_path):
    from apps.ingest.cli import upload_file, load_config

    session_file = tmp_path / "test.jsonl"
    session_file.write_text('{"type":"system","subtype":"init","session_id":"s1"}\n')

    config = load_config(config_file)
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "data": {"session_slug": "abc", "message_count": 1, "cli_session_id": "s1"},
        "error": None,
    }

    with patch("httpx.post", return_value=mock_response) as mock_post:
        result = upload_file(session_file, config)

    assert result is True
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "Bearer test-token-123" in str(call_kwargs)


def test_upload_duplicate_returns_false(config_file, tmp_path):
    from apps.ingest.cli import upload_file, load_config

    session_file = tmp_path / "test.jsonl"
    session_file.write_text('{"type":"system"}\n')

    config = load_config(config_file)
    mock_response = MagicMock()
    mock_response.status_code = 409
    mock_response.json.return_value = {
        "data": None,
        "error": {"code": "duplicate", "message": "already uploaded"},
    }

    with patch("httpx.post", return_value=mock_response):
        result = upload_file(session_file, config)

    assert result is False


def test_load_config(config_file):
    from apps.ingest.cli import load_config

    config = load_config(config_file)
    assert config.server == "http://localhost:8000/ace"
    assert config.token == "test-token-123"


def test_load_config_missing_raises(tmp_path):
    from apps.ingest.cli import load_config

    with pytest.raises(SystemExit):
        load_config(tmp_path / "nonexistent.toml")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest apps/ingest/tests/test_cli.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the CLI**

Create `apps/ingest/cli.py`:

```python
"""ace-upload: Upload .jsonl Claude CLI sessions to ace-web.

This is a standalone script. It does NOT import Django. It uses httpx to
POST files to the ingest endpoint and reads config from ~/.ace/config.toml.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import httpx


@dataclass
class Config:
    server: str
    token: str


def load_config(path: Path) -> Config:
    if not path.exists():
        print(f"Config not found: {path}", file=sys.stderr)
        print("Run: ace-upload --configure", file=sys.stderr)
        sys.exit(1)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Config(server=data["server"], token=data["token"])


def upload_file(path: Path, config: Config) -> bool:
    """Upload a single .jsonl file. Returns True on success, False on skip/error."""
    url = f"{config.server.rstrip('/')}/api/ingest/upload"
    with open(path, "rb") as f:
        resp = httpx.post(
            url,
            files={"file": (path.name, f, "application/x-ndjson")},
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=60,
        )
    if resp.status_code == 201:
        data = resp.json().get("data", {})
        print(
            f"  ✓ {path.name} → {data.get('session_slug')} "
            f"({data.get('message_count', '?')} messages)",
            file=sys.stderr,
        )
        return True
    if resp.status_code == 409:
        print(f"  — {path.name} (already uploaded, skipping)", file=sys.stderr)
        return False
    error = resp.json().get("error", {}).get("message", resp.text[:200])
    print(f"  ✗ {path.name}: {resp.status_code} {error}", file=sys.stderr)
    return False


def configure(config_path: Path) -> None:
    """Interactive config setup."""
    print("ace-upload configuration")
    server = input(f"Server URL [https://labs.connect.dimagi.com/ace]: ").strip()
    if not server:
        server = "https://labs.connect.dimagi.com/ace"
    token = input("Personal token: ").strip()
    if not token:
        print("Token is required.", file=sys.stderr)
        sys.exit(1)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(f'server = "{server}"\ntoken = "{token}"\n')
    print(f"Config written to {config_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ace-upload",
        description="Upload .jsonl Claude CLI sessions to ace-web.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="A .jsonl file or directory of .jsonl files",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Set up server URL and token",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".ace" / "config.toml",
        help="Config file path (default: ~/.ace/config.toml)",
    )
    args = parser.parse_args()

    if args.configure:
        configure(args.config)
        return

    if not args.path:
        parser.error("Provide a .jsonl file or directory, or use --configure")

    config = load_config(args.config)
    target = args.path

    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(target.glob("*.jsonl"))
        if not files:
            print(f"No .jsonl files found in {target}", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(files)} .jsonl files", file=sys.stderr)
    else:
        print(f"Not found: {target}", file=sys.stderr)
        sys.exit(1)

    successes = 0
    for f in files:
        if upload_file(f, config):
            successes += 1

    print(f"\n{successes}/{len(files)} uploaded", file=sys.stderr)
    sys.exit(0 if successes == len(files) else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add pyproject.toml entrypoint**

Add to `pyproject.toml`:

```toml
[project.scripts]
ace-upload = "apps.ingest.cli:main"
```

- [ ] **Step 5: Run tests**

```bash
pytest apps/ingest/tests/test_cli.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/ingest/cli.py apps/ingest/tests/test_cli.py pyproject.toml
git commit -m "feat: ace-upload CLI for batch JSONL session import"
```

---

## Task 15: Imported session resume behavior

**Files:**
- Modify: `frontend/src/components/SendBox.tsx`
- Modify: `apps/sessions/views.py` (send_message auto-activates imported sessions)

- [ ] **Step 1: Write backend test for imported session activation**

Add to `apps/sessions/tests/test_views.py`:

```python
def test_send_message_activates_imported_session(client, user):
    s = Session.objects.create(
        owner=user, title="imported", source="upload", status="imported"
    )
    resp = client.post(f"/api/sessions/{s.slug}/messages", {"text": "continue"}, format="json")
    assert resp.status_code == 201
    s.refresh_from_db()
    assert s.status == "active"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/sessions/tests/test_views.py::test_send_message_activates_imported_session -v
```

Expected: FAIL — status stays "imported".

- [ ] **Step 3: Implement activation in send_message**

In `apps/sessions/views.py`, in the `send_message` function, add after acquiring the `select_for_update` lock:

```python
# Auto-activate imported sessions on first message send
if session.status == "imported":
    session.status = "active"
    session.save(update_fields=["status", "updated_at"])
```

- [ ] **Step 4: Run test**

```bash
pytest apps/sessions/tests/test_views.py::test_send_message_activates_imported_session -v
```

Expected: PASS.

- [ ] **Step 5: Update SendBox for imported session hint**

In `frontend/src/components/SendBox.tsx`, update the component to accept `sessionSource` and `sessionStatus` props. When `source === "upload"` and `status === "imported"`, show a hint above the input:

```tsx
{sessionSource === "upload" && sessionStatus === "imported" && (
  <div className="px-3 py-1.5 text-xs text-muted-foreground border-b border-border bg-muted/50">
    Imported session — send a message to continue it with Claude.
  </div>
)}
```

The `disabled` prop should NOT be set based on source/status — the user can always send.

Update `ChatPage.tsx` to pass these new props:

```tsx
<SendBox
  disabled={false}
  isStreaming={isStreaming}
  sessionSource={session.source}
  sessionStatus={session.status}
  onSend={handleSend}
  onStop={stream.cancel}
/>
```

- [ ] **Step 6: Verify build**

```bash
cd frontend && bun run build
```

Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add apps/sessions/ frontend/src/
git commit -m "feat: imported sessions are resumable — auto-activates on first send"
```

---

## Task 16: Upload button on library page

**Files:**
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Create: `frontend/src/api/ingest.ts`

- [ ] **Step 1: Create ingest API function**

Create `frontend/src/api/ingest.ts`:

```typescript
import type { ApiEnvelope } from "./types";

interface UploadResult {
  session_slug: string;
  message_count: number;
  cli_session_id: string;
}

// Use raw fetch instead of apiFetch because apiFetch auto-sets
// Content-Type: application/json which breaks multipart uploads.
// Build the URL the same way client.ts does (BASE_URL prefix).
const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");

export const uploadSession = async (file: File): Promise<UploadResult> => {
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch(`${API_PREFIX}/api/ingest/upload`, {
    method: "POST",
    body: formData,
    credentials: "same-origin",
  });
  const json: ApiEnvelope<UploadResult> = await resp.json();
  if (json.error) {
    throw new Error(json.error.message);
  }
  if (!json.data) {
    throw new Error("No data in response");
  }
  return json.data;
};
```

- [ ] **Step 2: Wire upload button into LibraryPage**

In `LibraryPage.tsx`, replace the upload `<Button>` that links to `/settings` with a file-picker trigger:

```tsx
const fileInputRef = useRef<HTMLInputElement>(null);

const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    const result = await uploadSession(file);
    toast.success(`Uploaded: ${result.message_count} messages`);
    load();
  } catch (err) {
    toast.error(String(err instanceof Error ? err.message : err));
  }
  // Reset so the same file can be re-selected
  e.target.value = "";
};
```

```tsx
<>
  <input
    ref={fileInputRef}
    type="file"
    accept=".jsonl"
    className="hidden"
    onChange={handleUpload}
  />
  <Button
    variant="outline"
    size="sm"
    onClick={() => fileInputRef.current?.click()}
  >
    <Upload className="mr-1.5 h-3.5 w-3.5" />
    Upload .jsonl
  </Button>
</>
```

- [ ] **Step 3: Verify build**

```bash
cd frontend && bun run build
```

Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat: upload .jsonl directly from the library page"
```

---

## Task 17: Final integration and test pass

**Files:**
- All previously created/modified files

- [ ] **Step 1: Run full backend test suite**

```bash
pytest -v
```

Expected: all tests PASS (existing + new). Fix any failures.

- [ ] **Step 2: Run lint**

```bash
ruff check .
```

Expected: clean. Fix any issues.

- [ ] **Step 3: Run frontend build**

```bash
cd frontend && bun run build
```

Expected: clean build.

- [ ] **Step 4: Manual end-to-end walkthrough**

With `docker compose up`:

1. Log in → see TopNav with Library / Chat / Opps links
2. Toggle dark/light mode — verify Workbench, ChatPage, Library all theme correctly
3. Visit `/library` — see empty state
4. Click "+ New chat" — redirects to `/chat/<slug>`
5. Send a message — verify streaming works
6. Visit `/library` — see the session in the list
7. Search by title — verify filter works
8. Archive a session — verify it moves to "Archived" filter
9. Delete a session — verify confirmation dialog and removal
10. Visit `/settings` — create a personal token
11. Copy the token, run `ace-upload --configure` locally
12. Run `ace-upload <some-fixture.jsonl>` — verify it uploads
13. Visit `/library`, filter by "Imported" — see the uploaded session
14. Open it — verify messages render
15. Send a message — verify it activates and CLIBackend resumes

- [ ] **Step 5: Commit any fixes**

```bash
git add -A && git commit -m "fix: integration test fixes for Phase 4"
```

(Only if there were issues to fix.)
