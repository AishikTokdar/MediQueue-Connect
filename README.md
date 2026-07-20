# 🏥 MediQueue Connect

> **A Secure, Multi-Client Healthcare Consultation & Queue Management Platform built over TCP and UDP Sockets.**

MediQueue Connect simulates a real-life hospital workflow. It enables patients to discover doctors, book appointments based on specialization and insurance, wait in a FIFO queue if the doctor is busy, and establish secure, encrypted live UDP chat consultations. An integrated Admin Console, Live Metrics Dashboard, and Performance Benchmarking tool provide a full-fledged demonstration of network concepts.

---

## 📊 Quick Badges

![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform Support](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-success?style=for-the-badge&logo=linux&logoColor=white)
![Protocols](https://img.shields.io/badge/Protocols-TCP%20%2B%20UDP-orange?style=for-the-badge)
![Security](https://img.shields.io/badge/Security-AES%20Fernet%20Encryption%20%2B%20Rate%20Limiter-red?style=for-the-badge)
![License](https://img.shields.io/badge/License-GPLv3-lightgrey?style=for-the-badge)

---

## 📌 Table of Contents

1. [Overview](#-overview)
2. [System Architecture](#-system-architecture)
3. [Core Computer Network Concepts Used](#-core-computer-network-concepts-used)
4. [File and Folder Structure](#-file-and-folder-structure)
5. [Installation & Requirements](#-installation--requirements)
6. [Pre-configured Accounts (For Testing)](#-pre-configured-accounts-for-testing)
7. [Step-by-Step Run Guide](#-step-by-step-run-guide)
8. [Feature Tour & Interactive Demos](#-feature-tour--interactive-demos)
9. [Security Features & Controls](#-security-features--controls)
10. [Troubleshooting & OS Compatibility Notes](#-troubleshooting--os-compatibility-notes)
11. [Future Improvements](#-future-improvements)
12. [Contributors](#-contributors)
13. [License](#-license)

---

## ✨ Overview

MediQueue Connect bridges the gap between theoretical computer networking concepts and practical software engineering. Developed as part of the **Computer Communication and Networks (CCN/CN) curriculum**, this multi-threaded application leverages custom client-server application-layer protocols to orchestrate:

- **Patient Portal**: Profile registration, login, filterable scheduling system based on patient's health insurance eligibility, and real-time appointment booking.
- **Doctor Terminal**: Online/Offline toggle, live consultation channel, and a multi-peer clinical invite system.
- **Queue Orchestration Engine**: FIFO-based waiting room that handles doctor-busy states, and automatically notifies queued patients when it is their turn.
- **Secure Chat Layer**: A hybrid messaging channel that negotiates session keys via TCP and routes low-latency, Fernet-encrypted conversation messages over UDP.
- **Admin Command Center**: Database manager allowing admins to delete bookings, audit session transcripts, unban IPs, and broadcast messages to all connected entities.
- **Live Monitor Dashboard**: Uptime tracking, message/booking statistics counters, and live visualization of doctor workloads, patient queues, and banned IPs.
- **Performance Evaluator**: Side-by-side RTT latency analyzer comparing TCP control traffic against UDP echo streams.

---

## 🏗️ System Architecture

The following diagram illustrates how the core components communicate using TCP, UDP, local JSON datastores, and the publish-subscribe model:

```mermaid
graph TD
    subgraph Clients ["Client Layer"]
        P[Patient CLI - patient.py]
        D[Doctor Console - doctor.py]
    end

    subgraph Monitoring ["Monitoring & Admin"]
        A[Admin Console - admin.py]
        DS[Live Dashboard - dashboard.py]
        PA[Perf Analyzer - performance_analysis.py]
    end

    subgraph Server ["Server Layer (health_server.py)"]
        TCP[TCP Control Listener: Port 4000]
        RL[Rate Limiter & IP Ban Engine]
        QM[Queue Manager & Session Orchestration]
        SM[Scheduler & Booking Manager]
        AM[Auth Manager & Session Token Cache]
        CH[Chat History Logger]
    end

    subgraph Data ["Storage Layer"]
        D_JSON[(doctors.json)]
        U_JSON[(users.json)]
        B_JSON[(bookings.json)]
        C_LOGS[(chat_history/)]
        S_LOGS[(server_logs.txt)]
    end

    %% Network Connections
    P <-- TCP command/response --> TCP
    D <-- TCP status/handshake --> TCP
    P -- Encrypted UDP Chat --> D
    D -- UDP Invite Collaboration --> D
    A <-- TCP Admin commands --> TCP
    DS <-- Polling TCP stats --> TCP
    PA <-- TCP ping / UDP echo --> TCP

    %% Internal Server flows
    TCP --> RL
    TCP --> AM
    TCP --> SM
    TCP --> QM
    TCP --> CH

    %% File IO
    AM <--> U_JSON
    SM <--> D_JSON
    SM <--> B_JSON
    CH --> C_LOGS
    TCP --> S_LOGS
    DS -. Reads logs .-> S_LOGS
```

---

## 🧠 Core Computer Network Concepts Used

MediQueue Connect is a sandbox for demonstrating several primary networking paradigms:

1. **Transport Protocol Selection**:
   - **TCP (Transmission Control Protocol)** is utilized for session establishment, authentication, slot scheduling, administrative tasks, and pub-sub notifications where data integrity and in-order delivery are non-negotiable.
   - **UDP (User Datagram Protocol)** is used for actual chat messaging and doctor-to-doctor invitations. Because UDP avoids connection overhead, it offers low latency suited for real-time interaction.
2. **Application-Layer Custom Protocol**:
   - Communication between the client and server relies on a custom newline-delimited (`\n`) JSON message exchange protocol. This defines clear primitives for actions like `LOGIN`, `BOOK_SLOT`, `REQUEST_CHAT`, `END_SESSION`, and `ADMIN_GLOBAL_MSG`.
3. **Multi-Threaded Concurrency**:
   - The Health Server maintains a connection thread pool (`threading.Thread`) to concurrently handle multiple incoming client requests.
   - Separate daemon threads are used on clients to handle real-time server push events (broadcasts, session termination) without freezing the main CLI interface.
4. **Publish-Subscribe Pattern**:
   - Clients invoke a persistent `SUBSCRIBE` command. The server holds these open connections in an active subscriber list. If the admin broadcasts a global message or terminates a session, the server pushes the payload down all subscriber sockets instantly.
5. **Stateful Session Management**:
   - Transient UUID session tokens are generated upon successful login. These tokens validate subsequent actions, maintaining state across disconnected TCP transactions without requiring credentials to be re-transmitted.
6. **Rate Limiting & DDoS Prevention**:
   - A token-bucket algorithm monitors incoming IP addresses. Request frequency exceeding defined thresholds triggers a temporary 5-minute IP ban, simulating firewalls and intrusion prevention systems.

---

## 📁 Project Structure

```text
MediQueue-Connect/
│
├── requirements.txt            # Package dependencies (cryptography)
├── LICENSE                     # GPLv3 License
├── README.md                   # Project Documentation
│
├── clients/
│   ├── patient.py              # CLI client for patient registration, booking, and UDP chat
│   └── doctor.py               # CLI endpoint for online status updates and UDP consultation
│
├── server/
│   ├── health_server.py        # Central TCP socket server and dispatcher
│   ├── auth.py                 # Handles SHA-256 hashed password storage & authentication
│   ├── scheduler.py            # Manages appointments and filters slots by insurance
│   ├── queue_manager.py        # Handles doctor busy states & FIFO queues
│   ├── chat_history.py         # Logs session transcripts to JSONL format
│   ├── crypto_utils.py         # Symmetric Fernet encryption helpers & key exchange
│   ├── logger.py               # Thread-safe file/console logging
│   ├── admin.py                # Command-line interface for administrative operations
│   ├── dashboard.py            # Live-updating ANSI terminal dashboard
│   └── performance_analysis.py # Comparative TCP vs UDP latency benchmark utility
│
└── data/
    ├── doctors.json            # Hardcoded registry of doctor attributes, ports, and specialties
    ├── users.json              # Hashed credentials database
    ├── bookings.json           # Active appointment reservations
    ├── server_logs.txt         # Server runtime event log
    └── chat_history/           # Folder containing audit trails for patient-doctor conversations
```

---

## ⚡ Installation & Requirements

### Dependencies
- **Python**: Version 3.10 or higher.
- **Cryptography**: Required for encrypted consultations (`pip install cryptography`).

### 1) Clone and Prepare Environment

Open your terminal or PowerShell and run:

```bash
# Clone the repository
git clone https://github.com/AishikTokdar/MediQueue-Connect.git
cd MediQueue-Connect

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Windows (CMD):
.\.venv\Scripts\activate.bat
# On Linux / macOS:
source .venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

---

## 🔑 Pre-configured Accounts & Doctor Specializations (For Testing)

### Patient Accounts
To log in immediately, use any of the pre-configured patients. The default password is identical to the username:

| Username | Default Password | Covered Specializations | Pre-registered Insurance |
| :--- | :--- | :--- | :--- |
| `patient1` | `patient1` | General Physician, Cardiologist, Dermatologist, Neurologist, Orthopedic, Pediatrician | `insuranceA` |
| `patient2` | `patient2` | General Physician, Cardiologist, Dermatologist, Neurologist, Orthopedic, Pediatrician | `insuranceB` |
| `patient3` | `patient3` | General Physician, Cardiologist, Dermatologist, Neurologist, Orthopedic, Pediatrician | `insuranceA`, `insuranceB` |
| `patient4` | `patient4` | General Physician, Cardiologist, Dermatologist, Neurologist, Orthopedic, Pediatrician | `insuranceA` |
| `patient5` | `patient5` | General Physician, Cardiologist, Dermatologist, Neurologist, Orthopedic, Pediatrician | `insuranceB` |
| `patient6` | `patient6` | General Physician, Cardiologist, Dermatologist, Neurologist, Orthopedic, Pediatrician | `insuranceA`, `insuranceB` |

### Doctor Registry & Specialization Matrix (`data/doctors.json`)

Doctors are categorized into specific specializations and accept different insurance policies:

| Doctor ID | Specialization | Accepted Insurance | UDP Port | Available Slots |
| :--- | :--- | :--- | :--- | :--- |
| `doctor1` | General Physician | `insuranceA`, `insuranceB` | `5001` | `10AM`, `11AM` |
| `doctor5` | General Physician | `insuranceA` | `5005` | `9AM`, `12PM` |
| `doctor6` | General Physician | `insuranceB` | `5006` | `2PM`, `5PM` |
| `doctor2` | Cardiologist | `insuranceB` | `5002` | `12PM`, `1PM` |
| `doctor7` | Cardiologist | `insuranceA` | `5007` | `9AM`, `10AM` |
| `doctor8` | Cardiologist | `insuranceA`, `insuranceB` | `5008` | `2PM`, `3PM`, `4PM` |
| `doctor3` | Dermatologist | `insuranceA` | `5003` | `2PM`, `3PM` |
| `doctor9` | Dermatologist | `insuranceB` | `5009` | `11AM`, `12PM` |
| `doctor10` | Dermatologist | `insuranceA`, `insuranceB` | `5010` | `9AM`, `1PM`, `5PM` |
| `doctor4` | Neurologist | `insuranceA`, `insuranceB` | `5004` | `9AM`, `10AM`, `4PM` |
| `doctor11` | Neurologist | `insuranceA` | `5011` | `10AM`, `11AM` |
| `doctor12` | Neurologist | `insuranceB` | `5012` | `1PM`, `2PM`, `3PM` |
| `doctor13` | Orthopedic | `insuranceA` | `5013` | `9AM`, `11AM` |
| `doctor14` | Orthopedic | `insuranceB` | `5014` | `2PM`, `4PM` |
| `doctor15` | Pediatrician | `insuranceA`, `insuranceB` | `5015` | `10AM`, `1PM`, `3PM` |
| `doctor16` | Pediatrician | `insuranceA` | `5016` | `9AM`, `12PM` |

*Note: You can also register new doctors dynamically using `python clients/doctor.py`.*

---

---

## ⚡ Execution Guide

You can run MediQueue Connect either using the **Automated Launcher Scripts** (one-click startup for all components) or **Manually Step-by-Step**.

---

### 🚀 Option A: Automated One-Click Launcher (Recommended)

Automated scripts spawn the Health Server, Doctor processes, and Dashboard in separate background windows, leaving your primary terminal ready for Patient interaction:

#### On Linux / macOS / WSL / Git Bash:
```bash
chmod +x run_demo.sh
./run_demo.sh
```

#### On Windows (CMD / PowerShell):
```cmd
run_demo.bat
```

*What the launcher does automatically:*
1. Starts the TLS-Secured Health Server on port `4000`.
2. Boots `doctor1` (General Physician) on UDP port `5001`.
3. Boots `doctor2` (Cardiologist) on UDP port `5002`.
4. Starts the Live Monitoring Dashboard.
5. Connects your main terminal directly into the Patient CLI (`clients/patient.py`).

---

### 🛠️ Option B: Manual Step-by-Step Execution

If you prefer launching each component manually across separate terminal windows:

#### Step 1: Start the Health Center Server
Open **Terminal 1** and start the central TLS control server:
```bash
python server/health_server.py
```
*Expected Console Output:*
```text
=== Health Center Server (TLS Secured) started on 127.0.0.1:4000 ===
```

#### Step 2: Launch Doctor Clients
Open **Terminal 2** (and optionally **Terminal 3**) to set doctors online or register new doctor profiles:
```bash
# Launch pre-configured doctor profile (Terminal 2)
python clients/doctor.py doctor1

# Launch via interactive startup menu to select profile or register new doctor (Terminal 3)
python clients/doctor.py
```
*Expected Console Output:*
```text
=======================================================
  Dr. doctor1  –  General Physician
  UDP port: 5001
=======================================================
  Waiting for patients...
```

#### Step 3: Launch Patient Clients
Open **Terminal 4** to initiate appointment bookings or live consultations:
```bash
python clients/patient.py
```
*In the patient CLI:*
1. Select **1. Login** or **2. Register**.
2. Log in using `patient1` (password: `patient1`).
3. Select **1. Book appointment** or **2. Request immediate consultation**.
4. Filter by doctor specialization (e.g. *General Physician*, *Cardiologist*) to view doctors matching your insurance coverage.

#### Step 4: Launch the Live Dashboard (Optional)
Open **Terminal 5** to view real-time system metrics, doctor availability, queue positions, and server logs:
```bash
python server/dashboard.py --interval 2
```

#### Step 5: Launch the Admin Console (Optional)
Open **Terminal 6** to execute administrative commands (e.g. broadcast system alerts, terminate sessions, unban rate-limited IPs):
```bash
python server/admin.py
```

#### Step 6: Run Network Performance Analysis (Optional)
Open **Terminal 7** to benchmark TCP vs UDP latency under customizable round-trip counts and payload sizes:
```bash
python server/performance_analysis.py --rounds 50 --payload 128
```

---

## 🛠️ Feature Tour & Interactive Demos

### 1. Booking a Slot & Patient Scheduling
1. Run `patient.py` and log in as `patient1` (password: `patient1`).
2. Choose **Option 1: Book appointment**.
3. Select a specialization (e.g., *General Physician*) or type `0` to list all doctors.
4. The patient client will list only doctors who accept `insuranceA` (matching `patient1`'s profile).
5. Select a doctor (e.g. `doctor1`) and type an available slot (e.g., `10AM`).
6. Confirm booking. The client will query if you want to chat now. Choosing `yes` immediately launches the consultation routing.

### 2. Real-time Queue Orchestration
If a doctor is already consulting a patient, other incoming patients are placed in a queue:
1. Ensure `doctor1` is online.
2. Start Patient Terminal A (`patient1`), start a chat with `doctor1`. An active UDP chat begins.
3. Start Patient Terminal B (`patient2`), attempt to chat with `doctor1`.
4. Patient B will receive a message: `Doctor is busy. You are #1 in the queue.`
5. On Patient Terminal B, you will see a waiting screen. Pressing `c` sends a `CANCEL_QUEUE` packet to exit.
6. When Patient A types `exit`, the chat session ends.
7. The server automatically processes the queue, sends a `TURN_READY` TCP packet to Patient B, and connects Patient B to `doctor1`'s UDP socket automatically.

### 3. Consultation Layer (Encrypted vs Plaintext)
- **If `cryptography` is installed**:
  - Upon starting a UDP session, the doctor client generates an ephemeral Fernet key.
  - The doctor client encrypts this session key using a shared secret passphrase (`HealthcareCN2024SecretPassphrase!`) and sends it to the patient.
  - The patient client decrypts the session key. All subsequent conversation messages (`type: CHAT`) are sent as ciphertext.
  - The Patient terminal displays a `🔒 Encrypted chat with Dr. <name> started` banner.
- **If `cryptography` is NOT installed**:
  - The handshake falls back to plaintext.
  - Sockets transmit raw text, and the patient terminal displays a `⚠ Plaintext chat with Dr. <name> started` warning.

### 4. Doctor-to-Doctor Invite Feature (Collaboration)
While engaged in a live chat, doctors can invite offline/online colleagues for a joint consultation:
1. During an active chat with a patient, the doctor can type:
   ```text
   /invite doctor2
   ```
2. If the second doctor is online (on their designated port), they receive the invitation packet and join the active chat session.
3. Messages are broadcasted across all participating endpoints.

### 5. Admin global controls
Using `admin.py`:
- **Global Broadcast**: Select **Option 4** and type a message. All connected doctors and patients will instantly receive a highlighted server broadcast alert in their consoles.
- **Kill Session**: Select **Option 3**, view active sessions, and type `kill <session_number>`. The server will transmit a termination packet to the subscriber thread of both patient and doctor, ending the consultation immediately.

---

## 🔒 Security Features & Controls

MediQueue Connect includes basic security features suited for simulated and educational network environments:

### Rate Limiting & Auto-Ban
- Prevents socket flooding (denial of service).
- Configured in `server/health_server.py` via `RateLimiter`:
  - **Bucket capacity**: 20 tokens.
  - **Refill rate**: 10 tokens per second.
  - **Ban duration**: 300 seconds (5 minutes).
- Triggering the rate limit returns a `BANNED: Rate limit exceeded` JSON response and ignores subsequent packets from that IP.

### Password Hashing
- Client passwords are never stored in plaintext.
- Passwords are submitted to the server, hashed using SHA-256 with `hashlib`, and compared against the values stored in `data/users.json`.

---

## 🩺 Troubleshooting & OS Compatibility Notes

### ⚠️ Windows Console Colors
If ANSI escape sequences (like `\033[91m`) appear as raw characters in Windows Command Prompt, run the script once to enable virtual terminal processing, or use Windows Terminal (PowerShell).

### ⚠️ OS Compatibility & Terminal Performance
> [!NOTE]
> The patient client (`clients/patient.py`) uses a cross-platform non-blocking key detector (`check_cancel_key()`).
> On **Windows**, it utilizes `msvcrt.kbhit()`. On **Linux and macOS**, it dynamically leverages `select.select()` and POSIX `termios` cbreak mode.
> Queue cancellation via the `'c'` key is fully supported on Windows, Linux, and macOS without extra dependencies.

### ⚠️ Udp Port Conflicts
Each doctor operates on a dedicated UDP port defined in `data/doctors.json` (ranging from `5001` to `5012`). If you receive a socket bind error, verify that no other process is using those ports:
- On Windows: `netstat -ano | findstr <port>`
- On Linux: `sudo lsof -i :<port>`

---

## 🚀 Future Improvements

To transition MediQueue Connect from an educational simulation to a production-grade application, several architectural improvements could be made:

1. **Cross-Platform Queue Management** *(Implemented ✓)*:
   Implemented a unified non-blocking input layer (`check_cancel_key`) in `clients/patient.py`. Windows uses `msvcrt`, while Linux and macOS use `select.select` with POSIX `termios` cbreak mode for queue cancellation without blocking the thread.
2. **TLS/SSL for TCP Socket Communication** *(Implemented ✓)*:
   Wrapped the main TCP control listener (`health_server.py`) and all client applications (`patient.py`, `doctor.py`, `admin.py`, `dashboard.py`, `performance_analysis.py`) using Python's `ssl` module. The system automatically generates RSA-2048 self-signed TLS certificates stored in `data/certs/`, securing all control plane operations (credentials, tokens, bookings, administrative commands) against eavesdropping.
3. **True Diffie-Hellman Key Exchange (DHKE)**:
   Implement an actual Diffie-Hellman or Elliptic Curve Diffie-Hellman (ECDH) key exchange protocol at the start of UDP sessions. This would allow patients and doctors to generate a shared session key without relying on a hardcoded passphrase (`HealthcareCN2024SecretPassphrase!`).
4. **Dynamic Doctor Registration** *(Implemented ✓)*:
   Implemented full dynamic doctor registration protocol (`REGISTER_DOCTOR` command). Doctors can launch `clients/doctor.py` without hardcoded configuration files, specify their specialization (*General Physician, Cardiologist, Dermatologist, Neurologist, Orthopedic, Pediatrician* or custom), choose accepted insurance policies (*insuranceA*, *insuranceB*, or both), and assign listening UDP ports dynamically at boot time.
5. **Persistent Database Integration**:
   Replace local JSON storage (`users.json`, `bookings.json`) with an ACID-compliant database like SQLite or PostgreSQL. This would resolve potential file-lock conflicts caused by concurrent read/write operations.
6. **Real-time Audio/Video Streaming (RTP/RTCP)**:
   Extend the consultation layer to support voice and video by packetizing microphone/camera streams and transmitting them over UDP, managed by a session signaling protocol.

---

## 🙌 Contributors

- [Aishik Tokdar](https://github.com/AishikTokdar)
- [Shataghnee Chatterjee](https://github.com/shataghnee05)
- [Dipyaman Chakraborty](https://github.com/dipyamanchakraborty)

---

## 📜 License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. See the `LICENSE` file for details.
