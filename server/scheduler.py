import json
import os
import threading


class Scheduler:

    def __init__(self):
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
        self._doctors_path = os.path.join(data_dir, "doctors.json")
        self._bookings_path = os.path.join(data_dir, "bookings.json")

        with open(self._doctors_path) as f:
            self.doctors: dict = json.load(f)

        try:
            with open(self._bookings_path) as f:
                content = f.read().strip()
                self.bookings: dict = json.loads(content) if content else {}
        except (FileNotFoundError, json.JSONDecodeError):
            self.bookings = {}

        self.lock = threading.Lock()
        self._normalize_bookings()

    def _extract_patient(self, booking_entry) -> str | None:
        if isinstance(booking_entry, dict):
            patient = booking_entry.get("patient")
            return patient if isinstance(patient, str) and patient.strip() else None
        if isinstance(booking_entry, str) and booking_entry.strip():
            return booking_entry
        return None

    def _normalize_bookings(self) -> None:
        normalized = {}
        changed = False

        for doctor, slots in self.bookings.items():
            if not isinstance(slots, dict):
                changed = True
                continue

            normalized_slots = {}
            for slot, booking_entry in slots.items():
                patient = self._extract_patient(booking_entry)
                if not patient:
                    changed = True
                    continue
                normalized_slots[slot] = {"patient": patient}
                if not isinstance(booking_entry, dict):
                    changed = True

            if normalized_slots:
                normalized[doctor] = normalized_slots
            elif slots:
                changed = True

        if changed or normalized != self.bookings:
            self.bookings = normalized
            self.save_bookings()

    def save_bookings(self) -> None:
        with open(self._bookings_path, "w") as f:
            json.dump(self.bookings, f, indent=4)

    def get_all_bookings(self) -> dict:
        with self.lock:
            all_bookings = {}
            for doctor, slots in self.bookings.items():
                if not slots:
                    continue
                all_bookings[doctor] = {
                    slot: entry["patient"]
                    for slot, entry in slots.items()
                    if isinstance(entry, dict) and entry.get("patient")
                }
                if not all_bookings[doctor]:
                    del all_bookings[doctor]
            return all_bookings

    def remove_booking(self, doctor: str, slot: str) -> bool:
        with self.lock:
            if doctor in self.bookings and slot in self.bookings[doctor]:
                del self.bookings[doctor][slot]
                if not self.bookings[doctor]:
                    del self.bookings[doctor]
                self.save_bookings()
                return True
            return False

    def get_slots(self, insurance: list, specialization: str | None = None) -> dict:
        filtered = {}
        for doc, info in self.doctors.items():
            if not any(i in info.get("accepted_insurance", []) for i in insurance):
                continue
            if specialization and specialization.lower() not in info.get("specialization", "").lower():
                continue
            booked_slots = set(self.bookings.get(doc, {}).keys())
            available = [s for s in info["slots"] if s not in booked_slots]
            filtered[doc] = {
                "slots": available,
                "accepted_insurance": info["accepted_insurance"],
                "specialization": info.get("specialization", "General"),
                "udp_port": info["udp_port"],
            }
        return filtered

    def get_slots_by_insurance(self, insurance: list) -> dict:
        return self.get_slots(insurance)

    def book_slot(self, user: str, doctor: str, slot: str) -> dict:
        with self.lock:
            if doctor not in self.doctors:
                return {"status": "UNAVAILABLE", "reason": "Doctor not found"}

            booked_slots = self.bookings.get(doctor, {})
            if slot in booked_slots:
                return {"status": "UNAVAILABLE", "reason": "Slot already booked"}

            if slot not in self.doctors[doctor]["slots"]:
                return {"status": "UNAVAILABLE", "reason": "Slot does not exist"}

            if doctor not in self.bookings:
                self.bookings[doctor] = {}

            self.bookings[doctor][slot] = {"patient": user}
            self.save_bookings()

            return {
                "status": "BOOKED",
                "doctor": doctor,
                "slot": slot,
                "udp_port": self.doctors[doctor]["udp_port"],
                "specialization": self.doctors[doctor].get("specialization", "General"),
            }

    def get_bookings_for_patient(self, user: str) -> list:
        with self.lock:
            results = []
            for doctor, slots in self.bookings.items():
                specialization = self.doctors.get(doctor, {}).get("specialization", "General")
                for slot, entry in slots.items():
                    patient = self._extract_patient(entry)
                    if patient == user:
                        results.append({
                            "doctor": doctor,
                            "specialization": specialization,
                            "slot": slot,
                            "patient": patient,
                        })
            results.sort(key=lambda x: (x["doctor"].lower(), x["slot"].lower()))
            return results

    def remove_booking_for_patient(self, user: str, doctor: str, slot: str) -> dict:
        with self.lock:
            if doctor not in self.bookings or slot not in self.bookings[doctor]:
                return {"status": "FAIL", "reason": "Booking not found"}

            patient = self._extract_patient(self.bookings[doctor][slot])
            if patient != user:
                return {"status": "FAIL", "reason": "You can only cancel your own appointments"}

            del self.bookings[doctor][slot]
            if not self.bookings[doctor]:
                del self.bookings[doctor]
            self.save_bookings()
            return {"status": "OK"}

    def get_all_doctors(self) -> dict:
        return self.doctors

    def get_specializations(self) -> list:
        specs = {info.get("specialization", "General") for info in self.doctors.values()}
        return sorted(specs)
