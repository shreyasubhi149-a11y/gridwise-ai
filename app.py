from flask import Flask, jsonify, request, render_template, send_from_directory
import sqlite3
import os
import random
from datetime import datetime, timedelta


# ============================================================
# APP
# ============================================================

app = Flask(__name__)
@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        app.static_folder,
        "service-worker.js",
        mimetype="application/javascript"
    )


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "gridwise_ai.db")


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now()


def now_iso():
    return now().isoformat(timespec="seconds")


# ============================================================
# EVENT LOG
# ============================================================

def log_event(conn, machine_id, event_type, message):
    conn.execute(
        """
        INSERT INTO events
        (machine_id, event_type, message, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            machine_id,
            event_type,
            message,
            now_iso()
        )
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database():

    conn = get_db()

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode TEXT NOT NULL DEFAULT 'day',

            peak_start TEXT NOT NULL DEFAULT '16:00',
            peak_end TEXT NOT NULL DEFAULT '21:00',

            peak_rate REAL NOT NULL DEFAULT 8.5,
            offpeak_rate REAL NOT NULL DEFAULT 5.0,

            system_limit_kw REAL NOT NULL DEFAULT 18.0,

            created_at TEXT NOT NULL
        );


        CREATE TABLE IF NOT EXISTS machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,
            category TEXT NOT NULL,

            base_kw REAL NOT NULL DEFAULT 1.0,
            limit_kw REAL NOT NULL DEFAULT 2.0,

            priority INTEGER NOT NULL DEFAULT 50,
            day_priority INTEGER NOT NULL DEFAULT 50,
            night_priority INTEGER NOT NULL DEFAULT 50,

            criticality TEXT NOT NULL DEFAULT 'Normal',

            auto_shutdown INTEGER NOT NULL DEFAULT 1,
            shutdown_delay INTEGER NOT NULL DEFAULT 5,

            enabled INTEGER NOT NULL DEFAULT 1,

            current_kw REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ON',

            alert_cooldown_until TEXT,

            created_at TEXT NOT NULL
        );


        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            machine_id INTEGER NOT NULL,

            current_kw REAL NOT NULL,
            limit_kw REAL NOT NULL,

            priority INTEGER NOT NULL,
            day_night_mode TEXT NOT NULL,
            criticality TEXT NOT NULL,

            status TEXT NOT NULL DEFAULT 'ACTIVE',

            user_action TEXT,

            reason TEXT,

            created_at TEXT NOT NULL,
            deadline TEXT NOT NULL,

            resolved_at TEXT,

            resolution_machine_id INTEGER,

            ai_decision TEXT,

            FOREIGN KEY(machine_id)
                REFERENCES machines(id)
        );


        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            machine_id INTEGER,

            event_type TEXT NOT NULL,

            message TEXT NOT NULL,

            created_at TEXT NOT NULL
        );


        CREATE TABLE IF NOT EXISTS energy_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            reading_at TEXT NOT NULL,

            kwh REAL NOT NULL
        );


        CREATE TABLE IF NOT EXISTS meter_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            reading_at TEXT NOT NULL,

            meter_value REAL NOT NULL,

            source TEXT NOT NULL DEFAULT 'manual'
        );


        CREATE TABLE IF NOT EXISTS hardware_state (
            machine_id INTEGER PRIMARY KEY,

            relay_state TEXT NOT NULL DEFAULT 'ON',

            last_command TEXT,

            last_command_at TEXT,

            FOREIGN KEY(machine_id)
                REFERENCES machines(id)
        );
        """
    )


    # --------------------------------------------------------
    # DEFAULT SETTINGS
    # --------------------------------------------------------

    settings = conn.execute(
        "SELECT id FROM settings WHERE id = 1"
    ).fetchone()

    if settings is None:

        conn.execute(
            """
            INSERT INTO settings
            (
                id,
                mode,
                peak_start,
                peak_end,
                peak_rate,
                offpeak_rate,
                system_limit_kw,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "day",
                "16:00",
                "21:00",
                8.5,
                5.0,
                18.0,
                now_iso()
            )
        )


    # --------------------------------------------------------
    # DEFAULT MACHINES
    # --------------------------------------------------------

    machine_count = conn.execute(
        "SELECT COUNT(*) AS count FROM machines"
    ).fetchone()["count"]


    if machine_count == 0:

        default_machines = [

            (
                "Production Motor",
                "Industrial",
                8.4,
                7.0,
                80,
                85,
                45,
                "Important",
                1,
                5
            ),

            (
                "HVAC System",
                "Cooling",
                5.7,
                5.0,
                65,
                55,
                75,
                "Normal",
                1,
                5
            ),

            (
                "Water Pump",
                "Utility",
                3.2,
                4.0,
                50,
                60,
                40,
                "Normal",
                1,
                5
            ),

            (
                "Auxiliary Equipment",
                "Equipment",
                2.9,
                2.5,
                30,
                25,
                35,
                "Non-critical",
                1,
                5
            ),

            (
                "Security System",
                "Security",
                1.0,
                1.5,
                100,
                100,
                100,
                "Critical",
                0,
                5
            )
        ]


        for machine in default_machines:

            cursor = conn.execute(
                """
                INSERT INTO machines
                (
                    name,
                    category,
                    base_kw,
                    limit_kw,

                    priority,
                    day_priority,
                    night_priority,

                    criticality,

                    auto_shutdown,
                    shutdown_delay,

                    enabled,
                    current_kw,
                    status,

                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'ON', ?)
                """,
                (
                    machine[0],
                    machine[1],
                    machine[2],
                    machine[3],

                    machine[4],
                    machine[5],
                    machine[6],

                    machine[7],

                    machine[8],
                    machine[9],

                    machine[2],
                    now_iso()
                )
            )

            machine_id = cursor.lastrowid

            conn.execute(
                """
                INSERT OR REPLACE INTO hardware_state
                (
                    machine_id,
                    relay_state,
                    last_command,
                    last_command_at
                )
                VALUES (?, 'ON', 'ON', ?)
                """,
                (
                    machine_id,
                    now_iso()
                )
            )


    conn.commit()
    conn.close()


# ============================================================
# DEMO ENERGY DATA
# ============================================================

def seed_energy_data():

    conn = get_db()

    count = conn.execute(
        "SELECT COUNT(*) AS count FROM energy_readings"
    ).fetchone()["count"]

    if count > 0:
        conn.close()
        return


    random.seed(42)

    start = now() - timedelta(days=60)


    for hour_number in range(60 * 24):

        timestamp = start + timedelta(
            hours=hour_number
        )

        hour = timestamp.hour


        if 7 <= hour <= 10:
            base = 15.0

        elif 11 <= hour <= 15:
            base = 12.5

        elif 16 <= hour <= 21:
            base = 17.0

        elif 22 <= hour <= 23:
            base = 9.0

        else:
            base = 6.0


        energy = max(
            1.0,
            base + random.uniform(-2.0, 2.0)
        )


        conn.execute(
            """
            INSERT INTO energy_readings
            (
                reading_at,
                kwh
            )
            VALUES (?, ?)
            """,
            (
                timestamp.isoformat(
                    timespec="seconds"
                ),
                round(energy, 3)
            )
        )


    conn.commit()
    conn.close()


# ============================================================
# TARIFF
# ============================================================

def tariff_for_timestamp(timestamp, settings):

    timestamp = timestamp.strftime("%H:%M")

    peak_start = settings["peak_start"]
    peak_end = settings["peak_end"]

    if peak_start <= timestamp <= peak_end:

        return {
            "period": "Peak",
            "rate": float(settings["peak_rate"])
        }

    return {
        "period": "Off-Peak",
        "rate": float(settings["offpeak_rate"])
    }


def current_tariff(conn):

    settings = conn.execute(
        "SELECT * FROM settings WHERE id = 1"
    ).fetchone()

    return tariff_for_timestamp(
        now(),
        settings
    )


# ============================================================
# HARDWARE SIMULATION
# ============================================================

def update_hardware(conn, machine_id, command):

    command = str(command).upper()

    conn.execute(
        """
        INSERT INTO hardware_state
        (
            machine_id,
            relay_state,
            last_command,
            last_command_at
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(machine_id)
        DO UPDATE SET

            relay_state = excluded.relay_state,
            last_command = excluded.last_command,
            last_command_at = excluded.last_command_at
        """,
        (
            machine_id,
            command,
            command,
            now_iso()
        )
    )


# ============================================================
# DAY/NIGHT PRIORITY
# ============================================================

def machine_priority(machine, mode):

    if mode == "night":

        return int(
            machine["night_priority"]
        )

    return int(
        machine["day_priority"]
    )


# ============================================================
# AI DECISION
# ============================================================

def choose_ai_machine(conn, excluded_machine_id=None):

    settings = conn.execute(
        "SELECT * FROM settings WHERE id = 1"
    ).fetchone()

    mode = settings["mode"]

    system_limit = float(
        settings["system_limit_kw"]
    )


    machines = conn.execute(
        """
        SELECT *
        FROM machines

        WHERE enabled = 1
        AND status = 'ON'
        """
    ).fetchall()


    total_kw = sum(
        float(machine["current_kw"])
        for machine in machines
    )


    best_machine = None
    best_score = -999999


    for machine in machines:

        if excluded_machine_id is not None:

            if machine["id"] == excluded_machine_id:
                continue


        # Critical machines are protected
        if machine["criticality"] == "Critical":
            continue


        if not machine["auto_shutdown"]:
            continue


        current_kw = float(
            machine["current_kw"]
        )

        limit_kw = max(
            float(machine["limit_kw"]),
            0.1
        )


        excess_percent = max(
            0,
            ((current_kw - limit_kw)
             / limit_kw) * 100
        )


        priority = machine_priority(
            machine,
            mode
        )


        system_pressure = 0

        if system_limit > 0:

            system_pressure = max(
                0,
                ((total_kw - system_limit)
                 / system_limit) * 100
            )


        score = 0


        # Lower priority = easier to switch off
        score += (
            100 - priority
        ) * 1.5


        # Over-limit machines become more likely
        score += excess_percent * 2


        # Consumption matters
        score += current_kw * 3


        # System pressure matters
        score += system_pressure * 0.5


        # Criticality
        if machine["criticality"] == "Non-critical":
            score += 50

        elif machine["criticality"] == "Normal":
            score += 15

        elif machine["criticality"] == "Important":
            score -= 40


        if score > best_score:

            best_score = score
            best_machine = machine


    return best_machine


# ============================================================
# SWITCH OFF
# ============================================================

def switch_off(conn, machine, reason, event_type):

    machine_id = machine["id"]


    conn.execute(
        """
        UPDATE machines

        SET
            status = 'OFF',
            current_kw = 0,
            alert_cooldown_until = NULL

        WHERE id = ?
        """,
        (
            machine_id,
        )
    )


    update_hardware(
        conn,
        machine_id,
        "OFF"
    )


    log_event(
        conn,
        machine_id,
        event_type,
        (
            f"{machine['name']} switched OFF. "
            f"{reason}"
        )
    )


# ============================================================
# CREATE ALERT
# ============================================================

def create_alert_if_needed(conn, machine):

    if not machine["enabled"]:
        return None


    if machine["status"] != "ON":
        return None


    current_kw = float(
        machine["current_kw"]
    )

    limit_kw = float(
        machine["limit_kw"]
    )


    if current_kw <= limit_kw:
        return None


    existing = conn.execute(
        """
        SELECT *

        FROM alerts

        WHERE machine_id = ?
        AND status = 'ACTIVE'

        LIMIT 1
        """,
        (
            machine["id"],
        )
    ).fetchone()


    if existing:
        return existing


    settings = conn.execute(
        "SELECT * FROM settings WHERE id = 1"
    ).fetchone()


    mode = settings["mode"]


    delay = max(
        5,
        min(
            20,
            int(machine["shutdown_delay"])
        )
    )


    deadline = (
        now() +
        timedelta(minutes=delay)
    )


    excess = (
        ((current_kw - limit_kw)
         / limit_kw)
        * 100
    )


    reason = (
        f"{machine['name']} is using "
        f"{current_kw:.2f} kW, above its "
        f"{limit_kw:.2f} kW limit."
    )


    cursor = conn.execute(
        """
        INSERT INTO alerts
        (
            machine_id,
            current_kw,
            limit_kw,

            priority,
            day_night_mode,
            criticality,

            status,

            reason,

            created_at,
            deadline
        )
        VALUES
        (
            ?, ?, ?,
            ?, ?, ?,
            'ACTIVE',
            ?,
            ?, ?
        )
        """,
        (
            machine["id"],
            current_kw,
            limit_kw,

            machine_priority(
                machine,
                mode
            ),

            mode,

            machine["criticality"],

            reason,

            now_iso(),
            deadline.isoformat(
                timespec="seconds"
            )
        )
    )


    alert_id = cursor.lastrowid


    log_event(
        conn,
        machine["id"],
        "ALERT",
        (
            f"{reason} "
            f"AI/manual decision window: "
            f"{delay} minutes."
        )
    )


    return conn.execute(
        """
        SELECT *
        FROM alerts
        WHERE id = ?
        """,
        (
            alert_id,
        )
    ).fetchone()


# ============================================================
# ALERT PROCESSING
# ============================================================

def process_alerts(conn):

    machines = conn.execute(
        "SELECT * FROM machines"
    ).fetchall()


    for machine in machines:

        if machine["status"] != "ON":
            continue


        if float(machine["current_kw"]) > float(
            machine["limit_kw"]
        ):

            create_alert_if_needed(
                conn,
                machine
            )


    # --------------------------------------------------------
    # AUTO AI DECISION AFTER COUNTDOWN
    # --------------------------------------------------------

    active_alerts = conn.execute(
        """
        SELECT *
        FROM alerts

        WHERE status = 'ACTIVE'
        """
    ).fetchall()


    for alert in active_alerts:

        try:

            deadline = datetime.fromisoformat(
                alert["deadline"]
            )

        except Exception:
            continue


        if now() < deadline:
            continue


        candidate = choose_ai_machine(
            conn
        )


        if candidate is None:

            conn.execute(
                """
                UPDATE alerts

                SET
                    status = 'RESOLVED',
                    user_action = 'AI_NO_ACTION',
                    ai_decision = ?,
                    resolved_at = ?

                WHERE id = ?
                """,
                (
                    "No eligible appliance could be stopped.",
                    now_iso(),
                    alert["id"]
                )
            )

            log_event(
                conn,
                alert["machine_id"],
                "AI_DECISION",
                (
                    "AI could not find an eligible "
                    "appliance to switch off."
                )
            )

            continue


        reason = (
            f"AI selected {candidate['name']} "
            f"using {get_current_mode(conn)} priority, "
            f"criticality, consumption and "
            f"system demand."
        )


        switch_off(
            conn,
            candidate,
            reason,
            "AI_AUTO_SHUTDOWN"
        )


        conn.execute(
            """
            UPDATE alerts

            SET
                status = 'RESOLVED',
                user_action = 'AI_AUTO_OFF',
                ai_decision = ?,
                resolution_machine_id = ?,
                resolved_at = ?

            WHERE id = ?
            """,
            (
                reason,
                candidate["id"],
                now_iso(),
                alert["id"]
            )
        )


    conn.commit()


# ============================================================
# ENERGY + TARIFF
# ============================================================

def energy_summary(conn):

    settings = conn.execute(
        "SELECT * FROM settings WHERE id = 1"
    ).fetchone()


    current_tariff = tariff_for_timestamp(
        now(),
        settings
    )


    today_start = now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


    month_start = now().replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


    sixty_start = (
        now() -
        timedelta(days=60)
    )


    rows = conn.execute(
        """
        SELECT reading_at, kwh
        FROM energy_readings

        WHERE reading_at >= ?

        ORDER BY reading_at
        """,
        (
            sixty_start.isoformat(),
        )
    ).fetchall()


    today_kwh = 0
    today_cost = 0

    month_kwh = 0
    month_cost = 0

    sixty_kwh = 0
    sixty_cost = 0


    hourly = []


    for row in rows:

        try:

            timestamp = datetime.fromisoformat(
                row["reading_at"]
            )

        except Exception:

            continue


        kwh = float(
            row["kwh"]
        )


        tariff = tariff_for_timestamp(
            timestamp,
            settings
        )


        cost = (
            kwh *
            tariff["rate"]
        )


        sixty_kwh += kwh
        sixty_cost += cost


        if timestamp >= month_start:

            month_kwh += kwh
            month_cost += cost


        if timestamp >= today_start:

            today_kwh += kwh
            today_cost += cost


    # Last 24 readings for dashboard chart
    for row in rows[-24:]:

        hourly.append(
            {
                "time": row["reading_at"],
                "kwh": round(
                    float(row["kwh"]),
                    2
                )
            }
        )


    # Energy accounting estimate
    accounted_kwh = (
        sixty_kwh * 0.94
    )


    unaccounted_kwh = max(
        0,
        sixty_kwh - accounted_kwh
    )


    return {

        "today_kwh": round(
            today_kwh,
            2
        ),

        "today_cost": round(
            today_cost,
            2
        ),

        "month_kwh": round(
            month_kwh,
            2
        ),

        "month_cost": round(
            month_cost,
            2
        ),

        "sixty_day_kwh": round(
            sixty_kwh,
            2
        ),

        "sixty_day_cost": round(
            sixty_cost,
            2
        ),

        "accounted_kwh": round(
            accounted_kwh,
            2
        ),

        "unaccounted_kwh": round(
            unaccounted_kwh,
            2
        ),

        "current_rate": current_tariff["rate"],

        "current_period": current_tariff["period"],

        "hourly": hourly
    }


# ============================================================
# OPTIMIZATION
# ============================================================

def optimization_summary(conn):

    machines = conn.execute(
        """
        SELECT *
        FROM machines
        WHERE enabled = 1
        """
    ).fetchall()


    baseline_kw = sum(
        float(machine["base_kw"])
        for machine in machines
    )


    saving_kw = 0


    for machine in machines:

        if machine["criticality"] == "Critical":

            factor = 0.02

        elif machine["criticality"] == "Important":

            factor = 0.05

        elif machine["criticality"] == "Normal":

            factor = 0.10

        else:

            factor = 0.18


        saving_kw += (
            float(machine["base_kw"])
            * factor
        )


    optimized_kw = max(
        0,
        baseline_kw - saving_kw
    )


    baseline_daily = (
        baseline_kw * 8
    )

    optimized_daily = (
        optimized_kw * 8
    )

    saving_daily = (
        baseline_daily -
        optimized_daily
    )


    saving_cost = (
        saving_daily * 5.0
    )


    return {

        "baseline_daily_kwh": round(
            baseline_daily,
            2
        ),

        "optimized_daily_kwh": round(
            optimized_daily,
            2
        ),

        "saving_kwh": round(
            saving_daily,
            2
        ),

        "saving_cost": round(
            saving_cost,
            2
        )
    }


# ============================================================
# SERIALIZATION
# ============================================================

def machine_dict(machine):

    return {

        "id": machine["id"],

        "name": machine["name"],

        "category": machine["category"],

        "base_kw": float(
            machine["base_kw"]
        ),

        "limit_kw": float(
            machine["limit_kw"]
        ),

        "priority": int(
            machine["priority"]
        ),

        "day_priority": int(
            machine["day_priority"]
        ),

        "night_priority": int(
            machine["night_priority"]
        ),

        "criticality": machine["criticality"],

        "auto_shutdown": bool(
            machine["auto_shutdown"]
        ),

        "shutdown_delay": int(
            machine["shutdown_delay"]
        ),

        "enabled": bool(
            machine["enabled"]
        ),

        "current_kw": float(
            machine["current_kw"]
        ),

        "status": machine["status"],

        "alert_cooldown_until":
            machine["alert_cooldown_until"],

        "created_at":
            machine["created_at"]
    }


def alert_dict(alert):

    return {

        "id": alert["id"],

        "machine_id":
            alert["machine_id"],

        "current_kw":
            float(alert["current_kw"]),

        "limit_kw":
            float(alert["limit_kw"]),

        "priority":
            int(alert["priority"]),

        "day_night_mode":
            alert["day_night_mode"],

        "criticality":
            alert["criticality"],

        "status":
            alert["status"],

        "user_action":
            alert["user_action"],

        "reason":
            alert["reason"],

        "created_at":
            alert["created_at"],

        "deadline":
            alert["deadline"],

        "resolved_at":
            alert["resolved_at"],

        "resolution_machine_id":
            alert["resolution_machine_id"],

        "ai_decision":
            alert["ai_decision"],

        "machine_name":
            alert["machine_name"],

        "machine_category":
            alert["machine_category"],

        "machine_status":
            alert["machine_status"]
    }


def get_current_mode(conn):

    settings = conn.execute(
        "SELECT mode FROM settings WHERE id = 1"
    ).fetchone()

    if settings is None:
        return "day"

    return settings["mode"]


# ============================================================
# MAIN PAGE
# ============================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# ============================================================
# SERVICE WORKER
# ============================================================

@app.route("/service-worker.js")



# ============================================================
# DASHBOARD API
# ============================================================

@app.route("/api/dashboard")
def dashboard():

    conn = get_db()

    process_alerts(conn)


    settings = conn.execute(
        "SELECT * FROM settings WHERE id = 1"
    ).fetchone()


    machines = conn.execute(
        """
        SELECT *
        FROM machines
        ORDER BY id
        """
    ).fetchall()


    alerts = conn.execute(
        """
        SELECT
            alerts.*,

            machines.name AS machine_name,
            machines.category AS machine_category,
            machines.status AS machine_status

        FROM alerts

        JOIN machines
            ON machines.id = alerts.machine_id

        WHERE alerts.status = 'ACTIVE'

        ORDER BY alerts.id DESC
        """
    ).fetchall()


    events = conn.execute(
        """
        SELECT
            events.*,
            machines.name AS machine_name

        FROM events

        LEFT JOIN machines
            ON machines.id = events.machine_id

        ORDER BY events.id DESC

        LIMIT 30
        """
    ).fetchall()


    hardware = conn.execute(
        """
        SELECT
            hardware_state.*,
            machines.name AS machine_name

        FROM hardware_state

        JOIN machines
            ON machines.id =
               hardware_state.machine_id

        ORDER BY machines.id
        """
    ).fetchall()


    energy = energy_summary(
        conn
    )


    optimization = optimization_summary(
        conn
    )


    current_kw = sum(
        float(machine["current_kw"])
        for machine in machines
    )


    system_limit = float(
        settings["system_limit_kw"]
    )


    if current_kw >= system_limit:

        pressure = "HIGH"

    elif current_kw >= system_limit * 0.8:

        pressure = "MEDIUM"

    else:

        pressure = "NORMAL"


    result = {

        "success": True,

        "settings": {

            "mode":
                settings["mode"],

            "peak_start":
                settings["peak_start"],

            "peak_end":
                settings["peak_end"],

            "peak_rate":
                float(settings["peak_rate"]),

            "offpeak_rate":
                float(settings["offpeak_rate"]),

            "system_limit_kw":
                system_limit
        },


        "mode":
            settings["mode"],


        "machines": [

            machine_dict(machine)

            for machine in machines
        ],


        "alerts": [

            alert_dict(alert)

            for alert in alerts
        ],


        "events": [

            {

                "id":
                    event["id"],

                "machine_id":
                    event["machine_id"],

                "event_type":
                    event["event_type"],

                "message":
                    event["message"],

                "created_at":
                    event["created_at"],

                "machine_name":
                    event["machine_name"]
            }

            for event in events
        ],


        "hardware": [

            {

                "machine_id":
                    item["machine_id"],

                "relay_state":
                    item["relay_state"],

                "last_command":
                    item["last_command"],

                "last_command_at":
                    item["last_command_at"],

                "machine_name":
                    item["machine_name"]
            }

            for item in hardware
        ],


        "energy":
            energy,


        "optimization":
            optimization,


        "system": {

            "current_kw":
                round(
                    current_kw,
                    2
                ),

            "limit_kw":
                system_limit,

            "pressure":
                pressure
        }
    }


    conn.close()

    return jsonify(result)


# ============================================================
# CHANGE DAY / NIGHT
# ============================================================

@app.route(
    "/api/settings",
    methods=["POST"]
)
def change_settings():

    data = request.get_json(
        silent=True
    ) or {}


    mode = str(
        data.get(
            "mode",
            ""
        )
    ).lower().strip()


    if mode not in (
        "day",
        "night"
    ):

        return jsonify({
            "success": False,
            "error": "Mode must be day or night."
        }), 400


    conn = get_db()


    conn.execute(
        """
        UPDATE settings

        SET mode = ?

        WHERE id = 1
        """,
        (
            mode,
        )
    )


    log_event(
        conn,
        None,
        "MODE_CHANGE",
        (
            f"Operating mode changed "
            f"to {mode.upper()}."
        )
    )


    conn.commit()
    conn.close()


    return jsonify({

        "success": True,

        "mode": mode
    })


# ============================================================
# MACHINE ON/OFF
# ============================================================

@app.route(
    "/api/machines/<int:machine_id>/control",
    methods=["POST"]
)
def control_machine(machine_id):

    data = request.get_json(
        silent=True
    ) or {}


    command = str(
        data.get(
            "command",
            ""
        )
    ).upper().strip()


    if command not in (
        "ON",
        "OFF"
    ):

        return jsonify({

            "success": False,

            "error":
                "Command must be ON or OFF."
        }), 400


    conn = get_db()


    machine = conn.execute(
        """
        SELECT *
        FROM machines
        WHERE id = ?
        """,
        (
            machine_id,
        )
    ).fetchone()


    if machine is None:

        conn.close()

        return jsonify({

            "success": False,

            "error":
                "Machine not found."
        }), 404


    if command == "OFF":

        status = "OFF"
        current_kw = 0

        message = (
            f"{machine['name']} "
            f"switched OFF."
        )

    else:

        status = "ON"

        current_kw = float(
            machine["base_kw"]
        )

        message = (
            f"{machine['name']} "
            f"switched ON."
        )


    conn.execute(
        """
        UPDATE machines

        SET
            status = ?,
            current_kw = ?,
            alert_cooldown_until = NULL

        WHERE id = ?
        """,
        (
            status,
            current_kw,
            machine_id
        )
    )


    update_hardware(
        conn,
        machine_id,
        command
    )


    log_event(
        conn,
        machine_id,
        "MANUAL_CONTROL",
        message
    )


    conn.commit()
    conn.close()


    return jsonify({

        "success": True,

        "machine_id":
            machine_id,

        "command":
            command,

        "status":
            status,

        "current_kw":
            current_kw,

        "message":
            message
    })


# ============================================================
# ALERT ACTION
# ============================================================

@app.route(
    "/api/alerts/<int:alert_id>/action",
    methods=["POST"]
)
def alert_action(alert_id):

    data = request.get_json(
        silent=True
    ) or {}


    action = str(
        data.get(
            "action",
            ""
        )
    ).upper().strip()


    if action not in (
        "OFF",
        "AI"
    ):

        return jsonify({

            "success": False,

            "error":
                "Action must be OFF or AI."
        }), 400


    conn = get_db()


    alert = conn.execute(
        """
        SELECT
            alerts.*,

            machines.name AS machine_name,
            machines.category AS machine_category

        FROM alerts

        JOIN machines
            ON machines.id =
               alerts.machine_id

        WHERE alerts.id = ?
        """,
        (
            alert_id,
        )
    ).fetchone()


    if alert is None:

        conn.close()

        return jsonify({

            "success": False,

            "error":
                "Alert not found."
        }), 404


    if alert["status"] != "ACTIVE":

        conn.close()

        return jsonify({

            "success": False,

            "error":
                "This alert has already been handled."
        }), 400


    # --------------------------------------------------------
    # USER MANUAL STOP
    # --------------------------------------------------------

    if action == "OFF":

        machine = conn.execute(
            """
            SELECT *
            FROM machines
            WHERE id = ?
            """,
            (
                alert["machine_id"],
            )
        ).fetchone()


        if machine:

            switch_off(
                conn,
                machine,
                "User selected manual stop.",
                "USER_MANUAL_STOP"
            )


        conn.execute(
            """
            UPDATE alerts

            SET
                status = 'RESOLVED',
                user_action = 'MANUAL_OFF',
                resolved_at = ?

            WHERE id = ?
            """,
            (
                now_iso(),
                alert_id
            )
        )


        conn.commit()
        conn.close()


        return jsonify({

            "success": True,

            "action":
                "OFF",

            "message":
                f"{alert['machine_name']} "
                f"was manually switched OFF."
        })


    # --------------------------------------------------------
    # USER CHOOSES AI
    # --------------------------------------------------------

    candidate = choose_ai_machine(
        conn
    )


    if candidate is None:

        conn.execute(
            """
            UPDATE alerts

            SET
                status = 'RESOLVED',
                user_action = 'AI_NO_ACTION',
                ai_decision = ?,
                resolved_at = ?

            WHERE id = ?
            """,
            (
                "No eligible appliance was available.",
                now_iso(),
                alert_id
            )
        )


        conn.commit()
        conn.close()


        return jsonify({

            "success": True,

            "action":
                "AI",

            "message":
                "AI found no eligible appliance."
        })


    reason = (
        f"AI selected {candidate['name']} "
        f"using {get_current_mode(conn)} "
        f"priority, criticality, current "
        f"consumption and system demand."
    )


    switch_off(
        conn,
        candidate,
        reason,
        "AI_USER_DECISION"
    )


    conn.execute(
        """
        UPDATE alerts

        SET
            status = 'RESOLVED',
            user_action = 'AI_OFF',
            ai_decision = ?,
            resolution_machine_id = ?,
            resolved_at = ?

        WHERE id = ?
        """,
        (
            reason,
            candidate["id"],
            now_iso(),
            alert_id
        )
    )


    conn.commit()
    conn.close()


    return jsonify({

        "success": True,

        "action":
            "AI",

        "selected_machine":
            candidate["name"],

        "message":
            reason
    })


# ============================================================
# DEMO ALERT
# ============================================================

@app.route(
    "/api/demo/trigger-alert",
    methods=["POST"]
)
def trigger_demo_alert():

    conn = get_db()


    machine = conn.execute(
        """
        SELECT *
        FROM machines

        WHERE name =
              'Auxiliary Equipment'

        LIMIT 1
        """
    ).fetchone()


    if machine is None:

        machine = conn.execute(
            """
            SELECT *
            FROM machines

            ORDER BY id

            LIMIT 1
            """
        ).fetchone()


    if machine is None:

        conn.close()

        return jsonify({

            "success": False,

            "error":
                "No machine exists."
        }), 404


    demo_kw = (
        float(machine["limit_kw"])
        + 0.8
    )


    # Remove previous active alert
    conn.execute(
        """
        UPDATE alerts

        SET
            status = 'RESOLVED',
            resolved_at = ?

        WHERE machine_id = ?

        AND status = 'ACTIVE'
        """,
        (
            now_iso(),
            machine["id"]
        )
    )


    conn.execute(
        """
        UPDATE machines

        SET
            status = 'ON',
            current_kw = ?,
            alert_cooldown_until = NULL

        WHERE id = ?
        """,
        (
            demo_kw,
            machine["id"]
        )
    )


    refreshed = conn.execute(
        """
        SELECT *
        FROM machines

        WHERE id = ?
        """,
        (
            machine["id"],
        )
    ).fetchone()


    alert = create_alert_if_needed(
        conn,
        refreshed
    )


    log_event(
        conn,
        machine["id"],
        "DEMO_ALERT",
        (
            f"Demo alert triggered for "
            f"{machine['name']}."
        )
    )


    conn.commit()
    conn.close()


    return jsonify({

        "success": True,

        "alert_id":
            alert["id"]
            if alert
            else None,

        "message":
            (
                f"Alert triggered for "
                f"{machine['name']}."
            )
    })


# ============================================================
# ADD MACHINE
# ============================================================

@app.route(
    "/api/machines",
    methods=["POST"]
)
def add_machine():

    data = request.get_json(
        silent=True
    ) or {}


    name = str(
        data.get(
            "name",
            ""
        )
    ).strip()


    if not name:

        return jsonify({

            "success": False,

            "error":
                "Machine name is required."
        }), 400


    category = str(
        data.get(
            "category",
            "General"
        )
    ).strip()


    try:

        base_kw = float(
            data.get(
                "base_kw",
                1
            )
        )

        limit_kw = float(
            data.get(
                "limit_kw",
                2
            )
        )

        day_priority = int(
            data.get(
                "day_priority",
                50
            )
        )

        night_priority = int(
            data.get(
                "night_priority",
                50
            )
        )

        shutdown_delay = int(
            data.get(
                "shutdown_delay",
                5
            )
        )

    except Exception:

        return jsonify({

            "success": False,

            "error":
                "Invalid numeric values."
        }), 400


    criticality = str(
        data.get(
            "criticality",
            "Normal"
        )
    )


    if criticality not in (
        "Critical",
        "Important",
        "Normal",
        "Non-critical"
    ):

        criticality = "Normal"


    auto_shutdown = int(
        bool(
            data.get(
                "auto_shutdown",
                True
            )
        )
    )


    conn = get_db()


    cursor = conn.execute(
        """
        INSERT INTO machines
        (
            name,
            category,

            base_kw,
            limit_kw,

            priority,
            day_priority,
            night_priority,

            criticality,

            auto_shutdown,
            shutdown_delay,

            enabled,
            current_kw,
            status,

            created_at
        )
        VALUES
        (
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?,
            ?, ?,
            1, ?, 'ON',
            ?
        )
        """,
        (
            name,
            category,

            base_kw,
            limit_kw,

            50,
            day_priority,
            night_priority,

            criticality,

            auto_shutdown,
            max(
                5,
                min(
                    20,
                    shutdown_delay
                )
            ),

            base_kw,

            now_iso()
        )
    )


    machine_id = cursor.lastrowid


    update_hardware(
        conn,
        machine_id,
        "ON"
    )


    log_event(
        conn,
        machine_id,
        "MACHINE_ADDED",
        (
            f"{name} added to GridWise AI."
        )
    )


    conn.commit()


    machine = conn.execute(
        """
        SELECT *
        FROM machines
        WHERE id = ?
        """,
        (
            machine_id,
        )
    ).fetchone()


    conn.close()


    return jsonify({

        "success": True,

        "machine":
            machine_dict(machine)
    })


# ============================================================
# UPDATE MACHINE
# ============================================================

@app.route(
    "/api/machines/<int:machine_id>",
    methods=["PUT"]
)
def update_machine(machine_id):

    data = request.get_json(
        silent=True
    ) or {}


    conn = get_db()


    machine = conn.execute(
        """
        SELECT *
        FROM machines
        WHERE id = ?
        """,
        (
            machine_id,
        )
    ).fetchone()


    if machine is None:

        conn.close()

        return jsonify({

            "success": False,

            "error":
                "Machine not found."
        }), 404


    try:

        name = str(
            data.get(
                "name",
                machine["name"]
            )
        ).strip()


        category = str(
            data.get(
                "category",
                machine["category"]
            )
        ).strip()


        base_kw = float(
            data.get(
                "base_kw",
                machine["base_kw"]
            )
        )


        limit_kw = float(
            data.get(
                "limit_kw",
                machine["limit_kw"]
            )
        )


        day_priority = int(
            data.get(
                "day_priority",
                machine["day_priority"]
            )
        )


        night_priority = int(
            data.get(
                "night_priority",
                machine["night_priority"]
            )
        )


        shutdown_delay = int(
            data.get(
                "shutdown_delay",
                machine["shutdown_delay"]
            )
        )

    except Exception:

        conn.close()

        return jsonify({

            "success": False,

            "error":
                "Invalid machine values."
        }), 400


    criticality = str(
        data.get(
            "criticality",
            machine["criticality"]
        )
    )


    if criticality not in (
        "Critical",
        "Important",
        "Normal",
        "Non-critical"
    ):

        criticality = machine["criticality"]


    auto_shutdown = int(
        bool(
            data.get(
                "auto_shutdown",
                bool(
                    machine["auto_shutdown"]
                )
            )
        )
    )


    conn.execute(
        """
        UPDATE machines

        SET

            name = ?,
            category = ?,

            base_kw = ?,
            limit_kw = ?,

            day_priority = ?,
            night_priority = ?,

            criticality = ?,

            auto_shutdown = ?,
            shutdown_delay = ?

        WHERE id = ?
        """,
        (
            name,
            category,

            base_kw,
            limit_kw,

            day_priority,
            night_priority,

            criticality,

            auto_shutdown,

            max(
                5,
                min(
                    20,
                    shutdown_delay
                )
            ),

            machine_id
        )
    )


    log_event(
        conn,
        machine_id,
        "MACHINE_UPDATED",
        (
            f"{name} configuration updated."
        )
    )


    conn.commit()


    updated = conn.execute(
        """
        SELECT *
        FROM machines

        WHERE id = ?
        """,
        (
            machine_id,
        )
    ).fetchone()


    conn.close()


    return jsonify({

        "success": True,

        "machine":
            machine_dict(updated)
    })


# ============================================================
# DELETE MACHINE
# ============================================================

@app.route(
    "/api/machines/<int:machine_id>",
    methods=["DELETE"]
)
def delete_machine(machine_id):

    conn = get_db()


    machine = conn.execute(
        """
        SELECT *
        FROM machines

        WHERE id = ?
        """,
        (
            machine_id,
        )
    ).fetchone()


    if machine is None:

        conn.close()

        return jsonify({

            "success": False,

            "error":
                "Machine not found."
        }), 404


    name = machine["name"]


    conn.execute(
        """
        DELETE FROM alerts

        WHERE machine_id = ?
        """,
        (
            machine_id,
        )
    )


    conn.execute(
        """
        DELETE FROM hardware_state

        WHERE machine_id = ?
        """,
        (
            machine_id,
        )
    )


    conn.execute(
        """
        DELETE FROM machines

        WHERE id = ?
        """,
        (
            machine_id,
        )
    )


    log_event(
        conn,
        None,
        "MACHINE_DELETED",
        (
            f"{name} removed from GridWise AI."
        )
    )


    conn.commit()
    conn.close()


    return jsonify({

        "success": True,

        "message":
            f"{name} deleted."
    })


# ============================================================
# MANUAL ENERGY ENTRY
# ============================================================

@app.route(
    "/api/energy",
    methods=["POST"]
)
def add_energy():

    data = request.get_json(
        silent=True
    ) or {}


    try:

        kwh = float(
            data.get(
                "kwh"
            )
        )

    except Exception:

        return jsonify({

            "success": False,

            "error":
                "Enter a valid energy value."
        }), 400


    if kwh <= 0:

        return jsonify({

            "success": False,

            "error":
                "Energy must be greater than zero."
        }), 400


    conn = get_db()


    reading_time = now()


    conn.execute(
        """
        INSERT INTO energy_readings
        (
            reading_at,
            kwh
        )
        VALUES (?, ?)
        """,
        (
            reading_time.isoformat(
                timespec="seconds"
            ),
            kwh
        )
    )


    settings = conn.execute(
        """
        SELECT *
        FROM settings
        WHERE id = 1
        """
    ).fetchone()


    tariff = tariff_for_timestamp(
        reading_time,
        settings
    )


    cost = (
        kwh *
        tariff["rate"]
    )


    log_event(
        conn,
        None,
        "ENERGY_READING",
        (
            f"{kwh:.2f} kWh recorded at "
            f"₹{tariff['rate']:.2f}/kWh "
            f"({tariff['period']}). "
            f"Cost: ₹{cost:.2f}."
        )
    )


    conn.commit()
    conn.close()


    return jsonify({

        "success": True,

        "kwh":
            kwh,

        "tariff":
            tariff["rate"],

        "period":
            tariff["period"],

        "cost":
            round(
                cost,
                2
            )
    })


# ============================================================
# RESET DEMO
# ============================================================

@app.route(
    "/api/reset",
    methods=["POST"]
)
def reset_demo():

    conn = get_db()


    conn.execute(
        "DELETE FROM alerts"
    )

    conn.execute(
        "DELETE FROM events"
    )

    conn.execute(
        "DELETE FROM energy_readings"
    )

    conn.execute(
        "DELETE FROM meter_readings"
    )

    conn.execute(
        "DELETE FROM hardware_state"
    )

    conn.execute(
        "DELETE FROM machines"
    )


    conn.execute(
        """
        UPDATE settings

        SET

            mode = 'day',

            peak_start = '16:00',
            peak_end = '21:00',

            peak_rate = 8.5,
            offpeak_rate = 5.0,

            system_limit_kw = 18.0

        WHERE id = 1
        """
    )


    conn.commit()
    conn.close()


    initialize_database()
    seed_energy_data()


    conn = get_db()


    log_event(
        conn,
        None,
        "SYSTEM",
        "GridWise AI demo was reset."
    )


    conn.commit()
    conn.close()


    return jsonify({

        "success": True,

        "message":
            "GridWise AI reset successfully."
    })


# ============================================================
# STARTUP
# ============================================================

initialize_database()
seed_energy_data()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    import os
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )