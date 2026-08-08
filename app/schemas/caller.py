from pydantic import BaseModel


class CallerRequest(BaseModel):
    customer_name: str
    phone_number: str
    hotel_name: str
    check_in_date: str
    check_out_date: str