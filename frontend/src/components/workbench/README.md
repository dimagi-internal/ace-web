# WorkbenchLayout kit

Generic three-pane workbench shell: **[ left rail | center | right rail ]**.
Each rail is independently collapsible (`push` reflows the center; `overlay`
slides over it). Center always grows. Pure presentational — pass collapse
state in via `usePaneCollapsed(storageKey, default)`.

## Contract (future UIs + an eventual canopy-web migration conform to this)

- **Left rail** = the entity navigator: the list you select from (lifecycle
  steps / narrative beats + runs). Collapsible.
- **Center** = the detail canvas for the selected entity. Always flex-grows.
- **Right rail** = the inspector / chat / edit surface for the selection.
- **Header** slot holds the run picker; **toolbar** slot holds view tabs.

## Usage

```tsx
const nav = usePaneCollapsed("ace.video.navCollapsed");
const inspector = usePaneCollapsed("ace.video.inspectorCollapsed");

<WorkbenchLayout
  header={<MyHeader />}
  toolbar={<MyTabs />}
  left={{ title: "Narrative", collapsed: nav.collapsed, onToggle: nav.toggle, content: <NavRail /> }}
  center={<DetailPane />}
  right={{
    title: "Inspector",
    collapsed: inspector.collapsed,
    onToggle: inspector.toggle,
    content: <Inspector />,
    mode: "overlay",
  }}
/>;
```

## Boundary

No app/store/domain imports — props in only — so this is cheap to extract
into a shared cross-repo package when a second app (canopy-web) adopts it.
