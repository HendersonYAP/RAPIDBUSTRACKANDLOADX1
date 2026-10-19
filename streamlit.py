import logging
import re
import time
from datetime import datetime
from typing import Dict, List

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup


# Page configuration
st.set_page_config(page_title="Rapid Bus KL Live Tracker", page_icon="🚌", layout="wide")


# Monitored Routes Configuration
TARGET_ROUTES: Dict[str, Dict[str, str]] = {
    "300": {"kiosk_id": "474", "label": "U300 / Lebuh Ampang - Terminal Pudu"},
    "420": {"kiosk_id": "481", "label": "U420 / Pandan Indah - Lebuh Ampang"},
    "450": {"kiosk_id": "483", "label": "U450 / Terminal Selatan - Lebuh Ampang"},
    "600": {"kiosk_id": "678", "label": "U600 / Puchong Utama - Pasar Seni"},
    "640": {"kiosk_id": "714", "label": "U640 / Taman Sri Manja - Pasar Seni"},
    "751": {"kiosk_id": "497", "label": "U751 / UiTM Puncak Alam - Taman Sri Muda"},
    "772": {"kiosk_id": "834", "label": "U772 / Subang Suria - Pasar Seni"},
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://myrapidbus.prasarana.com.my/kiosk",
    "X-Requested-With": "XMLHttpRequest",
}


# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("rapidbus")


@st.cache_data(ttl=15)
def fetch_live_bus_data() -> pd.DataFrame:
    """Fetch real-time bus telemetry & Device ID (DiD) from MyRapidBus Kiosk endpoints.

    Returns a pandas DataFrame with discovered vehicles for all TARGET_ROUTES.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    all_buses: List[Dict[str, str]] = []

    # HTML parsing regex (captures Bus Code, Device ID, GPS Time, Speed, Sub-Route)
    pattern = re.compile(
        r"<b>(.*?)\s*\((.*?)\)</b>.*?GPS:\s*(.*?)<br>.*?Speed:\s*(.*?)<br>.*?Route:\s*(.*?)(?:<br>|<span|$)",
        re.DOTALL | re.IGNORECASE,
    )

    for route_number, config in TARGET_ROUTES.items():
        url = f"https://myrapidbus.prasarana.com.my/kiosk/rpg?route={config['kiosk_id']}&bus="

        try:
            resp = session.get(url, timeout=8)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            popups = soup.find_all("div", class_="leaflet-popup-content")

            for popup in popups:
                html_content = str(popup)
                match = pattern.search(html_content)

                if not match:
                    continue

                bus_name, did, gps_time, speed, sub_route = match.groups()
                sub_route_clean = (sub_route.split("<")[0].strip() if sub_route else "N/A")

                all_buses.append(
                    {
                        "Target Route": route_number,
                        "Route Description": config["label"],
                        "Bus Code": bus_name.strip(),
                        "Device ID (DiD)": did.strip(),
                        "Sub-Route": sub_route_clean,
                        "Speed": speed.strip(),
                        "GPS Time": gps_time.strip(),
                        "Snapshot Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

        except requests.RequestException as e:
            logger.warning("Network error fetching route %s (kiosk %s): %s", route_number, config["kiosk_id"], e)
        except Exception:
            # Catch parsing or unexpected errors, but log details for easier debugging
            logger.exception("Unexpected error parsing data for route %s", route_number)

    if all_buses:
        return pd.DataFrame(all_buses)

    return pd.DataFrame(columns=[
        "Target Route",
        "Route Description",
        "Bus Code",
        "Device ID (DiD)",
        "Sub-Route",
        "Speed",
        "GPS Time",
        "Snapshot Timestamp",
    ])


# --- Dashboard Interface ---
st.title("🚌 Rapid Bus KL Live DiD Tracker")
st.markdown(
    "Monitoring target routes **300, 420, 450, 600, 640, 751, 772** via Prasarana Kiosk elemental feeds."
)

# Sidebar controls
st.sidebar.header("Controls")
auto_refresh = st.sidebar.checkbox("Enable Auto-Refresh (30s)", value=False)

if st.sidebar.button("🔄 Refresh Data Now"):
    # Clear the cached results so that the next fetch pulls fresh data
    st.cache_data.clear()

# Fetch data (cached)
df_buses = fetch_live_bus_data()

# Metrics summary
col1, col2 = st.columns(2)
with col1:
    st.metric(label="Active Target Corridors", value=len(TARGET_ROUTES))
with col2:
    st.metric(label="Total Active Fleet Units", value=len(df_buses) if not df_buses.empty else 0)

st.markdown("---")

if not df_buses.empty:
    st.subheader("🟢 Live Fleet Telemetry Data")

    # Display table
    display_cols = [
        "Target Route",
        "Bus Code",
        "Device ID (DiD)",
        "Sub-Route",
        "Speed",
        "GPS Time",
        "Snapshot Timestamp",
    ]
    st.dataframe(df_buses[display_cols], use_container_width=True)

    # Export capabilities
    st.markdown("### 💾 Data Export")
    csv_bytes = df_buses.to_csv(index=False).encode("utf-8")
    filename = f"rapid_bus_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    st.download_button(
        label="📥 Download Current Snapshot CSV",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
    )
else:
    st.warning(
        "No active vehicles currently detected on the kiosk endpoints for these specific routes. Try refreshing shortly."
    )

# Auto-refresh loop handling
if auto_refresh:
    # Small sleep to avoid hammering the kiosk endpoints; Streamlit will re-run the script
    time.sleep(30)
    # Use the stable experimental API for re-run across Streamlit versions
    try:
        st.experimental_rerun()
    except Exception:
        # Fallback to st.experimental_rerun if st.rerun not available
        try:
            st.rerun()
        except Exception:
            logger.exception("Failed to programmatically rerun Streamlit app")
