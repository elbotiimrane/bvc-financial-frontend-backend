import { useState, useEffect, useRef, useCallback, useMemo } from "react";

// ─── Sub-components ──────────────────────────────────────────────────────────

const AgentLog = ({ entries }) => {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries]);
  const levelColors = {
    INFO: "#f0b429", SUCCESS: "#4ade80", WARN: "#fb923c",
    ERROR: "#f87171", DATA: "#60a5fa", AGENT: "#c084fc", DONE: "#4ade80",
  };
  return (
    <div ref={ref} style={{ height: "240px", overflowY: "auto", background: "#0a0a0a", border: "1px solid #2a2a2a", borderRadius: "4px", padding: "12px", fontFamily: "'Courier New',monospace", fontSize: "12px", lineHeight: "1.7" }}>
      {entries.map((e, i) => (
        <div key={i} style={{ display: "flex", gap: "10px" }}>
          <span style={{ color: "#555", flexShrink: 0 }}>{e.time || "--:--:--"}</span>
          <span style={{ color: levelColors[e.level] || "#aaa", flexShrink: 0, width: "62px" }}>[{e.level}]</span>
          <span style={{ color: "#d4c5a0" }}>{e.msg}</span>
        </div>
      ))}
      {entries.length === 0 && (
        <span style={{ color: "#444" }}>Agent idle. Press START AGENT to begin real data collection from Avito.ma + Mubawab.ma...</span>
      )}
    </div>
  );
};

const StatCard = ({ label, value, sub, accent }) => (
  <div style={{ background: "#111", border: `1px solid ${accent || "#2a2a2a"}`, borderRadius: "4px", padding: "16px 20px", position: "relative", overflow: "hidden" }}>
    <div style={{ position: "absolute", top: 0, left: 0, width: "3px", height: "100%", background: accent || "#f0b429" }} />
    <div style={{ color: "#666", fontSize: "10px", letterSpacing: "2px", marginBottom: "8px" }}>{label.toUpperCase()}</div>
    <div style={{ color: "#f0e8d0", fontSize: "24px", fontWeight: "700", fontFamily: "'Courier New',monospace" }}>{value}</div>
    {sub && <div style={{ color: "#555", fontSize: "10px", marginTop: "4px" }}>{sub}</div>}
  </div>
);

