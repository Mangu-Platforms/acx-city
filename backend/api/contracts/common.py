from pydantic import BaseModel


class ErrorOut(BaseModel):
    error: str
