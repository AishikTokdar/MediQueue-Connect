#!/usr/bin/env bash
# =======================================================
#   MediQueue Connect - Automated Production Launcher
# =======================================================

echo "======================================================="
echo "    MediQueue Connect - Automated Production Launcher"
echo "======================================================="
echo ""

if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python is not installed or not in PATH."
    exit 1
fi

if [[ "$1" == "--test" ]]; then
    echo "[0/4] Running Automated Pytest Suite..."
    $PYTHON_CMD -m pytest -v tests/
    if [ $? -ne 0 ]; then
        echo "[ERROR] Test suite failed! Aborting startup."
        exit 1
    fi
    echo ""
fi

launch_terminal() {
    TITLE="$1"
    CMD="$2"

    if [[ "$OSTYPE" == "darwin"* ]]; then
        osascript -e "tell application \"Terminal\" to do script \"cd '$(pwd)' && $CMD\""
    elif command -v gnome-terminal &>/dev/null; then
        gnome-terminal --title="$TITLE" -- bash -c "$CMD; exec bash"
    elif command -v xfce4-terminal &>/dev/null; then
        xfce4-terminal --title="$TITLE" -e "bash -c '$CMD; exec bash'"
    elif command -v konsole &>/dev/null; then
        konsole --title="$TITLE" -e bash -c "$CMD; exec bash"
    elif command -v x-terminal-emulator &>/dev/null; then
        x-terminal-emulator -e bash -c "$CMD; exec bash"
    elif command -v xterm &>/dev/null; then
        xterm -T "$TITLE" -e bash -c "$CMD; exec bash" &
    else
        echo "Starting $TITLE in background..."
        $CMD &
    fi
}

echo "[1/4] Starting Async Health Center Server (Port 4000)..."
launch_terminal "MediQueue Health Server" "$PYTHON_CMD server/health_server.py"
sleep 2

echo "[2/4] Starting Doctor 1 (General Physician)..."
launch_terminal "MediQueue - Dr. doctor1" "$PYTHON_CMD clients/doctor.py doctor1"
sleep 1

echo "[3/4] Starting Doctor 2 (Cardiologist)..."
launch_terminal "MediQueue - Dr. doctor2" "$PYTHON_CMD clients/doctor.py doctor2"
sleep 1

echo "[4/4] Starting System Dashboard..."
launch_terminal "MediQueue Dashboard" "$PYTHON_CMD server/dashboard.py --interval 2"
sleep 1

echo ""
echo "======================================================="
echo "  All background services launched!"
echo "  Launching Patient Client in this terminal window..."
echo "======================================================="
echo ""
$PYTHON_CMD clients/patient.py
