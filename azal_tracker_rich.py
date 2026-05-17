import os
import time
import requests
import folium

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# Universal Airport Code Dictionary for translating raw ICAO codes to gorgeous city banners
AIRPORT_MAP = {
    "UBBB": "Baku (GYD) 🇦🇿",
    "LTFM": "Istanbul (IST) 🇹🇷",
    "LTFJ": "Istanbul (SAW) 🇹🇷",
    "EGLL": "London (LHR) 🇬🇧",
    "EGKK": "London (LGW) 🇬🇧",
    "UUDD": "Moscow (DME) 🇷🇺",
    "UUWW": "Moscow (VKO) 🇷🇺",
    "OMDB": "Dubai (DXB) 🇦🇪",
    "EDDF": "Frankfurt (FRA) 🇩🇪",
    "VIDP": "Delhi (DEL) 🇮🇳",
    "VABB": "Mumbai (BOM) 🇮🇳",
    "OERK": "Riyadh (RUH) 🇸🇦",
    "OEJN": "Jeddah (JED) 🇸🇦",
    "UGTB": "Tbilisi (TBS) 🇬🇪",
    "LLBG": "Tel Aviv (TLV) 🇮🇱",
    "UAAA": "Almaty (ALA) 🇰🇿",
    "UACC": "Astana (NQZ) 🇰🇿",
    "UTTT": "Tashkent (TAS) 🇺🇿",
    "LKPR": "Prague (PRG) 🇨🇿",
    "LOWW": "Vienna (VIE) 🇦🇹",
    "LFPG": "Paris (CDG) 🇫🇷",
    "EDDB": "Berlin (BER) 🇩🇪",
    "LIMC": "Milan (MXP) 🇮🇹",
    "UBBN": "Nakhchivan (NAJ) 🇦🇿",
    "UBGG": "Ganja (GNJ) 🇦🇿",
    "UATE": "Aktau (SCO) 🇰🇿"
}


def resolve_airport(icao):
    """Translates ICAO airport identifiers to beautiful strings."""
    if not icao:
        return "[italic dim white]Unavailable[/italic dim white]"
    return AIRPORT_MAP.get(icao.upper(), f"Code: {icao.upper()}")


def fetch_route_info(icao24):
    """
    Queries OpenSky's active flight manifest history for the specific airframe
    to extract the current departure and arrival hubs.
    """
    now = int(time.time())
    twenty_four_hours_ago = now - 86400

    url = f"https://opensky-network.org/api/flights/aircraft"
    params = {"icao24": icao24, "begin": twenty_four_hours_ago, "end": now}

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            flights = response.json()
            if flights:
                # The last item in the logged array contains the active or most immediate flight data leg
                latest_flight = flights[-1]
                return {
                    "departure": latest_flight.get("estDepartureAirport"),
                    "arrival": latest_flight.get("estArrivalAirport")
                }
    except Exception:
        pass
    return {"departure": None, "arrival": None}


