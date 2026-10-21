# Interface implementation reference

Reference: dashboard-concept.png. Full tablet primary surface; extend its same component families into details, forms, settings, and phone lists.

- Canvas #f6f9fc; white panels; sidebar #102132; text #102139; muted #64748b; border #e1e8f0; accent #009e70; danger #e84c61; warning #e9a229.
- System/Inter-like sans typography: heading 30/36 bold; section 18/24 semibold; body 14/21; helper 12/18; controls 14/20 medium.
- Sidebar 224px, content padding 28px, 18px panel gaps, 12px panel corners. No gradients, photographic assets, or overlays. Outline Lucide icons at 20px, 1.8 stroke.
- Overview hierarchy: title/subtitle/actions; four stats; main server table plus active incidents; application rows plus activity. Compact resource bars with text labels; no gauges or decorative charts.
- Allowed overview copy: Cronos, Overview, Servers, Applications, Alerts, Settings, Your infrastructure, at a glance., Demo data, Refresh, Add server, Servers monitored, Healthy, Needs attention, Unreachable, Active incidents, View all, Activity, Latest checks; table column/data labels.
- Dynamic data must reflect API values and freshness. Reference metric numbers are illustrative only; implemented scoring takes precedence over illustrative concept numbers.
- Phone: top toolbar, two-column stats, stacked readable server rows, incidents and application list, four-item bottom navigation. Tablet: sidebar and wide tables; smaller tablets stack right column below.
- Required additions to reference: actual sign-in, offline/error/empty states; accessible add/edit enrollment dialog; details/charts; alert acknowledgement and comments; settings/maintenance/notification configuration. These are functional scope from the specification.

## Generated concept brief

Built-in image generation was used for a full landscape Cronos monitoring dashboard: dark navy navigation with Overview/Servers/Applications/Alerts/Settings; cool pale canvas and white bordered panels; emerald primary actions; four summary metrics; a six-server table with health/resource bars and independent status; an adjacent active incident list; application status/latency rows; and recent collection activity. All interface controls and text are implemented natively in Vue/Quasar. No raster screenshot is used as the application UI. The generated concept is retained at `docs/dashboard-concept.png`.
