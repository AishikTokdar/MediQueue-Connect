from pydantic import BaseModel, Field
from typing import List, Optional, Any, Tuple


class LoginPayload(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterPayload(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    insurance: List[str] = Field(default_factory=list)


class TokenPayload(BaseModel):
    token: str = Field(..., min_length=1)


class GetSlotsPayload(BaseModel):
    token: str = Field(..., min_length=1)
    specialization: Optional[str] = None


class BookPayload(BaseModel):
    token: str = Field(..., min_length=1)
    doctor: str = Field(..., min_length=1)
    slot: str = Field(..., min_length=1)


class CancelPayload(BaseModel):
    token: str = Field(..., min_length=1)
    doctor: str = Field(..., min_length=1)
    slot: str = Field(..., min_length=1)


class QueuePayload(BaseModel):
    token: str = Field(..., min_length=1)
    doctor: str = Field(..., min_length=1)


class RegisterDoctorPayload(BaseModel):
    token: Optional[str] = None
    doctor: str = Field(..., min_length=1)
    specialization: str = Field(..., min_length=1)
    accepted_insurance: List[str] = Field(default_factory=list)
    udp_port: int = Field(..., ge=1024, le=65535)
    slots: Optional[List[str]] = None


class RequestChatPayload(BaseModel):
    token: str = Field(..., min_length=1)
    doctor: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)


class SessionPayload(BaseModel):
    token: str = Field(..., min_length=1)
    doctor: str = Field(..., min_length=1)
    session_id: Optional[str] = None


class DoctorStatePayload(BaseModel):
    token: Optional[str] = None
    doctor: str = Field(..., min_length=1)


class AdminRemoveBookingPayload(BaseModel):
    doctor: str = Field(..., min_length=1)
    slot: str = Field(..., min_length=1)


class AdminKillSessionPayload(BaseModel):
    session_id: str = Field(..., min_length=1)


class AdminUnbanIpPayload(BaseModel):
    ip: str = Field(..., min_length=1)


class AdminGlobalMsgPayload(BaseModel):
    message: str = Field(..., min_length=1)


class GeneratePdfPayload(BaseModel):
    token: Optional[str] = None
    session_id: str = Field(..., min_length=1)
    doctor: str = Field(..., min_length=1)
    patient: Optional[str] = None


class GetTaskStatusPayload(BaseModel):
    task_id: str = Field(..., min_length=1)


COMMAND_MODELS = {
    "LOGIN": LoginPayload,
    "REGISTER": RegisterPayload,
    "GET_SLOTS": GetSlotsPayload,
    "BOOK": BookPayload,
    "BOOK_SLOT": BookPayload,
    "MY_BOOKINGS": TokenPayload,
    "GET_MY_APPOINTMENTS": TokenPayload,
    "CANCEL_BOOKING": CancelPayload,
    "CANCEL_MY_BOOKING": CancelPayload,
    "JOIN_QUEUE": QueuePayload,
    "LEAVE_QUEUE": QueuePayload,
    "CANCEL_QUEUE": QueuePayload,
    "NEXT_PATIENT": QueuePayload,
    "GET_QUEUE": QueuePayload,
    "REGISTER_DOCTOR": RegisterDoctorPayload,
    "UNBAN_IP": TokenPayload,
    "CLEAR_BOOKING": CancelPayload,
    "GET_DOCTORS": GetSlotsPayload,
    "REQUEST_CHAT": RequestChatPayload,
    "START_CHAT": SessionPayload,
    "END_SESSION": SessionPayload,
    "DOCTOR_ONLINE": DoctorStatePayload,
    "DOCTOR_OFFLINE": DoctorStatePayload,
    "SUBSCRIBE": TokenPayload,
    "ADMIN_REMOVE_BOOKING": AdminRemoveBookingPayload,
    "ADMIN_KILL_SESSION": AdminKillSessionPayload,
    "ADMIN_UNBAN_IP": AdminUnbanIpPayload,
    "ADMIN_GLOBAL_MSG": AdminGlobalMsgPayload,
    "GENERATE_TRANSCRIPT_PDF": GeneratePdfPayload,
    "GET_TASK_STATUS": GetTaskStatusPayload,
}



def validate_request_payload(command: str, data: dict) -> Tuple[bool, Optional[str], Optional[dict]]:
    """
    Validates payload dict against command schema model.
    Returns (is_valid, error_msg, validated_dict).
    """
    model_cls = COMMAND_MODELS.get(command.upper())
    if not model_cls:
        # Commands without mandatory payload schema (e.g. GET_STATS, GET_SPECIALIZATIONS)
        return True, None, data

    try:
        validated = model_cls(**data)
        return True, None, validated.model_dump()
    except Exception as e:
        return False, f"Invalid payload schema for {command}: {str(e)}", None
