from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class SignupRequest(BaseModel):
    email: str