def fetch_live_azal_fleet():
    """Fetches real-time telemetry state vectors and maps flight profiles."""
    url = "https://opensky-network.org/api/states/all"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        console.print(f"\n[bold red][!] Connection Failure:[/bold red] {e}")
        return []

    all_states = data.get("states", [])
    if not all_states:
        return []

    raw_active_azal = []
    for state in all_states:
        callsign = (state[1] if state[1] else "").strip()
        if callsign.upper().startswith("AHY") and state[6] is not None and state[5] is not None:
            raw_active_azal.append(state)

    enriched_fleet = []

    # Process route discovery loops using a progress bar
    if raw_active_azal:
        with Progress(
                SpinnerColumn(spinner_name="earth"),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[bold sky_blue]Resolving Route Tracking Logs...", total=len(raw_active_azal))

            for state in raw_active_azal:
                icao24 = state[0]
                callsign = state[1].strip()

                # Fetch deeper departure/arrival telemetry paths
                route = fetch_route_info(icao24)

                alt_meters = state[7]
                altitude_ft = int(alt_meters * 3.28084) if alt_meters is not None else "Ground"

                speed_ms = state[9]
                speed_knots = int(speed_ms * 1.94384) if speed_ms is not None else 0

                # Extract Ascent/Descent vector rates (meters per second)
                v_rate = state[11]
                if v_rate is not None:
                    if v_rate > 0.5:
                        trend = "Climbing ↗"
                    elif v_rate < -0.5:
                        trend = "Descending ↘"
                    else:
                        trend = "Cruising ➔"
                else:
                    trend = "Steady"

                # Extract Squawk (Air Traffic Control transponder assignment token)
                squawk = state[14] if state[14] else "0000"

                enriched_fleet.append({
                    "icao24": icao24,
                    "callsign": callsign,
                    "lat": state[6],
                    "lon": state[5],
                    "altitude": altitude_ft,
                    "speed": speed_knots,
                    "heading": int(state[10]) if state[10] is not None else 0,
                    "trend": trend,
                    "squawk": squawk,
                    "departure": resolve_airport(route["departure"]),
                    "arrival": resolve_airport(route["arrival"]),
                    "on_ground": state[8]
                })
                progress.advance(task)

    return enriched_fleet


def generate_map(flights, output_filename="azal_advanced_tracker.html"):
    """Generates an enhanced geographical map overlay file."""
    baku_coords = [40.4675, 50.0467]
    flight_map = folium.Map(location=baku_coords, zoom_start=4, tiles="CartoDB positron")

    for flight in flights:
        popup_html = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; font-size: 13px; min-width: 220px; padding: 5px;">
            <h3 style="margin: 0 0 5px 0; color: #002B49; font-size: 16px;">✈ Flight {flight['callsign']}</h3>
            <span style="color: #666; font-size: 11px;">ICAO Address: {flight['icao24'].upper()}</span>
            <hr style="border: 0; border-top: 1px solid #ddd; margin: 8px 0;">
            <b style="color: #d85c00;">Route Profile:</b><br>
            <span style="font-size:12px; font-weight: bold;">{flight['departure']} ➔ {flight['arrival']}</span><br><br>
            <b>Altitude Status:</b> {flight['altitude']:,} ft ({flight['trend']})<br>
            <b>Airspeed Vector:</b> {flight['speed']} knots<br>
            <b>ATC Squawk:</b> {flight['squawk']}<br>
            <b>Heading Bearing:</b> {flight['heading']}°
        </div>
        """
        folium.Marker(
            location=[flight['lat'], flight['lon']],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{flight['callsign']} | {flight['departure']} to {flight['arrival']}",
            icon=folium.Icon(color="blue", icon="plane", prefix="fa")
        ).add_to(flight_map)

    flight_map.save(output_filename)
    return os.path.abspath(output_filename)


def main():
    os.system('cls' if os.name == 'nt' else 'clear')

    header_text = Text(
        "\n✈  AZERBAIJAN AIRLINES (AZAL) ULTRA-DASHBOARD  ✈\nREAL-TIME FLET DEPARTURES, ARRIVALS & ADVANCED TELEMETRY\n",
        style="bold white center")
    console.print(Panel(header_text, style="on navy_blue", border_style="gold1", expand=False))
    console.print()

    flights = fetch_live_azal_fleet()

    if not flights:
        warning_msg = Text("No active airborne AZAL assets intercepted over transponder arrays right now.",
                           style="bold yellow")
        console.print(
            Panel(warning_msg, title="[bold red]System Notification[/bold red]", border_style="red", expand=False))
        return

    # Advanced Multi-Column Data Matrix Layout Table
    table = Table(
        title="[bold gold1]Live Operational Flight Manifest Status Screen",
        title_style="bold white",
        border_style="grey50",
        header_style="bold bright_white",
        show_lines=True
    )

    table.add_column("Flight", style="bold yellow", justify="center")
    table.add_column("Departure Station (From)", style="bold chartreuse3", justify="left")
    table.add_column("Arrival Station (To)", style="bold deep_sky_blue1", justify="left")
    table.add_column("Altitude & Trend", style="bold white", justify="right")
    table.add_column("Airspeed", style="spring_green3", justify="right")
    table.add_column("Squawk", style="medium_purple1", justify="center")
    table.add_column("Bearing", style="italic grey70", justify="right")
    table.add_column("ICAO Hex", style="dim cyan", justify="center")

    for f in flights:
        alt_display = f"{f['altitude']:,} ft" if isinstance(f['altitude'], int) else str(f['altitude'])

        # Color code flight behaviors
        if "Climbing" in f['trend']:
            trend_colored = f"[bold green]{alt_display} ↗[/bold green]"
        elif "Descending" in f['trend']:
            trend_colored = f"[bold gold1]{alt_display} ↘[/bold gold1]"
        else:
            trend_colored = f"[bold cyan]{alt_display} ➔[/bold cyan]"

        table.add_row(
            f['callsign'],
            f['departure'],
            f['arrival'],
            trend_colored,
            f"{f['speed']} kts",
            f['squawk'],
            f"{f['heading']}°",
            f['icao24'].upper()
        )

    console.print(table)
    console.print()

    map_path = generate_map(flights)

    map_success_text = Text()
    map_success_text.append("✔ Extended Geospatial Fleet Mapping Pipeline Succeeded!\n\n", style="bold green")
    map_success_text.append("Open the browser visualization layout engine at:\n", style="white")
    map_success_text.append(f"file://{map_path}", style="bold bright_cyan underline")

    console.print(
        Panel(Align.center(map_success_text), title="[bold green]System Output Map Manifest Saved[/bold green]",
              border_style="gold1", expand=False))
    console.print()


if __name__ == "__main__":
    main()