# 🏥 MediQueue Connect

> A networked healthcare appointment and consultation system built using Python sockets.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-success)
![Protocols](https://img.shields.io/badge/Protocols-TCP%20%2B%20UDP-orange)
![License](https://img.shields.io/badge/License-GPLv3-red)

## 📌 Table of Contents

- [Overview](#-overview)
- [Highlights](#-highlights)
- [CN Concepts Used (Short)](#-cn-concepts-used-short)
- [Quick Start](#-quick-start)
- [System Flow](#-system-flow)
- [Project Structure](#-project-structure)
- [Key Features for GitHub Visitors](#-key-features-for-github-visitors)
- [Run Profiles](#-run-profiles)
- [Troubleshooting](#-troubleshooting)
- [Important Notes](#-important-notes)
- [Contributing](#-contributing)
- [Contributors](#-contributors)
- [License](#-license)

## ✨ Overview

MediQueue Connect simulates a real hospital workflow where patients can discover doctors, book appointments, wait in queue when doctors are busy, and start live consultations.

This project was developed as part of the **Computer Communication and Networks (CCN/CN) curriculum**, with focus on practical networking concepts through a real, multi-client application.

## 🚀 Highlights

- 👤 **Patient Portal**: Register, login, filter doctors by specialization and insurance, and book slots.
- 👨‍⚕️ **Doctor Endpoint**: Doctors can go online/offline and manage real-time consultations.
- 💬 **Live Chat Layer**: Low-latency UDP chat for doctor-patient communication.
- 🔐 **Optional Encryption**: Session key exchange and encrypted chat via Fernet (`cryptography`).
- ⏳ **Queue Management**: FIFO queue when doctors are busy, with turn notification and cancellation.
- 🛠️ **Admin Console**: View/remove bookings, review chat histories, broadcast global messages, and manage banned IPs.
- 📊 **Live Dashboard**: Monitor uptime, login/book/chat counters, queue status, and rate-limit bans.
- 📈 **Performance Tool**: Compare TCP and UDP round-trip performance for educational benchmarking.

## 🧠 CN Concepts Used (Short)

- **Transport Layer Protocols**:
  TCP is used for reliable command/response control traffic.
  UDP is used for lower-overhead chat delivery.
- **Client-Server Architecture**:
  Central TCP server manages authentication, scheduling, queueing, and coordination.
- **Application-Layer Protocol Design**:
  Newline-delimited JSON messages act as a custom protocol.
- **Session & State Management**:
  Token-based sessions over TCP; active consultation state maintained per doctor.
- **Concurrency**:
  Multithreading is used to serve multiple clients and subscribers simultaneously.
- **Rate Limiting and Security Controls**:
  Token-bucket style limiting and temporary IP bans demonstrate practical network defense.
- **Latency Trade-off Analysis**:
  TCP vs UDP benchmark module illustrates protocol-performance differences.

## ⚡ Quick Start

### 1) Install dependencies

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Run the core services (separate terminals)

```bash
python server/health_server.py
python clients/doctor.py doctor1
python clients/patient.py
```

### 3) Optional utilities

```bash
python server/admin.py
python server/dashboard.py --interval 4
python server/performance_analysis.py --rounds 30 --payload 64
```

## 🏗️ System Flow

1. Patient authenticates via TCP.
2. Patient fetches specializations/doctors and books an available slot.
3. Patient requests consultation.
4. If doctor is busy, patient enters queue.
5. When turn is ready, server notifies patient.
6. Patient and doctor establish UDP chat (encrypted if available).
7. Session events/messages are logged and persisted.

## 📁 Project Structure

```text
clients/
  doctor.py                 # Doctor-side UDP endpoint + server status updates
  patient.py                # Patient CLI for auth, booking, queue, and chat

server/
  health_server.py          # Main TCP server and command dispatcher
  auth.py                   # User authentication and session token manager
  scheduler.py              # Slot filtering and booking persistence
  queue_manager.py          # Queue, doctor availability, active session state
  chat_history.py           # Transcript/session persistence (JSONL)
  crypto_utils.py           # Encryption/key exchange helpers
  logger.py                 # Thread-safe logging helper
  admin.py                  # Admin operations console
  dashboard.py              # Live monitoring dashboard
  performance_analysis.py   # TCP vs UDP performance analyzer

data/
  doctors.json
  users.json
  bookings.json
  chat_history/
```

## 🔧 Key Features for GitHub Visitors

- End-to-end socket application with both TCP and UDP in one system
- Role-based clients (Patient, Doctor, Admin)
- Queue orchestration and session lifecycle handling
- Real-time push notifications and global broadcast support
- Secure chat option with key exchange flow
- Monitoring and observability via dashboard + logs
- Performance study module for network coursework demonstration

## 🖥️ Run Profiles

- **Minimum demo**: server + one doctor + one patient
- **Full showcase**: add admin panel and dashboard
- **CN experiment mode**: run performance analysis module for TCP vs UDP comparison

Suggested startup order:
1. `python server/health_server.py`
2. `python clients/doctor.py doctor1`
3. `python clients/patient.py`
4. (optional) `python server/admin.py`
5. (optional) `python server/dashboard.py --interval 4`

## 🩺 Troubleshooting

- **Server not reachable**:
  Ensure `health_server.py` is running on `127.0.0.1:4000`.
- **Doctor appears offline**:
  Start doctor client with a valid doctor name from `data/doctors.json`.
- **Encryption not active**:
  Install dependency with `pip install -r requirements.txt` and ensure `cryptography` is available.
- **Queue not progressing**:
  End active doctor session correctly (`exit`) so the next patient can be notified.

## 📝 Important Notes

- Passwords are stored as SHA-256 hashes in `data/users.json`.
- Session tokens are in-memory and reset on server restart.
- Encryption depends on `cryptography` availability.
- `APP_PASSPHRASE` is hardcoded for educational/demo purposes.

## 🤝 Contributing

Contributions are welcome.

1. Fork and create a feature branch.
2. Keep commits focused and well named.
3. Update docs when behavior changes.
4. Include test/run notes in your pull request.

## 🙌 Contributors

- [Aishik Tokdar](https://github.com/AishikTokdar)
- [Shataghnee Chatterjee](https://github.com/shataghnee05)
- [Dipyaman Chakraborty](https://github.com/dipyamanchakraborty)

## 📜 License

Licensed under the **GNU General Public License v3.0 (GPL-3.0)**.
