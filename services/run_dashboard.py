"""
services/run_dashboard.py — TEDENG Live Dashboard

Displays:
1. Signal Engine (Live model predictions & confidence)
2. Market Explorer (Search & Chart any Alpaca/Binance symbol)
3. Trading & Portfolio (Execution logs and open paper trades)

Usage:
    streamlit run services/run_dashboard.py
"""

from __future__ import annotations
import sys
import os
import time
from datetime import datetime, timezone, timedelta
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from middleware.file_store import read_all, read_latest, read_all_executions

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG & CSS
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TEDENG — Live Prediction Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load Premium CSS
css_path = os.path.join(os.path.dirname(__file__), "style.css")
if os.path.exists(css_path):
    with open(css_path, "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
else:
    st.warning("style.css not found.")
    
def color_pnl(val):
    if pd.isna(val):
        return ''
    try:
        fval = float(val)
        color = '#10b981' if fval > 0 else '#ef4444' if fval < 0 else '#94a3b8'
        return f'color: {color}; font-weight: bold;'
    except ValueError:
        return ''

# ─────────────────────────────────────────────────────────────────────────────
# CHART HELPERS
# ─────────────────────────────────────────────────────────────────────────────
_BG   = "rgba(0,0,0,0)"
_GRID = "rgba(99,179,237,0.08)"
_TICK = "#718096"

def gauge(value: float) -> go.Figure:
    color = "#48bb78" if value > 0.05 else "#f56565" if value < -0.05 else "#718096"
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"font": {"size": 40, "color": color, "family": "Inter"}, "valueformat": "+.3f"},
        title={"text": "Direction  [ −1 SHORT → +1 LONG ]", "font": {"size": 11, "color": "#63b3ed", "family": "Inter"}},
        gauge={
            "axis": {"range": [-1, 1], "tickvals": [-1,-0.5,0,0.5,1], "tickcolor": _TICK, "tickfont": {"size": 10, "color": _TICK}},
            "bar": {"color": color, "thickness": 0.28},
            "bgcolor": "rgba(10,20,40,0.8)", "borderwidth": 0,
            "steps": [
                {"range": [-1, -0.33], "color": "rgba(245,101,101,0.12)"},
                {"range": [-0.33,0.33], "color": "rgba(113,128,150,0.08)"},
                {"range": [0.33, 1],   "color": "rgba(72,187,120,0.12)"},
            ],
        },
    ))
    fig.update_layout(paper_bgcolor=_BG, plot_bgcolor=_BG, margin=dict(l=20,r=20,t=50,b=10), height=230, font_family="Inter")
    return fig

def conf_bar(conf: float) -> go.Figure:
    color = "#48bb78" if conf > config.MIN_CONFIDENCE_THRESHOLD else "#ed8936" if conf > 0.2 else "#f56565"
    fig = go.Figure(go.Bar(
        x=[conf], y=[""], orientation="h", marker_color=color, marker_line_width=0, width=0.5,
        text=[f"{conf:.1%}"], textposition="inside", textfont={"size": 15, "color": "white", "family": "Inter"},
    ))
    fig.update_layout(paper_bgcolor=_BG, plot_bgcolor=_BG, xaxis=dict(range=[0,1], showticklabels=False, showgrid=False, zeroline=False), yaxis=dict(showticklabels=False, showgrid=False), margin=dict(l=0,r=0,t=0,b=0), height=60, font_family="Inter")
    return fig

def model_bars(per_model: dict) -> go.Figure:
    labels = {"ridge": "Ridge", "xgb": "XGBoost", "lstm": "LSTM"}
    models = list(per_model.keys())
    values = [per_model[m] for m in models]
    colors = ["#48bb78" if v > 0 else "#f56565" for v in values]
    fig = go.Figure(go.Bar(
        x=[labels.get(m, m) for m in models], y=values, marker_color=colors, marker_line_width=0,
        text=[f"{v:+.3f}" for v in values], textposition="outside", textfont={"size": 13, "color": "#e2e8f0", "family": "Inter"},
    ))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.15)", line_width=1)
    fig.update_layout(paper_bgcolor=_BG, plot_bgcolor=_BG, xaxis=dict(showgrid=False, tickfont={"color":"#a0aec0","size":12}), yaxis=dict(range=[-1.2,1.2], gridcolor=_GRID, tickfont={"color":_TICK,"size":10}, zeroline=False), margin=dict(l=10,r=10,t=30,b=10), height=230, font_family="Inter", bargap=0.35)
    return fig

