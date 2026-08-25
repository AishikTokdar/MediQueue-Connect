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


COMMAND_MODELS = {
    "LOGIN": LoginPayload,
    "REGISTER": RegisterPayload,
    "GET_SLOTS": GetSlotsPayload,
    "BOOK": BookPayload,
    "MY_BOOKINGS": TokenPayload,
    "CANCEL_BOOKING": CancelPayload,
    "JOIN_QUEUE": QueuePayload,
    "LEAVE_QUEUE": QueuePayload,
    "NEXT_PATIENT": QueuePayload,
    "GET_QUEUE": QueuePayload,
    "REGISTER_DOCTOR": RegisterDoctorPayload,
    "UNBAN_IP": TokenPayload,
    "CLEAR_BOOKING": CancelPayload,
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