const CityBar = ({ city, value, max, count }) => {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div style={{ marginBottom: "10px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
        <span style={{ fontSize: "11px", color: "#c5b990" }}>{city}</span>
        <span style={{ fontSize: "11px", fontFamily: "monospace", color: "#f0b429" }}>
          {value.toLocaleString()} MAD/m² <span style={{ color: "#555" }}>({count})</span>
        </span>
      </div>
      <div style={{ height: "4px", background: "#1a1a1a", borderRadius: "2px" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: "linear-gradient(90deg,#f0b429,#fb923c)", borderRadius: "2px", transition: "width 0.6s ease" }} />
      </div>
    </div>
  );
};

// ─── Main App ────────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;
const PIPELINE_STAGES = ["Discovery", "Scraping", "Cleaning", "Storage"];

export default function App() {
  const [running, setRunning] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [listings, setListings] = useState([]);
  const [stats, setStats] = useState(null);
  const [logs, setLogs] = useState([]);
  const [pipelineStage, setPipelineStage] = useState(-1);
  const [liveCount, setLiveCount] = useState(0);
  const [backendOk, setBackendOk] = useState(null); // null=checking, true/false
  const [page, setPage] = useState(1);
  const [filterCity, setFilterCity] = useState("All");
  const [filterTxn, setFilterTxn] = useState("All");
  const [filterType, setFilterType] = useState("All");
  const [sortCol, setSortCol] = useState("scraped_at");
  const [sortDir, setSortDir] = useState("desc");
  const [search, setSearch] = useState("");

  const esRef = useRef(null);

  // Check backend health on mount
  useEffect(() => {
    fetch("/api/health")
      .then(r => r.json())
      .then(d => {
        setBackendOk(true);
        if (d.listings_in_db > 0) {
          setLoaded(true);
        }
      })
      .catch(() => setBackendOk(false));
  }, []);

  const addLog = useCallback((entry) => {
    setLogs(prev => [...prev.slice(-300), entry]);
  }, []);

  const fetchListings = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (filterCity !== "All") params.set("city", filterCity);
      if (filterTxn !== "All") params.set("txn", filterTxn);
      if (filterType !== "All") params.set("prop_type", filterType);
      if (search.trim()) params.set("q", search.trim());
      const res = await fetch(`/api/listings?${params}`);
      const data = await res.json();
      setListings(data.listings || []);
    } catch (e) {
      console.error("Failed to fetch listings:", e);
    }
  }, [filterCity, filterTxn, filterType, search]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch("/api/stats");
      const data = await res.json();
      setStats(data);
    } catch {}
  }, []);

  const handleExport = async () => {
    try {
      const response = await fetch("/api/export");
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "morocco-real-estate-listings.csv";
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Export failed", err);
    }
  };

  // Re-fetch when filters change (if already loaded)
  useEffect(() => {
    if (loaded) {
      fetchListings();
      fetchStats();
      setPage(1);
    }
  }, [filterCity, filterTxn, filterType, search, loaded, fetchListings, fetchStats]);

  const handleStart = async () => {
    if (running) return;

    setRunning(true);
    setLoaded(false);
    setListings([]);
    setStats(null);
    setLogs([]);
    setLiveCount(0);
    setPipelineStage(0);
    setPage(1);

    // Start scrape on backend
    try {
      const res = await fetch("/api/scrape/start", { method: "POST" });
      const d = await res.json();
      if (!d.ok) {
        if (d.msg === "Scrape already running") {
          addLog({ time: new Date().toISOString().slice(11, 19), level: "INFO", msg: "Reconnected to running scrape." });
        } else {
          addLog({ time: "--:--:--", level: "WARN", msg: d.msg || "Could not start scrape" });
          setRunning(false);
          return;
        }
      }
    } catch (e) {
      addLog({ time: "--:--:--", level: "ERROR", msg: "Cannot reach backend. Is it running on port 8000?" });
      setRunning(false);
      return;
    }

    // Connect SSE for live log streaming
    if (esRef.current) esRef.current.close();
    const es = new EventSource("/api/scrape/status");
    esRef.current = es;

    let stageIdx = 0;
    const stageKeywords = ["discovery", "scraping", "avito", "mubawab", "sarouty", "cleaning", "dedup", "storage", "complete"];

    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data);

        if (entry.msg === "__DONE__") {
          es.close();
          setRunning(false);
          setPipelineStage(PIPELINE_STAGES.length);
          fetchListings();
          fetchStats();
          setLoaded(true);
          return;
        }

        addLog(entry);

        // Advance pipeline stage based on log content
        const lower = (entry.msg || "").toLowerCase();
        if (lower.includes("phase 1") || lower.includes("avito")) setPipelineStage(1);
        else if (lower.includes("phase 2") || lower.includes("mubawab")) setPipelineStage(1);
        else if (lower.includes("phase 3") || lower.includes("sarouty")) setPipelineStage(1);
        else if (lower.includes("stored") || lower.includes("complete") || lower.includes("pipeline")) setPipelineStage(3);

        // Update live count
        const m = lower.match(/(\d[\d,]+)\s*listings?(?: in database| stored)/);
        if (m) setLiveCount(parseInt(m[1].replace(/,/g, "")));

      } catch {}
    };

    es.onerror = () => {
      es.close();
      setRunning(false);
    };
  };

  const handleStop = async () => {
    if (esRef.current) esRef.current.close();
    setRunning(false);
    setPipelineStage(-1);
    addLog({ time: new Date().toISOString().slice(11, 19), level: "WARN", msg: "Agent manually stopped by operator." });
  };

  // ── Sorting ────────────────────────────────────────────────────────────────
  const sortedListings = useMemo(() => {
    return [...listings].sort((a, b) => {
      let av = a[sortCol], bv = b[sortCol];
      if (av === null || av === undefined) av = "";
      if (bv === null || bv === undefined) bv = "";
      if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortDir === "asc" ? av - bv : bv - av;
    });
  }, [listings, sortCol, sortDir]);

  const totalPages = Math.ceil(sortedListings.length / PAGE_SIZE);
  const pageData = sortedListings.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const toggleSort = col => {
    if (sortCol === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir("asc"); }
    setPage(1);
  };
  const sortArrow = col => sortCol === col ? (sortDir === "asc" ? " ↑" : " ↓") : "";

  // ── Filter options from data ───────────────────────────────────────────────
  const cities = useMemo(() => ["All", ...new Set(listings.map(l => l.city).filter(Boolean)).values()].sort(), [listings]);
  const types  = useMemo(() => ["All", ...new Set(listings.map(l => l.type).filter(Boolean)).values()].sort(), [listings]);

  // ── Display stats ──────────────────────────────────────────────────────────
  const displayStats = stats || {
    total: listings.length,
    sales: listings.filter(l => l.transaction === "Vente").length,
    rents: listings.filter(l => l.transaction === "Location").length,
    avg_price_per_sqm: 0,
    cities: [],
    types: [],
  };
  const maxAvg = displayStats.cities[0]?.avg_ppsm || 1;

  const thStyle = {
    padding: "9px 10px", textAlign: "left", color: "#555", fontSize: "9px",
    letterSpacing: "1px", borderBottom: "1px solid #1f1f1f",
    whiteSpace: "nowrap", cursor: "pointer", userSelect: "none",
  };
  const tdStyle = {
    padding: "8px 10px", fontSize: "11px", color: "#c5b990",
    borderBottom: "1px solid #0f0f0f", whiteSpace: "nowrap",
    fontFamily: "'EB Garamond',serif",
  };

  return (
    <div style={{ minHeight: "100vh", background: "#080808", color: "#d4c5a0", fontFamily: "'Georgia',serif", padding: "24px" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=IBM+Plex+Mono:wght@400;600&family=EB+Garamond:wght@400;500&display=swap');
        * { box-sizing:border-box; margin:0; padding:0; }
        ::-webkit-scrollbar { width:4px; height:4px; }
        ::-webkit-scrollbar-track { background:#111; }
        ::-webkit-scrollbar-thumb { background:#f0b429; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        @keyframes slideIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
        .tr-hover:hover td { background:#111008 !important; }
      `}</style>

      {/* ── Header ── */}
      <div style={{ borderBottom: "1px solid #2a2a2a", paddingBottom: "20px", marginBottom: "24px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ color: "#f0b429", fontSize: "9px", letterSpacing: "4px", marginBottom: "8px" }}>
              SYSTÈME AGENT IA — MAROC IMMOBILIER
            </div>
            <h1 style={{ fontFamily: "'Playfair Display',serif", fontSize: "26px", fontWeight: "900", color: "#f5edd8", letterSpacing: "-0.5px" }}>
              Real Estate Data Agent
            </h1>
            <div style={{ color: "#666", fontSize: "12px", marginTop: "4px", fontFamily: "'IBM Plex Mono',monospace" }}>
              Live scraping · Avito + Mubawab + Sarouty · 12 cities · SQLite storage
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "8px" }}>
            {/* Backend status */}
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: backendOk === null ? "#666" : backendOk ? "#4ade80" : "#f87171", animation: backendOk ? "none" : "pulse 1s infinite" }} />
              <span style={{ fontSize: "10px", fontFamily: "monospace", color: backendOk === null ? "#555" : backendOk ? "#4ade80" : "#f87171" }}>
                {backendOk === null ? "Checking backend..." : backendOk ? "Backend ✓ port 8000" : "Backend offline — start it first!"}
              </span>
            </div>
            <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
              <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: running ? "#4ade80" : "#444", animation: running ? "pulse 1s infinite" : "none" }} />
              <span style={{ fontFamily: "'IBM Plex Mono',monospace", fontSize: "11px", color: running ? "#4ade80" : "#555" }}>
                {running ? `AGENT RUNNING — ${liveCount.toLocaleString()} scraped` : "STANDBY"}
              </span>
              <button onClick={running ? handleStop : handleStart} disabled={backendOk === false}
                style={{ background: running ? "transparent" : backendOk === false ? "#2a2a2a" : "#f0b429", color: running ? "#f87171" : backendOk === false ? "#555" : "#0a0a0a", border: running ? "1px solid #f87171" : "none", padding: "8px 18px", fontFamily: "'IBM Plex Mono',monospace", fontSize: "11px", letterSpacing: "1px", cursor: backendOk === false ? "not-allowed" : "pointer", borderRadius: "2px", fontWeight: "600" }}>
                {running ? "STOP AGENT" : "START AGENT"}
              </button>
              <button onClick={handleExport} disabled={listings.length === 0}
                style={{ background: "#222", color: listings.length === 0 ? "#444" : "#4ade80", border: "1px solid #333", padding: "8px 14px", fontFamily: "'IBM Plex Mono',monospace", fontSize: "11px", letterSpacing: "1px", cursor: listings.length === 0 ? "not-allowed" : "pointer", borderRadius: "2px" }}>
                EXPORT CSV
              </button>
            </div>
          </div>
        </div>

        {/* Backend offline warning */}
        {backendOk === false && (
          <div style={{ marginTop: "16px", background: "#1a0808", border: "1px solid #f87171", borderRadius: "4px", padding: "12px 16px", fontFamily: "monospace", fontSize: "12px", color: "#f87171" }}>
            ⚠ Backend is not running. Open a terminal and run:<br />
            <span style={{ color: "#f0b429" }}>cd backend &amp;&amp; pip install -r requirements.txt &amp;&amp; python -m uvicorn main:app --reload --port 8000</span>
          </div>
        )}
      </div>

      {/* ── Stat Cards ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: "10px", marginBottom: "20px" }}>
        <StatCard label="Total Listings" value={(displayStats.total || 0).toLocaleString()} sub="real data from 3 sources" accent="#f0b429"/>
        <StatCard label="Ventes" value={(displayStats.sales || 0).toLocaleString()} sub="for sale" accent="#4ade80"/>
        <StatCard label="Locations" value={(displayStats.rents || 0).toLocaleString()} sub="for rent" accent="#60a5fa"/>
        <StatCard label="Avg MAD/m²" value={(displayStats.avg_price_per_sqm || 0).toLocaleString()} sub="national avg · sales" accent="#fb923c"/>
        <StatCard label="Cities" value={displayStats.cities?.length || 0} sub="covered" accent="#c084fc"/>
      </div>

      {/* ── Pipeline + Logs ── */}
      <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: "14px", marginBottom: "18px" }}>
        <div style={{ background: "#0f0f0f", border: "1px solid #1f1f1f", borderRadius: "4px", padding: "16px 14px" }}>
          <div style={{ color: "#555", fontSize: "9px", letterSpacing: "3px", marginBottom: "14px" }}>PIPELINE</div>
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {PIPELINE_STAGES.map((s, i) => {
              const status = pipelineStage >= PIPELINE_STAGES.length ? "done" : pipelineStage > i ? "done" : pipelineStage === i ? "active" : "idle";
              const colors = { done: "#f0b429", active: "#fff", idle: "#333" };
              const tc = { done: "#f0b429", active: "#fff", idle: "#444" };
              return (
                <div key={s} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: colors[status], boxShadow: status === "active" ? "0 0 8px #fff" : "none", animation: status === "active" ? "pulse 1s infinite" : "none" }} />
                  <span style={{ color: tc[status], fontSize: "12px", letterSpacing: "1px" }}>{s}</span>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: "20px", color: "#555", fontSize: "9px", letterSpacing: "2px", marginBottom: "8px" }}>SOURCES</div>
          {["Avito.ma", "Mubawab.ma", "Sarouty.ma"].map(src => (
            <div key={src} style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" }}>
              <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: running || loaded ? "#f0b429" : "#333" }} />
              <span style={{ fontSize: "10px", color: running || loaded ? "#f0b429" : "#444" }}>{src}</span>
            </div>
          ))}
        </div>
        <div>
          <div style={{ color: "#555", fontSize: "9px", letterSpacing: "3px", marginBottom: "8px" }}>AGENT LOGS — LIVE</div>
          <AgentLog entries={logs} />
        </div>
      </div>

      {/* ── Analytics Charts (shown after data loads) ── */}
      {loaded && displayStats.cities.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px", marginBottom: "18px" }}>
          <div style={{ background: "#0f0f0f", border: "1px solid #1f1f1f", borderRadius: "4px", padding: "18px 20px" }}>
            <div style={{ color: "#555", fontSize: "9px", letterSpacing: "3px", marginBottom: "16px" }}>PRIX MOYEN/m² PAR VILLE — DONNÉES RÉELLES AVITO</div>
            {displayStats.cities.map(({ city, avg_ppsm, count }) => (
              <CityBar key={city} city={city} value={Math.round(avg_ppsm || 0)} max={maxAvg} count={count} />
            ))}
          </div>
          <div style={{ background: "#0f0f0f", border: "1px solid #1f1f1f", borderRadius: "4px", padding: "18px 20px" }}>
            <div style={{ color: "#555", fontSize: "9px", letterSpacing: "3px", marginBottom: "16px" }}>RÉPARTITION PAR TYPE DE BIEN — {displayStats.total.toLocaleString()} ANNONCES</div>
            {displayStats.types.map(({ type, count }) => {
              const pct = displayStats.total > 0 ? (count / displayStats.total) * 100 : 0;
              return (
                <div key={type} style={{ marginBottom: "9px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                    <span style={{ fontSize: "11px", color: "#c5b990" }}>{type || "Autre"}</span>
                    <span style={{ fontSize: "11px", fontFamily: "monospace", color: "#60a5fa" }}>
                      {count.toLocaleString()} <span style={{ color: "#444" }}>({pct.toFixed(1)}%)</span>
                    </span>
                  </div>
                  <div style={{ height: "3px", background: "#1a1a1a", borderRadius: "2px" }}>
                    <div style={{ height: "100%", width: `${Math.min(pct * 5, 100)}%`, background: "linear-gradient(90deg,#60a5fa,#c084fc)", borderRadius: "2px" }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Filters ── */}
      {loaded && (
        <div style={{ display: "flex", gap: "10px", marginBottom: "12px", alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ color: "#555", fontSize: "9px", letterSpacing: "2px", marginRight: "4px" }}>FILTRES:</div>
          {[
            ["filterCity", filterCity, setFilterCity, cities],
            ["filterTxn", filterTxn, setFilterTxn, ["All", "Vente", "Location"]],
            ["filterType", filterType, setFilterType, types],
          ].map(([key, val, setter, opts]) => (
            <select key={key} value={val} onChange={e => { setter(e.target.value); setPage(1); }}
              style={{ background: "#111", color: "#d4c5a0", border: "1px solid #2a2a2a", padding: "5px 10px", fontSize: "11px", fontFamily: "'IBM Plex Mono',monospace", borderRadius: "2px", cursor: "pointer" }}>
              {opts.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          ))}
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Rechercher par titre, ville, quartier…"
            style={{ background: "#111", color: "#d4c5a0", border: "1px solid #2a2a2a", padding: "5px 10px", fontSize: "11px", fontFamily: "'IBM Plex Mono',monospace", borderRadius: "2px", outline: "none", minWidth: "240px" }} />
          <span style={{ color: "#555", fontSize: "10px", fontFamily: "monospace", marginLeft: "auto" }}>
            {listings.length.toLocaleString()} résultats · page {page}/{totalPages || 1}
          </span>
        </div>
      )}

      {/* ── Data Table ── */}
      {loaded && listings.length > 0 && (
        <div>
          <div style={{ overflowX: "auto", border: "1px solid #1f1f1f", borderRadius: "4px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "#0d0d0d" }}>
                  {[
                    ["id", "ID"], ["status", "Status"], ["transaction", "Txn"], ["type", "Type"], ["city", "Ville"],
                    ["neighborhood", "Quartier"], ["surface", "Surf."], ["rooms", "Ch."],
                    ["price", "Prix (MAD)"], ["price_per_sqm", "MAD/m²"],
                    ["date_listing", "Annonce"], ["source", "Source"], ["seller", "Vendeur"], ["scraped_at", "Collecté"],
                  ].map(([col, label]) => (
                    <th key={col} style={thStyle} onClick={() => toggleSort(col)}>
                      {label.toUpperCase()}{sortArrow(col)}
                    </th>
                  ))}
                  <th style={thStyle}>LIEN</th>
                </tr>
              </thead>
              <tbody>
                {pageData.map((l, i) => (
                  <tr key={l.id} className="tr-hover" style={{ background: i % 2 === 0 ? "#080808" : "#090908" }}>
                    <td style={tdStyle}><span style={{ color: "#f0b429", fontFamily: "monospace", fontSize: "10px" }}>{l.id}</span></td>
                    <td style={tdStyle}>
                      <span style={{ 
                        padding: "2px 6px", 
                        borderRadius: "2px", 
                        fontSize: "9px", 
                        textTransform: "uppercase",
                        background: l.status === "Vendu" ? "#1a0808" : "#081a08",
                        color: l.status === "Vendu" ? "#f87171" : "#4ade80",
                        border: `1px solid ${l.status === "Vendu" ? "#311" : "#131"}`
                      }}>
                        {l.status || "Actif"}
                      </span>
                    </td>
                    <td style={tdStyle}><span style={{ color: l.transaction === "Vente" ? "#4ade80" : "#60a5fa", fontSize: "10px", fontFamily: "monospace" }}>{l.transaction}</span></td>
                    <td style={tdStyle}>{l.type}</td>
                    <td style={tdStyle}><span style={{ color: "#c084fc" }}>{l.city}</span></td>
                    <td style={tdStyle}><span style={{ color: "#999" }}>{l.neighborhood}</span></td>
                    <td style={tdStyle}>{l.surface ? `${l.surface} m²` : "—"}</td>
                    <td style={tdStyle}>{l.rooms || "—"}</td>
                    <td style={tdStyle}><span style={{ fontFamily: "monospace" }}>{l.price ? l.price.toLocaleString() : "—"}</span></td>
                    <td style={tdStyle}><span style={{ fontFamily: "monospace", color: "#f0b429" }}>{l.price_per_sqm ? l.price_per_sqm.toLocaleString() : "—"}</span></td>
                    <td style={tdStyle}><span style={{ color: "#d4c5a0", fontSize: "10px" }}>{l.date_listing || "—"}</span></td>
                    <td style={tdStyle}><span style={{ color: "#666", fontSize: "10px" }}>{l.source}</span></td>
                    <td style={tdStyle}><span style={{ color: "#888", fontSize: "10px" }}>{l.seller?.slice(0, 20)}</span></td>
                    <td style={tdStyle}><span style={{ color: "#555", fontSize: "10px" }}>{l.scraped_at?.slice(0, 10)}</span></td>
                    <td style={tdStyle}>
                      {l.url && (
                        <a href={l.url} target="_blank" rel="noreferrer"
                          style={{ color: "#f0b429", fontSize: "10px", fontFamily: "monospace", textDecoration: "none" }}>
                          →
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div style={{ display: "flex", gap: "6px", marginTop: "12px", alignItems: "center", justifyContent: "center", flexWrap: "wrap" }}>
            <button onClick={() => setPage(1)} disabled={page === 1} style={{ ...pBtn, opacity: page === 1 ? 0.3 : 1 }}>«</button>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} style={{ ...pBtn, opacity: page === 1 ? 0.3 : 1 }}>‹</button>
            {Array.from({ length: Math.min(9, totalPages) }, (_, i) => {
              const start = Math.max(1, Math.min(page - 4, totalPages - 8));
              const pg = start + i;
              return pg <= totalPages ? (
                <button key={pg} onClick={() => setPage(pg)}
                  style={{ ...pBtn, background: pg === page ? "#f0b429" : "transparent", color: pg === page ? "#0a0a0a" : "#888", borderColor: pg === page ? "#f0b429" : "#2a2a2a" }}>
                  {pg}
                </button>
              ) : null;
            })}
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} style={{ ...pBtn, opacity: page === totalPages ? 0.3 : 1 }}>›</button>
            <button onClick={() => setPage(totalPages)} disabled={page === totalPages} style={{ ...pBtn, opacity: page === totalPages ? 0.3 : 1 }}>»</button>
            <span style={{ color: "#444", fontSize: "10px", fontFamily: "monospace", marginLeft: "10px" }}>
              {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{Math.min(page * PAGE_SIZE, listings.length).toLocaleString()} / {listings.length.toLocaleString()}
            </span>
          </div>

          <div style={{ color: "#333", fontSize: "10px", marginTop: "8px", fontFamily: "'IBM Plex Mono',monospace", textAlign: "center" }}>
            Données réelles scrappées depuis Avito.ma + Mubawab.ma · SQLite backend · Cliquer → pour voir l'annonce originale
          </div>
        </div>
      )}

      {/* Empty state */}
      {loaded && listings.length === 0 && (
        <div style={{ textAlign: "center", padding: "60px", color: "#444", fontFamily: "monospace", fontSize: "13px" }}>
          No listings in database matching current filters.<br />
          <span style={{ color: "#f0b429" }}>Press START AGENT to scrape real data.</span>
        </div>
      )}
    </div>
  );
}

const pBtn = {
  background: "transparent", color: "#888", border: "1px solid #2a2a2a",
  padding: "5px 10px", fontFamily: "'IBM Plex Mono',monospace",
  fontSize: "11px", cursor: "pointer", borderRadius: "2px", minWidth: "32px",
};