def history_chart(history: list[dict]) -> go.Figure:
    if not history: return go.Figure()
    ts   = [datetime.fromtimestamp(h["timestamp_generated"], tz=timezone.utc) for h in history]
    dirs = [h["direction_magnitude"] for h in history]
    confs= [h["confidence_score"] for h in history]
    fig  = go.Figure()
    fig.add_trace(go.Scatter(x=ts, y=[c*0.5 for c in confs], name="Confidence (½ scale)", fill="tozeroy", fillcolor="rgba(99,179,237,0.07)", line=dict(color="rgba(99,179,237,0.25)", width=1), mode="lines"))
    fig.add_trace(go.Scatter(x=ts, y=dirs, name="Direction", line=dict(color="#63b3ed", width=2), mode="lines+markers", marker=dict(size=6, color=["#48bb78" if d>0 else "#f56565" for d in dirs], line=dict(color="white", width=1))))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.12)", line_width=1, line_dash="dot")
    fig.update_layout(paper_bgcolor=_BG, plot_bgcolor=_BG, xaxis=dict(showgrid=False, tickfont={"color":_TICK,"size":10}, zeroline=False), yaxis=dict(range=[-1.2,1.2], gridcolor=_GRID, tickfont={"color":_TICK,"size":10}, zeroline=False), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font={"color":"#a0aec0","size":11}, bgcolor=_BG), margin=dict(l=10,r=10,t=10,b=10), height=260, font_family="Inter", hovermode="x unified")
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHING HELPERS
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def fetch_alpaca_chart(symbol: str):
    url = f"{config.ALPACA_DATA_URL}/stocks/{symbol}/bars"
    headers = {"APCA-API-KEY-ID": config.ALPACA_API_KEY, "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET}
    end = datetime.now(timezone.utc)
    start = end - pd.Timedelta(days=60)
    # Alpaca API expects RFC-3339 datetime strings like '2023-01-01T00:00:00Z'
    params = {
        "timeframe": "1Day",
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 100,
        "feed": "iex" # Required for free tier accounts
    }
    
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code == 200 and resp.json().get("bars"):
        df = pd.DataFrame(resp.json()["bars"])
        df.index = pd.to_datetime(df["t"], utc=True)
        return df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    return None

def fetch_alpaca_account():
    url = f"{config.ALPACA_BASE_URL}/account"
    headers = {"APCA-API-KEY-ID": config.ALPACA_API_KEY, "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET}
    resp = requests.get(url, headers=headers)
    return resp.json() if resp.status_code == 200 else {}

def fetch_alpaca_positions():
    url = f"{config.ALPACA_BASE_URL}/positions"
    headers = {"APCA-API-KEY-ID": config.ALPACA_API_KEY, "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET}
    resp = requests.get(url, headers=headers)
    return resp.json() if resp.status_code == 200 else []

# ─────────────────────────────────────────────────────────────────────────────
# STATE & LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
store = read_all()
exec_store = read_all_executions()
active_instruments = [i for i in config.INSTRUMENTS if i in store and store[i]]
backend_running = bool(active_instruments)

with st.sidebar:
    st.markdown("""
    <div style="text-align:center;padding:16px 0 24px 0;">
        <div style="font-size:32px;margin-bottom:8px;">⚡</div>
        <div style="font-size:16px;font-weight:700;color:#63b3ed;letter-spacing:2px;">TEDENG</div>
        <div style="font-size:10px;color:#718096;letter-spacing:1px;text-transform:uppercase;margin-top:2px;">
            Algorithmic Trading
        </div>
    </div>""", unsafe_allow_html=True)

    nav = st.radio("Navigation", ["Prediction Engine", "Market Explorer", "Trading & Portfolio"])
    
    st.markdown("---")
    
    st.markdown("**Risk Profile**")
    st.markdown(f"Currently active: `{config.ACTIVE_RISK_PROFILE}`")
    
    st.markdown("---")
    if nav == "Prediction Engine":
        selected = st.selectbox("Instrument", options=config.INSTRUMENTS, index=0)
    
    st.markdown("**System Status**")
    for instr in config.INSTRUMENTS:
        dot = "🟢" if instr in store and store[instr] else "🔴"
        st.markdown(f"{dot} `{instr}`")
        
    st.markdown("---")
    if st.button("🔄 Force Refresh", use_container_width=True):
        st.rerun()

now_str = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
status_txt = "LIVE" if backend_running else "WAITING FOR BACKEND"

st.markdown(f"""
<div class="dashboard-header">
  <div>
    <div class="dashboard-title">⚡ TEDENG</div>
    <div style="font-size:12px;color:#718096;margin-top:2px;">{nav.upper()}</div>
  </div>
  <div style="text-align:right;">
    <div style="font-size:12px;color:#a0aec0;">
      <span class="live-dot" style="background:{'#48bb78' if backend_running else '#f56565'};"></span>
      {status_txt}
    </div>
    <div style="font-size:11px;color:#4a5568;margin-top:2px;">{now_str}</div>
  </div>
</div>""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# VIEW 1: PREDICTION ENGINE (Core Signals)
# ─────────────────────────────────────────────────────────────────────────────
if nav == "Prediction Engine":
    if not backend_running:
        st.warning("⏳ **Backend not running.** Launch `run_backend.py` in a separate terminal.")
        time.sleep(config.DASHBOARD_REFRESH_SECONDS); st.rerun()
        
    signal = read_latest(selected)
    history = store.get(selected, [])
    if not signal:
        st.info(f"No signals yet for **{selected}**.")
        time.sleep(config.DASHBOARD_REFRESH_SECONDS); st.rerun()

    direction   = signal["direction_magnitude"]
    confidence  = signal["confidence_score"]
    regime      = signal["regime_flag"]
    latency     = signal["latency_ms"]
    per_model   = signal.get("per_model", {})
    ohlcv       = signal.get("ohlcv", {})
    signal_id   = signal.get("signal_id", "—")
    
    dir_label = "LONG" if direction > 0.1 else "SHORT" if direction < -0.1 else "FLAT"
    dir_class = "signal-long" if direction > 0.1 else "signal-short" if direction < -0.1 else "signal-flat"
    regime_cls = "badge-low" if "low" in regime else "badge-high" if "high" in regime else "badge-trend"
    
    st.markdown(f'<div class="section-title">📊 Market Snapshot — {selected}</div>', unsafe_allow_html=True)
    cols = st.columns(5)
    cards = [
        ("CLOSE",  f"${ohlcv.get('close',0):,.2f}",    "Latest bar"),
        ("OPEN",   f"${ohlcv.get('open',0):,.2f}",     "Bar open"),
        ("HIGH",   f"${ohlcv.get('high',0):,.2f}",     "Bar high"),
        ("LOW",    f"${ohlcv.get('low',0):,.2f}",      "Bar low"),
        ("SIGNAL", f'<span class="{dir_class}">{dir_label}</span>', f"ID: {signal_id[:12]}…"),
    ]
    for col, (lbl, val, sub) in zip(cols, cards):
        with col:
            st.markdown(f"""<div class="metric-card"><div class="metric-label">{lbl}</div>
                <div class="metric-value">{val}</div><div class="metric-sub">{sub}</div></div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-title">🧠 Brain Output</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Direction Magnitude**")
        st.plotly_chart(gauge(direction), use_container_width=True, config={"displayModeBar":False})
        st.markdown(f'<div style="text-align:center;margin-top:-10px;"><span class="badge {regime_cls}">{regime.replace("_"," ").title()}</span></div>', unsafe_allow_html=True)
    with c2:
        st.markdown("**Confidence Score**")
        st.plotly_chart(conf_bar(confidence), use_container_width=True, config={"displayModeBar":False})
        st.markdown(f'<div style="text-align:center;margin-top:20px;color:#a0aec0;font-size:12px;">Min Threshold: {config.MIN_CONFIDENCE_THRESHOLD:.1%}</div>', unsafe_allow_html=True)
    with c3:
        st.markdown("**Per-Model Signals**")
        if per_model: st.plotly_chart(model_bars(per_model), use_container_width=True, config={"displayModeBar":False})

    st.markdown(f'<div class="section-title">📈 Signal History — {selected}</div>', unsafe_allow_html=True)
    if history: st.plotly_chart(history_chart(history), use_container_width=True, config={"displayModeBar":False})

    time.sleep(config.DASHBOARD_REFRESH_SECONDS)
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# VIEW 2: MARKET EXPLORER (Search & Chart)
# ─────────────────────────────────────────────────────────────────────────────
elif nav == "Market Explorer":
    st.markdown('<div class="section-title">🔍 Search Alpaca Market Data</div>', unsafe_allow_html=True)
    search_sym = st.text_input("Enter US Stock Symbol (e.g., TSLA, MSFT, NVDA)", "TSLA").upper().strip()
    
    if search_sym:
        with st.spinner(f"Fetching {search_sym} from Alpaca..."):
            df = fetch_alpaca_chart(search_sym)
            if df is not None and not df.empty:
                st.markdown(f"### {search_sym} (Last 60 Days)")
                fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'])])
                fig.update_layout(paper_bgcolor=_BG, plot_bgcolor=_BG, font_family="Inter", xaxis_rangeslider_visible=False, height=500,
                                  yaxis=dict(gridcolor=_GRID), xaxis=dict(gridcolor=_GRID))
                st.plotly_chart(fig, use_container_width=True)
                
                # Show raw data tail
                st.dataframe(df.tail(10)[["Open", "High", "Low", "Close", "Volume"]].sort_index(ascending=False), use_container_width=True)
            else:
                st.error(f"Could not fetch data for {search_sym}. Symbol may be invalid.")

# ─────────────────────────────────────────────────────────────────────────────
# VIEW 3: TRADING & PORTFOLIO
# ─────────────────────────────────────────────────────────────────────────────
elif nav == "Trading & Portfolio":
    # Auto-refresh every 2 seconds
    st_autorefresh(interval=2000, limit=None, key="portfolio_refresh")
    
    st.markdown('<div class="section-title">💼 Portfolio Status</div>', unsafe_allow_html=True)
    
    if config.USE_SIMULATED_FUTURES:
        st.info("🚀 **Simulated Futures Engine Active (10x Leverage)** — Bypassing Alpaca API.")
        from execution.simulated_oms import SimulatedFuturesOMS
        oms = SimulatedFuturesOMS()
        acc = oms.get_account_state()
        equity = acc.get("equity", 0.0)
        buying_power = acc.get("buying_power", 0.0)
        state = oms._read_state()
        positions = state.get("positions", {})
        total_pnl = sum(p["unrealized_pl"] for p in positions.values())
        
        pnl_class = "val-up" if total_pnl > 0 else "val-down" if total_pnl < 0 else "val-neu"
        pnl_sign = "+" if total_pnl > 0 else ""
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='metric-card'><div class='metric-label'>Simulated Net Equity</div><div class='metric-value'>${float(equity):,.2f}</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='metric-card'><div class='metric-label'>Available Buying Power (10x)</div><div class='metric-value'>${float(buying_power):,.2f}</div></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='metric-card'><div class='metric-label'>Open P/L</div><div class='metric-value {pnl_class}'>{pnl_sign}${float(total_pnl):,.2f}</div></div>", unsafe_allow_html=True)
        
        if positions:
            st.markdown('<div class="section-title">📊 Active Live Trades</div>', unsafe_allow_html=True)
            
            cards_html = "<div class='position-grid'>"
            for sym, p in positions.items():
                pl = p["unrealized_pl"]
                plpc = p["unrealized_plpc"]
                
                pl_color_class = "val-up" if pl > 0 else "val-down" if pl < 0 else "val-neu"
                pl_sign = "+" if pl > 0 else ""
                
                direction = "LONG" if p["qty"] > 0 else "SHORT"
                badge_class = "badge-long" if direction == "LONG" else "badge-short"
                
                cards_html += f'''<div class="metric-card position-card">
    <div class="pos-header">
        <span class="pos-symbol">{sym}</span>
        <span class="{badge_class}">{direction}</span>
    </div>
    <div class="pos-row">
        <span class="pos-label">Qty</span>
        <span class="pos-value">{abs(p["qty"]):.4f}</span>
    </div>
    <div class="pos-row">
        <span class="pos-label">Entry</span>
        <span class="pos-value">${p["entry_price"]:,.2f}</span>
    </div>
    <div class="pos-row-mb">
        <span class="pos-label">Market</span>
        <span class="pos-value">${p["current_price"]:,.2f}</span>
    </div>
    <div class="pos-footer">
        <span class="pos-label">Unrealized P/L</span>
        <span class="{pl_color_class} pos-pnl-val">{pl_sign}${pl:,.2f} <span class="pos-pnl-pct">({pl_sign}{plpc:.2%})</span></span>
    </div>
</div>'''
            cards_html += "</div>"
            st.markdown(cards_html, unsafe_allow_html=True)
            
        else:
            st.info("No active simulated positions.")
            
    else:
        st.markdown('**Alpaca Paper Portfolio**')
        acc = fetch_alpaca_account()
        equity = acc.get("equity", 0.0)
        buying_power = acc.get("buying_power", 0.0)
        
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"<div class='metric-card'><div class='metric-label'>Total Equity</div><div class='metric-value'>${float(equity):,.2f}</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='metric-card'><div class='metric-label'>Buying Power</div><div class='metric-value'>${float(buying_power):,.2f}</div></div>", unsafe_allow_html=True)
        
        positions = fetch_alpaca_positions()
        if positions:
            st.markdown("### Open Positions")
            df = pd.DataFrame(positions)
            if not df.empty:
                # Ensure the columns exist before trying to style them
                if 'unrealized_pl' in df.columns:
                    df['unrealized_pl'] = pd.to_numeric(df['unrealized_pl'], errors='coerce')
                if 'unrealized_plpc' in df.columns:
                    df['unrealized_plpc'] = pd.to_numeric(df['unrealized_plpc'], errors='coerce')
                styled_df = df[["symbol", "qty", "market_value", "unrealized_pl", "unrealized_plpc"]].style.map(color_pnl, subset=['unrealized_pl', 'unrealized_plpc']).format({
                    'unrealized_pl': '${:.2f}',
                    'unrealized_plpc': '{:.2%}'
                })
                st.dataframe(styled_df, use_container_width=True)
            else:
                st.info("No open positions on Alpaca.")
        else:
            st.info("No open positions on Alpaca.")
            
    st.markdown('<div class="section-title">📜 Bot Execution Logs</div>', unsafe_allow_html=True)
    if exec_store:
        rows = []
        for e in reversed(exec_store[-100:]):
            ts_utc = datetime.fromtimestamp(e.get("risk_check_timestamp", 0), tz=timezone.utc)
            ts_ist = ts_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
            rows.append({
                "Time (IST)": ts_ist.strftime("%m-%d %H:%M:%S"),
                "Instrument": e.get("instrument"),
                "Action": e.get("action"),
                "Alloc %": f"{e.get('portfolio_allocation_pct', 0):.1%}",
                "Risk State": e.get("risk_state"),
                "OMS State": e.get("oms_state", "N/A"),
                "Detail": e.get("detail", e.get("oms_detail", ""))
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        if st.button("🔄 Auto-Refresh Trading Logs"):
            st.rerun()
    else:
        st.info("No executions recorded yet. (Bot might be holding or waiting for confidence).")

