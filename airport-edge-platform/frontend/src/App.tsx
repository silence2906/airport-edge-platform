import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity, AlertTriangle, ArrowDownToLine, Bell, Camera, Check, ChevronDown,
  CircleHelp, Clock3, Cpu, Fingerprint, Gauge, Luggage, Radio, Search, Shield,
  ShieldCheck, Thermometer, UserRound, Users, Wifi, X,
} from "lucide-react";

type Device = {
  device_id: string; device_type: string; location: string; status: string;
  last_seen: string; capabilities: string[];
};
type EventItem = {
  event_id: string; event_type: string; severity: string; source: string;
  passenger_id: string | null; timestamp: string; description: string;
  confidence: number | null; status: string;
};
type Passenger = {
  passenger_id: string; name: string; identity_detected: boolean;
  identity_verified: boolean; boarding_pass_verified: boolean;
  flight: string; destination: string; checkin_status: string;
};
type Health = { status: string; devices_total: number; devices_online: number };
type Metrics = {
  passengers_processed: number; identity_verified: number; checkins_completed: number;
  failed_validations: number; total_scans: number; anomalies_detected: number;
  high_severity_events: number; manual_review: number;
};

/** Call one versioned edge API route and raise a readable error for failures. */
const api = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
};

/** Render live edge status, passenger workflows, scan controls, and event review. */
function App() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [health, setHealth] = useState<Health>();
  const [metrics, setMetrics] = useState<Metrics>();
  const [passenger, setPassenger] = useState<Passenger>();
  const [passengerId, setPassengerId] = useState("PAX-10001");
  const [baggageStatus, setBaggageStatus] = useState("PENDING");
  const [deviceFilter, setDeviceFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [passengerFilter, setPassengerFilter] = useState("");
  const [timeFilter, setTimeFilter] = useState("");
  const [query, setQuery] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);

  /** Refresh all dashboard data from the local edge server. */
  const refresh = useCallback(async () => {
    const [deviceData, eventData, healthData, passengerData, metricData] = await Promise.all([
      api<Device[]>("/devices"),
      api<EventItem[]>("/events?limit=100"),
      api<Health>("/health"),
      api<Passenger>(`/passenger/${encodeURIComponent(passengerId)}`),
      api<Metrics>("/metrics"),
    ]);
    setDevices(deviceData);
    setEvents(eventData);
    setHealth(healthData);
    setPassenger(passengerData);
    setMetrics(metricData);
  }, [passengerId]);

  useEffect(() => {
    refresh().catch((error: Error) => setToast(`Edge server unavailable: ${error.message}`));
    const timer = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 12000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${window.location.host}/ws/events`);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = () => refresh().catch(() => undefined);
    return () => socket.close();
  }, [refresh]);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(""), 4500);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const visibleEvents = useMemo(() => events.filter((event) => {
    const matchesDevice = !deviceFilter || event.source === deviceFilter;
    const matchesSeverity = !severityFilter || event.severity === severityFilter;
    const matchesType = !eventTypeFilter || event.event_type === eventTypeFilter;
    const matchesStatus = !statusFilter || event.status === statusFilter;
    const matchesPassenger = !passengerFilter || event.passenger_id === passengerFilter;
    const eventTime = new Date(event.timestamp).getTime();
    const matchesTime = !timeFilter ||
      (timeFilter === "hour" && Date.now() - eventTime <= 60 * 60 * 1000) ||
      (timeFilter === "today" && new Date(event.timestamp).toDateString() === new Date().toDateString());
    const text = `${event.event_id} ${event.event_type} ${event.source} ${event.passenger_id ?? ""} ${event.description}`.toLowerCase();
    return matchesDevice && matchesSeverity && matchesType && matchesStatus &&
      matchesPassenger && matchesTime && text.includes(query.toLowerCase());
  }), [events, deviceFilter, severityFilter, eventTypeFilter, statusFilter, passengerFilter, timeFilter, query]);

  /** Submit a simulated workflow request and refresh the dashboard on success. */
  const runAction = async (name: string, path: string, body: unknown) => {
    setBusy(true);
    try {
      await api(path, { method: "POST", body: JSON.stringify(body) });
      setToast(`${name} completed`);
      await refresh();
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  /** Simulate identity capture and mock profile/boarding-pass verification. */
  const verifyIdentity = () => runAction("Identity verification", "/identity/verify", {
    passenger_id: passengerId, identity_detected: true, mock_identity_match: true,
    boarding_pass_present: true,
  });
  /** Submit the passenger's profile-matching answers for self check-in. */
  const runCheckin = () => runAction("Self check-in", "/checkin/self", {
    passenger_id: passengerId,
    answers: [
      { question: "What is your flight number?", answer: passenger?.flight ?? "" },
      { question: "What is your destination?", answer: passenger?.destination ?? "" },
    ],
  });
  /** Submit operator verification and baggage review for assisted check-in. */
  const runAssistedCheckin = () => runAction("Assisted check-in", "/checkin/assisted", {
    passenger_id: passengerId,
    operator_id: "OP-001",
    identity_verified: passenger?.identity_verified ?? false,
    boarding_pass_verified: passenger?.boarding_pass_verified ?? false,
    flight_number: passenger?.flight ?? "",
    baggage_status: baggageStatus,
  });
  /** Generate a mock thermal sample that exercises configured thresholds. */
  const runThermal = () => runAction("Thermal scan", "/thermal/scan", {
    device_id: "THERMAL-001", temperature_c: 38.2,
  });
  /** Submit synthetic baggage detections to the mock scanner endpoint. */
  const runBaggage = () => runAction("Baggage scan", "/baggage/scan", {
    bag_id: `BAG-${Date.now()}`, passenger_id: passengerId, scan_type: "XRAY",
    simulated_objects: ["mock_demo_restricted"],
  });
  /** Submit a synthetic camera frame and demo object detection. */
  const runCamera = () => runAction("Camera scan", "/camera/scan", {
    device_id: "CAM-001", frame_id: `FRAME-${Date.now()}`,
    detections: [{ object_type: "mock_demo_restricted", confidence: 0.91 }],
  });

  /** Mark an event as acknowledged after an operator review action. */
  const acknowledge = async (eventId: string) => {
    try {
      await api(`/events/${eventId}`, {
        method: "PATCH", body: JSON.stringify({ status: "ACKNOWLEDGED" }),
      });
      await refresh();
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Could not update event");
    }
  };

  /** Download currently filtered event rows as a CSV file. */
  const exportEvents = () => {
    const rows = [
      ["Time", "Event ID", "Device", "Passenger", "Event Type", "Severity", "Confidence", "Status"],
      ...visibleEvents.map((event) => [
        event.timestamp,
        event.event_id,
        event.source,
        event.passenger_id ?? "",
        event.event_type,
        event.severity,
        event.confidence == null ? "" : String(event.confidence),
        event.status,
      ]),
    ];
    const csv = rows
      .map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(","))
      .join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `airport-events-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const reviewCount = metrics?.manual_review ?? 0;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Radio size={21} /></div>
          <div><strong>EDGE<span>PORT</span></strong><small>Airport intelligence</small></div>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <button className="nav-item active"><Gauge size={18} /> Operations overview</button>
        <button className="nav-item" onClick={() => document.getElementById("passenger-panel")?.scrollIntoView({ behavior: "smooth" })}><Users size={18} /> Passenger processing</button>
        <button className="nav-item" onClick={() => document.getElementById("event-table")?.scrollIntoView({ behavior: "smooth" })}><Shield size={18} /> Security events <span className="nav-count">{reviewCount}</span></button>
        <button className="nav-item" onClick={() => document.getElementById("device-panel")?.scrollIntoView({ behavior: "smooth" })}><Cpu size={18} /> Edge devices</button>
        <div className="sidebar-bottom">
          <div className="edge-card">
            <div className="edge-card-top"><span className="pulse-dot" /> LOCAL EDGE</div>
            <strong>Processing on-site</strong>
            <p>Services remain available without a cloud connection.</p>
            <div className="edge-uptime"><Wifi size={13} /> {connected ? "Event stream connected" : "Event stream reconnecting"}</div>
          </div>
          <div className="profile-row"><div className="avatar">OP</div><div><strong>Airport Operator</strong><small>Operations desk</small></div><ChevronDown size={15} /></div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">Airport operations <span>/</span> <strong>Overview</strong></div>
          <div className="topbar-right">
            <div className="live-status"><span className="pulse-dot" /> EDGE SERVER {health?.status === "healthy" ? "ONLINE" : "CONNECTING"}</div>
            <button className="icon-button" aria-label="Notifications"><Bell size={18} /><i /></button>
            <div className="today"><Clock3 size={15} /> {new Date().toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</div>
          </div>
        </header>

        <div className="content">
          <section className="welcome">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" /> EDGE CONTROL CENTER</div>
              <h1>Good day, Operator<span>.</span></h1>
              <p>Here's what's happening across your airport edge network.</p>
            </div>
            <div className="system-pill"><span className="pulse-dot" /><div><small>SYSTEM STATUS</small><strong>{health ? (health.devices_online === health.devices_total ? "All systems operational" : "Device attention required") : "Connecting to edge..."}</strong></div><Activity size={20} /></div>
          </section>

          <section className="metrics">
            <Metric icon={<Users />} label="Passengers processed" value={String(metrics?.passengers_processed ?? 0).padStart(2, "0")} trend="Identity captures" tint="blue" />
            <Metric icon={<Fingerprint />} label="Identity verified" value={String(metrics?.identity_verified ?? 0).padStart(2, "0")} trend="Mock profile matches" tint="green" />
            <Metric icon={<ShieldCheck />} label="Check-ins completed" value={String(metrics?.checkins_completed ?? 0).padStart(2, "0")} trend="Self + assisted" tint="violet" />
            <Metric icon={<AlertTriangle />} label="Failed validations" value={String(metrics?.failed_validations ?? 0).padStart(2, "0")} trend="Identity / check-in" tint="amber" />
            <Metric icon={<Camera />} label="Total scans" value={String(metrics?.total_scans ?? 0).padStart(2, "0")} trend="Camera · thermal · baggage" tint="blue" />
            <Metric icon={<Activity />} label="Anomalies detected" value={String(metrics?.anomalies_detected ?? 0).padStart(2, "0")} trend="All event types" tint="violet" />
            <Metric icon={<AlertTriangle />} label="High severity" value={String(metrics?.high_severity_events ?? 0).padStart(2, "0")} trend="HIGH + CRITICAL" tint="amber" />
            <Metric icon={<Bell />} label="Manual review" value={String(reviewCount).padStart(2, "0")} trend="Operator action needed" tint="green" />
          </section>

          <section className="section-heading">
            <div><h2>Live operations</h2><p>Device network health and passenger workflow</p></div>
            <button className="outline-button" onClick={() => refresh().catch((error: Error) => setToast(error.message))}><Activity size={15} /> Refresh data</button>
          </section>

          <section className="overview-grid">
            <article className="panel device-panel" id="device-panel">
              <div className="panel-head"><div><div className="panel-title"><span className="title-icon"><Cpu size={17} /></span><h3>Connected devices</h3></div><p>{health?.devices_online ?? 0} of {health?.devices_total ?? 0} devices online</p></div><button className="more-button" aria-label="Device options">···</button></div>
              <div className="device-list">
                {devices.map((device) => <div className="device-row" key={device.device_id}>
                  <div className={`device-icon ${device.device_type.toLowerCase().includes("thermal") ? "thermal" : device.device_type.toLowerCase().includes("baggage") ? "baggage" : device.device_type.toLowerCase().includes("camera") ? "camera" : "kiosk"}`}>
                    {device.device_type.toLowerCase().includes("thermal") ? <Thermometer /> : device.device_type.toLowerCase().includes("baggage") ? <Luggage /> : device.device_type.toLowerCase().includes("camera") ? <Camera /> : <Cpu />}
                  </div>
                  <div className="device-info"><strong>{device.device_id}</strong><small>{device.location} · {device.device_type.replaceAll("_", " ")}</small></div>
                  <Status value={device.status} />
                  <span className="device-time">{timeAgo(device.last_seen)}</span>
                </div>)}
              </div>
              <button className="text-link" onClick={() => setToast("Register devices through POST /api/v1/devices")}>Device registry <span>↗</span></button>
            </article>

            <article className="panel passenger-panel" id="passenger-panel">
              <div className="panel-head"><div><div className="panel-title"><span className="title-icon green"><UserRound size={17} /></span><h3>Passenger workflow</h3></div><p>Mock identity · profile · boarding validation</p></div><span className="demo-tag">SIMULATION</span></div>
              <div className="passenger-search">
                <Search size={16} />
                <input aria-label="Passenger ID" value={passengerId} onChange={(event) => setPassengerId(event.target.value)} onBlur={() => refresh().catch((error: Error) => setToast(error.message))} />
                <button onClick={() => refresh().catch((error: Error) => setToast(error.message))}>Find</button>
              </div>
              {passenger ? <>
                <div className="passenger-details">
                  <div className="passenger-avatar">{passenger.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</div>
                  <div><strong>{passenger.name}</strong><small>{passenger.passenger_id}</small></div>
                  <div className="flight-info"><span>{passenger.flight}</span><small>FLIGHT</small></div>
                  <div className="flight-info"><span>{passenger.destination}</span><small>DESTINATION</small></div>
                </div>
                <div className="verification-list">
                  <Verification label="Identity captured" value={passenger.identity_detected ? "VERIFIED" : "PENDING"} />
                  <Verification label="Identity verified" value={passenger.identity_verified ? "VERIFIED" : "PENDING"} />
                  <Verification label="Boarding pass" value={passenger.boarding_pass_verified ? "VERIFIED" : "PENDING"} />
                  <Verification label="Check-in" value={passenger.checkin_status} />
                </div>
                <label className="baggage-review"><span>Assisted baggage review</span>
                  <select value={baggageStatus} onChange={(event) => setBaggageStatus(event.target.value)}>
                    {["PENDING", "VERIFIED", "FAILED", "REQUIRES_MANUAL_REVIEW"].map((status) => <option key={status}>{status}</option>)}
                  </select>
                </label>
                <div className="workflow-actions">
                  <button className="primary-button" disabled={busy} onClick={verifyIdentity}><Fingerprint size={15} /> Verify identity</button>
                  <button className="outline-button" disabled={busy || !passenger.identity_verified || !passenger.boarding_pass_verified} onClick={runCheckin}><Check size={15} /> Complete check-in</button>
                  <button className="outline-button" disabled={busy} onClick={runAssistedCheckin}><UserRound size={15} /> Assisted check-in</button>
                </div>
              </> : <div className="empty-state"><CircleHelp size={20} /> Passenger not found in mock profiles.</div>}
            </article>
          </section>

          <section className="section-heading scan-heading">
            <div><h2>Simulation controls</h2><p>Generate edge-device input without physical hardware</p></div>
            <span className="offline-note"><span className="pulse-dot" /> Runs locally</span>
          </section>
          <section className="simulation-grid">
            <SimulationCard icon={<Camera />} title="Camera frame" description="Simulate a camera frame with a configured demo object." button="Run camera scan" onClick={runCamera} busy={busy} />
            <SimulationCard icon={<Thermometer />} title="Thermal reading" description="Generate a 38.2°C reading for manual review." button="Run thermal scan" onClick={runThermal} busy={busy} />
            <SimulationCard icon={<Luggage />} title="Baggage scan" description="Send synthetic X-ray object labels through configured rules." button="Run baggage scan" onClick={runBaggage} busy={busy} />
          </section>

          <section className="section-heading event-heading">
            <div><h2>Recent events <span className="event-total">{events.length}</span></h2><p>Edge-generated events requiring visibility or action</p></div>
            <button className="outline-button" onClick={exportEvents}><ArrowDownToLine size={15} /> Export CSV</button>
          </section>
          <section className="panel events-panel" id="event-table">
            <div className="event-filters">
              <div className="search-box"><Search size={15} /><input aria-label="Search events" placeholder="Search events..." value={query} onChange={(event) => setQuery(event.target.value)} /></div>
              <select aria-label="Filter device" value={deviceFilter} onChange={(event) => setDeviceFilter(event.target.value)}><option value="">All devices</option>{devices.map((device) => <option key={device.device_id}>{device.device_id}</option>)}</select>
              <select aria-label="Filter passenger" value={passengerFilter} onChange={(event) => setPassengerFilter(event.target.value)}><option value="">All passengers</option>{Array.from(new Set(events.map((item) => item.passenger_id).filter((id): id is string => Boolean(id)))).map((id) => <option key={id}>{id}</option>)}</select>
              <select aria-label="Filter event type" value={eventTypeFilter} onChange={(event) => setEventTypeFilter(event.target.value)}><option value="">All event types</option>{Array.from(new Set(events.map((item) => item.event_type))).map((type) => <option key={type}>{type}</option>)}</select>
              <select aria-label="Filter severity" value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}><option value="">All severity</option>{["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].map((severity) => <option key={severity}>{severity}</option>)}</select>
              <select aria-label="Filter status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">All statuses</option>{["REQUIRES_MANUAL_REVIEW", "ACKNOWLEDGED", "RESOLVED"].map((status) => <option key={status}>{status}</option>)}</select>
              <select aria-label="Filter time" value={timeFilter} onChange={(event) => setTimeFilter(event.target.value)}><option value="">Any time</option><option value="hour">Last hour</option><option value="today">Today</option></select>
              <button className="filter-button" onClick={() => { setDeviceFilter(""); setSeverityFilter(""); setEventTypeFilter(""); setStatusFilter(""); setPassengerFilter(""); setTimeFilter(""); setQuery(""); }}>Clear filters <X size={13} /></button>
            </div>
            <div className="table-scroll">
              <table>
                <thead><tr><th>TIME</th><th>EVENT</th><th>DEVICE / SOURCE</th><th>PASSENGER</th><th>TYPE</th><th>SEVERITY</th><th>CONFIDENCE</th><th>STATUS</th><th /></tr></thead>
                <tbody>
                  {visibleEvents.map((event) => <tr key={event.event_id}>
                    <td className="muted-cell">{new Date(event.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
                    <td><span className="event-id">{event.event_id}</span><small className="event-desc">{event.description}</small></td>
                    <td><span className="source-cell"><span className="source-dot" />{event.source}</span></td>
                    <td className="muted-cell">{event.passenger_id ?? "—"}</td>
                    <td><span className="type-pill">{event.event_type.replaceAll("_", " ")}</span></td>
                    <td><Severity value={event.severity} /></td>
                    <td className="muted-cell">{event.confidence == null ? "—" : `${Math.round(event.confidence * 100)}%`}</td>
                    <td><Status value={event.status} /></td>
                    <td>{event.status === "REQUIRES_MANUAL_REVIEW" && <button className="review-button" onClick={() => acknowledge(event.event_id)}>Review</button>}</td>
                  </tr>)}
                  {!visibleEvents.length && <tr><td colSpan={9} className="empty-table">No events match the current filters.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="table-footer"><span>Showing <strong>{visibleEvents.length}</strong> of <strong>{events.length}</strong> events</span><span><span className="pulse-dot" /> Live event stream {connected ? "active" : "reconnecting"}</span></div>
          </section>
          <footer>EDGEPORT · AIRPORT EDGE PLATFORM <span>Mock data only · No real identity information</span></footer>
        </div>
      </main>
      {toast && <div className="toast"><span><Check size={16} /></span>{toast}<button onClick={() => setToast("")} aria-label="Dismiss"><X size={15} /></button></div>}
    </div>
  );
}

/** Display one aggregate metric with its icon and contextual caption. */
function Metric({ icon, label, value, trend, tint }: { icon: ReactNode; label: string; value: string; trend: string; tint: string }) {
  return <article className="metric-card"><div className={`metric-icon ${tint}`}>{icon}</div><div className="metric-label">{label}</div><div className="metric-bottom"><strong>{value}</strong><span>{trend}</span></div></article>;
}
/** Render a workflow or device state using its matching visual treatment. */
function Status({ value }: { value: string }) {
  const ok = ["ONLINE", "VERIFIED", "COMPLETED", "ACKNOWLEDGED", "RESOLVED"].includes(value);
  const bad = ["OFFLINE", "FAILED", "CRITICAL"].includes(value);
  return <span className={`status-pill ${ok ? "ok" : bad ? "bad" : "pending"}`}><i />{value.replaceAll("_", " ")}</span>;
}
/** Render an event severity label with a color-coded indicator. */
function Severity({ value }: { value: string }) {
  return <span className={`severity ${value.toLowerCase()}`}><i />{value}</span>;
}
/** Display one named identity, boarding-pass, or check-in verification state. */
function Verification({ label, value }: { label: string; value: string }) {
  return <div className="verification-row"><span>{label}</span><Status value={value} /></div>;
}
/** Present a device simulation action and its purpose in the dashboard. */
function SimulationCard({ icon, title, description, button, onClick, busy }: { icon: ReactNode; title: string; description: string; button: string; onClick: () => void; busy: boolean }) {
  return <article className="simulation-card"><div className="simulation-icon">{icon}</div><div><h3>{title}</h3><p>{description}</p></div><button disabled={busy} onClick={onClick}>{button}<span>↗</span></button></article>;
}
/** Format a device's last-seen timestamp as a short elapsed-time label. */
function timeAgo(value: string) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  return seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`;
}

export default App;
