from sqlalchemy.orm import Session

from app.models.caller import Caller
from app.schemas.caller import CallerRequest


def save_call(db: Session, request: CallerRequest):

    caller = Caller(
        customer_name=request.customer_name,
        phone_number=request.phone_number,
        hotel_name=request.hotel_name,
        check_in_date=request.check_in_date,
        check_out_date=request.check_out_date
    )

    db.add(caller)
    db.commit()
    db.refresh(caller)

    return caller
